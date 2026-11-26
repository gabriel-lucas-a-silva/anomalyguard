from datetime import timedelta

import pytest

from anomalyguard.demo import CATALOG, DemoConflict, DemoDisabled, DemoIncidents, DemoUnknownFault
from anomalyguard.flags import FlagError
from tests.helpers import FakeClock, alert, settings, world


class FakeFlags:
    def __init__(self):
        self.values = {"paymentFailure": "off"}
        self.calls = []
        self.fail_on = None

    def set(self, flag, variant):
        self.calls.append((flag, variant))
        if self.fail_on == variant:
            raise FlagError("demo fora do ar")
        self.values[flag] = variant


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def __call__(self, delay_s, function):
        job = {"delay": delay_s, "function": function, "cancelled": False}
        self.jobs.append(job)

        def cancel():
            job["cancelled"] = True

        return cancel


def build(demo_mode=True, **overrides):
    service, store, hub, clock, config = world(demo_mode=demo_mode, **overrides)
    flags, scheduler = FakeFlags(), FakeScheduler()
    return DemoIncidents(store, flags, config, clock, scheduler), flags, scheduler, store, clock, service


def test_starting_turns_the_fault_on_and_records_an_active_incident():
    demo, flags, scheduler, store, clock, _ = build()
    view = demo.start("payment_failure")
    assert flags.values["paymentFailure"] == "100%"
    assert view["state"] == "active" and view["investigation_id"] is None and store.active_incident()["kind"] == "payment_failure"
    assert store.active_incident()["id"] == view["id"]


def test_the_fault_is_scheduled_to_turn_off_after_the_configured_duration():
    demo, flags, scheduler, *_ = build(demo_duration_s=420)
    demo.start("payment_failure")
    assert scheduler.jobs[0]["delay"] == 420


def test_the_scheduled_end_turns_the_fault_off_and_finishes_the_incident():
    demo, flags, scheduler, store, clock, _ = build()
    demo.start("payment_failure")
    clock.advance(420)
    scheduler.jobs[0]["function"]()
    assert flags.values["paymentFailure"] == "off"
    assert store.active_incident() is None and store.latest_incident()["state"] == "finished"


def test_a_second_simulation_is_refused_while_one_is_active():
    demo, flags, *_ = build()
    demo.start("payment_failure")
    with pytest.raises(DemoConflict, match="em andamento"):
        demo.start("payment_failure")
    assert flags.calls == [("paymentFailure", "100%")]


def test_stopping_turns_the_fault_off_right_away_and_cancels_the_schedule():
    demo, flags, scheduler, store, *_ = build()
    demo.start("payment_failure")
    demo.stop()
    assert flags.values["paymentFailure"] == "off" and scheduler.jobs[0]["cancelled"] is True
    assert store.latest_incident()["state"] == "stopped"


def test_stopping_without_a_simulation_is_a_conflict():
    demo, *_ = build()
    with pytest.raises(DemoConflict, match="não há simulação"):
        demo.stop()


def test_a_flag_that_cannot_be_turned_on_leaves_no_incident():
    demo, flags, scheduler, store, *_ = build()
    flags.fail_on = "100%"
    with pytest.raises(FlagError):
        demo.start("payment_failure")
    assert store.latest_incident() is None and scheduler.jobs == []


def test_a_flag_that_cannot_be_turned_off_marks_the_incident_as_failed_with_the_reason():
    demo, flags, scheduler, store, clock, _ = build()
    demo.start("payment_failure")
    flags.fail_on = "off"
    clock.advance(420)
    view = scheduler.jobs[0]["function"]()
    assert view["state"] == "failed" and "fora do ar" in view["failure_reason"]
    assert store.active_incident() is None


def test_finishing_twice_does_nothing_the_second_time():
    demo, flags, scheduler, *_ = build()
    view = demo.start("payment_failure")
    demo.finish(view["id"], "finished")
    flags.calls.clear()
    assert demo.finish(view["id"], "finished") is None and flags.calls == []


def test_the_current_view_links_the_investigation_opened_after_the_start():
    demo, flags, scheduler, store, clock, service = build()
    demo.start("payment_failure")
    clock.advance(180)
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    assert demo.current()["investigation_id"] == identifier


def test_the_current_view_is_the_last_incident_when_none_is_active_and_none_before_any():
    demo, flags, scheduler, *_ = build()
    assert demo.current() is None
    view = demo.start("payment_failure")
    demo.stop()
    assert demo.current()["id"] == view["id"] and demo.current()["state"] == "stopped"


def test_after_a_restart_an_expired_incident_is_finished_and_a_live_one_is_rescheduled():
    demo, flags, scheduler, store, clock, _ = build()
    demo.start("payment_failure")
    clock.advance(100)
    demo.recover()
    assert scheduler.jobs[-1]["delay"] == 320 and flags.values["paymentFailure"] == "100%"
    clock.advance(400)
    demo.recover()
    assert flags.values["paymentFailure"] == "off" and store.active_incident() is None


def test_everything_is_refused_when_the_demo_mode_is_off():
    demo, flags, *_ = build(demo_mode=False)
    for action in (lambda: demo.start("payment_failure"), demo.stop, demo.current, demo.options):
        with pytest.raises(DemoDisabled):
            action()
    demo.recover()
    assert flags.calls == []


def test_an_incident_records_which_service_is_the_real_cause():
    demo, flags, scheduler, store, clock, _ = build()
    view = demo.start("payment_failure")
    incident = store.active_incident()
    assert incident["root_cause_service"] == "payment" and incident["expected_signal"] == "trace_err"


def test_the_view_names_the_chosen_fault_but_not_its_flag_or_cause():
    demo, *_ = build()
    view = demo.start("product_catalog_lock_contention")
    assert view["kind"] == "product_catalog_lock_contention" and view["title"] == "Trava no banco do catálogo"
    assert "root_cause_service" not in view and "flag" not in view


@pytest.mark.parametrize("kind", sorted(CATALOG))
def test_each_fault_turns_its_own_flag_on_and_records_its_own_cause(kind):
    demo, flags, scheduler, store, clock, _ = build()
    demo.start(kind)
    fault = CATALOG[kind]
    assert flags.values[fault["flag"]] == fault["variant"]
    incident = store.active_incident()
    assert incident["kind"] == kind and incident["root_cause_service"] == fault["service"] and incident["expected_signal"] == fault["signal"]
    clock.advance(420)
    scheduler.jobs[0]["function"]()
    assert flags.values[fault["flag"]] == "off"


def test_an_unknown_fault_is_refused_before_touching_the_demo():
    demo, flags, *_ = build()
    with pytest.raises(DemoUnknownFault):
        demo.start("cartFailure")
    assert flags.calls == []


def test_the_options_list_every_fault_with_what_the_user_needs_to_choose():
    demo, *_ = build()
    options = demo.options()
    assert [o["kind"] for o in options] == list(CATALOG)
    for option in options:
        assert set(option) == {"kind", "title", "description", "affected_service", "alert"}
        assert all(isinstance(option[key], str) and option[key] for key in option)


def test_a_latency_fault_expects_the_latency_alert_and_the_error_faults_the_error_alert():
    options = {o["kind"]: o for o in build()[0].options()}
    assert options["product_catalog_lock_contention"]["alert"] == "ProductCatalogHighLatency"
    assert options["payment_failure"]["alert"] == "FrontendHighErrorRate"
    assert CATALOG["product_catalog_lock_contention"]["signal"] == "trace_lat"
