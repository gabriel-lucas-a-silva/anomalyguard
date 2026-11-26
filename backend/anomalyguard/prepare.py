import collections
import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

STEP = 15
MAX_OPS_PER_SERVICE = 8
MAX_TEMPLATES_PER_SERVICE = 8
MIN_OPERATION_CALLS = 10
MIN_TEMPLATE_COUNT = 3
SEP = "|"

SPAN_CALLS = "traces_span_metrics_calls_total"
SPAN_COUNT = "traces_span_metrics_duration_milliseconds_count"
SPAN_SUM = "traces_span_metrics_duration_milliseconds_sum"
SPAN_BUCKET = "traces_span_metrics_duration_milliseconds_bucket"
CONTAINER_METRICS = [("cpu", "container_cpu_utilization_ratio", 100.0, False),
                     ("mem", "container_memory_usage_total_bytes", 1.0, False),
                     ("diskio", "container_blockio_io_service_bytes_recursive_total", 1.0, True)]


@dataclass
class Prepared:
    metrics: pd.DataFrame
    logs: pd.DataFrame
    trace_err: pd.DataFrame
    trace_lat: pd.DataFrame
    log_templates: dict
    catalog: dict
    coverage: dict
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def tables(self):
        return {"metrics": self.metrics, "logs": self.logs, "trace_err": self.trace_err, "trace_lat": self.trace_lat}


