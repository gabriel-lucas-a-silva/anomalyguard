import pytest
from fastapi.testclient import TestClient

from anomalyguard.api import create_app
from anomalyguard.demo import DemoIncidents
from anomalyguard.flags import FlagError
from tests.helpers import EVIDENCE, RANKING, START, SUSPECT, completed_with_ranking, finish_row, raw_alert, world

HEADERS = {"Authorization": "Bearer secret"}


@pytest.fixture
def parts():
    service, store, hub, clock, config = world()
    return TestClient(create_app(service, store, hub, config)), store, service


def webhook(*alerts):
    return {"version": "4", "status": "firing", "alerts": list(alerts)}


def test_the_webhook_requires_the_token(parts):
    client, _, _ = parts
    assert client.post("/webhooks/alertmanager", json=webhook(raw_alert())).status_code == 401
    assert client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers={"Authorization": "secret"}).status_code == 401


def test_a_valid_webhook_opens_an_investigation(parts):
    client, store, _ = parts
    response = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {"received": 1, "outcomes": [{"action": "new_investigation", "id": "INV-0001"}]}
    assert store.get("INV-0001")["state"] == "waiting"


def test_a_webhook_with_two_alerts_of_the_same_service_makes_one_investigation(parts):
    client, store, _ = parts
    body = webhook(raw_alert(), raw_alert(name="FrontendHighLatency", fingerprint="fp-2"))
    response = client.post("/webhooks/alertmanager", json=body, headers=HEADERS)
    assert [o["action"] for o in response.json()["outcomes"]] == ["new_investigation", "grouped"]
    assert len(store.rows) == 1


def test_an_invalid_webhook_is_a_400_with_the_reason(parts):
    client, store, _ = parts
    response = client.post("/webhooks/alertmanager", json={"alerts": [{"status": "firing"}]}, headers=HEADERS)
    assert response.status_code == 400 and "alertname" in response.json()["detail"]
    assert client.post("/webhooks/alertmanager", json={"x": 1}, headers=HEADERS).status_code == 400
    assert store.rows == {}


def test_the_same_webhook_delivered_twice_is_idempotent(parts):
    client, store, _ = parts
    client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS)
    again = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS)
    assert again.json()["outcomes"] == [{"action": "repeated", "id": None}]
    assert len(store.rows) == 1


def test_the_manual_route_opens_an_investigation_that_waits(parts):
    client, store, _ = parts
    response = client.post("/api/investigations", json={"alert_name": "FrontendHighErrorRate", "service": "frontend", "starts_at": "2026-11-22T02:06:40Z"})
    assert response.status_code == 202
    assert response.json() == {"id": "INV-0001", "action": "new_investigation"}
    assert store.get("INV-0001")["state"] == "waiting"


def test_a_manual_timestamp_without_timezone_is_rejected(parts):
    client, _, _ = parts
    body = {"alert_name": "X", "service": "frontend", "starts_at": "2026-11-22T02:06:40"}
    assert client.post("/api/investigations", json=body).status_code == 422


def test_the_detail_follows_the_contract(parts):
    client, store, service = parts
    identifier = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS).json()["outcomes"][0]["id"]
    finish_row(store, identifier, [SUSPECT], [EVIDENCE])
    detail = client.get("/api/investigations/" + identifier).json()
    assert set(detail) == {"summary", "gabarito", "replayable", "failure_reason", "log", "suspects", "narrative", "evidence", "limitations", "timings_ms", "missing_sources"}
    assert detail["summary"] == {"id": identifier, "alert_name": "FrontendHighErrorRate", "service": "frontend", "received_at": "2026-11-22T02:06:40Z",
                                 "state": "completed", "stage": 6, "top_suspect": {"service": "payment", "share": 0.4},
                                 "grouped_alerts": 1, "resolved_before_analysis": False, "replay_of": None, "gabarito": None}
    assert detail["suspects"][0]["evidence_ids"] == [1] and detail["narrative"]["kind"] == "fixed"
    assert detail["evidence"] == [{"id": 1, "service": "payment", "text": EVIDENCE["text"]}]


