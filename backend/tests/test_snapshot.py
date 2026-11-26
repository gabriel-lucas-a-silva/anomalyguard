from datetime import datetime, timezone

import numpy as np
import pandas as pd

from anomalyguard import snapshot
from anomalyguard.windows import Plan
from tests.helpers import synthetic_case

PLAN = Plan(datetime(2026, 11, 22, 17, 30, 5, tzinfo=timezone.utc), 600, 315, 180)


def test_freezing_and_thawing_gives_back_the_same_tables():
    frames, prepared = synthetic_case()
    payload = snapshot.unpack(snapshot.pack(snapshot.freeze(prepared, PLAN)))
    thawed, plan = snapshot.thaw(payload)
    for name, frame in frames.items():
        pd.testing.assert_frame_equal(thawed.tables()[name], frame, check_dtype=False)
    assert thawed.catalog == prepared.catalog and thawed.coverage == prepared.coverage


def test_missing_values_and_infinity_come_back_as_missing():
    frame = pd.DataFrame({"time": [0, 15, 30], "payment|cpu": [1.5, np.nan, np.inf], "ad|trace_err:Op": [0.0, 2.0, 3.0]})
    empty = pd.DataFrame({"time": [0, 15, 30]})
    prepared = type("P", (), {"catalog": {}, "coverage": {}, "tables": lambda self: {"metrics": frame, "logs": empty, "trace_err": empty, "trace_lat": empty}})()
    thawed, _ = snapshot.thaw(snapshot.unpack(snapshot.pack(snapshot.freeze(prepared, PLAN))))
    cpu = thawed.tables()["metrics"]["payment|cpu"]
    assert cpu[0] == 1.5 and np.isnan(cpu[1]) and np.isnan(cpu[2])
    assert list(thawed.tables()["metrics"]["ad|trace_err:Op"]) == [0.0, 2.0, 3.0]


def test_the_plan_is_kept_to_replay_the_same_windows():
    _, prepared = synthetic_case()
    _, plan = snapshot.thaw(snapshot.freeze(prepared, PLAN))
    assert plan == {"t_alert": "2026-11-22T17:30:05+00:00", "baseline_s": 600, "margin_s": 315, "delta_s": 180}


def test_the_packed_snapshot_is_small():
    _, prepared = synthetic_case()
    assert len(snapshot.pack(snapshot.freeze(prepared, PLAN))) < 200_000


def test_replaying_the_frozen_tables_gives_the_same_ranking():
    from anomalyguard.analysis import analyze_full
    from tests.synthetic import t_alert
    plan = Plan(datetime.fromtimestamp(t_alert(), timezone.utc), 600, 315, 180)
    frames, prepared = synthetic_case()
    original = analyze_full(frames, prepared, t_alert(), plan)
    thawed, saved = snapshot.thaw(snapshot.unpack(snapshot.pack(snapshot.freeze(prepared, plan))))
    again = analyze_full(thawed.tables(), thawed, t_alert(), plan)
    assert again[2] == original[2] and again[0] == original[0] and again[1] == original[1]
    assert saved["margin_s"] == 315
