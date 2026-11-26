from anomalyguard.report import fixed_report
from anomalyguard.verifier import verify
from tests.helpers import EVIDENCE, SUSPECT

CONTEXT = {
    "alert": {"name": "FrontendHighErrorRate", "service": "frontend", "started_at": "2026-11-22T02:06:40Z"},
    "suspects": [SUSPECT, dict(SUSPECT, rank=2, service="ad", share=0.17, evidence_ids=[2])],
    "evidence": [EVIDENCE, dict(EVIDENCE, id=2, service="ad", text="ad: Disco. Normal (mediana): 0,01. No incidente (máximo): 140.", incident_max=140.0, normal_median=0.01)],
    "limitations": ["Sem logs para ad."],
}


def test_the_fixed_report_names_the_top_suspect_and_the_alert():
    headline, paragraphs = fixed_report(CONTEXT)
    assert headline == "payment é a hipótese mais provável para o alerta FrontendHighErrorRate."
    assert len(paragraphs) == 4


def test_each_suspect_paragraph_cites_its_evidence():
    _, paragraphs = fixed_report(CONTEXT)
    assert paragraphs[0].endswith("[1]") and "40%" in paragraphs[0]
    assert paragraphs[1].endswith("[2]") and "2º lugar" in paragraphs[1]


def test_the_fixed_report_mentions_limitations_and_is_not_a_definitive_cause():
    _, paragraphs = fixed_report(CONTEXT)
    assert paragraphs[2] == "Limitações: Sem logs para ad."
    assert "não uma causa definitiva" in paragraphs[-1]


def test_the_fixed_report_passes_the_same_verifier():
    headline, paragraphs = fixed_report(CONTEXT)
    text = "\n\n".join([headline] + paragraphs)
    assert verify(text, CONTEXT["evidence"], CONTEXT["suspects"]) == []


def test_without_suspects_the_report_says_so():
    assert fixed_report({"alert": {"name": "X"}, "suspects": [], "evidence": []}) == ("Não há suspeitos para este alerta.", [])
