import pytest

from anomalyguard import gabarito

TRUTH = {"root_cause_service": "payment", "fault_kind": "payment_failure", "expected_signal": "trace_err", "source": "simulation"}
RANKING = [{"position": 1, "service": "frontend", "score": 0.23}, {"position": 2, "service": "payment", "score": 0.2}, {"position": 3, "service": "checkout", "score": 0.19},
           {"position": 4, "service": "ad", "score": 0.1}]


def row(state="completed", ranking=None, suspects=None):
    return {"state": state, "ranking": RANKING if ranking is None else ranking, "suspects": suspects or []}


def test_no_truth_means_no_evaluation():
    assert gabarito.evaluate(None, row()) is None
    assert gabarito.compact(None) is None


def test_a_cause_in_first_place_is_top1_and_top3():
    view = gabarito.evaluate(TRUTH, row(ranking=[{"position": 1, "service": "payment", "score": 0.4}]))
    assert (view["rank"], view["top1"], view["top3"], view["status"]) == (1, True, True, "evaluated")


def test_a_cause_in_second_place_is_top3_but_not_top1():
    view = gabarito.evaluate(TRUTH, row())
    assert (view["rank"], view["top1"], view["top3"]) == (2, False, True)


def test_a_cause_in_fourth_place_is_a_miss_for_both():
    view = gabarito.evaluate(dict(TRUTH, root_cause_service="ad"), row())
    assert (view["rank"], view["top1"], view["top3"]) == (4, False, False)


def test_a_cause_missing_from_the_ranking_has_no_rank_and_is_a_miss():
    view = gabarito.evaluate(dict(TRUTH, root_cause_service="shipping"), row())
    assert (view["rank"], view["top1"], view["top3"], view["status"]) == (None, False, False, "evaluated")


def test_an_investigation_that_has_not_finished_is_pending():
    view = gabarito.evaluate(TRUTH, row(state="analyzing"))
    assert (view["status"], view["rank"], view["top1"], view["top3"]) == ("pending", None, None, None)


def test_an_investigation_that_failed_has_no_result():
    assert gabarito.evaluate(TRUTH, row(state="failed"))["status"] == "no_result"


def test_without_the_full_ranking_the_top_three_suspects_are_used():
    suspects = [{"rank": 1, "service": "frontend"}, {"rank": 2, "service": "payment"}, {"rank": 3, "service": "checkout"}]
    assert gabarito.evaluate(TRUTH, row(ranking=[], suspects=suspects))["rank"] == 2
    assert gabarito.evaluate(dict(TRUTH, root_cause_service="ad"), row(ranking=[], suspects=suspects))["rank"] is None


def test_the_view_keeps_what_the_truth_says():
    view = gabarito.evaluate(TRUTH, row())
    assert view["root_cause_service"] == "payment" and view["source"] == "simulation" and view["expected_signal"] == "trace_err"


def test_compact_keeps_only_what_the_list_needs():
    assert set(gabarito.compact(gabarito.evaluate(TRUTH, row()))) == {"root_cause_service", "rank", "top1", "top3", "status"}


def test_the_summary_counts_hits_pending_and_failures():
    cases = [
        {"status": "evaluated", "top1": True, "top3": True},
        {"status": "evaluated", "top1": False, "top3": True},
        {"status": "evaluated", "top1": False, "top3": False},
        {"status": "pending", "top1": None, "top3": None},
        {"status": "no_result", "top1": None, "top3": None},
    ]
    assert gabarito.summarize(cases) == {"labeled": 5, "evaluated": 3, "top1": 1, "top3": 2, "pending": 1, "no_result": 1}


def test_the_summary_of_nothing_is_all_zeros():
    assert gabarito.summarize([]) == {"labeled": 0, "evaluated": 0, "top1": 0, "top3": 0, "pending": 0, "no_result": 0}


@pytest.mark.parametrize("module", ["analysis", "torai", "prepare", "adapt", "suspects", "narrator", "report", "verifier", "gemini", "windows", "connectors/prometheus", "connectors/opensearch"])
def test_the_rca_engine_and_the_narrator_never_touch_the_truth(module):
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1] / "anomalyguard" / (module + ".py")).read_text(encoding="utf-8").lower()
    assert "ground_truth" not in source and "gabarito" not in source and "root_cause_service" not in source
