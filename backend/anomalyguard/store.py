import copy
import threading
from datetime import timedelta

import psycopg2
import psycopg2.extras

from . import snapshot as snapshots

STAGES = {"received": 0, "waiting": 1, "collecting": 2, "preparing": 3, "analyzing": 4, "explaining": 5, "completed": 6}
TERMINAL = ("completed", "failed")
WORKING = ("collecting", "preparing", "analyzing", "explaining")

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS investigation_seq;
CREATE TABLE IF NOT EXISTS investigation (
    id text PRIMARY KEY DEFAULT 'INV-' || lpad(nextval('investigation_seq')::text, 4, '0'),
    alert_name text NOT NULL,
    service text NOT NULL,
    received_at timestamptz NOT NULL,
    state text NOT NULL,
    failure_reason text,
    log jsonb NOT NULL DEFAULT '[]',
    suspects jsonb NOT NULL DEFAULT '[]',
    timings jsonb NOT NULL DEFAULT '{}',
    missing_sources jsonb NOT NULL DEFAULT '[]',
    warnings jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS margin_s integer NOT NULL DEFAULT 315;
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS ready_at timestamptz;
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS grouped_alerts integer NOT NULL DEFAULT 1;
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS resolved_before_analysis boolean NOT NULL DEFAULT false;
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS evidence jsonb NOT NULL DEFAULT '[]';
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS limitations jsonb NOT NULL DEFAULT '[]';
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS narrative jsonb;
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS ranking jsonb NOT NULL DEFAULT '[]';
ALTER TABLE investigation ADD COLUMN IF NOT EXISTS replay_of text;
CREATE INDEX IF NOT EXISTS investigation_received_idx ON investigation (received_at DESC);
CREATE INDEX IF NOT EXISTS investigation_state_idx ON investigation (state);
CREATE TABLE IF NOT EXISTS alert (
    id bigserial PRIMARY KEY,
    investigation_id text NOT NULL REFERENCES investigation (id) ON DELETE CASCADE,
    fingerprint text NOT NULL,
    status text NOT NULL,
    role text NOT NULL,
    alert_name text NOT NULL,
    labels jsonb NOT NULL DEFAULT '{}',
    annotations jsonb NOT NULL DEFAULT '{}',
    starts_at timestamptz NOT NULL,
    ends_at timestamptz,
    received_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fingerprint, starts_at, status)
);
CREATE INDEX IF NOT EXISTS alert_fingerprint_idx ON alert (fingerprint);
CREATE TABLE IF NOT EXISTS demo_incident (
    id serial PRIMARY KEY,
    kind text NOT NULL,
    flag text NOT NULL,
    variant text NOT NULL,
    state text NOT NULL DEFAULT 'active',
    started_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    finished_at timestamptz,
    failure_reason text
);
ALTER TABLE demo_incident ADD COLUMN IF NOT EXISTS root_cause_service text NOT NULL DEFAULT 'payment';
ALTER TABLE demo_incident ADD COLUMN IF NOT EXISTS expected_signal text NOT NULL DEFAULT 'trace_err';
CREATE TABLE IF NOT EXISTS snapshot (
    investigation_id text PRIMARY KEY REFERENCES investigation (id) ON DELETE CASCADE,
    payload bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS campaign (
    id serial PRIMARY KEY,
    state text NOT NULL DEFAULT 'running',
    per_fault integer NOT NULL,
    total integer NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    pause_reason text,
    phase_since timestamptz
);
CREATE TABLE IF NOT EXISTS campaign_case (
    id serial PRIMARY KEY,
    campaign_id integer NOT NULL REFERENCES campaign (id) ON DELETE CASCADE,
    position integer NOT NULL,
    kind text NOT NULL,
    state text NOT NULL DEFAULT 'pending',
    incident_id integer,
    investigation_id text,
    status text,
    top_service text,
    root_cause_service text,
    rank integer,
    started_at timestamptz,
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS campaign_case_campaign_idx ON campaign_case (campaign_id, position);
CREATE TABLE IF NOT EXISTS ground_truth (
    investigation_id text PRIMARY KEY REFERENCES investigation (id) ON DELETE CASCADE,
    root_cause_service text NOT NULL,
    fault_kind text NOT NULL,
    expected_signal text,
    source text NOT NULL,
    incident_id integer,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
"""

CAMPAIGN_COLUMNS = "id, state, per_fault, total, started_at, finished_at, pause_reason, phase_since"
CASE_COLUMNS = ("id, campaign_id, position, kind, state, incident_id, investigation_id, status, top_service, root_cause_service, rank, started_at, finished_at")
CAMPAIGN_FIELDS = ("state", "finished_at", "pause_reason", "phase_since")
CASE_FIELDS = ("state", "incident_id", "investigation_id", "status", "top_service", "root_cause_service", "rank", "started_at", "finished_at")
ACTIVE_CAMPAIGN = ("running", "paused")

INCIDENT_COLUMNS = "id, kind, flag, variant, state, started_at, ends_at, finished_at, failure_reason, root_cause_service, expected_signal"
TRUTH_COLUMNS = "investigation_id, root_cause_service, fault_kind, expected_signal, source, incident_id, recorded_at"
COVERAGE_MARGIN_S = 120

COLUMNS = ("id, alert_name, service, received_at, state, failure_reason, log, suspects, timings, missing_sources, warnings, "
           "margin_s, ready_at, grouped_alerts, resolved_before_analysis, evidence, limitations, narrative, ranking, replay_of, updated_at")
QUALIFIED = ", ".join("i." + c.strip() for c in COLUMNS.split(","))


def log_entry(at, tag, message):
    return {"at": at.isoformat(), "tag": tag, "message": message}


def finish_entries(clock, narrative):
    if narrative.get("kind") == "llm" and narrative.get("verified"):
        explained = log_entry(clock(), "relatório", "Citações conferidas: a explicação foi verificada")
    else:
        reason = narrative.get("failure_reason") or "sem motivo registrado"
        explained = log_entry(clock(), "relatório", "Explicação não verificada: usando o texto automático (%s)" % reason)
    return [explained, log_entry(clock(), "fim", "Investigação concluída")]


def result_entries(clock):
    return [log_entry(clock(), "análise", "Ranking dos suspeitos pronto"), log_entry(clock(), "relatório", "Escrevendo a explicação com as evidências numeradas")]


STATE_FILTERS = ("running", "completed", "failed")


def state_matches(state, wanted):
    if wanted is None:
        return True
    if wanted == "running":
        return state not in TERMINAL
    return state == wanted


class MemoryStore:
    def __init__(self, clock):
        self.clock = clock
        self.rows = {}
        self.alerts = []
        self.incidents = []
        self.truths = {}
        self.snapshots = {}
        self.campaigns = []
        self.cases = []
        self.sequence = 0
        self.lock = threading.Lock()

    def save_snapshot(self, identifier, payload):
        with self.lock:
            self.snapshots[identifier] = copy.deepcopy(payload)

    def get_snapshot(self, identifier):
        with self.lock:
            payload = self.snapshots.get(identifier)
            return copy.deepcopy(payload) if payload is not None else None

    def snapshot_ids(self, identifiers):
        with self.lock:
            return {i for i in identifiers if i in self.snapshots}

    def set_ground_truth(self, identifier, service, fault_kind, expected_signal, source, incident_id=None):
        with self.lock:
            truth = {"investigation_id": identifier, "root_cause_service": service, "fault_kind": fault_kind, "expected_signal": expected_signal,
                     "source": source, "incident_id": incident_id, "recorded_at": self.clock()}
            self.truths[identifier] = truth
            return dict(truth)

    def get_ground_truth(self, identifier):
        with self.lock:
            truth = self.truths.get(identifier)
            return dict(truth) if truth else None

    def ground_truths(self, identifiers):
        with self.lock:
            return {i: dict(self.truths[i]) for i in identifiers if i in self.truths}

    def labeled(self):
        with self.lock:
            rows = [(copy.deepcopy(self.rows[i]), dict(t)) for i, t in self.truths.items() if i in self.rows and not self.rows[i]["replay_of"]]
            rows.sort(key=lambda pair: (pair[0]["received_at"], pair[0]["id"]), reverse=True)
            return rows

    def incident_covering(self, moment):
        with self.lock:
            margin = timedelta(seconds=COVERAGE_MARGIN_S)
            covering = [i for i in self.incidents if i["started_at"] <= moment <= (i["finished_at"] or i["ends_at"]) + margin]
            return dict(covering[-1]) if covering else None

    def create_incident(self, kind, flag, variant, started_at, ends_at, root_cause_service="payment", expected_signal="trace_err"):
        with self.lock:
            incident = {"id": len(self.incidents) + 1, "kind": kind, "flag": flag, "variant": variant, "state": "active", "started_at": started_at,
                        "ends_at": ends_at, "finished_at": None, "failure_reason": None, "root_cause_service": root_cause_service,
                        "expected_signal": expected_signal}
            self.incidents.append(incident)
            return dict(incident)

    def create_campaign(self, per_fault, kinds, started_at):
        with self.lock:
            campaign = {"id": len(self.campaigns) + 1, "state": "running", "per_fault": per_fault, "total": len(kinds), "started_at": started_at,
                        "finished_at": None, "pause_reason": None, "phase_since": started_at}
            self.campaigns.append(campaign)
            for position, kind in enumerate(kinds):
                self.cases.append({"id": len(self.cases) + 1, "campaign_id": campaign["id"], "position": position, "kind": kind, "state": "pending",
                                   "incident_id": None, "investigation_id": None, "status": None, "top_service": None, "root_cause_service": None,
                                   "rank": None, "started_at": None, "finished_at": None})
            return dict(campaign)

    def get_campaign(self, identifier):
        with self.lock:
            return next((dict(c) for c in self.campaigns if c["id"] == identifier), None)

    def latest_campaign(self):
        with self.lock:
            return dict(self.campaigns[-1]) if self.campaigns else None

    def active_campaign(self):
        with self.lock:
            return next((dict(c) for c in reversed(self.campaigns) if c["state"] in ACTIVE_CAMPAIGN), None)

    def update_campaign(self, identifier, **fields):
        with self.lock:
            campaign = next(c for c in self.campaigns if c["id"] == identifier)
            campaign.update({k: v for k, v in fields.items() if k in CAMPAIGN_FIELDS})
            return dict(campaign)

    def campaign_cases(self, campaign_id):
        with self.lock:
            return sorted((dict(c) for c in self.cases if c["campaign_id"] == campaign_id), key=lambda c: c["position"])

    def update_case(self, identifier, **fields):
        with self.lock:
            case = next(c for c in self.cases if c["id"] == identifier)
            case.update({k: v for k, v in fields.items() if k in CASE_FIELDS})
            return dict(case)

    def cancel_open_cases(self, campaign_id):
        with self.lock:
            for case in self.cases:
                if case["campaign_id"] == campaign_id and case["state"] != "done":
                    case["state"] = "cancelled"

    def campaign_case_for_incident(self, incident_id):
        with self.lock:
            return next((dict(c) for c in self.cases if c["incident_id"] == incident_id), None)

    def get_incident(self, identifier):
        with self.lock:
            return next((dict(i) for i in self.incidents if i["id"] == identifier), None)

    def active_incident(self):
        with self.lock:
            return next((dict(i) for i in reversed(self.incidents) if i["state"] == "active"), None)

    def active_incidents(self):
        with self.lock:
            return [dict(i) for i in self.incidents if i["state"] == "active"]

    def latest_incident(self):
        with self.lock:
            return dict(self.incidents[-1]) if self.incidents else None

    def finish_incident(self, identifier, state, finished_at, reason):
        with self.lock:
            incident = next(i for i in self.incidents if i["id"] == identifier)
            incident.update(state=state, finished_at=finished_at, failure_reason=reason)
            return dict(incident)

    def first_investigation_since(self, since):
        with self.lock:
            rows = [r for r in self.rows.values() if r["created_at"] >= since and not r["replay_of"]]
            rows.sort(key=lambda r: (r["created_at"], r["id"]))
            return copy.deepcopy(rows[0]) if rows else None

    def stale(self, before):
        with self.lock:
            return [copy.deepcopy(r) for r in self.rows.values() if r["state"] in WORKING and r["updated_at"] < before]

    def _touch(self, row):
        row["updated_at"] = self.clock()
        return copy.deepcopy(row)

    def create_investigation(self, alert_name, service, t_alert, margin_s, ready_at, replay_of=None, first_message=None):
        with self.lock:
            self.sequence += 1
            identifier = "INV-%04d" % self.sequence
            message = first_message or "Alerta %s recebido (serviço %s)" % (alert_name, service)
            row = {"id": identifier, "alert_name": alert_name, "service": service, "received_at": t_alert, "state": "received",
                   "failure_reason": None, "log": [log_entry(self.clock(), "alerta", message)],
                   "suspects": [], "timings": {}, "missing_sources": [], "warnings": [], "margin_s": margin_s, "ready_at": ready_at,
                   "grouped_alerts": 1, "resolved_before_analysis": False, "evidence": [], "limitations": [], "narrative": None,
                   "ranking": [], "replay_of": replay_of, "created_at": self.clock()}
            self.rows[identifier] = row
            return self._touch(row)

    def delete_investigations(self, identifiers):
        with self.lock:
            removed = [i for i in identifiers if self.rows.pop(i, None) is not None]
            for identifier in removed:
                self.truths.pop(identifier, None)
                self.snapshots.pop(identifier, None)
            self.alerts = [a for a in self.alerts if a["investigation_id"] not in removed]
            return removed

    def terminal_ids(self):
        with self.lock:
            return [r["id"] for r in self.rows.values() if r["state"] in TERMINAL]

    def alert_exists(self, fingerprint, starts_at, status):
        with self.lock:
            return any(a["fingerprint"] == fingerprint and a["starts_at"] == starts_at and a["status"] == status for a in self.alerts)

    def add_alert(self, identifier, alert, role):
        with self.lock:
            self.alerts.append({"investigation_id": identifier, "fingerprint": alert.fingerprint, "status": alert.status, "role": role,
                                "starts_at": alert.starts_at, "alert_name": alert.alert_name})

    def get(self, identifier):
        with self.lock:
            row = self.rows.get(identifier)
            return copy.deepcopy(row) if row else None

    def list(self, limit, cursor=None, state=None, service=None):
        with self.lock:
            rows = [r for r in self.rows.values() if state_matches(r["state"], state) and (service is None or r["service"] == service)]
            rows.sort(key=lambda r: (r["received_at"], r["id"]), reverse=True)
            if cursor is not None:
                rows = [r for r in rows if (r["received_at"], r["id"]) < cursor]
            return [copy.deepcopy(r) for r in rows[:limit]]

    def count(self, state=None, service=None):
        with self.lock:
            return sum(1 for r in self.rows.values() if state_matches(r["state"], state) and (service is None or r["service"] == service))

    def services(self):
        with self.lock:
            counts = {}
            for row in self.rows.values():
                counts[row["service"]] = counts.get(row["service"], 0) + 1
            return [{"service": name, "count": counts[name]} for name in sorted(counts)]

    def find_open(self, service):
        with self.lock:
            rows = [r for r in self.rows.values() if r["service"] == service and r["state"] not in TERMINAL and not r["replay_of"]]
            rows.sort(key=lambda r: r["received_at"], reverse=True)
            return copy.deepcopy(rows[0]) if rows else None

    def find_recent_terminal(self, service, since):
        with self.lock:
            rows = [r for r in self.rows.values() if r["service"] == service and r["state"] in TERMINAL and r["updated_at"] >= since and not r["replay_of"]]
            rows.sort(key=lambda r: r["updated_at"], reverse=True)
            return copy.deepcopy(rows[0]) if rows else None

    def find_by_fingerprint(self, fingerprint):
        with self.lock:
            ids = [a["investigation_id"] for a in self.alerts if a["fingerprint"] == fingerprint]
            return copy.deepcopy(self.rows[ids[-1]]) if ids else None

    def bump_grouped(self, identifier):
        with self.lock:
            row = self.rows[identifier]
            row["grouped_alerts"] += 1
            return self._touch(row)

    def mark_resolved(self, identifier):
        with self.lock:
            row = self.rows[identifier]
            if row["state"] not in TERMINAL:
                row["resolved_before_analysis"] = True
            return self._touch(row)

    def add_log(self, identifier, tag, message):
        with self.lock:
            row = self.rows[identifier]
            row["log"] = row["log"] + [log_entry(self.clock(), tag, message)]
            return self._touch(row)

    def due(self, now):
        with self.lock:
            rows = [r for r in self.rows.values() if r["state"] == "waiting" and r["ready_at"] is not None and r["ready_at"] <= now]
            rows.sort(key=lambda r: r["ready_at"])
            return [copy.deepcopy(r) for r in rows]

    def interrupted(self):
        with self.lock:
            return [copy.deepcopy(r) for r in self.rows.values() if r["state"] in WORKING]

    def claim(self, identifier):
        with self.lock:
            row = self.rows[identifier]
            if row["state"] != "waiting":
                return False
            row["state"] = "collecting"
            self._touch(row)
            return True

    def advance(self, identifier, state, tag, message):
        with self.lock:
            row = self.rows[identifier]
            row["state"] = state
            row["log"] = row["log"] + [log_entry(self.clock(), tag, message)]
            return self._touch(row)

    def save_result(self, identifier, suspects, evidence, limitations, timings, missing_sources, warnings, ranking=None):
        with self.lock:
            row = self.rows[identifier]
            row.update(state="explaining", suspects=suspects, evidence=evidence, limitations=limitations, timings=timings,
                       missing_sources=missing_sources, warnings=warnings, ranking=ranking or [])
            row["log"] = row["log"] + result_entries(self.clock)
            return self._touch(row)

    def finish(self, identifier, narrative):
        with self.lock:
            row = self.rows[identifier]
            row.update(state="completed", narrative=narrative)
            row["log"] = row["log"] + finish_entries(self.clock, narrative)
            return self._touch(row)

    def fail(self, identifier, reason):
        with self.lock:
            row = self.rows[identifier]
            row.update(state="failed", failure_reason=reason)
            row["log"] = row["log"] + [log_entry(self.clock(), "erro", reason)]
            return self._touch(row)


class PostgresStore:
    def __init__(self, url, clock):
        self.url = url
        self.clock = clock
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(SCHEMA)

    def _connect(self):
        return psycopg2.connect(self.url, cursor_factory=psycopg2.extras.RealDictCursor)

    def _row(self, cursor):
        row = cursor.fetchone()
        return dict(row) if row else None

    def _rows(self, cursor):
        return [dict(r) for r in cursor.fetchall()]

    def create_investigation(self, alert_name, service, t_alert, margin_s, ready_at, replay_of=None, first_message=None):
        entry = log_entry(self.clock(), "alerta", first_message or "Alerta %s recebido (serviço %s)" % (alert_name, service))
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO investigation (alert_name, service, received_at, state, log, margin_s, ready_at, replay_of) "
                "VALUES (%s, %s, %s, 'received', %s, %s, %s, %s) RETURNING " + COLUMNS,
                (alert_name, service, t_alert, psycopg2.extras.Json([entry]), margin_s, ready_at, replay_of))
            return self._row(cursor)

    def alert_exists(self, fingerprint, starts_at, status):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM alert WHERE fingerprint = %s AND starts_at = %s AND status = %s", (fingerprint, starts_at, status))
            return cursor.fetchone() is not None

    def add_alert(self, identifier, alert, role):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO alert (investigation_id, fingerprint, status, role, alert_name, labels, annotations, starts_at, ends_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (identifier, alert.fingerprint, alert.status, role, alert.alert_name, psycopg2.extras.Json(alert.labels),
                 psycopg2.extras.Json(alert.annotations), alert.starts_at, alert.ends_at))

    def get(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE id = %s", (identifier,))
            return self._row(cursor)

    def delete_investigations(self, identifiers):
        if not identifiers:
            return []
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM investigation WHERE id = ANY(%s) RETURNING id", (list(identifiers),))
            return [row["id"] for row in cursor.fetchall()]

    def terminal_ids(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id FROM investigation WHERE state = ANY(%s)", (list(TERMINAL),))
            return [row["id"] for row in cursor.fetchall()]

    def create_incident(self, kind, flag, variant, started_at, ends_at, root_cause_service="payment", expected_signal="trace_err"):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO demo_incident (kind, flag, variant, started_at, ends_at, root_cause_service, expected_signal) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING " + INCIDENT_COLUMNS,
                           (kind, flag, variant, started_at, ends_at, root_cause_service, expected_signal))
            return self._row(cursor)

    def save_snapshot(self, identifier, payload):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO snapshot (investigation_id, payload) VALUES (%s, %s) ON CONFLICT (investigation_id) DO UPDATE SET payload = EXCLUDED.payload, created_at = now()",
                           (identifier, psycopg2.Binary(snapshots.pack(payload))))

    def get_snapshot(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM snapshot WHERE investigation_id = %s", (identifier,))
            row = cursor.fetchone()
            return snapshots.unpack(row["payload"]) if row else None

    def snapshot_ids(self, identifiers):
        if not identifiers:
            return set()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT investigation_id FROM snapshot WHERE investigation_id = ANY(%s)", (list(identifiers),))
            return {r["investigation_id"] for r in cursor.fetchall()}

    def set_ground_truth(self, identifier, service, fault_kind, expected_signal, source, incident_id=None):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO ground_truth (investigation_id, root_cause_service, fault_kind, expected_signal, source, incident_id) "
                           "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (investigation_id) DO UPDATE SET root_cause_service = EXCLUDED.root_cause_service, "
                           "fault_kind = EXCLUDED.fault_kind, expected_signal = EXCLUDED.expected_signal, source = EXCLUDED.source, "
                           "incident_id = EXCLUDED.incident_id, recorded_at = now() RETURNING " + TRUTH_COLUMNS,
                           (identifier, service, fault_kind, expected_signal, source, incident_id))
            return self._row(cursor)

    def get_ground_truth(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + TRUTH_COLUMNS + " FROM ground_truth WHERE investigation_id = %s", (identifier,))
            return self._row(cursor)

    def ground_truths(self, identifiers):
        if not identifiers:
            return {}
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + TRUTH_COLUMNS + " FROM ground_truth WHERE investigation_id = ANY(%s)", (list(identifiers),))
            return {r["investigation_id"]: dict(r) for r in cursor.fetchall()}

    def labeled(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + QUALIFIED + " FROM investigation i JOIN ground_truth g ON g.investigation_id = i.id WHERE i.replay_of IS NULL "
                           "ORDER BY i.received_at DESC, i.id DESC")
            rows = self._rows(cursor)
            truths = {t["investigation_id"]: t for t in self._truths_for(cursor, [r["id"] for r in rows])}
        return [(row, truths[row["id"]]) for row in rows]

    def _truths_for(self, cursor, identifiers):
        if not identifiers:
            return []
        cursor.execute("SELECT " + TRUTH_COLUMNS + " FROM ground_truth WHERE investigation_id = ANY(%s)", (identifiers,))
        return [dict(r) for r in cursor.fetchall()]

    def incident_covering(self, moment):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + INCIDENT_COLUMNS + " FROM demo_incident WHERE started_at <= %s "
                           "AND %s <= COALESCE(finished_at, ends_at) + make_interval(secs => %s) ORDER BY id DESC LIMIT 1",
                           (moment, moment, COVERAGE_MARGIN_S))
            return self._row(cursor)

    def create_campaign(self, per_fault, kinds, started_at):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO campaign (per_fault, total, started_at, phase_since) VALUES (%s, %s, %s, %s) RETURNING " + CAMPAIGN_COLUMNS,
                           (per_fault, len(kinds), started_at, started_at))
            campaign = self._row(cursor)
            for position, kind in enumerate(kinds):
                cursor.execute("INSERT INTO campaign_case (campaign_id, position, kind) VALUES (%s, %s, %s)", (campaign["id"], position, kind))
            return campaign

    def get_campaign(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + CAMPAIGN_COLUMNS + " FROM campaign WHERE id = %s", (identifier,))
            return self._row(cursor)

    def latest_campaign(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + CAMPAIGN_COLUMNS + " FROM campaign ORDER BY id DESC LIMIT 1")
            return self._row(cursor)

    def active_campaign(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + CAMPAIGN_COLUMNS + " FROM campaign WHERE state = ANY(%s) ORDER BY id DESC LIMIT 1", (list(ACTIVE_CAMPAIGN),))
            return self._row(cursor)

    def update_campaign(self, identifier, **fields):
        fields = {k: v for k, v in fields.items() if k in CAMPAIGN_FIELDS}
        with self._connect() as connection, connection.cursor() as cursor:
            if fields:
                cursor.execute("UPDATE campaign SET " + ", ".join("%s = %%s" % k for k in fields) + " WHERE id = %s", list(fields.values()) + [identifier])
            cursor.execute("SELECT " + CAMPAIGN_COLUMNS + " FROM campaign WHERE id = %s", (identifier,))
            return self._row(cursor)

    def campaign_cases(self, campaign_id):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + CASE_COLUMNS + " FROM campaign_case WHERE campaign_id = %s ORDER BY position", (campaign_id,))
            return self._rows(cursor)

    def update_case(self, identifier, **fields):
        fields = {k: v for k, v in fields.items() if k in CASE_FIELDS}
        with self._connect() as connection, connection.cursor() as cursor:
            if fields:
                cursor.execute("UPDATE campaign_case SET " + ", ".join("%s = %%s" % k for k in fields) + " WHERE id = %s", list(fields.values()) + [identifier])
            cursor.execute("SELECT " + CASE_COLUMNS + " FROM campaign_case WHERE id = %s", (identifier,))
            return self._row(cursor)

    def cancel_open_cases(self, campaign_id):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE campaign_case SET state = 'cancelled' WHERE campaign_id = %s AND state <> 'done'", (campaign_id,))

    def campaign_case_for_incident(self, incident_id):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + CASE_COLUMNS + " FROM campaign_case WHERE incident_id = %s LIMIT 1", (incident_id,))
            return self._row(cursor)

    def get_incident(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + INCIDENT_COLUMNS + " FROM demo_incident WHERE id = %s", (identifier,))
            return self._row(cursor)

    def active_incident(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + INCIDENT_COLUMNS + " FROM demo_incident WHERE state = 'active' ORDER BY id DESC LIMIT 1")
            return self._row(cursor)

    def active_incidents(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + INCIDENT_COLUMNS + " FROM demo_incident WHERE state = 'active' ORDER BY id")
            return self._rows(cursor)

    def latest_incident(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + INCIDENT_COLUMNS + " FROM demo_incident ORDER BY id DESC LIMIT 1")
            return self._row(cursor)

    def finish_incident(self, identifier, state, finished_at, reason):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE demo_incident SET state = %s, finished_at = %s, failure_reason = %s WHERE id = %s RETURNING " + INCIDENT_COLUMNS,
                           (state, finished_at, reason, identifier))
            return self._row(cursor)

    def first_investigation_since(self, since):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE created_at >= %s AND replay_of IS NULL ORDER BY created_at, id LIMIT 1", (since,))
            return self._row(cursor)

    def stale(self, before):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE state IN ('collecting', 'preparing', 'analyzing', 'explaining') AND updated_at < %s", (before,))
            return self._rows(cursor)

    def _filters(self, state, service):
        clauses, params = [], []
        if state == "running":
            clauses.append("state NOT IN ('completed', 'failed')")
        elif state is not None:
            clauses.append("state = %s")
            params.append(state)
        if service is not None:
            clauses.append("service = %s")
            params.append(service)
        return clauses, params

    def list(self, limit, cursor=None, state=None, service=None):
        clauses, params = self._filters(state, service)
        if cursor is not None:
            clauses.append("(received_at, id) < (%s, %s)")
            params.extend(cursor)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as connection, connection.cursor() as cursor_:
            cursor_.execute("SELECT " + COLUMNS + " FROM investigation" + where + " ORDER BY received_at DESC, id DESC LIMIT %s", params + [limit])
            return self._rows(cursor_)

    def count(self, state=None, service=None):
        clauses, params = self._filters(state, service)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS n FROM investigation" + where, params)
            return cursor.fetchone()["n"]

    def services(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT service, count(*) AS count FROM investigation GROUP BY service ORDER BY service")
            return [{"service": r["service"], "count": r["count"]} for r in cursor.fetchall()]

    def find_open(self, service):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE service = %s AND state NOT IN ('completed', 'failed') AND replay_of IS NULL "
                           "ORDER BY received_at DESC LIMIT 1", (service,))
            return self._row(cursor)

    def find_recent_terminal(self, service, since):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE service = %s AND state IN ('completed', 'failed') AND replay_of IS NULL "
                           "AND updated_at >= %s ORDER BY updated_at DESC LIMIT 1", (service, since))
            return self._row(cursor)

    def find_by_fingerprint(self, fingerprint):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + QUALIFIED + " FROM investigation i JOIN alert a ON a.investigation_id = i.id "
                           "WHERE a.fingerprint = %s ORDER BY a.id DESC LIMIT 1", (fingerprint,))
            return self._row(cursor)

    def bump_grouped(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET grouped_alerts = grouped_alerts + 1, updated_at = now() WHERE id = %s RETURNING " + COLUMNS, (identifier,))
            return self._row(cursor)

    def mark_resolved(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET resolved_before_analysis = resolved_before_analysis OR state NOT IN ('completed', 'failed'), "
                           "updated_at = now() WHERE id = %s RETURNING " + COLUMNS, (identifier,))
            return self._row(cursor)

    def add_log(self, identifier, tag, message):
        entry = log_entry(self.clock(), tag, message)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET log = log || %s, updated_at = now() WHERE id = %s RETURNING " + COLUMNS,
                           (psycopg2.extras.Json([entry]), identifier))
            return self._row(cursor)

    def due(self, now):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE state = 'waiting' AND ready_at IS NOT NULL AND ready_at <= %s "
                           "ORDER BY ready_at", (now,))
            return self._rows(cursor)

    def interrupted(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT " + COLUMNS + " FROM investigation WHERE state IN ('collecting', 'preparing', 'analyzing', 'explaining')")
            return self._rows(cursor)

    def claim(self, identifier):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET state = 'collecting', updated_at = now() WHERE id = %s AND state = 'waiting'", (identifier,))
            return cursor.rowcount == 1

    def advance(self, identifier, state, tag, message):
        entry = log_entry(self.clock(), tag, message)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET state = %s, log = log || %s, updated_at = now() WHERE id = %s RETURNING " + COLUMNS,
                           (state, psycopg2.extras.Json([entry]), identifier))
            return self._row(cursor)

    def save_result(self, identifier, suspects, evidence, limitations, timings, missing_sources, warnings, ranking=None):
        entries = result_entries(self.clock)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE investigation SET state = 'explaining', suspects = %s, evidence = %s, limitations = %s, timings = %s, "
                "missing_sources = %s, warnings = %s, ranking = %s, log = log || %s, updated_at = now() WHERE id = %s RETURNING " + COLUMNS,
                (psycopg2.extras.Json(suspects), psycopg2.extras.Json(evidence), psycopg2.extras.Json(limitations), psycopg2.extras.Json(timings),
                 psycopg2.extras.Json(missing_sources), psycopg2.extras.Json(warnings), psycopg2.extras.Json(ranking or []), psycopg2.extras.Json(entries), identifier))
            return self._row(cursor)

    def finish(self, identifier, narrative):
        entries = finish_entries(self.clock, narrative)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET state = 'completed', narrative = %s, log = log || %s, updated_at = now() WHERE id = %s RETURNING " + COLUMNS,
                           (psycopg2.extras.Json(narrative), psycopg2.extras.Json(entries), identifier))
            return self._row(cursor)

    def fail(self, identifier, reason):
        entry = log_entry(self.clock(), "erro", reason)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE investigation SET state = 'failed', failure_reason = %s, log = log || %s, updated_at = now() "
                           "WHERE id = %s RETURNING " + COLUMNS, (reason, psycopg2.extras.Json([entry]), identifier))
            return self._row(cursor)
