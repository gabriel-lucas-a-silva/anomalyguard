import logging
import threading
from datetime import timedelta

from . import views
from .flags import FlagError

log = logging.getLogger("anomalyguard.demo")

ALERT = "FrontendHighErrorRate"
LATENCY_ALERT = "ProductCatalogHighLatency"

CATALOG = {
    "payment_failure": {
        "title": "Pagamento falhando",
        "description": "O serviço de pagamento recusa todas as cobranças. O checkout devolve erro e o frontend mostra falha ao finalizar a compra.",
        "flag": "paymentFailure", "variant": "100%", "service": "payment", "signal": "trace_err", "alert": ALERT,
    },
    "product_catalog_lock_contention": {
        "title": "Trava no banco do catálogo",
        "description": "O banco do catálogo de produtos fica travado por disputa de bloqueios. O catálogo e quem depende dele, como as recomendações, ficam muito lentos, mas sem devolver erro.",
        "flag": "productCatalogLockContention", "variant": "on", "service": "product-catalog", "signal": "trace_lat", "alert": LATENCY_ALERT,
    },
}


class DemoDisabled(Exception):
    pass


class DemoConflict(Exception):
    pass


class DemoUnknownFault(Exception):
    pass


def threading_schedule(delay_s, function):
    timer = threading.Timer(delay_s, function)
    timer.daemon = True
    timer.start()
    return timer.cancel


class DemoIncidents:
    def __init__(self, store, flags, settings, clock, schedule=threading_schedule):
        self.store = store
        self.flags = flags
        self.settings = settings
        self.clock = clock
        self.schedule = schedule
        self.lock = threading.Lock()
        self.cancel = None

    def require_enabled(self):
        if not self.settings.demo_mode:
            raise DemoDisabled("o modo demonstração está desligado")

    def options(self):
        self.require_enabled()
        return [{"kind": kind, "title": fault["title"], "description": fault["description"], "affected_service": fault["service"], "alert": fault["alert"]}
                for kind, fault in CATALOG.items()]

    def start(self, kind):
        self.require_enabled()
        if kind not in CATALOG:
            raise DemoUnknownFault("falha desconhecida %s; as possíveis são: %s" % (kind, ", ".join(sorted(CATALOG))))
        with self.lock:
            if self.store.active_incident() is not None:
                raise DemoConflict("já existe uma simulação em andamento")
            fault = CATALOG[kind]
            self.flags.set(fault["flag"], fault["variant"])
            now = self.clock()
            incident = self.store.create_incident(kind, fault["flag"], fault["variant"], now, now + timedelta(seconds=self.settings.demo_duration_s),
                                                  fault["service"], fault["signal"])
            self.arm(incident)
            return self.view(incident)

    def arm(self, incident):
        delay = max(0.0, (incident["ends_at"] - self.clock()).total_seconds())
        self.cancel = self.schedule(delay, lambda: self.finish(incident["id"], "finished"))

    def finish(self, identifier, state):
        with self.lock:
            incident = self.store.get_incident(identifier)
            if incident is None or incident["state"] != "active":
                return None
            try:
                self.flags.set(incident["flag"], "off")
            except FlagError as e:
                log.error("could not turn off %s: %s", incident["flag"], e)
                return self.view(self.store.finish_incident(identifier, "failed", self.clock(), str(e)))
            return self.view(self.store.finish_incident(identifier, state, self.clock(), None))

    def stop(self):
        self.require_enabled()
        incident = self.store.active_incident()
        if incident is None:
            raise DemoConflict("não há simulação em andamento")
        if self.cancel:
            self.cancel()
            self.cancel = None
        return self.finish(incident["id"], "stopped")

    def current(self):
        self.require_enabled()
        incident = self.store.active_incident() or self.store.latest_incident()
        return self.view(incident) if incident else None

    def recover(self):
        if not self.settings.demo_mode:
            return
        for incident in self.store.active_incidents():
            if incident["ends_at"] <= self.clock():
                self.finish(incident["id"], "finished")
            else:
                self.arm(incident)

    def view(self, incident):
        linked = self.store.first_investigation_since(incident["started_at"])
        return {
            "id": incident["id"], "kind": incident["kind"], "title": CATALOG.get(incident["kind"], {}).get("title"), "state": incident["state"],
            "started_at": views.to_iso(incident["started_at"]), "ends_at": views.to_iso(incident["ends_at"]),
            "finished_at": views.to_iso(incident["finished_at"]) if incident.get("finished_at") else None,
            "failure_reason": incident.get("failure_reason"),
            "investigation_id": linked["id"] if linked else None,
        }
