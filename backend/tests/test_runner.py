from datetime import timedelta

import pytest

from anomalyguard import runner as runner_module
from anomalyguard.analysis import AnalysisError, AnalysisResult
from anomalyguard.runner import Runner
from tests.helpers import EVIDENCE, START, SUSPECT, Recorder, alert, world


class FakeNarrator:
    def __init__(self, narrative=None, error=None):
        self.narrative = narrative or {"state": "ready", "kind": "llm", "verified": True, "headline": "h", "paragraphs": ["p [1]"], "evidence": [], "failure_reason": None}
        self.error = error
        self.contexts = []
        self.clock = lambda: 0.0

    def write(self, context, on_chunk, on_reset):
        self.contexts.append(context)
        if self.error:
            raise self.error
        on_chunk(0, "h")
        return self.narrative

    def fixed(self, context, reason, started, attempts):
        return {"state": "ready", "kind": "fixed", "verified": None, "headline": "fixo", "paragraphs": [], "evidence": [], "failure_reason": reason}


def start(monkeypatch, behavior, narrator=None):
    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    recorder = Recorder(hub, identifier)
    monkeypatch.setattr(runner_module, "run_analysis", behavior)
    Runner(service, None, config, narrator or FakeNarrator()).run(identifier, START)
    return store.get(identifier), recorder


def good(collector, t_alert, settings, on_stage):
    on_stage("collecting", "coleta", "Coletando")
    on_stage("analyzing", "análise", "Calculando")
    return AnalysisResult([SUSPECT], {"collect": 10}, [], [], [EVIDENCE], ["Sem logs para payment."])


def test_a_successful_analysis_is_narrated_and_completes(monkeypatch):
    narrator = FakeNarrator()
    row, recorder = start(monkeypatch, good, narrator)
    assert row["state"] == "completed" and row["suspects"] == [SUSPECT] and row["narrative"]["verified"] is True
    assert [e["tag"] for e in row["log"]] == ["alerta", "espera", "coleta", "análise", "análise", "relatório", "relatório", "fim"]
    assert recorder.names().count("suspects") == 1 and "narrative.chunk" in recorder.names() and recorder.names().count("narrative.done") == 1


def test_the_narrator_receives_the_alert_the_suspects_the_evidence_and_the_limitations(monkeypatch):
    narrator = FakeNarrator()
    start(monkeypatch, good, narrator)
    context = narrator.contexts[0]
    assert context["alert"] == {"name": "FrontendHighErrorRate", "service": "frontend", "started_at": "2026-11-22T02:06:40Z"}
    assert context["suspects"] == [SUSPECT] and context["evidence"] == [EVIDENCE] and context["limitations"] == ["Sem logs para payment."]
    assert set(context) == {"alert", "suspects", "evidence", "limitations"}


def test_the_data_of_the_analysis_is_recorded_for_a_later_replay(monkeypatch):
    def behavior(collector, t_alert, settings, on_stage):
        return AnalysisResult([SUSPECT], {}, [], [], [EVIDENCE], [], [], {"tables": {}, "plan": {"margin_s": 315}})

    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    monkeypatch.setattr(runner_module, "run_analysis", behavior)
    Runner(service, None, config, FakeNarrator()).run(identifier, START)
    assert store.get_snapshot(identifier) == {"tables": {}, "plan": {"margin_s": 315}}


def test_the_top_3_is_published_before_the_narrative_is_written(monkeypatch):
    row, recorder = start(monkeypatch, good)
    names = recorder.names()
    assert names.index("suspects") < names.index("narrative.chunk") < names.index("narrative.done")


def test_a_narrator_crash_falls_back_to_the_fixed_text_and_still_completes(monkeypatch):
    row, _ = start(monkeypatch, good, FakeNarrator(error=RuntimeError("boom")))
    assert row["state"] == "completed" and row["narrative"]["kind"] == "fixed" and "RuntimeError" in row["narrative"]["failure_reason"]


def test_an_analysis_error_fails_the_investigation_with_the_reason(monkeypatch):
    def behavior(collector, t_alert, settings, on_stage):
        raise AnalysisError("fonte indisponível")

    row, recorder = start(monkeypatch, behavior)
    assert row["state"] == "failed" and row["failure_reason"] == "fonte indisponível" and row["narrative"] is None


def test_an_unexpected_error_is_reported_and_not_raised(monkeypatch):
    def behavior(collector, t_alert, settings, on_stage):
        raise RuntimeError("boom")

    row, _ = start(monkeypatch, behavior)
    assert row["state"] == "failed" and "boom" in row["failure_reason"]


def test_the_margin_of_the_investigation_overrides_the_default(monkeypatch):
    seen = {}

    def behavior(collector, t_alert, settings, on_stage):
        seen["margin"] = settings.margin_s
        return AnalysisResult([SUSPECT], {}, [], [], [EVIDENCE], [])

    service, store, hub, clock, config = world()
    identifier = service.ingest(alert()).investigation_id
    monkeypatch.setattr(runner_module, "run_analysis", behavior)
    Runner(service, None, config, FakeNarrator()).run(identifier, START, 120)
    assert seen["margin"] == 120


class OwningCampaigns:
    def __init__(self, owns):
        self.owns = owns

    def owns_incident(self, incident_id):
        return self.owns


def test_a_campaign_case_is_not_sent_to_the_llm(monkeypatch):
    service, store, hub, clock, config = world()
    store.create_incident("payment_failure", "paymentFailure", "100%", START - timedelta(minutes=1), START + timedelta(minutes=6), "payment", "trace_err")
    identifier = service.ingest(alert()).investigation_id
    monkeypatch.setattr(runner_module, "run_analysis", good)
    narrator = FakeNarrator()
    runner = Runner(service, None, config, narrator)
    runner.campaigns = OwningCampaigns(True)
    runner.run(identifier, START)
    row = store.get(identifier)
    assert narrator.contexts == [] and row["state"] == "completed" and row["narrative"]["kind"] == "fixed" and "campanha" in row["narrative"]["failure_reason"]


def test_a_manual_simulation_is_still_explained_by_the_llm(monkeypatch):
    service, store, hub, clock, config = world()
    store.create_incident("payment_failure", "paymentFailure", "100%", START - timedelta(minutes=1), START + timedelta(minutes=6), "payment", "trace_err")
    identifier = service.ingest(alert()).investigation_id
    monkeypatch.setattr(runner_module, "run_analysis", good)
    narrator = FakeNarrator()
    runner = Runner(service, None, config, narrator)
    runner.campaigns = OwningCampaigns(False)
    runner.run(identifier, START)
    assert len(narrator.contexts) == 1 and store.get(identifier)["narrative"]["kind"] == "llm"
