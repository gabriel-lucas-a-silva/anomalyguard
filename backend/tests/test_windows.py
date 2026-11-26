from datetime import datetime, timedelta, timezone

from anomalyguard.windows import Plan

T = datetime(2026, 11, 21, 14, 3, 10, tzinfo=timezone.utc)


def test_the_baseline_ends_one_margin_before_the_alert():
    plan = Plan(T, 600, 315, 180)
    assert plan.baseline_end == T - timedelta(seconds=315)
    assert plan.baseline_start == T - timedelta(seconds=915)


def test_the_anomaly_window_runs_delta_seconds_after_the_alert():
    assert Plan(T, 600, 315, 180).anomaly_end == T + timedelta(seconds=180)


def test_the_collection_window_covers_baseline_and_anomaly():
    window = Plan(T, 600, 315, 180).collection_window()
    assert window.start == T - timedelta(seconds=915)
    assert window.end == T + timedelta(seconds=180)


def test_data_is_ready_after_the_anomaly_window_plus_the_lag():
    assert Plan(T, 600, 315, 180).data_ready_at(75) == T + timedelta(seconds=255)
