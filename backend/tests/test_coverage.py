from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from anomalyguard.analysis import AnalysisError, check_coverage, coverage
from anomalyguard.windows import Plan

T = datetime(2026, 11, 21, 14, 3, 10, tzinfo=timezone.utc)
PLAN = Plan(T, 600, 315, 180)


def prepared(frame):
    return SimpleNamespace(tables=lambda: {"metrics": frame})


def metrics(missing_before=None, missing_after=None):
    times = np.arange(int(PLAN.baseline_start.timestamp()), int(PLAN.anomaly_end.timestamp()), 15)
    values = np.ones(len(times))
    frame = pd.DataFrame({"time": times, "payment|cpu": values})
    if missing_before:
        frame.loc[frame["time"] < PLAN.baseline_end.timestamp() - missing_before, "payment|cpu"] = np.nan
    if missing_after:
        frame.loc[frame["time"] >= PLAN.t_alert.timestamp() + missing_after, "payment|cpu"] = np.nan
    return frame


def test_complete_data_passes():
    check_coverage(prepared(metrics()), PLAN)


def test_a_baseline_without_data_is_rejected_with_the_reason():
    frame = metrics(missing_before=1)
    frame.loc[frame["time"] < PLAN.baseline_end.timestamp(), "payment|cpu"] = np.nan
    with pytest.raises(AnalysisError, match="período normal"):
        check_coverage(prepared(frame), PLAN)


def test_data_missing_after_the_alert_is_rejected_with_the_reason():
    with pytest.raises(AnalysisError, match="depois do alerta"):
        check_coverage(prepared(metrics(missing_after=20)), PLAN)


def test_coverage_is_the_share_of_rows_with_any_value():
    frame = pd.DataFrame({"time": [0, 15, 30, 45], "a": [1.0, np.nan, 1.0, np.nan]})
    assert coverage(frame, 0, 60) == 0.5


def test_coverage_of_an_empty_range_is_zero():
    frame = pd.DataFrame({"time": [0, 15], "a": [1.0, 1.0]})
    assert coverage(frame, 100, 200) == 0.0
