from datetime import timedelta

from tests.helpers import EVIDENCE, RANKING, START, SUSPECT, Recorder, alert, completed_with_ranking, finish_row, world


def test_a_new_alert_opens_an_investigation_that_waits_for_the_data():
    service, store, hub, clock, config = world()
    global_events, = [Recorder(hub, "*")]
    outcome = service.ingest(alert())
    row = store.get(outcome.investigation_id)
    assert outcome.action == "new_investigation"
    assert row["state"] == "waiting"
    assert row["ready_at"] == START + timedelta(seconds=config.delta_s + config.data_lag_s)
    assert global_events.names()[0] == "investigation.created"
    assert "investigation.updated" in global_events.names()
    assert row["log"][-1]["tag"] == "espera"


def test_the_margin_comes_from_the_annotations_or_the_default():
    service, store, *_ = world()
    annotations = {"export_interval_s": "60", "rate_window_s": "120", "for_s": "60", "eval_interval_s": "15"}
    with_margin = store.get(service.ingest(alert(annotations={"export_interval_s": "30", "rate_window_s": "60", "for_s": "30", "eval_interval_s": "15"})).investigation_id)
    assert with_margin["margin_s"] == 30 + 60 + 30 + 15 + 60
    other = store.get(service.ingest(alert(service="cart", fingerprint="fp-2")).investigation_id)
    assert other["margin_s"] == 315
    assert annotations


def test_a_second_alert_for_the_same_service_joins_the_open_investigation():
    service, store, *_ = world()
    first = service.ingest(alert())
    second = service.ingest(alert(name="FrontendHighLatency", fingerprint="fp-2"))
    assert second.action == "grouped" and second.investigation_id == first.investigation_id
    assert store.get(first.investigation_id)["grouped_alerts"] == 2
    assert len(store.rows) == 1


def test_an_alert_for_another_service_opens_another_investigation():
    service, store, *_ = world()
    service.ingest(alert())
    service.ingest(alert(service="cart", fingerprint="fp-2"))
    assert len(store.rows) == 2


def test_the_same_alert_delivered_twice_is_ignored():
    service, store, *_ = world()
    service.ingest(alert())
    again = service.ingest(alert())
    assert again.action == "repeated" and len(store.rows) == 1
    assert store.get("INV-0001")["grouped_alerts"] == 1


def test_an_alert_that_returns_inside_the_window_is_attached_as_a_recurrence():
    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    finish_row(store, identifier)
    clock.advance(config.group_window_s - 10)
    again = service.ingest(alert(fingerprint="fp-2", starts_at=clock.now))
    assert again.action == "recurrence" and again.investigation_id == identifier


def test_an_alert_that_returns_after_the_window_opens_a_new_investigation():
    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    finish_row(store, identifier)
    clock.advance(config.group_window_s + 10)
    again = service.ingest(alert(fingerprint="fp-2", starts_at=clock.now))
    assert again.action == "new_investigation" and again.investigation_id != identifier


def test_a_resolved_alert_before_the_analysis_is_flagged_and_the_investigation_continues():
    service, store, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    outcome = service.ingest(alert(status="resolved", ends_at=START + timedelta(minutes=2)))
    row = store.get(identifier)
    assert outcome.action == "resolved_attached"
    assert row["resolved_before_analysis"] is True and row["state"] == "waiting"
    assert "resolvido antes da análise" in row["log"][-1]["message"]


def test_a_resolved_alert_after_completion_does_not_flag_the_investigation():
    service, store, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    finish_row(store, identifier)
    service.ingest(alert(status="resolved", ends_at=START + timedelta(minutes=9)))
    assert store.get(identifier)["resolved_before_analysis"] is False


def test_a_resolved_alert_of_an_unknown_fingerprint_is_ignored():
    service, store, *_ = world()
    outcome = service.ingest(alert(status="resolved", fingerprint="never-seen", ends_at=START + timedelta(minutes=2)))
    assert outcome.action == "ignored" and store.rows == {}


def test_advancing_publishes_stage_log_and_summary_events():
    service, store, hub, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    topic, global_topic = Recorder(hub, identifier), Recorder(hub, "*")
    service.advance(identifier, "collecting", "coleta", "Coletando")
    assert topic.names() == ["stage", "log"]
    assert topic.events[0]["data"] == {"state": "collecting", "stage": 2}
    assert topic.events[1]["data"]["message"] == "Coletando"
    assert global_topic.names() == ["investigation.updated"]


def test_the_result_publishes_the_suspects_and_moves_to_the_report_stage():
    from anomalyguard.analysis import AnalysisResult
    service, store, hub, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    topic = Recorder(hub, identifier)
    service.analysis_done(identifier, AnalysisResult([SUSPECT], {"torai": 5}, [], [], [EVIDENCE], ["Sem logs para payment."]))
    row = store.get(identifier)
    assert topic.names() == ["suspects", "stage", "log", "log"]
    assert topic.events[0]["data"]["suspects"][0]["evidence_ids"] == [1]
    assert topic.events[0]["data"]["evidence"] == [{"id": 1, "service": "payment", "text": EVIDENCE["text"]}]
    assert topic.events[0]["data"]["limitations"] == ["Sem logs para payment."]
    assert topic.events[1]["data"] == {"state": "explaining", "stage": 5}
    assert row["evidence"] == [EVIDENCE] and row["limitations"] == ["Sem logs para payment."]


