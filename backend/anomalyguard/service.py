import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from . import views
from .alerts import margin_from
from .events import GLOBAL_TOPIC
from .store import TERMINAL


class ReplayNotFound(Exception):
    pass


class ReplayConflict(Exception):
    pass


class DeleteNotFound(Exception):
    pass


class DeleteBusy(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    action: str
    investigation_id: Optional[str]


class Investigations:
    def __init__(self, store, hub, settings, clock):
        self.store = store
        self.hub = hub
        self.settings = settings
        self.clock = clock
        self.partials = {}
        self.lock = threading.Lock()

    def get(self, identifier):
        return self.store.get(identifier)

    def detail(self, identifier):
        row = self.store.get(identifier)
        if row is None:
            return None
        replayable = row["state"] == "completed" and bool(self.store.snapshot_ids([identifier]))
        return views.detail(row, self.partial_view(identifier, row), self.store.get_ground_truth(identifier), replayable)

    def delete(self, identifier):
        row = self.store.get(identifier)
        if row is None:
            raise DeleteNotFound("investigação %s não encontrada" % identifier)
        if row["state"] not in TERMINAL:
            raise DeleteBusy("a investigação %s ainda está em andamento; espere ela terminar" % identifier)
        self.store.delete_investigations([identifier])
        self._forget([identifier])
        return {"deleted": [identifier]}

    def delete_all(self):
        removed = self.store.delete_investigations(self.store.terminal_ids())
        self._forget(removed)
        return {"deleted": removed, "count": len(removed)}

    def _forget(self, identifiers):
        with self.lock:
            for identifier in identifiers:
                self.partials.pop(identifier, None)
        for identifier in identifiers:
            self.hub.publish(identifier, "investigation.deleted", {"id": identifier})
        self.hub.publish(GLOBAL_TOPIC, "investigation.deleted", {"ids": list(identifiers)})

    def partial_view(self, identifier, row):
        with self.lock:
            paragraphs = list(self.partials.get(identifier) or [])
        if not paragraphs:
            return None
        evidence = views.evidence_view(row)
        return {"state": "writing", "kind": "llm", "verified": None, "headline": paragraphs[0], "paragraphs": paragraphs[1:], "evidence": evidence,
                "model": None, "failure_reason": None}

    def _emit(self, row, entries=()):
        summary = views.summary(row, self.store.get_ground_truth(row["id"]))
        self.hub.publish(row["id"], "stage", {"state": row["state"], "stage": summary["stage"]})
        for entry in entries:
            self.hub.publish(row["id"], "log", entry)
        self.hub.publish(GLOBAL_TOPIC, "investigation.updated", summary)
        return row

    def advance(self, identifier, state, tag, message):
        row = self.store.advance(identifier, state, tag, message)
        return self._emit(row, row["log"][-1:])

    def note(self, identifier, tag, message):
        row = self.store.add_log(identifier, tag, message)
        return self._emit(row, row["log"][-1:])

    def analysis_done(self, identifier, result):
        row = self.store.save_result(identifier, result.suspects, result.evidence, result.limitations, result.timings_ms, result.missing_sources, result.warnings, result.ranking)
        shown = views.detail(row)
        self.hub.publish(identifier, "suspects", {"suspects": shown["suspects"], "evidence": shown["evidence"], "limitations": shown["limitations"]})
        return self._emit(row, row["log"][-2:])

    def narrative_chunk(self, identifier, paragraph, text):
        with self.lock:
            partial = self.partials.setdefault(identifier, [])
            while len(partial) <= paragraph:
                partial.append("")
            partial[paragraph] += text
        self.hub.publish(identifier, "narrative.chunk", {"paragraph": paragraph, "text": text})

    def narrative_reset(self, identifier):
        with self.lock:
            self.partials.pop(identifier, None)
        self.hub.publish(identifier, "narrative.reset", {})

    def finish(self, identifier, narrative):
        row = self.store.finish(identifier, narrative)
        with self.lock:
            self.partials.pop(identifier, None)
        self.hub.publish(identifier, "narrative.done", {"narrative": narrative})
        return self._emit(row, row["log"][-2:])

    def fail(self, identifier, reason):
        row = self.store.fail(identifier, reason)
        return self._emit(row, row["log"][-1:])

    def ingest(self, alert):
        if self.store.alert_exists(alert.fingerprint, alert.starts_at, alert.status):
            return Outcome("repeated", None)
        if alert.status == "resolved":
            return self._resolved(alert)
        open_row = self.store.find_open(alert.service)
        if open_row:
            return self._attach(open_row, alert, "grouped", "Mais um alerta (%s) entrou nesta investigação" % alert.alert_name)
        since = self.clock() - timedelta(seconds=self.settings.group_window_s)
        simulation = self.store.latest_incident()
        if simulation is not None and simulation["started_at"] > since:
            since = simulation["started_at"]
        recent = self.store.find_recent_terminal(alert.service, since)
        if recent:
            return self._attach(recent, alert, "recurrence", "O alerta %s voltou e foi anexado a esta investigação" % alert.alert_name)
        return self._open(alert)

    def open_replay(self, source_id):
        source = self.store.get(source_id)
        if source is None:
            raise ReplayNotFound("investigação não encontrada")
        if source["state"] != "completed":
            raise ReplayConflict("só dá para reproduzir uma investigação concluída")
        if not self.store.snapshot_ids([source_id]):
            raise ReplayConflict("esta investigação não tem dados gravados, porque é anterior à gravação")
        now = self.clock()
        row = self.store.create_investigation(source["alert_name"], source["service"], now, source["margin_s"], now, replay_of=source_id,
                                              first_message="Reprodução do caso %s, sobre os dados gravados na época" % source_id)
        truth = self.store.get_ground_truth(source_id)
        if truth is not None:
            self.store.set_ground_truth(row["id"], truth["root_cause_service"], truth["fault_kind"], truth["expected_signal"], truth["source"], truth["incident_id"])
        self.hub.publish(GLOBAL_TOPIC, "investigation.created", views.summary(row, self.store.get_ground_truth(row["id"])))
        self.advance(row["id"], "collecting", "coleta", "Lendo os dados gravados em vez de consultar o ambiente")
        return row["id"]

    def label_from_simulation(self, identifier, alert):
        incident = self.store.incident_covering(alert.starts_at)
        if incident is None:
            return None
        return self.store.set_ground_truth(identifier, incident["root_cause_service"], incident["kind"], incident["expected_signal"], "simulation", incident["id"])

    def _attach(self, row, alert, role, message):
        self.store.add_alert(row["id"], alert, role)
        self.store.bump_grouped(row["id"])
        self.note(row["id"], "alerta", message)
        return Outcome(role, row["id"])

    def _resolved(self, alert):
        row = self.store.find_by_fingerprint(alert.fingerprint)
        if row is None:
            return Outcome("ignored", None)
        self.store.add_alert(row["id"], alert, "resolved")
        row = self.store.mark_resolved(row["id"])
        if row["state"] not in ("completed", "failed"):
            self.note(row["id"], "alerta", "O alerta foi resolvido antes da análise; a investigação continua")
        return Outcome("resolved_attached", row["id"])

    def _open(self, alert):
        margin = margin_from(alert.annotations) or self.settings.margin_s
        ready_at = alert.starts_at + timedelta(seconds=self.settings.delta_s + self.settings.data_lag_s)
        row = self.store.create_investigation(alert.alert_name, alert.service, alert.starts_at, margin, ready_at)
        self.store.add_alert(row["id"], alert, "initial")
        self.label_from_simulation(row["id"], alert)
        self.hub.publish(GLOBAL_TOPIC, "investigation.created", views.summary(row, self.store.get_ground_truth(row["id"])))
        self.advance(row["id"], "waiting", "espera", "Aguardando %d s de dados depois do alerta" % self.settings.delta_s)
        return Outcome("new_investigation", row["id"])
