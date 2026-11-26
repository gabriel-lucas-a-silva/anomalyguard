from types import SimpleNamespace

import numpy as np

from anomalyguard.connectors.base import MetricSeries
from anomalyguard.prepare import Grid, prepare

START = 1_796_220_000
BINS = 40
OP = "oteldemo.PaymentService/Charge"


def collection(calls):
    def counter(name, per_bin, **labels):
        values = tuple((float(START + 15 * i), str(per_bin * i)) for i in range(BINS))
        return MetricSeries(name, dict(span_kind="SPAN_KIND_SERVER", span_name=OP, **labels), "payment", values)

    metrics = [
        counter("traces_span_metrics_calls_total", calls, status_code="STATUS_CODE_UNSET"),
        counter("traces_span_metrics_duration_milliseconds_count", calls),
        counter("traces_span_metrics_duration_milliseconds_sum", calls * 40),
    ]
    return SimpleNamespace(records=lambda kind: metrics if kind == "metrics" else [])


def grid():
    return Grid(START, START + 15 * (BINS - 1))


def test_a_low_traffic_operation_is_kept_when_it_reaches_the_minimum():
    prepared = prepare(collection(calls=1), grid(), min_operation_calls=10)
    assert prepared.coverage["payment"]["traces"] is True


def test_a_low_traffic_operation_is_dropped_below_the_minimum():
    prepared = prepare(collection(calls=1), grid(), min_operation_calls=100)
    assert prepared.coverage.get("payment", {}).get("traces", False) is False


def test_the_default_minimum_keeps_an_operation_with_ten_calls():
    prepared = prepare(collection(calls=1), grid())
    assert prepared.coverage["payment"]["traces"] is True
