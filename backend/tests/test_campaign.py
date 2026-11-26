import random
from datetime import timedelta

import pytest

from anomalyguard.campaign import CampaignConflict, CampaignEngine, CampaignInvalid, CampaignNotFound
from anomalyguard.demo import CATALOG, DemoConflict, DemoIncidents
from anomalyguard.flags import FlagError
from tests.helpers import RANKING, alert, completed_with_ranking, world


class FakeFlags:
    def __init__(self):
        self.values = {}
        self.fail = False

    def set(self, flag, variant):
        if self.fail:
            raise FlagError("demo fora do ar")
        self.values[flag] = variant


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def __call__(self, delay_s, function):
        self.jobs.append(function)
        return lambda: None


class FakeGate:
    def __init__(self):
        self.calm = False
        self.reason = "há alerta ativo (X)"
        self.seconds = 0
        self.resets = 0

    def observe(self):
        return self.calm

    def is_calm(self):
        return self.calm

    def calm_for(self):
        return self.seconds

    def reset(self):
        self.resets += 1
        self.calm = False


def build(**overrides):
    service, store, hub, clock, config = world(demo_mode=True, **overrides)
    flags, scheduler, gate = FakeFlags(), FakeScheduler(), FakeGate()
    demo = DemoIncidents(store, flags, config, clock, scheduler)
    engine = CampaignEngine(store, demo, gate, hub, config, clock, random.Random(1))
    return engine, service, store, hub, clock, gate, flags


def events(hub):
    seen = []
    hub.subscribe("*", seen.append)
    return seen


def run_one_case(engine, service, store, clock, gate, ranking=RANKING):
    gate.calm = True
    engine.tick()
    incident = store.active_incident()
    identifier = service.ingest(alert(starts_at=clock.now, fingerprint="fp-%d" % incident["id"])).investigation_id
    completed_with_ranking(store, identifier, ranking)
    engine.tick()
    return incident, identifier


def test_starting_plans_every_fault_the_requested_number_of_times_in_shuffled_order():
    engine, _, store, *_ = build()
    view = engine.start(4)
    cases = store.campaign_cases(view["id"])
    assert view["total"] == 8 and view["done"] == 0 and view["state"] == "running" and view["per_fault"] == 4
    assert sorted(c["kind"] for c in cases) == sorted(list(CATALOG) * 4)
    assert [c["kind"] for c in cases] != sorted(c["kind"] for c in cases)


def test_a_second_campaign_or_a_manual_simulation_blocks_a_new_one():
    engine, _, store, *_ = build()
    engine.start(1)
    with pytest.raises(CampaignConflict):
        engine.start(1)
    engine2, *_ = build()
    engine2.demo.start("payment_failure")
    with pytest.raises(CampaignConflict):
        engine2.start(1)


@pytest.mark.parametrize("size", [0, 31, -1])
def test_the_size_must_be_reasonable(size):
    engine, *_ = build()
    with pytest.raises(CampaignInvalid):
        engine.start(size)


def test_nothing_starts_until_the_demo_is_calm_and_the_view_says_why():
    engine, _, store, hub, clock, gate, flags = build()
    engine.start(1)
    engine.tick()
    assert flags.values == {} and store.active_incident() is None
    current = engine.view(store.active_campaign())["current"]
    assert current["phase"] == "calm_wait" and "alerta ativo" in current["detail"]


def test_a_full_case_turns_the_fault_on_waits_for_the_alert_and_records_the_rank():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    incident, identifier = run_one_case(engine, service, store, clock, gate)
    done = [c for c in store.campaign_cases(1) if c["state"] == "done"]
    assert len(done) == 1 and done[0]["investigation_id"] == identifier and done[0]["incident_id"] == incident["id"]
    expected = incident["root_cause_service"]
    rank = {r["service"]: r["position"] for r in RANKING}.get(expected)
    assert done[0]["status"] == "evaluated" and done[0]["rank"] == rank and done[0]["top_service"] == "frontend" and done[0]["root_cause_service"] == expected


def test_the_view_follows_the_case_from_fault_on_to_analysis():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    gate.calm = True
    engine.tick()
    assert engine.view(store.active_campaign())["current"]["phase"] == "fault_on"
    service.ingest(alert(starts_at=clock.now))
    engine.tick()
    assert engine.view(store.active_campaign())["current"]["phase"] == "analyzing"


def test_a_fault_that_never_raises_the_alert_becomes_a_no_alert_case_after_the_timeout():
    engine, service, store, hub, clock, gate, flags = build(campaign_alert_timeout_s=480)
    engine.start(1)
    gate.calm = True
    engine.tick()
    clock.advance(400)
    engine.tick()
    assert store.campaign_cases(1)[0]["state"] != "done" or store.campaign_cases(1)[0]["status"] != "no_alert"
    clock.advance(100)
    engine.tick()
    cases = [c for c in store.campaign_cases(1) if c["state"] == "done"]
    assert len(cases) == 1 and cases[0]["status"] == "no_alert" and cases[0]["investigation_id"] is None and cases[0]["rank"] is None


def test_an_investigation_that_fails_is_a_failed_case_not_a_miss():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    gate.calm = True
    engine.tick()
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    service.fail(identifier, "dados insuficientes")
    engine.tick()
    done = [c for c in store.campaign_cases(1) if c["state"] == "done"]
    assert done[0]["status"] == "failed" and done[0]["rank"] is None


