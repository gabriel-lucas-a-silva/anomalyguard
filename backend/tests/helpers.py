from types import SimpleNamespace

from tests.synthetic import tables

TABLE_OF = {"metrics": lambda name: name, "logs": lambda name: name, "trace_err": lambda name: name, "trace_lat": lambda name: name}


def prepared_from(frames):
    catalog = {}
    for table, frame in frames.items():
        for column in frame.columns:
            if column == "time":
                continue
            service, indicator = column.split("|", 1)
            catalog.setdefault(service, {})[indicator] = {"table": table, "column": column}
    coverage = {
        service: {
            "metrics": any(v["table"] == "metrics" for v in entries.values()),
            "logs": any(v["table"] == "logs" for v in entries.values()),
            "traces": any(v["table"] in ("trace_err", "trace_lat") for v in entries.values()),
        }
        for service, entries in catalog.items()
    }
    return SimpleNamespace(catalog=catalog, coverage=coverage, warnings=[], tables=lambda: frames)


def synthetic_case(**kwargs):
    frames = tables(**kwargs)
    return frames, prepared_from(frames)


from datetime import datetime, timedelta, timezone

from anomalyguard.alerts import normalize
from anomalyguard.config import Settings
from anomalyguard.events import EventHub
from anomalyguard.service import Investigations
from anomalyguard.store import MemoryStore

START = datetime(2026, 11, 22, 2, 6, 40, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=START + timedelta(minutes=10)):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


def settings(**overrides):
    base = dict(database_url="db", prometheus_url="http://p", opensearch_url="http://o", allowed_origins=(), webhook_token="secret")
    base.update(overrides)
    return Settings(**base)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_alert(status="firing", starts_at=START, name="FrontendHighErrorRate", service="frontend", fingerprint="fp-1", annotations=None, ends_at=None):
    body = {"status": status, "labels": {"alertname": name, "service": service}, "annotations": annotations or {}, "startsAt": iso(starts_at),
            "endsAt": iso(ends_at) if ends_at else "0001-01-01T00:00:00Z", "fingerprint": fingerprint}
    return body


def alert(**kwargs):
    return normalize(raw_alert(**kwargs))


class Recorder:
    def __init__(self, hub, topic):
        self.events = []
        self.subscription = hub.subscribe(topic, self.events.append)

    def names(self):
        return [e["event"] for e in self.events]


def world(clock=None, **setting_overrides):
    clock = clock or FakeClock()
    store = MemoryStore(clock)
    hub = EventHub()
    config = settings(**setting_overrides)
    return Investigations(store, hub, config, clock), store, hub, clock, config


SUSPECT = {"rank": 1, "service": "payment", "torai_score": 0.4, "share": 0.4, "signal": "Erros nos traces", "detail": "de 0 para 11 erros a cada 15 s", "evidence_ids": [1]}
EVIDENCE = {"id": 1, "service": "payment", "kind": "trace_err", "indicator": "trace_err:Charge", "signal": "Erros nos traces", "normal_median": 0.0,
            "incident_max": 11.0, "ratio": None, "text": "payment: Erros nos traces. Normal (mediana): 0 erros a cada 15 s. No incidente (máximo): 11 erros a cada 15 s."}


def finish_row(store, identifier, suspects=None, evidence=None):
    store.save_result(identifier, suspects if suspects is not None else [], evidence if evidence is not None else [], [], {}, [], [])
    return store.finish(identifier, {"state": "ready", "kind": "fixed", "verified": None, "headline": "x", "paragraphs": [], "evidence": [], "failure_reason": None})


def completed_with_ranking(store, identifier, ranking):
    suspects = [{"rank": r["position"], "service": r["service"], "torai_score": r["score"], "share": r["score"], "signal": "x", "detail": "y", "evidence_ids": []} for r in ranking[:3]]
    store.save_result(identifier, suspects, [], [], {}, [], [], ranking)
    return store.finish(identifier, {"state": "ready", "kind": "fixed", "verified": None, "headline": "x", "paragraphs": [], "evidence": [], "failure_reason": None})


RANKING = [{"position": 1, "service": "frontend", "score": 0.23}, {"position": 2, "service": "payment", "score": 0.2}, {"position": 3, "service": "checkout", "score": 0.19},
           {"position": 4, "service": "ad", "score": 0.1}]
