import gzip
import json
import math
from types import SimpleNamespace

import pandas as pd

TABLES = ("metrics", "logs", "trace_err", "trace_lat")


def column(series):
    return [None if isinstance(v, float) and not math.isfinite(v) else v for v in series.tolist()]


def freeze(prepared, plan):
    tables = prepared.tables()
    return {
        "tables": {name: {c: column(tables[name][c]) for c in tables[name].columns} for name in TABLES},
        "catalog": prepared.catalog,
        "coverage": prepared.coverage,
        "plan": {
            "t_alert": plan.t_alert.isoformat(),
            "baseline_s": plan.baseline_s,
            "margin_s": plan.margin_s,
            "delta_s": plan.delta_s,
        },
    }


def thaw(payload):
    frames = {name: pd.DataFrame(payload["tables"][name]) for name in TABLES}
    prepared = SimpleNamespace(catalog=payload["catalog"], coverage=payload["coverage"], warnings=[], tables=lambda: frames)
    return prepared, payload["plan"]


def pack(payload):
    return gzip.compress(json.dumps(payload, separators=(",", ":")).encode())


def unpack(blob):
    return json.loads(gzip.decompress(bytes(blob)).decode())