def test_a_cause_outside_the_ranking_is_evaluated_with_no_rank():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    run_one_case(engine, service, store, clock, gate, ranking=[{"position": 1, "service": "ad", "score": 0.3}])
    done = [c for c in store.campaign_cases(1) if c["state"] == "done"][0]
    assert done["status"] == "evaluated" and done["rank"] is None and done["top_service"] == "ad"


def test_the_next_case_waits_for_the_demo_to_calm_down_again():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(2)
    run_one_case(engine, service, store, clock, gate)
    for incident in store.active_incidents():
        engine.demo.finish(incident["id"], "finished")
    gate.calm = False
    engine.tick()
    assert sum(1 for c in store.campaign_cases(1) if c["state"] == "running") == 0 and store.active_incident() is None
    gate.calm = True
    engine.tick()
    assert sum(1 for c in store.campaign_cases(1) if c["state"] == "running") == 1


def test_the_campaign_finishes_after_the_last_case_and_the_report_covers_only_it():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    seen = events(hub)
    for _ in range(len(CATALOG)):
        run_one_case(engine, service, store, clock, gate)
        clock.advance(2000)
        for incident in store.active_incidents():
            engine.demo.finish(incident["id"], "finished")
    engine.tick()
    campaign = store.latest_campaign()
    assert campaign["state"] == "finished" and campaign["finished_at"] is not None
    report = engine.report()
    assert report["summary"]["cases"] == len(CATALOG) and report["campaign"]["state"] == "finished" and report["campaign"]["done"] == len(CATALOG)
    assert any(e["event"] == "accuracy.updated" for e in seen) and any(e["event"] == "campaign.updated" for e in seen)


def test_manual_simulations_never_enter_the_accuracy():
    engine, service, store, hub, clock, gate, flags = build()
    engine.demo.start("payment_failure")
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    completed_with_ranking(store, identifier, RANKING)
    assert engine.report()["summary"]["cases"] == 0 and engine.report()["campaign"] is None


def test_pausing_stops_new_cases_but_lets_the_running_one_finish():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(2)
    gate.calm = True
    engine.tick()
    engine.pause()
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    completed_with_ranking(store, identifier, RANKING)
    engine.tick()
    assert sum(1 for c in store.campaign_cases(1) if c["state"] == "done") == 1
    gate.calm = True
    engine.tick()
    assert sum(1 for c in store.campaign_cases(1) if c["state"] == "running") == 0
    for incident in store.active_incidents():
        engine.demo.finish(incident["id"], "finished")
    engine.resume()
    gate.calm = True
    engine.tick()
    assert sum(1 for c in store.campaign_cases(1) if c["state"] == "running") == 1


def test_pause_and_resume_validate_the_current_state():
    engine, *_ = build()
    with pytest.raises(CampaignNotFound):
        engine.pause()
    engine.start(1)
    with pytest.raises(CampaignConflict):
        engine.resume()
    engine.pause()
    with pytest.raises(CampaignConflict):
        engine.pause()


def test_stopping_cancels_the_open_cases_and_turns_a_running_fault_off():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(2)
    gate.calm = True
    engine.tick()
    assert store.active_incident() is not None
    view = engine.stop()
    assert view["state"] == "stopped" and store.active_incident() is None
    assert all(c["state"] == "cancelled" for c in store.campaign_cases(1))
    assert store.active_campaign() is None
    with pytest.raises(CampaignNotFound):
        engine.stop()


def test_a_demo_that_never_calms_down_pauses_the_campaign_with_the_reason():
    engine, service, store, hub, clock, gate, flags = build(campaign_calm_timeout_s=1800)
    engine.start(1)
    gate.reason = "a latência do frontend ainda está alta"
    clock.advance(1801)
    engine.tick()
    campaign = store.active_campaign()
    assert campaign["state"] == "paused" and "a latência do frontend" in campaign["pause_reason"] and "30 minutos" in campaign["pause_reason"]
    assert engine.view(campaign)["pause_reason"] == campaign["pause_reason"]


def test_a_flag_service_failure_pauses_instead_of_crashing():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    flags.fail = True
    gate.calm = True
    engine.tick()
    campaign = store.active_campaign()
    assert campaign["state"] == "paused" and "Não consegui ligar a falha" in campaign["pause_reason"]


def test_a_manual_simulation_started_meanwhile_just_makes_the_campaign_wait():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    engine.demo.start("payment_failure")
    gate.calm = True
    engine.tick()
    assert all(c["state"] == "pending" for c in store.campaign_cases(1))


def test_the_eta_uses_the_average_of_the_finished_cases():
    engine, service, store, hub, clock, gate, flags = build()
    view = engine.start(1)
    assert view["eta_s"] == len(CATALOG) * 1200
    run_one_case(engine, service, store, clock, gate)
    assert engine.view(store.active_campaign())["eta_s"] < view["eta_s"]


def test_owns_incident_tells_campaign_incidents_from_manual_ones():
    engine, service, store, hub, clock, gate, flags = build()
    engine.start(1)
    gate.calm = True
    engine.tick()
    assert engine.owns_incident(store.active_incident()["id"]) is True
    assert engine.owns_incident(999) is False and engine.owns_incident(None) is False