def test_a_waiting_investigation_is_on_the_wait_stage(parts):
    client, _, _ = parts
    identifier = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS).json()["outcomes"][0]["id"]
    summary = client.get("/api/investigations/" + identifier).json()["summary"]
    assert summary["state"] == "waiting" and summary["stage"] == 1 and summary["top_suspect"] is None


def test_the_list_shows_the_newest_first(parts):
    client, _, _ = parts
    client.post("/webhooks/alertmanager", json=webhook(raw_alert(starts_at=START)), headers=HEADERS)
    client.post("/webhooks/alertmanager", json=webhook(raw_alert(service="cart", fingerprint="fp-2", starts_at=START.replace(hour=3))), headers=HEADERS)
    items = client.get("/api/investigations").json()["items"]
    assert [i["service"] for i in items] == ["cart", "frontend"]


def test_a_failed_investigation_keeps_the_stage_it_reached(parts):
    client, store, service = parts
    identifier = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS).json()["outcomes"][0]["id"]
    service.advance(identifier, "collecting", "coleta", "Coletando")
    service.fail(identifier, "fonte indisponível")
    summary = client.get("/api/investigations/" + identifier).json()["summary"]
    assert summary["state"] == "failed" and summary["stage"] == 2


def test_unknown_investigations_are_404_for_detail_and_events(parts):
    client, _, _ = parts
    assert client.get("/api/investigations/INV-9999").status_code == 404
    assert client.get("/api/investigations/INV-9999/events").status_code == 404


def open_many(client, count, service="frontend", start_hour=0):
    for index in range(count):
        moment = START.replace(hour=start_hour, minute=index)
        client.post("/webhooks/alertmanager", json=webhook(raw_alert(service=service, fingerprint="%s-%d-%d" % (service, start_hour, index), starts_at=moment)), headers=HEADERS)


def test_the_list_is_paginated_with_a_cursor_and_a_total(parts):
    client, store, service = parts
    for index in range(5):
        client.post("/webhooks/alertmanager", json=webhook(raw_alert(service="svc%d" % index, fingerprint="fp-%d" % index, starts_at=START.replace(minute=index))), headers=HEADERS)
    first = client.get("/api/investigations?limit=2").json()
    assert [i["service"] for i in first["items"]] == ["svc4", "svc3"] and first["total"] == 5 and first["next_cursor"]
    second = client.get("/api/investigations?limit=2&cursor=" + first["next_cursor"]).json()
    assert [i["service"] for i in second["items"]] == ["svc2", "svc1"] and second["next_cursor"]
    third = client.get("/api/investigations?limit=2&cursor=" + second["next_cursor"]).json()
    assert [i["service"] for i in third["items"]] == ["svc0"] and third["next_cursor"] is None


def test_the_last_page_has_no_cursor_even_when_it_is_exactly_full(parts):
    client, _, _ = parts
    for index in range(2):
        client.post("/webhooks/alertmanager", json=webhook(raw_alert(service="s%d" % index, fingerprint="f%d" % index, starts_at=START.replace(minute=index))), headers=HEADERS)
    assert client.get("/api/investigations?limit=2").json()["next_cursor"] is None


def test_the_list_filters_by_state_and_service(parts):
    client, store, service = parts
    for name in ("cart", "frontend", "payment"):
        client.post("/webhooks/alertmanager", json=webhook(raw_alert(service=name, fingerprint="fp-" + name)), headers=HEADERS)
    service.fail("INV-0002", "boom")
    finish_row(store, "INV-0003")
    failed = client.get("/api/investigations?state=failed").json()
    assert [i["service"] for i in failed["items"]] == ["frontend"] and failed["total"] == 1
    assert client.get("/api/investigations?state=completed").json()["total"] == 1
    assert client.get("/api/investigations?state=running").json()["total"] == 1
    assert [i["id"] for i in client.get("/api/investigations?service=cart").json()["items"]] == ["INV-0001"]
    assert client.get("/api/investigations?state=failed&service=cart").json() == {"items": [], "next_cursor": None, "total": 0}


@pytest.mark.parametrize("query", ["state=quase", "limit=0", "limit=201", "cursor=lixo", "cursor=bm9fdGltZXN0YW1w"])
def test_invalid_list_parameters_are_rejected(parts, query):
    client, _, _ = parts
    assert client.get("/api/investigations?" + query).status_code in (400, 422)


