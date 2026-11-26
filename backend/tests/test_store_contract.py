import os
from datetime import datetime, timedelta, timezone

import pytest

from anomalyguard.store import MemoryStore, PostgresStore
from tests.helpers import START, alert

NARRATIVE = {"state": "ready", "kind": "llm", "verified": True, "headline": "h", "paragraphs": ["p [1]"], "evidence": [], "failure_reason": None}
DATABASE = os.environ.get("AG_TEST_DATABASE_URL")


def real_clock():
    return datetime.now(timezone.utc)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return MemoryStore(real_clock)
    if not DATABASE:
        pytest.skip("AG_TEST_DATABASE_URL is not set")
    created = PostgresStore(DATABASE, real_clock)
    with created._connect() as connection, connection.cursor() as cursor:
        cursor.execute("TRUNCATE alert, investigation, demo_incident, campaign RESTART IDENTITY CASCADE; ALTER SEQUENCE investigation_seq RESTART")
    return created


def create(store, service="frontend", ready_in=0):
    return store.create_investigation("FrontendHighErrorRate", service, START, 315, real_clock() + timedelta(seconds=ready_in))


def test_create_and_get_round_trip(store):
    row = create(store)
    got = store.get(row["id"])
    assert got["id"] == "INV-0001" and got["state"] == "received" and got["service"] == "frontend"
    assert got["received_at"] == START and got["margin_s"] == 315
    assert got["grouped_alerts"] == 1 and got["resolved_before_analysis"] is False
    assert got["log"][0]["tag"] == "alerta"


def test_a_missing_investigation_is_none(store):
    assert store.get("INV-9999") is None


def test_alerts_are_remembered_by_fingerprint_start_and_status(store):
    row = create(store)
    first = alert()
    assert store.alert_exists(first.fingerprint, first.starts_at, first.status) is False
    store.add_alert(row["id"], first, "initial")
    assert store.alert_exists(first.fingerprint, first.starts_at, first.status) is True
    assert store.find_by_fingerprint(first.fingerprint)["id"] == row["id"]
    assert store.find_by_fingerprint("other") is None


def test_open_investigations_are_found_by_service(store):
    row = create(store)
    assert store.find_open("frontend")["id"] == row["id"]
    assert store.find_open("cart") is None
    store.save_result(row["id"], [], [], [], {}, [], [])
    store.finish(row["id"], NARRATIVE)
    assert store.find_open("frontend") is None


def test_recent_terminal_investigations_are_found_inside_the_window(store):
    row = create(store)
    store.fail(row["id"], "x")
    assert store.find_recent_terminal("frontend", real_clock() - timedelta(seconds=60))["id"] == row["id"]
    assert store.find_recent_terminal("frontend", real_clock() + timedelta(seconds=60)) is None


def test_grouping_counts_and_resolution_flag(store):
    row = create(store)
    assert store.bump_grouped(row["id"])["grouped_alerts"] == 2
    assert store.mark_resolved(row["id"])["resolved_before_analysis"] is True


def test_resolution_does_not_flag_a_finished_investigation(store):
    row = create(store)
    store.save_result(row["id"], [], [], [], {}, [], [])
    store.finish(row["id"], NARRATIVE)
    assert store.mark_resolved(row["id"])["resolved_before_analysis"] is False


def test_due_investigations_are_the_waiting_ones_whose_data_is_ready(store):
    ready = create(store)
    later = create(store, ready_in=3600)
    store.advance(ready["id"], "waiting", "espera", "x")
    store.advance(later["id"], "waiting", "espera", "x")
    assert [r["id"] for r in store.due(real_clock() + timedelta(seconds=5))] == [ready["id"]]


def test_a_claim_succeeds_only_once(store):
    row = create(store)
    store.advance(row["id"], "waiting", "espera", "x")
    assert store.claim(row["id"]) is True
    assert store.claim(row["id"]) is False
    assert store.get(row["id"])["state"] == "collecting"


