from datetime import datetime, timezone

import pytest

from anomalyguard import suspects
from anomalyguard.analysis import analyze_full, analyze_tables, build_limitations
from anomalyguard.windows import Plan
from tests.helpers import synthetic_case
from tests.synthetic import t_alert

PLAN = Plan(datetime.fromtimestamp(t_alert(), timezone.utc), 600, 315, 180)


@pytest.fixture(scope="module")
def result():
    frames, prepared = synthetic_case()
    return analyze_tables(frames, prepared, t_alert(), PLAN)


def test_the_injected_fault_is_the_top_suspect(result):
    assert result[0][0]["service"] == "payment"


def test_only_the_three_first_services_are_returned(result):
    ranked, _ = result
    assert [s["rank"] for s in ranked] == [1, 2, 3]
    assert len({s["service"] for s in ranked}) == 3


def test_the_percentage_is_the_torai_score_between_zero_and_one(result):
    for s in result[0]:
        assert 0 <= s["share"] <= 1
        assert s["share"] == s["torai_score"]


def test_the_top_suspect_has_a_signal_and_a_change(result):
    top = result[0][0]
    assert top["signal"] in {"Erros nos traces", "Latência dos traces", "Taxa de erros", "Latência", "Logs fora do padrão"}
    assert "acima do normal" in top["detail"] or top["detail"].startswith("de 0")


def test_every_suspect_points_to_its_own_numbered_evidence(result):
    ranked, evidence = result
    by_id = {e["id"]: e for e in evidence}
    assert [e["id"] for e in evidence] == list(range(1, len(evidence) + 1))
    for s in ranked:
        assert s["evidence_ids"] and len(s["evidence_ids"]) <= suspects.PER_SERVICE
        assert all(by_id[i]["service"] == s["service"] for i in s["evidence_ids"])


def test_the_first_evidence_matches_the_signal_shown_on_the_card(result):
    ranked, evidence = result
    by_id = {e["id"]: e for e in evidence}
    for s in ranked:
        assert by_id[s["evidence_ids"][0]]["signal"] == s["signal"]


def test_evidence_text_carries_the_numbers_it_reports(result):
    _, evidence = result
    for item in evidence:
        assert item["text"].startswith(item["service"] + ": " + item["signal"])
        assert suspects.format_number(item["incident_display"]) in item["text"]


@pytest.mark.parametrize("dominant", ["trace_err", "trace_lat"])
def test_the_dominant_source_comes_first(dominant):
    frames, prepared = synthetic_case()
    severity = {"metric": 0.1, "log": 0.0, "trace_lat": 0.0, "trace_err": 0.0}
    severity[dominant] = 0.9
    items = suspects.evidence_items("payment", severity, prepared, t_alert(), 315, 180)
    assert items[0]["kind"] == dominant and len(items) == suspects.PER_SERVICE


def test_without_severity_the_strongest_change_comes_first():
    frames, prepared = synthetic_case()
    items = suspects.evidence_items("payment", None, prepared, t_alert(), 315, 180)
    assert items and items[0]["kind"] in {"trace_err", "trace_lat", "metric", "log"}


@pytest.mark.parametrize("indicator,label", [
    ("trace_err:oteldemo.PaymentService/Charge", "Erros nos traces"),
    ("trace_lat:oteldemo.PaymentService/Charge", "Latência dos traces"),
    ("log_template:3", "Logs fora do padrão"),
    ("latency_p90", "Latência"),
    ("error", "Taxa de erros"),
    ("unknown_metric", "unknown_metric"),
])
def test_signal_labels(indicator, label):
    assert suspects.signal_label(indicator) == label


@pytest.mark.parametrize("median,peak,text", [
    (0.01, 0.38, "38 vezes acima do normal"),
    (80.0, 130.0, "1,6 vez acima do normal"),
    (0.0, 94.0, "de 0 para 94"),
    (100.0, 105.0, "pouco acima do normal"),
    (0.0001, 140.0, "mais de 1.000 vezes acima do normal"),
])
def test_describe_change(median, peak, text):
    assert suspects.describe_change(median, peak) == text


def test_error_counts_carry_their_unit():
    assert suspects.describe_change(0.0, 3.0, " erros a cada 15 s") == "de 0 para 3,0 erros a cada 15 s"


def test_a_service_without_series_gets_a_neutral_signal_and_no_evidence():
    frames, prepared = synthetic_case()
    analysis = {"ranks": ["ghost"], "service_score": {"ghost": 0.01}, "severity": {}}
    ranked, evidence = suspects.build_suspects(analysis, prepared, t_alert(), 315, 180)
    assert ranked[0]["signal"] == suspects.NEUTRAL_SIGNAL and ranked[0]["evidence_ids"] == [] and evidence == []


def test_the_ratio_in_the_evidence_text_is_capped():
    item = {"service": "ad", "kind": "metric", "signal": "Disco", "normal_display": 0.0001, "incident_display": 140.0, "ratio": 1400000.0}
    assert "mais de 1.000 vezes o normal" in suspects.evidence_text(item)


def test_limitations_list_missing_sources_and_services_without_data():
    prepared = type("P", (), {"coverage": {"payment": {"metrics": True, "logs": False, "traces": True}}})()
    limitations = build_limitations([{"service": "payment"}], prepared, ["jaeger"])
    assert limitations == ["Fonte indisponível: jaeger.", "Sem logs para payment."]


@pytest.mark.parametrize("indicator,kind,raw,shown,unit", [
    ("mem", "metric", 184844288.0, 184.8443, " MB"),
    ("diskio", "metric", 1922662.0, 1.9227, " MB/s"),
    ("latency_p90", "metric", 130.0, 130.0, " ms"),
    ("cpu", "metric", 12.0, 12.0, "%"),
    ("trace_err:Op", "trace_err", 11.0, 11.0, " erros a cada 15 s"),
    ("log_template:1", "log", 4.0, 4.0, " ocorrências a cada 15 s"),
])
def test_values_are_shown_in_human_units(indicator, kind, raw, shown, unit):
    factor, text = suspects.unit_for(indicator, kind)
    assert round(raw * factor, 4) == shown and text == unit


def test_zero_is_written_as_zero_and_memory_in_megabytes():
    assert suspects.format_number(0.0) == "0"
    item = {"service": "frontend", "kind": "metric", "signal": "Memória", "unit": " MB", "normal_display": 180.883456, "incident_display": 184.844288, "ratio": 1.02}
    assert suspects.evidence_text(item) == "frontend: Memória. Normal (mediana): 181 MB. No incidente (máximo): 185 MB."


def test_the_full_ranking_lists_every_analyzed_service_once_in_the_order_of_the_top_three():
    frames, prepared = synthetic_case()
    suspects, _, ranking = analyze_full(frames, prepared, t_alert(), PLAN)
    assert [r["position"] for r in ranking] == list(range(1, len(ranking) + 1))
    assert len({r["service"] for r in ranking}) == len(ranking) == 6
    assert [r["service"] for r in ranking[:3]] == [s["service"] for s in suspects]
    assert all(0 <= r["score"] <= 1 for r in ranking)
