import numpy as np
import pandas as pd

STEP = 15
SEP = "|"
INDICATOR_NAMES = {"latency_p90": "latency"}


class InsufficientData(ValueError):
    pass


def service_aliases(services):
    ordered = sorted(services)
    aliases = {}
    for s in ordered:
        base = s.replace("_", "")
        if any(o != s and s.startswith(o) for o in ordered):
            base = "z" + base
        aliases[s] = base
    values = sorted(aliases.values())
    if len(set(values)) != len(values) or any(a != b and b.startswith(a) for a in values for b in values):
        raise ValueError("service names cannot be made prefix-free: %s" % ordered)
    return aliases


def _rename(frame, aliases, kind):
    renamed = {}
    for column in frame.columns:
        if column == "time":
            continue
        service, indicator = column.split(SEP, 1)
        if kind == "metrics":
            indicator = INDICATOR_NAMES.get(indicator, indicator)
        elif kind == "logs":
            indicator = indicator.split(":", 1)[1]
        else:
            indicator = indicator.split(":", 1)[1]
        renamed[column] = "%s_%s" % (aliases[service], indicator)
    return frame.rename(columns=renamed)


def _expand_to_seconds(frame):
    seconds = pd.concat([frame.assign(time=frame["time"] + offset) for offset in range(STEP)], ignore_index=True)
    return seconds.sort_values("time", kind="stable").reset_index(drop=True)


def build_inputs(tables, t_alert_epoch, margin_s, delta_s, normal_seconds=300):
    services = set()
    for frame in tables.values():
        services.update(c.split(SEP, 1)[0] for c in frame.columns if c != "time")
    aliases = service_aliases(services)
    inverse = {v: k for k, v in aliases.items()}
    inject_time = int(t_alert_epoch // STEP) * STEP
    cutoff = inject_time - margin_s

    if len(tables["metrics"].columns) <= 1:
        raise InsufficientData("the snapshot has no metric series")
    metric = _expand_to_seconds(_rename(tables["metrics"], aliases, "metrics"))
    metric = metric.loc[:, ~metric.columns.str.endswith("_latency-50")]
    metric = metric.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    normal_rows, anomaly_rows = normal_seconds, min(delta_s, normal_seconds)
    normal_df = metric[metric["time"] < cutoff].tail(normal_rows)
    anomal_df = metric[metric["time"] >= inject_time].head(anomaly_rows)
    if len(normal_df) < normal_rows // 2:
        raise InsufficientData("not enough baseline data before the margin: %d rows, at least %d needed" % (len(normal_df), normal_rows // 2))
    if len(anomal_df) < STEP * 11:
        raise InsufficientData("not enough data after the alert: %d rows, at least %d needed" % (len(anomal_df), STEP * 11))
    metric_window = pd.concat([normal_df, anomal_df], ignore_index=True)

    bins_before = normal_seconds // STEP
    bins_after = min(delta_s // STEP, bins_before)

    def window(frame):
        return pd.concat([frame[frame["time"] < cutoff].tail(bins_before), frame[frame["time"] >= inject_time].head(bins_after)], ignore_index=True)

    logs = window(_rename(tables["logs"], aliases, "logs"))
    if len(logs.columns) == 1:
        logs = logs[["time"]]
    has_traces = len(tables["trace_err"].columns) > 1
    trace_err = window(_rename(tables["trace_err"], aliases, "trace_err")) if has_traces else pd.DataFrame()
    trace_lat = window(_rename(tables["trace_lat"], aliases, "trace_lat")) if has_traces else pd.DataFrame()
    payload = {"metric": metric_window, "logts": logs, "tracets_err": trace_err, "tracets_lat": trace_lat}
    origins = {}
    for source, name in (("metric", "metrics"), ("log", "logs"), ("trace_err", "trace_err"), ("trace_lat", "trace_lat")):
        frame = tables[name]
        renamed = _rename(frame, aliases, name)
        origins[source] = {new: old for old, new in zip(frame.columns, renamed.columns) if old != "time"}
    info = {"origins": origins, "inject_time": inject_time, "margin_s": margin_s, "normal_rows": int(len(normal_df)), "anomaly_rows": int(len(anomal_df)),
            "services": sorted(services), "has_traces": has_traces}
    return payload, inject_time, inverse, info
