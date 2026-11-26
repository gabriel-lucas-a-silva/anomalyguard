from anomalyguard.verifier import parse_number, verify

EVIDENCE = [
    {"id": 1, "service": "payment", "normal_median": 0.0, "incident_max": 11.0, "ratio": None},
    {"id": 2, "service": "ad", "normal_median": 0.0001, "incident_max": 140.0, "ratio": 1400000.0},
    {"id": 3, "service": "frontend", "normal_median": 80.0, "incident_max": 130.0, "ratio": 1.625},
]
SUSPECTS = [{"service": "payment", "share": 0.2931}, {"service": "ad", "share": 0.1736}, {"service": "frontend", "share": 0.1204}]


def check(text):
    return verify(text, EVIDENCE, SUSPECTS)


def test_a_text_that_cites_existing_evidence_and_uses_its_numbers_passes():
    text = "payment é a hipótese mais provável [1].\n\nOs erros foram de 0 para 11 a cada 15 s [1], com 29% da anomalia."
    assert check(text) == []


def test_a_citation_to_a_missing_evidence_is_rejected():
    assert any("[7]" in p for p in check("payment falha [7]."))


def test_text_inside_brackets_is_rejected():
    assert any("colchetes com texto" in p for p in check("payment falha [comparacoes] e [1]."))


def test_a_text_without_citations_is_rejected():
    assert "nenhuma citação válida" in check("payment é o suspeito.")


def test_a_number_that_is_not_in_the_evidence_is_rejected():
    problems = check("payment teve 47 erros [1].")
    assert any("47" in p for p in problems)


def test_numbers_inside_citations_are_not_checked_as_values():
    assert check("payment [1] e frontend [3].") == []


def test_percentages_match_the_torai_scores_with_rounding():
    assert check("payment concentra 29% [1].") == []
    assert any("40" in p for p in check("payment concentra 40% [1]."))


def test_decimal_commas_and_thousand_separators_are_understood():
    assert parse_number("1,6") == 1.6 and parse_number("1.000") == 1000.0 and parse_number("0,01") == 0.01


def test_a_huge_ratio_can_be_written_as_more_than_a_thousand():
    assert check("ad ficou mais de 1.000 vezes acima do normal [2].") == []


def test_a_ratio_with_rounding_is_accepted():
    assert check("frontend foi de 80 para 130, 1,6 vez o normal [3].") == []


def test_clock_times_are_rejected():
    assert any("16" in p or "27" in p for p in check("Às 16:27 payment falhou [1]."))


def test_empty_text_is_rejected():
    assert check("   ") == ["texto vazio"]


def test_values_shown_in_other_units_are_accepted_from_the_display_fields():
    evidence = [{"id": 1, "service": "ad", "normal_median": 1365.0, "incident_max": 1922662.0, "normal_display": 0.0014, "incident_display": 1.9227, "ratio": 1408.0}]
    suspects = [{"service": "ad", "share": 0.17}]
    assert verify("ad foi a 1,9 MB/s [1].", evidence, suspects) == []
