from datetime import timedelta

from anomalyguard.calm import CalmGate
from anomalyguard.connectors.base import SourceUnavailable
from tests.helpers import FakeClock


class FakeProbe:
    def __init__(self):
        self.alert_names = []
        self.values = {"errors": 0.0, "requests": 5.0, "frontend": 0.02, "catalog": 40.0}
        self.broken = False

    def alerts(self):
        if self.broken:
            raise SourceUnavailable("fora do ar")
        return list(self.alert_names)

    def value(self, expression):
        if "http_response_status_code" in expression:
            return self.values["errors"]
        if "bucket" in expression and 'service_name="frontend"' in expression:
            return self.values["frontend"]
        if 'service_name="product-catalog"' in expression:
            return self.values["catalog"]
        return self.values["requests"]


class FakeFlags:
    def __init__(self):
        self.state = {"paymentFailure": "off", "productCatalogFailure": "off"}

    def get(self, flag):
        return self.state[flag]


def build(required=720):
    clock = FakeClock()
    probe, flags = FakeProbe(), FakeFlags()
    return CalmGate(probe, flags, list(flags.state), clock, required), probe, flags, clock


def test_a_quiet_demo_becomes_calm_only_after_the_required_time():
    gate, probe, flags, clock = build()
    assert gate.observe() is True and not gate.is_calm()
    clock.advance(719)
    gate.observe()
    assert not gate.is_calm()
    clock.advance(2)
    gate.observe()
    assert gate.is_calm() and gate.calm_for() == 721


def test_any_alert_resets_the_clock_and_names_the_alert():
    gate, probe, flags, clock = build()
    gate.observe()
    clock.advance(600)
    probe.alert_names = ["FrontendHighErrorRate"]
    assert gate.observe() is False and "FrontendHighErrorRate" in gate.reason and gate.calm_for() == 0
    probe.alert_names = []
    gate.observe()
    clock.advance(719)
    gate.observe()
    assert not gate.is_calm()


def test_a_fault_still_on_is_not_calm():
    gate, probe, flags, clock = build()
    flags.state["paymentFailure"] = "100%"
    assert gate.observe() is False and "paymentFailure" in gate.reason


def test_frontend_errors_slow_responses_and_a_slow_catalog_each_break_the_calm():
    for key, value, text in (("errors", 0.05, "erros"), ("frontend", 3.0, "latência"), ("catalog", 5000.0, "catálogo")):
        gate, probe, flags, clock = build()
        probe.values[key] = value
        assert gate.observe() is False and text in gate.reason


def test_too_little_traffic_is_not_calm_because_the_saturated_demo_looks_quiet():
    gate, probe, flags, clock = build()
    probe.values["requests"] = 0.05
    assert gate.observe() is False and "tráfego" in gate.reason


def test_a_missing_frontend_latency_is_not_calm_but_a_missing_catalog_latency_is():
    gate, probe, flags, clock = build()
    probe.values["frontend"] = None
    assert gate.observe() is False
    probe.values["frontend"] = 0.02
    probe.values["catalog"] = None
    assert gate.observe() is True


def test_a_prometheus_failure_is_not_calm_and_says_so():
    gate, probe, flags, clock = build()
    probe.broken = True
    assert gate.observe() is False and "não consegui consultar" in gate.reason


def test_reset_clears_the_streak():
    gate, probe, flags, clock = build(required=60)
    gate.observe()
    clock.advance(120)
    gate.observe()
    assert gate.is_calm()
    gate.reset()
    assert not gate.is_calm() and gate.calm_for() == 0
