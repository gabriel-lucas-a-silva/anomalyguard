import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from . import views
from .analysis import AnalysisError, replay_analysis, run_analysis

log = logging.getLogger("anomalyguard.runner")


class Runner:
    def __init__(self, service, collector, settings, narrator, executor=None):
        self.service = service
        self.collector = collector
        self.settings = settings
        self.narrator = narrator
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self.campaigns = None

    def submit(self, identifier, t_alert, margin_s=None):
        return self.executor.submit(self.run, identifier, t_alert, margin_s)

    def run(self, identifier, t_alert, margin_s=None):
        settings = replace(self.settings, margin_s=margin_s) if margin_s else self.settings
        try:
            result = run_analysis(self.collector, t_alert, settings, lambda state, tag, message: self.service.advance(identifier, state, tag, message))
            self.service.analysis_done(identifier, result)
            if result.snapshot:
                self.service.store.save_snapshot(identifier, result.snapshot)
            self.narrate(identifier, result)
        except AnalysisError as e:
            self.service.fail(identifier, str(e))
        except Exception as e:
            log.exception("investigation %s failed", identifier)
            self.service.fail(identifier, "erro inesperado: %s: %s" % (type(e).__name__, e))

    def submit_replay(self, identifier, source_id):
        return self.executor.submit(self.run_replay, identifier, source_id)

    def run_replay(self, identifier, source_id):
        try:
            payload = self.service.store.get_snapshot(source_id)
            if payload is None:
                raise AnalysisError("os dados gravados de %s não foram encontrados" % source_id)
            result = replay_analysis(payload, lambda state, tag, message: self.service.advance(identifier, state, tag, message))
            self.service.analysis_done(identifier, result)
            self.service.store.save_snapshot(identifier, result.snapshot)
            self.narrate(identifier, result)
        except AnalysisError as e:
            self.service.fail(identifier, str(e))
        except Exception as e:
            log.exception("replay %s failed", identifier)
            self.service.fail(identifier, "erro inesperado: %s: %s" % (type(e).__name__, e))

    def narrate(self, identifier, result):
        row = self.service.get(identifier)
        context = {
            "alert": {"name": row["alert_name"], "service": row["service"], "started_at": views.to_iso(row["received_at"])},
            "suspects": result.suspects,
            "evidence": result.evidence,
            "limitations": result.limitations,
        }
        if self.in_campaign(row):
            self.service.finish(identifier, self.narrator.fixed(context, "A explicação em linguagem natural fica desligada durante a campanha de acurácia.", self.narrator.clock(), 0))
            return
        try:
            narrative = self.narrator.write(context, lambda index, text: self.service.narrative_chunk(identifier, index, text),
                                            lambda: self.service.narrative_reset(identifier))
        except Exception as e:
            log.exception("narrator failed for %s", identifier)
            narrative = self.narrator.fixed(context, "erro inesperado no narrador: %s" % type(e).__name__, self.narrator.clock(), 0)
        self.service.finish(identifier, narrative)

    def in_campaign(self, row):
        if self.campaigns is None or row.get("replay_of"):
            return False
        incident = self.service.store.incident_covering(row["received_at"])
        return incident is not None and self.campaigns.owns_incident(incident["id"])