def test_working_investigations_are_listed_as_interrupted(store):
    row = create(store)
    store.advance(row["id"], "analyzing", "análise", "x")
    assert [r["id"] for r in store.interrupted()] == [row["id"]]


def test_the_result_moves_to_explaining_and_the_narrative_completes(store):
    row = create(store)
    suspects = [{"rank": 1, "service": "payment", "share": 0.3, "evidence_ids": [1]}]
    evidence = [{"id": 1, "service": "payment", "text": "t"}]
    saved = store.save_result(row["id"], suspects, evidence, ["Sem logs para payment."], {"torai": 5}, ["jaeger"], ["w"])
    assert saved["state"] == "explaining" and saved["suspects"] == suspects and saved["evidence"] == evidence
    assert saved["limitations"] == ["Sem logs para payment."] and saved["timings"] == {"torai": 5} and saved["missing_sources"] == ["jaeger"]
    assert saved["narrative"] is None and [e["tag"] for e in saved["log"]][-2:] == ["análise", "relatório"]
    finished = store.finish(row["id"], NARRATIVE)
    assert finished["state"] == "completed" and finished["narrative"] == NARRATIVE
    assert [e["tag"] for e in finished["log"]][-2:] == ["relatório", "fim"]


def test_a_fixed_narrative_logs_its_reason(store):
    row = create(store)
    store.save_result(row["id"], [], [], [], {}, [], [])
    finished = store.finish(row["id"], dict(NARRATIVE, kind="fixed", verified=None, failure_reason="Gemini indisponível"))
    assert "Gemini indisponível" in finished["log"][-2]["message"]


def test_explaining_investigations_are_listed_as_interrupted(store):
    row = create(store)
    store.save_result(row["id"], [], [], [], {}, [], [])
    assert [r["id"] for r in store.interrupted()] == [row["id"]]


def test_fail_records_the_reason(store):
    row = create(store)
    failed = store.fail(row["id"], "boom")
    assert failed["state"] == "failed" and failed["failure_reason"] == "boom" and failed["log"][-1]["tag"] == "erro"


def test_the_list_is_newest_first_by_alert_time(store):
    older = store.create_investigation("A", "frontend", START, 315, START)
    newer = store.create_investigation("B", "cart", START + timedelta(hours=1), 315, START)
    assert [r["id"] for r in store.list(10)] == [newer["id"], older["id"]]


def seed_history(store):
    ids = {}
    for index, (service, finish) in enumerate([("frontend", "completed"), ("cart", "completed"), ("frontend", "failed"), ("payment", None), ("frontend", None)]):
        row = store.create_investigation("Alerta%d" % index, service, START + timedelta(minutes=index), 315, START)
        if finish == "completed":
            store.save_result(row["id"], [], [], [], {}, [], [])
            store.finish(row["id"], NARRATIVE)
        elif finish == "failed":
            store.fail(row["id"], "boom")
        ids[index] = row["id"]
    return ids


def test_the_list_filters_by_state(store):
    ids = seed_history(store)
    assert [r["id"] for r in store.list(10, state="completed")] == [ids[1], ids[0]]
    assert [r["id"] for r in store.list(10, state="failed")] == [ids[2]]
    assert [r["id"] for r in store.list(10, state="running")] == [ids[4], ids[3]]


def test_the_list_filters_by_service(store):
    ids = seed_history(store)
    assert [r["id"] for r in store.list(10, service="frontend")] == [ids[4], ids[2], ids[0]]
    assert store.list(10, service="nobody") == []


def test_the_filters_combine(store):
    ids = seed_history(store)
    assert [r["id"] for r in store.list(10, state="completed", service="frontend")] == [ids[0]]


def test_the_cursor_continues_after_the_last_row_of_the_previous_page(store):
    ids = seed_history(store)
    first = store.list(2)
    assert [r["id"] for r in first] == [ids[4], ids[3]]
    last = first[-1]
    second = store.list(2, cursor=(last["received_at"], last["id"]))
    third = store.list(2, cursor=(second[-1]["received_at"], second[-1]["id"]))
    assert [r["id"] for r in second] == [ids[2], ids[1]] and [r["id"] for r in third] == [ids[0]]