def test_the_facets_list_the_services_and_the_state_counts(parts):
    client, store, service = parts
    for index, name in enumerate(("cart", "frontend", "cart")):
        client.post("/webhooks/alertmanager", json=webhook(raw_alert(service=name, fingerprint="fp-%d" % index, starts_at=START.replace(minute=index))), headers=HEADERS)
    facets = client.get("/api/investigations/facets").json()
    assert facets["services"] == [{"service": "cart", "count": 1}, {"service": "frontend", "count": 1}]
    assert facets["states"] == {"running": 2, "completed": 0, "failed": 0}


class StubFlags:
    def __init__(self):
        self.values = {"paymentFailure": "off"}
        self.error = None

    def set(self, flag, variant):
        if self.error:
            raise self.error
        self.values[flag] = variant


PAYMENT = {"kind": "payment_failure"}


def demo_parts(demo_mode=True):
    service, store, hub, clock, config = world(demo_mode=demo_mode)
    flags = StubFlags()
    demo = DemoIncidents(store, flags, config, clock, lambda delay, function: (lambda: None))
    return TestClient(create_app(service, store, hub, config, demo=demo, narrator_on=True)), flags, store


def test_health_tells_the_site_whether_the_demo_mode_and_the_narrator_are_on():
    client, _, _ = demo_parts()
    assert client.get("/api/health").json() == {"status": "ok", "demo_mode": True, "narrator": True}


def test_health_says_the_demo_mode_is_off_when_it_is_not_configured(parts):
    client, _, _ = parts
    assert client.get("/api/health").json() == {"status": "ok", "demo_mode": False, "narrator": False}


def test_the_demo_routes_do_not_exist_when_the_demo_mode_is_off(parts):
    client, _, _ = parts
    assert client.post("/api/demo/incidents", json=PAYMENT).status_code == 404
    assert client.get("/api/demo/incidents/current").status_code == 404
    assert client.delete("/api/demo/incidents/current").status_code == 404


def test_starting_a_simulation_turns_the_fault_on_and_returns_the_incident():
    client, flags, _ = demo_parts()
    response = client.post("/api/demo/incidents", json=PAYMENT)
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "active" and body["kind"] == "payment_failure" and body["title"] == "Pagamento falhando" and "root_cause_service" not in body and body["investigation_id"] is None
    assert body["started_at"].endswith("Z") and body["ends_at"].endswith("Z") and flags.values["paymentFailure"] == "100%"


def test_a_second_simulation_is_a_409():
    client, _, _ = demo_parts()
    client.post("/api/demo/incidents", json=PAYMENT)
    again = client.post("/api/demo/incidents", json=PAYMENT)
    assert again.status_code == 409 and "em andamento" in again.json()["detail"]


def test_the_current_incident_is_null_before_any_and_the_active_one_after():
    client, _, _ = demo_parts()
    assert client.get("/api/demo/incidents/current").json() == {"incident": None}
    client.post("/api/demo/incidents", json=PAYMENT)
    assert client.get("/api/demo/incidents/current").json()["incident"]["state"] == "active"


def test_stopping_turns_the_fault_off():
    client, flags, _ = demo_parts()
    client.post("/api/demo/incidents", json=PAYMENT)
    stopped = client.delete("/api/demo/incidents/current")
    assert stopped.status_code == 200 and stopped.json()["state"] == "stopped" and flags.values["paymentFailure"] == "off"
    assert client.delete("/api/demo/incidents/current").status_code == 409


def test_a_demo_that_cannot_change_the_fault_is_a_502_with_the_reason():
    client, flags, store = demo_parts()
    flags.error = FlagError("o serviço de falhas do Demo está inacessível: sem rede")
    response = client.post("/api/demo/incidents", json=PAYMENT)
    assert response.status_code == 502 and "inacessível" in response.json()["detail"] and store.latest_incident() is None


def open_investigation(client, **kwargs):
    return client.post("/webhooks/alertmanager", json=webhook(raw_alert(**kwargs)), headers=HEADERS).json()["outcomes"][0]["id"]


