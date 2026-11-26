import logging
import random
import threading
from datetime import timedelta

from . import accuracy, gabarito, views
from .demo import CATALOG, DemoConflict
from .events import GLOBAL_TOPIC
from .flags import FlagError

log = logging.getLogger("anomalyguard.campaign")

TERMINAL = ("completed", "failed")
DEFAULT_CASE_S = 1200
MAX_PER_FAULT = 30


class CampaignConflict(Exception):
    pass


class CampaignNotFound(Exception):
    pass


class CampaignInvalid(Exception):
    pass


class CampaignEngine:
    def __init__(self, store, demo, gate, hub, settings, clock, rng=None):
        self.store = store
        self.demo = demo
        self.gate = gate
        self.hub = hub
        self.settings = settings
        self.clock = clock
        self.rng = rng or random.Random()
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread = None

    def start(self, per_fault):
        self.demo.require_enabled()
        if not 1 <= per_fault <= MAX_PER_FAULT:
            raise CampaignInvalid("per_fault precisa estar entre 1 e %d" % MAX_PER_FAULT)
        with self.lock:
            if self.store.active_campaign() is not None:
                raise CampaignConflict("já existe uma campanha em andamento")
            if self.store.active_incident() is not None:
                raise CampaignConflict("já existe uma simulação em andamento")
            kinds = [kind for kind in CATALOG for _ in range(per_fault)]
            self.rng.shuffle(kinds)
            campaign = self.store.create_campaign(per_fault, kinds, self.clock())
            self.gate.reset()
            return self.updated(campaign)

    def pause(self):
        with self.lock:
            campaign = self.require_active()
            if campaign["state"] != "running":
                raise CampaignConflict("a campanha já está pausada")
            return self.updated(self.store.update_campaign(campaign["id"], state="paused", pause_reason=None))

    def resume(self):
        with self.lock:
            campaign = self.require_active()
            if campaign["state"] != "paused":
                raise CampaignConflict("a campanha não está pausada")
            self.gate.reset()
            return self.updated(self.store.update_campaign(campaign["id"], state="running", pause_reason=None, phase_since=self.clock()))

    def stop(self):
        with self.lock:
            campaign = self.require_active()
            running = [c for c in self.store.campaign_cases(campaign["id"]) if c["state"] == "running"]
            self.store.cancel_open_cases(campaign["id"])
            if running:
                try:
                    self.demo.stop()
                except DemoConflict:
                    pass
            return self.updated(self.store.update_campaign(campaign["id"], state="stopped", finished_at=self.clock()))

    def require_active(self):
        campaign = self.store.active_campaign()
        if campaign is None:
            raise CampaignNotFound("não há campanha em andamento")
        return campaign

    def updated(self, campaign):
        view = self.view(campaign)
        self.hub.publish(GLOBAL_TOPIC, "campaign.updated", view)
        return view

    def tick(self):
        with self.lock:
            campaign = self.store.active_campaign()
            if campaign is None:
                return
            cases = self.store.campaign_cases(campaign["id"])
            running = next((c for c in cases if c["state"] == "running"), None)
            if running:
                self.advance(campaign, running)
                return
            pending = next((c for c in cases if c["state"] == "pending"), None)
            if pending is None:
                self.updated(self.store.update_campaign(campaign["id"], state="finished", finished_at=self.clock()))
                self.hub.publish(GLOBAL_TOPIC, "accuracy.updated", {})
                return
            self.gate.observe()
            if campaign["state"] == "paused":
                return
            self.prepare(campaign, pending)

    def prepare(self, campaign, case):
        if self.gate.is_calm():
            try:
                incident = self.demo.start(case["kind"])
            except DemoConflict:
                return
            except FlagError as e:
                self.updated(self.store.update_campaign(campaign["id"], state="paused", pause_reason="Não consegui ligar a falha no Demo: %s" % e))
                return
            self.store.update_case(case["id"], state="running", incident_id=incident["id"], started_at=self.clock())
            self.gate.reset()
            self.updated(campaign)
            return
        waited = (self.clock() - campaign["phase_since"]).total_seconds()
        if waited > self.settings.campaign_calm_timeout_s:
            reason = "O Demo não ficou calmo em %d minutos (%s). Confira a máquina e retome." % (self.settings.campaign_calm_timeout_s // 60, self.gate.reason or "sem detalhe")
            self.updated(self.store.update_campaign(campaign["id"], state="paused", pause_reason=reason))

    def advance(self, campaign, case):
        incident = self.store.get_incident(case["incident_id"])
        cause = incident["root_cause_service"] if incident else CATALOG[case["kind"]]["service"]
        elapsed = (self.clock() - case["started_at"]).total_seconds()
        found = self.store.get(case["investigation_id"]) if case["investigation_id"] else self.store.first_investigation_since(case["started_at"])
        if found is None:
            if case["investigation_id"] or elapsed > self.settings.campaign_alert_timeout_s:
                status = "failed" if case["investigation_id"] else "no_alert"
                self.finish(campaign, case, status, None, None, cause, case["investigation_id"])
            return
        if not case["investigation_id"]:
            case = self.store.update_case(case["id"], investigation_id=found["id"])
        if found["state"] == "completed":
            rank = gabarito.positions(found).get(cause)
            top = (found.get("suspects") or [{}])[0].get("service")
            self.finish(campaign, case, "evaluated", rank, top, cause, found["id"])
        elif found["state"] == "failed":
            self.finish(campaign, case, "failed", None, None, cause, found["id"])
        elif elapsed > self.settings.campaign_alert_timeout_s + self.settings.campaign_analysis_timeout_s + self.settings.demo_duration_s:
            self.finish(campaign, case, "failed", None, None, cause, found["id"])

    def finish(self, campaign, case, status, rank, top_service, cause, investigation_id):
        self.store.update_case(case["id"], state="done", status=status, rank=rank, top_service=top_service, root_cause_service=cause,
                               investigation_id=investigation_id, finished_at=self.clock())
        refreshed = self.store.update_campaign(campaign["id"], phase_since=self.clock())
        self.updated(refreshed)
        self.hub.publish(GLOBAL_TOPIC, "accuracy.updated", {})

    def view(self, campaign):
        if campaign is None:
            return None
        cases = self.store.campaign_cases(campaign["id"])
        done = [c for c in cases if c["state"] == "done"]
        live = campaign["state"] in ("running", "paused")
        remaining = sum(1 for c in cases if c["state"] in ("pending", "running"))
        durations = [(c["finished_at"] - c["started_at"]).total_seconds() + self.settings.campaign_calm_s for c in done if c["started_at"] and c["finished_at"]]
        average = sum(durations) / len(durations) if durations else DEFAULT_CASE_S
        return {
            "id": campaign["id"], "state": campaign["state"], "per_fault": campaign["per_fault"], "total": campaign["total"], "done": len(done),
            "started_at": views.to_iso(campaign["started_at"]), "eta_s": int(remaining * average) if live else None,
            "pause_reason": campaign.get("pause_reason"), "current": self.current(campaign, cases) if live else None,
        }

    def current(self, campaign, cases):
        running = next((c for c in cases if c["state"] == "running"), None)
        if running:
            title = CATALOG[running["kind"]]["title"]
            if running["investigation_id"]:
                return {"kind": running["kind"], "title": title, "phase": "analyzing", "detail": "O alerta disparou e a análise está rodando"}
            return {"kind": running["kind"], "title": title, "phase": "fault_on", "detail": "Falha ligada, aguardando o alerta"}
        pending = next((c for c in cases if c["state"] == "pending"), None)
        if pending is None:
            return None
        minutes = int(self.gate.calm_for() // 60)
        detail = "Esperando o Demo ficar calmo: %d de %d minutos sem alertas nem erros" % (minutes, self.settings.campaign_calm_s // 60)
        if self.gate.reason:
            detail += " (%s)" % self.gate.reason
        return {"kind": pending["kind"], "title": CATALOG[pending["kind"]]["title"], "phase": "calm_wait", "detail": detail}

    def report(self):
        campaign = self.store.latest_campaign()
        cases = self.store.campaign_cases(campaign["id"]) if campaign else []
        result = accuracy.report(cases, CATALOG, campaign["per_fault"] if campaign else 0)
        result["campaign"] = self.view(campaign)
        return result

    def owns_incident(self, incident_id):
        return incident_id is not None and self.store.campaign_case_for_incident(incident_id) is not None

    def start_thread(self):
        self.stopped.clear()
        self.thread = threading.Thread(target=self.loop, name="campaign", daemon=True)
        self.thread.start()

    def stop_thread(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)

    def loop(self):
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("campaign cycle failed")
            self.stopped.wait(self.settings.campaign_tick_s)