def test_the_cursor_works_together_with_a_filter(store):
    ids = seed_history(store)
    page = store.list(1, service="frontend")
    rest = store.list(5, cursor=(page[0]["received_at"], page[0]["id"]), service="frontend")
    assert [r["id"] for r in rest] == [ids[2], ids[0]]


def test_the_count_follows_the_same_filters(store):
    seed_history(store)
    assert store.count() == 5 and store.count(state="running") == 2 and store.count(state="completed") == 2 and store.count(state="failed") == 1
    assert store.count(service="frontend") == 3 and store.count(state="completed", service="frontend") == 1


def test_the_services_are_listed_with_their_counts(store):
    seed_history(store)
    assert store.services() == [{"service": "cart", "count": 1}, {"service": "frontend", "count": 3}, {"service": "payment", "count": 1}]


def make_incident(store, state="active", offset=0):
    started = real_clock() + timedelta(seconds=offset)
    incident = store.create_incident("payment_failure", "paymentFailure", "100%", started, started + timedelta(minutes=7))
    if state != "active":
        store.finish_incident(incident["id"], state, real_clock(), None)
    return incident


def test_an_incident_is_stored_and_found_as_active(store):
    incident = make_incident(store)
    assert incident["state"] == "active" and incident["flag"] == "paymentFailure" and incident["finished_at"] is None
    assert store.get_incident(incident["id"])["variant"] == "100%"
    assert store.active_incident()["id"] == incident["id"] and [i["id"] for i in store.active_incidents()] == [incident["id"]]


def test_a_finished_incident_is_no_longer_active_and_keeps_its_reason(store):
    incident = make_incident(store)
    done = store.finish_incident(incident["id"], "failed", real_clock(), "demo fora do ar")
    assert done["state"] == "failed" and done["failure_reason"] == "demo fora do ar" and done["finished_at"] is not None
    assert store.active_incident() is None and store.active_incidents() == []


def test_the_latest_incident_is_the_newest_one(store):
    assert store.latest_incident() is None
    make_incident(store, "finished")
    newest = make_incident(store, "stopped")
    assert store.latest_incident()["id"] == newest["id"]


def test_the_first_investigation_since_a_moment_is_the_oldest_one_created_after_it(store):
    before = create(store)
    cut = real_clock()
    after_first = create(store, service="cart")
    create(store, service="payment")
    assert store.first_investigation_since(cut)["id"] == after_first["id"]
    assert store.first_investigation_since(real_clock() + timedelta(seconds=60)) is None
    assert before["id"] != after_first["id"]


def test_working_investigations_without_news_for_long_are_stale(store):
    row = create(store)
    store.advance(row["id"], "analyzing", "análise", "x")
    done = create(store, service="cart")
    store.fail(done["id"], "x")
    assert [r["id"] for r in store.stale(real_clock() + timedelta(seconds=60))] == [row["id"]]
    assert store.stale(real_clock() - timedelta(seconds=60)) == []


def test_the_full_ranking_is_saved_with_the_result(store):
    row = create(store)
    ranking = [{"position": 1, "service": "frontend", "score": 0.23}, {"position": 2, "service": "payment", "score": 0.2}]
    saved = store.save_result(row["id"], [], [], [], {}, [], [], ranking)
    assert saved["ranking"] == ranking and store.get(row["id"])["ranking"] == ranking
    assert store.save_result(create(store, service="cart")["id"], [], [], [], {}, [], [])["ranking"] == []