class Grid:
    def __init__(self, start_ts, end_ts, step=STEP):
        self.step = step
        self.start = int(start_ts // step) * step
        self.n = (int(end_ts // step) * step - self.start) // step + 1
        self.times = self.start + step * np.arange(self.n)

    def index(self, ts):
        return int((math.floor(float(ts) / self.step) * self.step - self.start) // self.step)

    def bins(self, values):
        arr = np.full(self.n, np.nan)
        for t, v in values:
            i = self.index(t)
            if 0 <= i < self.n:
                try:
                    arr[i] = float(v)
                except (TypeError, ValueError):
                    pass
        return arr


def _delta(arr):
    d = np.diff(arr, prepend=np.nan)
    return np.where(d < 0, 0.0, d)


def _total(arrays, n):
    return np.nansum(np.vstack(arrays), axis=0) if arrays else np.zeros(n)


def _p90(buckets, service, n):
    les = sorted(le for (s, le) in buckets if s == service)
    out = np.full(n, np.nan)
    if not les:
        return out
    cumulative = [_total(buckets[(service, le)], n) for le in les]
    for i in range(n):
        total = cumulative[-1][i]
        if not total > 0:
            continue
        target, previous_le, previous_count = 0.9 * total, 0.0, 0.0
        for le, series in zip(les, cumulative):
            count = series[i]
            if count >= target:
                if math.isinf(le):
                    out[i] = previous_le
                elif count == previous_count:
                    out[i] = le
                else:
                    out[i] = previous_le + (le - previous_le) * (target - previous_count) / (count - previous_count)
                break
            previous_le = previous_le if math.isinf(le) else le
            previous_count = count
    return out


def template(body):
    s = str(body)
    s = re.sub(r"\b[0-9a-fA-F]{8,}\b", "<*>", s)
    s = re.sub(r"\d+(\.\d+)?", "<*>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:110]


def _frame(grid, columns):
    frame = pd.DataFrame({"time": grid.times})
    for name, values in columns.items():
        frame[name] = values
    return frame


def _span_metrics(metrics, grid):
    calls, count, total, buckets = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for m in metrics:
        if m.service is None or m.labels.get("span_kind") != "SPAN_KIND_SERVER":
            continue
        op = m.labels.get("span_name")
        if m.name == SPAN_CALLS:
            calls[(m.service, op, m.labels.get("status_code"))].append(_delta(grid.bins(m.values)))
        elif m.name == SPAN_COUNT:
            count[(m.service, op)].append(_delta(grid.bins(m.values)))
        elif m.name == SPAN_SUM:
            total[(m.service, op)].append(_delta(grid.bins(m.values)))
        elif m.name == SPAN_BUCKET:
            le = float("inf") if m.labels.get("le") == "+Inf" else float(m.labels.get("le"))
            buckets[(m.service, le)].append(_delta(grid.bins(m.values)))
    return calls, count, total, buckets


def prepare(collection, grid, min_operation_calls=MIN_OPERATION_CALLS):
    warnings = []
    metrics = [m for m in collection.records("metrics")]
    logs = collection.records("logs")
    unattributed = {"metrics": sum(1 for m in metrics if m.service is None), "logs": sum(1 for r in logs if r.service is None)}
    n = grid.n
    columns, catalog = collections.OrderedDict(), collections.defaultdict(dict)

    def add(service, indicator, values):
        name = service + SEP + indicator
        columns[name] = values
        catalog[service][indicator] = {"table": "metrics", "column": name}

    for indicator, metric_name, scale, as_rate in CONTAINER_METRICS:
        per_service = collections.defaultdict(list)
        for m in metrics:
            if m.name == metric_name and m.service is not None:
                arr = grid.bins(m.values)
                per_service[m.service].append(_delta(arr) / STEP if as_rate else arr)
        for service, arrays in per_service.items():
            add(service, indicator, _total(arrays, n) * scale)

    calls, count, total, buckets = _span_metrics(metrics, grid)
    workload, errors = collections.defaultdict(lambda: np.zeros(n)), collections.defaultdict(lambda: np.zeros(n))
    for (service, op, status), arrays in calls.items():
        d = _total(arrays, n) / STEP
        workload[service] = workload[service] + d
        if status == "STATUS_CODE_ERROR":
            errors[service] = errors[service] + d
    for service in workload:
        add(service, "workload", workload[service])
        add(service, "error", errors[service])
        add(service, "latency_p90", _p90(buckets, service, n))

    err_columns, lat_columns = collections.OrderedDict(), collections.OrderedDict()
    ops_by_service = collections.defaultdict(list)
    for (service, op), arrays in count.items():
        ops_by_service[service].append((float(np.nansum(_total(arrays, n))), op))
    for service, operations in ops_by_service.items():
        for calls_total, op in sorted(operations, reverse=True)[:MAX_OPS_PER_SERVICE]:
            if calls_total < min_operation_calls:
                continue
            errors_for_op = _total([_total(calls[k], n) for k in calls if k[0] == service and k[1] == op and k[2] == "STATUS_CODE_ERROR"], n)
            c, s = _total(count[(service, op)], n), _total(total.get((service, op), []), n)
            with np.errstate(divide="ignore", invalid="ignore"):
                latency = np.where(c > 0, s / c, np.nan)
            err_name, lat_name = service + SEP + "trace_err:" + op, service + SEP + "trace_lat:" + op
            err_columns[err_name], lat_columns[lat_name] = errors_for_op, latency
            catalog[service]["trace_err:" + op] = {"table": "trace_err", "column": err_name}
            catalog[service]["trace_lat:" + op] = {"table": "trace_lat", "column": lat_name}

    counts = collections.defaultdict(lambda: np.zeros(n))
    for r in logs:
        if r.service is None:
            continue
        try:
            ts = pd.Timestamp(r.ts).timestamp()
        except (TypeError, ValueError):
            continue
        i = grid.index(ts)
        if 0 <= i < n:
            counts[(r.service, template(r.body))][i] += 1
    log_columns, log_templates, k = collections.OrderedDict(), {}, 0
    per_service = collections.defaultdict(list)
    for (service, text), arr in counts.items():
        per_service[service].append((arr.sum(), text, arr))
    for service, items in per_service.items():
        for amount, text, arr in sorted(items, key=lambda x: -x[0])[:MAX_TEMPLATES_PER_SERVICE]:
            if amount < MIN_TEMPLATE_COUNT:
                continue
            k += 1
            name = "%s%slog_template:%d" % (service, SEP, k)
            log_columns[name] = arr
            log_templates[str(k)] = {"service": service, "template": text}
            catalog[service]["log_template:%d" % k] = {"table": "logs", "column": name}

    if not metrics:
        warnings.append("no metrics available: the metric tables are empty")
    if not logs:
        warnings.append("no logs available: no log template series")
    if not (err_columns or lat_columns):
        warnings.append("no trace-derived series available (span metrics missing)")
    services = set(catalog)
    coverage = {}
    for service in sorted(services):
        indicators = catalog[service]
        coverage[service] = {
            "metrics": any(v["table"] == "metrics" for v in indicators.values()),
            "logs": any(v["table"] == "logs" for v in indicators.values()),
            "traces": any(v["table"] in ("trace_err", "trace_lat") for v in indicators.values()),
        }
    return Prepared(_frame(grid, columns), _frame(grid, log_columns), _frame(grid, err_columns), _frame(grid, lat_columns), log_templates,
                    {s: dict(v) for s, v in catalog.items()}, coverage, warnings,
                    {"bins": n, "step_s": grid.step, "metric_columns": len(columns), "log_columns": len(log_columns),
                     "trace_columns": len(err_columns), "unattributed": unattributed})