def test_an_unlabeled_case_has_no_gabarito(parts):
    client, _, _ = parts
    identifier = open_investigation(client)
    detail = client.get("/api/investigations/" + identifier).json()
    assert detail["gabarito"] is None and detail["summary"]["gabarito"] is None


def test_the_list_carries_the_gabarito_of_each_row(parts):
    client, store, _ = parts
    labeled = open_investigation(client, service="frontend", fingerprint="a", starts_at=START.replace(hour=1))
    open_investigation(client, service="cart", fingerprint="b", starts_at=START.replace(hour=2))
    completed_with_ranking(store, labeled, RANKING)
    store.set_ground_truth(labeled, "frontend", "payment_failure", "trace_err", "simulation", None)
    items = {i["service"]: i for i in client.get("/api/investigations").json()["items"]}
    assert items["frontend"]["gabarito"]["top1"] is True and items["cart"]["gabarito"] is None


def test_the_evaluation_counts_hits_and_lists_every_labeled_case(parts):
    client, store, _ = parts
    first = open_investigation(client, service="frontend", fingerprint="a", starts_at=START.replace(hour=1))
    second = open_investigation(client, service="cart", fingerprint="b", starts_at=START.replace(hour=2))
    open_investigation(client, service="ad", fingerprint="c", starts_at=START.replace(hour=3))
    completed_with_ranking(store, first, RANKING)
    completed_with_ranking(store, second, [{"position": 1, "service": "payment", "score": 0.4}])
    store.set_ground_truth(first, "payment", "payment_failure", "trace_err", "simulation", None)
    store.set_ground_truth(second, "payment", "payment_failure", "trace_err", "simulation", None)
    body = client.get("/api/evaluation").json()
    assert body["summary"] == {"labeled": 2, "evaluated": 2, "top1": 1, "top3": 2, "pending": 0, "no_result": 0}
    cases = {c["id"]: c for c in body["cases"]}
    assert cases[first]["rank"] == 2 and cases[second]["rank"] == 1 and cases[second]["top_suspect"]["service"] == "payment"
    assert [c["id"] for c in body["cases"]] == [second, first]


def test_the_evaluation_of_nothing_is_empty(parts):
    client, _, _ = parts
    body = client.get("/api/evaluation").json()
    assert body["summary"] == {"labeled": 0, "evaluated": 0, "top1": 0, "top3": 0, "pending": 0, "no_result": 0} and body["cases"] == []
    assert "services" not in body


ORIGIN = "http://localhost:5174"


@pytest.fixture
def browser():
    service, store, hub, clock, config = world(allowed_origins=(ORIGIN,))
    return TestClient(create_app(service, store, hub, config))


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/api/demo/incidents/current"),
    ("POST", "/api/demo/incidents"),
    ("GET", "/api/evaluation"),
])
def test_the_browser_is_allowed_to_call_every_method_the_site_uses(browser, method, path):
    response = browser.options(path, headers={"Origin": ORIGIN, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "content-type"})
    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_another_origin_is_not_allowed(browser):
    response = browser.options("/api/evaluation", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in response.headers


class ReplayRunner:
    def __init__(self):
        self.replays = []

    def submit(self, *args, **kwargs):
        return None

    def submit_replay(self, identifier, source_id):
        self.replays.append((identifier, source_id))


@pytest.fixture
def replay_parts():
    service, store, hub, clock, config = world()
    runner = ReplayRunner()
    return TestClient(create_app(service, store, hub, config, runner=runner)), store, service, runner


def make_replayable(client, store, service):
    identifier = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS).json()["outcomes"][0]["id"]
    finish_row(store, identifier, [SUSPECT], [EVIDENCE])
    store.save_snapshot(identifier, {"tables": {}})
    return identifier


def test_a_replay_is_accepted_and_handed_to_the_runner(replay_parts):
    client, store, service, runner = replay_parts
    source = make_replayable(client, store, service)
    response = client.post("/api/investigations/%s/replay" % source)
    assert response.status_code == 202
    body = response.json()
    assert body["replay_of"] == source and runner.replays == [(body["id"], source)]
    assert client.get("/api/investigations/" + body["id"]).json()["summary"]["replay_of"] == source


def test_replaying_an_unknown_investigation_is_a_404(replay_parts):
    client, _, _, runner = replay_parts
    assert client.post("/api/investigations/INV-9999/replay").status_code == 404 and runner.replays == []


