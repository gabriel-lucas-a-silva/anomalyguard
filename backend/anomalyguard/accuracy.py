import math

from . import views

Z95 = 1.96
TOP_THREE = 3


def rate(hits, total):
    if total == 0:
        return {"hits": hits, "of": total, "rate": None, "low": None, "high": None}
    p = hits / total
    denominator = 1 + Z95 * Z95 / total
    center = (p + Z95 * Z95 / (2 * total)) / denominator
    margin = Z95 * math.sqrt(p * (1 - p) / total + Z95 * Z95 / (4 * total * total)) / denominator
    return {"hits": hits, "of": total, "rate": p, "low": max(0.0, center - margin), "high": min(1.0, center + margin)}


def finished_cases(cases):
    return [c for c in cases if c["state"] == "done" and c["status"] in ("evaluated", "no_alert", "failed")]


def hits(cases):
    top1 = sum(1 for c in cases if c["rank"] == 1)
    top3 = sum(1 for c in cases if c["rank"] is not None and c["rank"] <= TOP_THREE)
    return top1, top3


def case_view(case, titles):
    finished = case.get("finished_at")
    return {"id": case.get("investigation_id"), "kind": case["kind"], "title": titles.get(case["kind"], case["kind"]), "status": case["status"],
            "top_service": case.get("top_service"), "root_cause_service": case["root_cause_service"], "rank": case.get("rank"),
            "finished_at": views.to_iso(finished) if finished else None}


def fault_view(kind, title, planned, cases):
    mine = [c for c in cases if c["kind"] == kind]
    evaluated = [c for c in mine if c["status"] == "evaluated"]
    top1, top3 = hits(evaluated)
    return {"kind": kind, "title": title, "planned": planned, "evaluated": len(evaluated), "no_alert": sum(1 for c in mine if c["status"] == "no_alert"),
            "failed": sum(1 for c in mine if c["status"] == "failed"), "top1": rate(top1, len(evaluated)), "top3": rate(top3, len(evaluated))}


def report(cases, faults, per_fault):
    done = finished_cases(cases)
    evaluated = [c for c in done if c["status"] == "evaluated"]
    top1, top3 = hits(evaluated)
    ranks = [c["rank"] for c in evaluated if c["rank"] is not None]
    titles = {kind: fault["title"] for kind, fault in faults.items()}
    ordered = sorted(done, key=lambda c: (c.get("finished_at") is None, c.get("finished_at")), reverse=True)
    return {
        "summary": {
            "cases": len(done),
            "evaluated": len(evaluated),
            "no_alert": sum(1 for c in done if c["status"] == "no_alert"),
            "failed": sum(1 for c in done if c["status"] == "failed"),
            "top1": rate(top1, len(evaluated)),
            "top3": rate(top3, len(evaluated)),
            "detection": rate(sum(1 for c in done if c["status"] != "no_alert"), len(done)),
            "mean_rank": sum(ranks) / len(ranks) if ranks else None,
        },
        "by_fault": [fault_view(kind, fault["title"], per_fault, done) for kind, fault in faults.items()],
        "cases": [case_view(c, titles) for c in ordered],
    }
