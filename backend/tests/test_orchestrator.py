from datetime import timedelta

from anomalyguard.orchestrator import Orchestrator
from tests.helpers import START, alert, world


class FakeRunner:
    def __init__(self):
        self.submitted = []

    def submit(self, identifier, t_alert, margin_s=None):
        self.submitted.append((identifier, t_alert, margin_s))


def build(clock=None):
    service, store, hub, clock, config = world(clock)
    runner = FakeRunner()
    return service, store, clock, config, runner, Orchestrator(store, service, runner, config, clock)


def test_an_investigation_runs_only_after_the_data_is_ready():
    service, store, clock, config, runner, orchestrator = build()
    clock.now = START + timedelta(seconds=100)
    service.ingest(alert())
    orchestrator.tick()
    assert runner.submitted == []
    clock.now = START + timedelta(seconds=config.delta_s + config.data_lag_s)
    orchestrator.tick()
    assert runner.submitted == [("INV-0001", START, 315)]


def test_a_due_investigation_is_submitted_once():
    service, store, clock, config, runner, orchestrator = build()
    service.ingest(alert())
    orchestrator.tick()
    orchestrator.tick()
    assert len(runner.submitted) == 1
    assert store.get("INV-0001")["state"] == "collecting"


def test_only_due_investigations_are_submitted():
    service, store, clock, config, runner, orchestrator = build()
    clock.now = START + timedelta(seconds=300)
    service.ingest(alert())
    service.ingest(alert(service="cart", fingerprint="fp-2", starts_at=START + timedelta(seconds=290)))
    orchestrator.tick()
    assert [s[0] for s in runner.submitted] == ["INV-0001"]


def test_recovery_fails_the_investigations_interrupted_by_a_restart():
    service, store, clock, config, runner, orchestrator = build()
    identifier = service.ingest(alert()).investigation_id
    service.advance(identifier, "analyzing", "análise", "Calculando")
    waiting = service.ingest(alert(service="cart", fingerprint="fp-2")).investigation_id
    orchestrator.recover()
    assert store.get(identifier)["state"] == "failed"
    assert "reiniciou" in store.get(identifier)["failure_reason"]
    assert store.get(waiting)["state"] == "waiting"


def test_an_analysis_with_no_news_for_too_long_is_failed_with_the_reason():
    service, store, clock, config, runner, orchestrator = build()
    identifier = service.ingest(alert()).investigation_id
    service.advance(identifier, "analyzing", "análise", "Calculando")
    clock.advance(config.stuck_after_s + 1)
    orchestrator.tick()
    row = store.get(identifier)
    assert row["state"] == "failed" and "nenhum sinal da análise por 900 s" in row["failure_reason"]


def test_an_analysis_that_is_still_moving_is_left_alone():
    service, store, clock, config, runner, orchestrator = build()
    identifier = service.ingest(alert()).investigation_id
    service.advance(identifier, "analyzing", "análise", "Calculando")
    clock.advance(config.stuck_after_s - 10)
    orchestrator.tick()
    assert store.get(identifier)["state"] == "analyzing"