def test_replaying_a_case_without_recorded_data_is_a_409_with_the_reason(replay_parts):
    client, store, service, runner = replay_parts
    identifier = client.post("/webhooks/alertmanager", json=webhook(raw_alert()), headers=HEADERS).json()["outcomes"][0]["id"]
    finish_row(store, identifier, [SUSPECT], [EVIDENCE])
    response = client.post("/api/investigations/%s/replay" % identifier)
    assert response.status_code == 409 and "dados gravados" in response.json()["detail"] and runner.replays == []


def test_the_detail_tells_the_site_whether_the_replay_button_applies(replay_parts):
    client, store, service, _ = replay_parts
    source = make_replayable(client, store, service)
    assert client.get("/api/investigations/" + source).json()["replayable"] is True
    other = client.post("/webhooks/alertmanager", json=webhook(raw_alert(service="cart", fingerprint="y")), headers=HEADERS).json()["outcomes"][0]["id"]
    assert client.get("/api/investigations/" + other).json()["replayable"] is False


def test_the_evaluation_counts_the_original_case_and_not_its_replays(replay_parts):
    client, store, service, _ = replay_parts
    source = make_replayable(client, store, service)
    store.set_ground_truth(source, "payment", "payment_failure", "trace_err", "simulation", None)
    client.post("/api/investigations/%s/replay" % source)
    assert client.get("/api/evaluation").json()["summary"]["labeled"] == 1


def test_nobody_can_set_or_remove_a_gabarito_through_the_api(parts):
    client, store, _ = parts
    identifier = open_investigation(client)
    path = "/api/investigations/%s/ground-truth" % identifier
    assert client.put(path, json={"root_cause_service": "payment"}).status_code in (404, 405)
    assert client.delete(path).status_code in (404, 405)


def test_the_detail_names_the_service_the_torai_put_first(parts):
    client, store, _ = parts
    identifier = open_investigation(client)
    completed_with_ranking(store, identifier, RANKING)
    store.set_ground_truth(identifier, "payment", "payment_failure", "trace_err", "simulation", None)
    gabarito = client.get("/api/investigations/" + identifier).json()["gabarito"]
    assert gabarito["top_service"] == "frontend" and gabarito["rank"] == 2 and gabarito["top1"] is False


def test_a_finished_investigation_can_be_deleted_with_its_gabarito(parts):
    client, store, _ = parts
    identifier = open_investigation(client)
    completed_with_ranking(store, identifier, RANKING)
    store.set_ground_truth(identifier, "payment", "payment_failure", "trace_err", "simulation", None)
    assert client.delete("/api/investigations/" + identifier).json() == {"deleted": [identifier]}
    assert client.get("/api/investigations/" + identifier).status_code == 404
    assert store.get_ground_truth(identifier) is None
    assert client.get("/api/investigations").json()["total"] == 0


def test_an_investigation_in_progress_cannot_be_deleted(parts):
    client, store, _ = parts
    identifier = open_investigation(client)
    response = client.delete("/api/investigations/" + identifier)
    assert response.status_code == 409 and "andamento" in response.json()["detail"]
    assert client.get("/api/investigations/" + identifier).status_code == 200


def test_deleting_an_unknown_investigation_is_a_404(parts):
    client, _, _ = parts
    assert client.delete("/api/investigations/INV-9999").status_code == 404


def test_delete_all_removes_the_finished_ones_and_keeps_those_in_progress(parts):
    client, store, _ = parts
    done = open_investigation(client, service="frontend", fingerprint="a", starts_at=START.replace(hour=1))
    running = open_investigation(client, service="cart", fingerprint="b", starts_at=START.replace(hour=2))
    completed_with_ranking(store, done, RANKING)
    body = client.delete("/api/investigations").json()
    assert body == {"deleted": [done], "count": 1}
    assert [i["id"] for i in client.get("/api/investigations").json()["items"]] == [running]


def test_deleting_publishes_an_event_and_ids_are_not_reused(parts):
    client, store, _ = parts
    first = open_investigation(client, service="frontend", fingerprint="a", starts_at=START.replace(hour=1))
    completed_with_ranking(store, first, RANKING)
    client.delete("/api/investigations/" + first)
    second = open_investigation(client, service="cart", fingerprint="b", starts_at=START.replace(hour=2))
    assert second != first


