TOP_FIRST = 1
TOP_THIRD = 3


def positions(row):
    ranking = row.get("ranking") or []
    if ranking:
        return {item["service"]: item["position"] for item in ranking}
    return {s["service"]: s["rank"] for s in row.get("suspects") or []}


def evaluate(truth, row):
    if truth is None:
        return None
    view = {
        "root_cause_service": truth["root_cause_service"],
        "fault_kind": truth["fault_kind"],
        "expected_signal": truth.get("expected_signal"),
        "source": truth["source"],
        "top_service": (row.get("suspects") or [{}])[0].get("service"),
        "rank": None,
        "top1": None,
        "top3": None,
        "status": "pending",
    }
    if row["state"] == "failed":
        view["status"] = "no_result"
        return view
    if row["state"] != "completed":
        return view
    rank = positions(row).get(truth["root_cause_service"])
    view.update(status="evaluated", rank=rank, top1=rank == TOP_FIRST, top3=rank is not None and rank <= TOP_THIRD)
    return view


def compact(view):
    if view is None:
        return None
    return {key: view[key] for key in ("root_cause_service", "rank", "top1", "top3", "status")}


def summarize(cases):
    evaluated = [c for c in cases if c["status"] == "evaluated"]
    return {
        "labeled": len(cases),
        "evaluated": len(evaluated),
        "top1": sum(1 for c in evaluated if c["top1"]),
        "top3": sum(1 for c in evaluated if c["top3"]),
        "pending": sum(1 for c in cases if c["status"] == "pending"),
        "no_result": sum(1 for c in cases if c["status"] == "no_result"),
    }
