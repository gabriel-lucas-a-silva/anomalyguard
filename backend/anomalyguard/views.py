from datetime import timezone

from . import gabarito
from .store import STAGES


def to_iso(value):
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return str(value)


TAG_STAGES = {"alerta": 0, "espera": 1, "coleta": 2, "preparo": 3, "análise": 4, "relatório": 5}


def stage_of(row):
    if row["state"] != "failed":
        return STAGES[row["state"]]
    reached = [TAG_STAGES[e["tag"]] for e in row["log"] if e["tag"] in TAG_STAGES]
    return max(reached, default=0)


def summary(row, truth=None):
    top = row["suspects"][0] if row["suspects"] else None
    return {
        "id": row["id"],
        "alert_name": row["alert_name"],
        "service": row["service"],
        "received_at": to_iso(row["received_at"]),
        "state": row["state"],
        "stage": stage_of(row),
        "top_suspect": {"service": top["service"], "share": top["share"]} if top else None,
        "grouped_alerts": row["grouped_alerts"],
        "resolved_before_analysis": row["resolved_before_analysis"],
        "replay_of": row.get("replay_of"),
        "gabarito": gabarito.compact(gabarito.evaluate(truth, row)),
    }


def evidence_view(row):
    return [{"id": e["id"], "service": e["service"], "text": e["text"]} for e in row.get("evidence", [])]


def detail(row, partial=None, truth=None, replayable=False):
    suspects = [dict(s, evidence_ids=s.get("evidence_ids", [])) for s in row["suspects"]]
    return {
        "summary": summary(row, truth),
        "gabarito": gabarito.evaluate(truth, row),
        "replayable": replayable,
        "failure_reason": row["failure_reason"],
        "log": row["log"],
        "suspects": suspects,
        "narrative": row.get("narrative") or partial,
        "evidence": evidence_view(row),
        "limitations": row.get("limitations", []),
        "timings_ms": row["timings"],
        "missing_sources": row["missing_sources"],
    }