def test_narrative_chunks_are_published_and_kept_as_a_partial_view():
    service, store, hub, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    store.save_result(identifier, [SUSPECT], [EVIDENCE], [], {}, [], [])
    topic = Recorder(hub, identifier)
    service.narrative_chunk(identifier, 0, "payment é ")
    service.narrative_chunk(identifier, 0, "o suspeito.")
    service.narrative_chunk(identifier, 1, "Veja [1].")
    assert topic.events[0]["data"] == {"paragraph": 0, "text": "payment é "}
    partial = service.detail(identifier)["narrative"]
    assert partial["state"] == "writing" and partial["headline"] == "payment é o suspeito." and partial["paragraphs"] == ["Veja [1]."]
    assert partial["evidence"][0]["id"] == 1


def test_a_reset_clears_the_partial_view():
    service, store, hub, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    topic = Recorder(hub, identifier)
    service.narrative_chunk(identifier, 0, "texto")
    service.narrative_reset(identifier)
    assert service.detail(identifier)["narrative"] is None and topic.names()[-1] == "narrative.reset"


def test_finishing_stores_the_narrative_and_completes():
    service, store, hub, *_ = world()
    identifier = service.ingest(alert()).investigation_id
    store.save_result(identifier, [SUSPECT], [EVIDENCE], [], {}, [], [])
    service.narrative_chunk(identifier, 0, "parcial")
    topic = Recorder(hub, identifier)
    narrative = {"state": "ready", "kind": "llm", "verified": True, "headline": "h", "paragraphs": ["p [1]"], "evidence": [], "failure_reason": None}
    service.finish(identifier, narrative)
    row = store.get(identifier)
    assert row["state"] == "completed" and row["narrative"] == narrative
    assert topic.names() == ["narrative.done", "stage", "log", "log"]
    assert "verificada" in row["log"][-2]["message"] and service.detail(identifier)["narrative"] == narrative


def test_a_new_simulation_never_attaches_its_alert_to_an_investigation_finished_before_it_started():
    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    finish_row(store, identifier)
    clock.advance(60)
    store.create_incident("payment_failure", "paymentFailure", "100%", clock.now, clock.now + timedelta(seconds=420))
    clock.advance(30)
    again = service.ingest(alert(fingerprint="fp-2", starts_at=clock.now))
    assert again.action == "new_investigation" and again.investigation_id != identifier


def test_an_alert_inside_the_window_still_attaches_when_the_simulation_started_before_that_investigation():
    service, store, hub, clock, config = world()
    store.create_incident("payment_failure", "paymentFailure", "100%", clock.now, clock.now + timedelta(seconds=420))
    clock.advance(30)
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    finish_row(store, identifier)
    clock.advance(60)
    again = service.ingest(alert(fingerprint="fp-2", starts_at=clock.now))
    assert again.action == "recurrence" and again.investigation_id == identifier


def start_simulation(store, clock, duration=420):
    return store.create_incident("payment_failure", "paymentFailure", "100%", clock.now, clock.now + timedelta(seconds=duration), "payment", "trace_err")


def test_an_investigation_opened_by_an_alert_during_a_simulation_gets_the_simulations_truth():
    service, store, hub, clock, config = world()
    incident = start_simulation(store, clock)
    clock.advance(180)
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    truth = store.get_ground_truth(identifier)
    assert truth["root_cause_service"] == "payment" and truth["source"] == "simulation" and truth["incident_id"] == incident["id"]
    assert truth["fault_kind"] == "payment_failure" and truth["expected_signal"] == "trace_err"


def test_an_alert_that_fired_when_no_simulation_was_running_gets_no_truth():
    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    assert store.get_ground_truth(identifier) is None


def test_an_alert_long_after_the_simulation_ended_gets_no_truth():
    service, store, hub, clock, config = world()
    start_simulation(store, clock)
    clock.advance(420 + 600)
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    assert store.get_ground_truth(identifier) is None


def test_an_alert_just_after_the_fault_was_turned_off_still_belongs_to_the_simulation():
    service, store, hub, clock, config = world()
    start_simulation(store, clock)
    clock.advance(420 + 60)
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    assert store.get_ground_truth(identifier)["root_cause_service"] == "payment"


def test_an_alert_that_only_joins_an_investigation_does_not_create_another_truth():
    service, store, hub, clock, config = world()
    start_simulation(store, clock)
    clock.advance(180)
    first = service.ingest(alert(starts_at=clock.now)).investigation_id
    service.ingest(alert(name="FrontendHighLatency", fingerprint="fp-2", starts_at=clock.now))
    assert list(store.truths) == [first]


def test_the_summary_events_carry_the_evaluation_once_the_investigation_completes():
    service, store, hub, clock, config = world()
    start_simulation(store, clock)
    clock.advance(180)
    identifier = service.ingest(alert(starts_at=clock.now)).investigation_id
    topic = Recorder(hub, "*")
    from anomalyguard.analysis import AnalysisResult
    service.analysis_done(identifier, AnalysisResult([SUSPECT], {}, [], [], [EVIDENCE], [], RANKING))
    service.finish(identifier, {"state": "ready", "kind": "fixed", "verified": None, "headline": "h", "paragraphs": [], "evidence": [], "failure_reason": None})
    last = topic.events[-1]["data"]["gabarito"]
    assert last == {"root_cause_service": "payment", "rank": 2, "top1": False, "top3": True, "status": "evaluated"}