def test_a_ground_truth_is_stored_read_and_replaced(store):
    row = create(store)
    assert store.get_ground_truth(row["id"]) is None
    truth = store.set_ground_truth(row["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    assert truth["root_cause_service"] == "payment" and truth["source"] == "simulation" and truth["recorded_at"] is not None
    replaced = store.set_ground_truth(row["id"], "cart", "manual", None, "manual", None)
    assert store.get_ground_truth(row["id"])["root_cause_service"] == "cart" and replaced["source"] == "manual"


def test_truths_are_fetched_for_a_page_of_investigations(store):
    first, second, third = create(store), create(store, service="cart"), create(store, service="payment")
    store.set_ground_truth(first["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    store.set_ground_truth(third["id"], "cart", "manual", None, "manual", None)
    found = store.ground_truths([first["id"], second["id"], third["id"]])
    assert set(found) == {first["id"], third["id"]} and found[first["id"]]["root_cause_service"] == "payment"
    assert store.ground_truths([]) == {}


def test_the_labeled_cases_pair_each_investigation_with_its_truth_newest_first(store):
    older = store.create_investigation("A", "frontend", START, 315, START)
    newer = store.create_investigation("B", "cart", START + timedelta(hours=1), 315, START)
    create(store, service="payment")
    store.set_ground_truth(older["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    store.set_ground_truth(newer["id"], "cart", "manual", None, "manual", None)
    pairs = store.labeled()
    assert [row["id"] for row, _ in pairs] == [newer["id"], older["id"]] and pairs[1][1]["root_cause_service"] == "payment"


def test_deleting_an_investigation_deletes_its_truth(store):
    if not hasattr(store, "_connect"):
        pytest.skip("only the database enforces the cascade")
    row = create(store)
    store.set_ground_truth(row["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    with store._connect() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM investigation WHERE id = %s", (row["id"],))
    assert store.get_ground_truth(row["id"]) is None


def test_an_incident_keeps_the_root_cause_it_was_started_with(store):
    started = real_clock()
    incident = store.create_incident("payment_failure", "paymentFailure", "100%", started, started + timedelta(minutes=7), "payment", "trace_err")
    assert incident["root_cause_service"] == "payment" and incident["expected_signal"] == "trace_err"
    assert store.get_incident(incident["id"])["root_cause_service"] == "payment"


def test_the_incident_covering_a_moment_is_found_with_a_margin_after_it_ended(store):
    started = real_clock()
    incident = store.create_incident("payment_failure", "paymentFailure", "100%", started, started + timedelta(minutes=7), "payment", "trace_err")
    assert store.incident_covering(started + timedelta(minutes=3))["id"] == incident["id"]
    assert store.incident_covering(started + timedelta(minutes=8))["id"] == incident["id"]
    assert store.incident_covering(started + timedelta(minutes=10)) is None
    assert store.incident_covering(started - timedelta(seconds=30)) is None


def test_a_stopped_early_incident_covers_only_until_it_stopped_plus_the_margin(store):
    started = real_clock()
    incident = store.create_incident("payment_failure", "paymentFailure", "100%", started, started + timedelta(minutes=7), "payment", "trace_err")
    store.finish_incident(incident["id"], "stopped", started + timedelta(minutes=2), None)
    assert store.incident_covering(started + timedelta(minutes=3))["id"] == incident["id"]
    assert store.incident_covering(started + timedelta(minutes=5)) is None


def test_a_snapshot_is_stored_read_and_listed(store):
    first, second = create(store), create(store, service="cart")
    payload = {"tables": {"metrics": {"time": [0, 15], "a|cpu": [1.5, None]}}, "catalog": {"a": {}}, "coverage": {}, "plan": {"margin_s": 315}}
    assert store.get_snapshot(first["id"]) is None
    store.save_snapshot(first["id"], payload)
    assert store.get_snapshot(first["id"]) == payload
    assert store.snapshot_ids([first["id"], second["id"]]) == {first["id"]} and store.snapshot_ids([]) == set()


def test_saving_a_snapshot_again_replaces_it(store):
    row = create(store)
    store.save_snapshot(row["id"], {"v": 1})
    store.save_snapshot(row["id"], {"v": 2})
    assert store.get_snapshot(row["id"]) == {"v": 2}


def test_a_replay_is_stored_with_its_link_and_its_own_first_message(store):
    source = create(store)
    replay = store.create_investigation("A", "frontend", START, 315, START, replay_of=source["id"], first_message="Reprodução do caso x")
    got = store.get(replay["id"])
    assert got["replay_of"] == source["id"] and got["log"][0]["message"] == "Reprodução do caso x" and store.get(source["id"])["replay_of"] is None


def test_replays_never_count_as_open_recent_labeled_or_linked_investigations(store):
    source = create(store)
    store.set_ground_truth(source["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    cut = real_clock() - timedelta(seconds=5)
    replay = store.create_investigation("A", "frontend", START, 315, START, replay_of=source["id"])
    store.set_ground_truth(replay["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    assert store.find_open("frontend")["id"] == source["id"]
    store.fail(source["id"], "x")
    store.fail(replay["id"], "x")
    assert store.find_recent_terminal("frontend", real_clock() - timedelta(seconds=60))["id"] == source["id"]
    assert [row["id"] for row, _ in store.labeled()] == [source["id"]]
    assert store.first_investigation_since(cut)["id"] == source["id"]


def test_deleting_investigations_removes_them_and_reports_which(store):
    first, second = create(store), create(store, service="cart")
    store.set_ground_truth(first["id"], "payment", "payment_failure", "trace_err", "simulation", None)
    assert store.delete_investigations([first["id"], "INV-9999"]) == [first["id"]]
    assert store.get(first["id"]) is None and store.get_ground_truth(first["id"]) is None and store.get(second["id"]) is not None
    assert store.delete_investigations([]) == []


def test_terminal_ids_lists_only_finished_investigations(store):
    running, done = create(store), create(store, service="cart")
    store.fail(done["id"], "x")
    assert store.terminal_ids() == [done["id"]] and running["id"] not in store.terminal_ids()


def test_a_campaign_is_stored_with_its_ordered_cases_and_can_be_updated(store):
    started = START
    campaign = store.create_campaign(2, ["payment_failure", "product_catalog_failure", "payment_failure", "product_catalog_failure"], started)
    assert campaign["state"] == "running" and campaign["total"] == 4 and campaign["per_fault"] == 2 and campaign["phase_since"] == started
    cases = store.campaign_cases(campaign["id"])
    assert [c["kind"] for c in cases] == ["payment_failure", "product_catalog_failure", "payment_failure", "product_catalog_failure"]
    assert [c["position"] for c in cases] == [0, 1, 2, 3] and all(c["state"] == "pending" for c in cases)
    updated = store.update_case(cases[0]["id"], state="done", status="evaluated", rank=2, top_service="frontend", root_cause_service="payment", investigation_id="INV-0001", finished_at=started)
    assert updated["rank"] == 2 and updated["status"] == "evaluated" and store.campaign_cases(campaign["id"])[0]["state"] == "done"
    paused = store.update_campaign(campaign["id"], state="paused", pause_reason="demo ocupado")
    assert paused["state"] == "paused" and paused["pause_reason"] == "demo ocupado"
    assert store.active_campaign()["id"] == campaign["id"] and store.latest_campaign()["id"] == campaign["id"]


def test_only_a_running_or_paused_campaign_is_active_and_open_cases_can_be_cancelled(store):
    campaign = store.create_campaign(1, ["payment_failure", "product_catalog_failure"], START)
    done = store.campaign_cases(campaign["id"])[0]
    store.update_case(done["id"], state="done", status="no_alert")
    store.cancel_open_cases(campaign["id"])
    states = [c["state"] for c in store.campaign_cases(campaign["id"])]
    assert states == ["done", "cancelled"]
    store.update_campaign(campaign["id"], state="stopped")
    assert store.active_campaign() is None and store.latest_campaign()["state"] == "stopped"


def test_a_case_is_found_by_its_incident_and_there_is_no_active_campaign_at_first(store):
    assert store.active_campaign() is None and store.latest_campaign() is None and store.campaign_case_for_incident(1) is None
    campaign = store.create_campaign(1, ["payment_failure"], START)
    case = store.campaign_cases(campaign["id"])[0]
    store.update_case(case["id"], state="running", incident_id=7, started_at=START)
    assert store.campaign_case_for_incident(7)["id"] == case["id"] and store.campaign_case_for_incident(8) is None