def test_a_simulation_can_be_forced_to_a_given_fault_and_unknown_ones_are_422():
    client, flags, store = demo_parts()
    assert client.post("/api/demo/incidents", json={"kind": "cartFailure"}).status_code == 422
    assert flags.values["paymentFailure"] == "off"
    response = client.post("/api/demo/incidents", json={"kind": "product_catalog_lock_contention"})
    assert response.status_code == 202 and flags.values["productCatalogLockContention"] == "on"
    assert store.active_incident()["root_cause_service"] == "product-catalog"


def test_the_faults_route_lists_the_options_the_user_can_pick():
    client, _, _ = demo_parts()
    body = client.get("/api/demo/faults").json()
    assert [f["kind"] for f in body["faults"]] == ["payment_failure", "product_catalog_lock_contention"]
    assert body["faults"][0]["title"] == "Pagamento falhando" and body["faults"][0]["affected_service"] == "payment"


def test_the_faults_route_does_not_exist_when_the_demo_mode_is_off(parts):
    client, _, _ = parts
    assert client.get("/api/demo/faults").status_code == 404


def test_a_simulation_needs_the_fault_to_be_chosen():
    client, flags, store = demo_parts()
    assert client.post("/api/demo/incidents").status_code == 422
    assert client.post("/api/demo/incidents", json={}).status_code == 422
    assert store.active_incident() is None


def campaign_parts():
    import random

    from anomalyguard.campaign import CampaignEngine
    from tests.test_campaign import FakeFlags as CampaignFlags, FakeGate, FakeScheduler

    service, store, hub, clock, config = world(demo_mode=True)
    flags, gate = CampaignFlags(), FakeGate()
    demo = DemoIncidents(store, flags, config, clock, FakeScheduler())
    engine = CampaignEngine(store, demo, gate, hub, config, clock, random.Random(1))
    return TestClient(create_app(service, store, hub, config, demo=demo, narrator_on=True, campaigns=engine)), engine, store, gate


def test_the_accuracy_route_is_empty_before_any_campaign():
    client, *_ = campaign_parts()
    body = client.get("/api/accuracy").json()
    assert body["campaign"] is None and body["summary"]["cases"] == 0 and body["cases"] == [] and len(body["by_fault"]) == 2


def test_a_campaign_can_be_started_paused_resumed_and_stopped_through_the_api():
    client, engine, store, gate = campaign_parts()
    started = client.post("/api/campaign", json={"per_fault": 4})
    assert started.status_code == 202 and started.json()["total"] == 8 and started.json()["state"] == "running"
    assert client.get("/api/accuracy").json()["campaign"]["done"] == 0
    assert client.patch("/api/campaign", json={"state": "paused"}).json()["state"] == "paused"
    assert client.patch("/api/campaign", json={"state": "running"}).json()["state"] == "running"
    assert client.delete("/api/campaign").json()["state"] == "stopped"
    assert client.delete("/api/campaign").status_code == 404


def test_the_campaign_routes_validate_and_conflict():
    client, *_ = campaign_parts()
    assert client.post("/api/campaign", json={"per_fault": 0}).status_code == 422
    assert client.post("/api/campaign", json={"per_fault": 99}).status_code == 422
    assert client.post("/api/campaign", json={}).status_code == 422
    assert client.post("/api/campaign", json={"per_fault": 1}).status_code == 202
    assert client.post("/api/campaign", json={"per_fault": 1}).status_code == 409
    assert client.patch("/api/campaign", json={"state": "running"}).status_code == 409
    assert client.patch("/api/campaign", json={"state": "stopped"}).status_code == 422


def test_the_campaign_routes_do_not_exist_when_the_demo_mode_is_off(parts):
    client, _, _ = parts
    assert client.get("/api/accuracy").status_code == 404
    assert client.post("/api/campaign", json={"per_fault": 1}).status_code == 404
    assert client.delete("/api/campaign").status_code == 404


def test_the_browser_may_patch_the_campaign(browser):
    response = browser.options("/api/campaign", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "content-type"})
    assert response.status_code == 200
