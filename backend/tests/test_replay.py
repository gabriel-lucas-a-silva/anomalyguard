from datetime import datetime, timezone

import pytest

from anomalyguard import snapshot
from anomalyguard.analysis import AnalysisResult, analyze_full
from anomalyguard.runner import Runner
from anomalyguard.service import ReplayConflict, ReplayNotFound
from anomalyguard.windows import Plan
from tests.helpers import alert, synthetic_case, world
from tests.synthetic import t_alert

NARRATIVE = {"state": "ready", "kind": "llm", "verified": True, "headline": "h", "paragraphs": ["p [1]"], "evidence": [], "failure_reason": None}


class FakeNarrator:
    def __init__(self):
        self.clock = lambda: 0.0

    def write(self, context, on_chunk, on_reset):
        on_chunk(0, "h")
        return NARRATIVE

    def fixed(self, context, reason, started, attempts):
        return dict(NARRATIVE, kind="fixed", verified=None, failure_reason=reason)


def completed_source(with_truth=True, with_snapshot=True):
    service, store, hub, clock, config = world()
    plan = Plan(datetime.fromtimestamp(t_alert(), timezone.utc), 600, 315, 180)
    frames, prepared = synthetic_case()
    if with_truth:
        store.create_incident("payment_failure", "paymentFailure", "100%", clock.now, clock.now, "payment", "trace_err")
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    suspects, evidence, ranking = analyze_full(frames, prepared, t_alert(), plan)
    payload = snapshot.freeze(prepared, plan)
    service.analysis_done(identifier, AnalysisResult(suspects, {}, [], [], evidence, [], ranking, payload))
    if with_snapshot:
        store.save_snapshot(identifier, payload)
    service.finish(identifier, NARRATIVE)
    return service, store, hub, clock, config, identifier, (suspects, evidence, ranking)


def test_a_replay_is_a_new_investigation_linked_to_the_original():
    service, store, hub, clock, config, source, _ = completed_source()
    new_id = service.open_replay(source)
    row = store.get(new_id)
    assert new_id != source and row["replay_of"] == source and row["state"] == "collecting"
    assert row["log"][0]["message"] == "Reprodução do caso %s, sobre os dados gravados na época" % source
    assert row["alert_name"] == store.get(source)["alert_name"] and row["service"] == "frontend"


def test_a_replay_keeps_the_gabarito_of_the_original():
    service, store, hub, clock, config, source, _ = completed_source()
    new_id = service.open_replay(source)
    assert store.get_ground_truth(new_id)["root_cause_service"] == "payment"


def test_a_replay_of_a_case_without_gabarito_has_none():
    service, store, hub, clock, config, source, _ = completed_source(with_truth=False)
    assert store.get_ground_truth(service.open_replay(source)) is None


def test_only_a_completed_investigation_with_recorded_data_can_be_replayed():
    with pytest.raises(ReplayNotFound):
        completed_source()[0].open_replay("INV-9999")
    service, store, *_ = completed_source(with_snapshot=False)
    with pytest.raises(ReplayConflict, match="dados gravados"):
        service.open_replay("INV-0001")
    service, store, hub, clock, config = world()
    waiting = service.ingest(alert()).investigation_id
    store.save_snapshot(waiting, {"x": 1})
    with pytest.raises(ReplayConflict, match="concluída"):
        service.open_replay(waiting)


def test_a_replay_in_progress_never_swallows_a_real_alert():
    service, store, hub, clock, config, source, _ = completed_source()
    replay = service.open_replay(source)
    clock.advance(config.group_window_s + 10)
    outcome = service.ingest(alert(fingerprint="real", starts_at=clock.now))
    assert store.get(replay)["state"] == "collecting"
    assert outcome.action == "new_investigation" and outcome.investigation_id not in (source, replay)
    assert store.get(outcome.investigation_id)["replay_of"] is None


def test_running_the_replay_gives_the_same_result_as_the_original():
    service, store, hub, clock, config, source, original = completed_source()
    new_id = service.open_replay(source)
    Runner(service, None, config, FakeNarrator()).run_replay(new_id, source)
    row = store.get(new_id)
    assert row["state"] == "completed" and row["suspects"] == original[0] and row["evidence"] == original[1] and row["ranking"] == original[2]
    assert row["narrative"]["verified"] is True


def test_a_replay_can_itself_be_replayed():
    service, store, hub, clock, config, source, original = completed_source()
    first = service.open_replay(source)
    Runner(service, None, config, FakeNarrator()).run_replay(first, source)
    second = service.open_replay(first)
    Runner(service, None, config, FakeNarrator()).run_replay(second, first)
    assert store.get(second)["suspects"] == original[0] and store.get(second)["replay_of"] == first


def test_the_replay_shows_the_evaluation_of_the_case():
    service, store, hub, clock, config, source, _ = completed_source()
    new_id = service.open_replay(source)
    Runner(service, None, config, FakeNarrator()).run_replay(new_id, source)
    view = service.detail(new_id)["gabarito"]
    assert view["root_cause_service"] == "payment" and view["status"] == "evaluated" and view["rank"] == 1


def test_a_replay_whose_data_disappeared_fails_with_the_reason():
    service, store, hub, clock, config, source, _ = completed_source()
    new_id = service.open_replay(source)
    del store.snapshots[source]
    Runner(service, None, config, FakeNarrator()).run_replay(new_id, source)
    row = store.get(new_id)
    assert row["state"] == "failed" and "não foram encontrados" in row["failure_reason"]


def test_the_detail_says_whether_a_case_can_be_replayed():
    service, store, hub, clock, config, source, _ = completed_source()
    assert service.detail(source)["replayable"] is True
    waiting = service.ingest(alert(service="cart", fingerprint="x")).investigation_id
    assert service.detail(waiting)["replayable"] is False


def test_replays_are_left_out_of_the_evaluation_and_of_the_simulation_link():
    service, store, hub, clock, config, source, _ = completed_source()
    new_id = service.open_replay(source)
    assert [row["id"] for row, _ in store.labeled()] == [source]
    assert store.first_investigation_since(clock.now)["id"] != new_id if store.first_investigation_since(clock.now) else True
