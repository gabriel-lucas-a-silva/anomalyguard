from datetime import datetime, timezone

from anomalyguard import accuracy
from anomalyguard.demo import CATALOG


def case(kind="payment_failure", status="evaluated", rank=1, top="payment", cause="payment", minute=0, state="done"):
    return {"id": minute + 1, "kind": kind, "state": state, "status": status, "rank": rank, "top_service": top, "root_cause_service": cause,
            "investigation_id": "INV-%04d" % (minute + 1) if status != "no_alert" else None, "finished_at": datetime(2026, 11, 23, 1, minute, tzinfo=timezone.utc)}


def test_the_wilson_interval_matches_the_known_value():
    result = accuracy.rate(15, 33)
    assert round(result["rate"], 3) == 0.455
    assert round(result["low"], 2) == 0.30 and round(result["high"], 2) == 0.62


def test_a_rate_over_nothing_has_no_value():
    assert accuracy.rate(0, 0) == {"hits": 0, "of": 0, "rate": None, "low": None, "high": None}


def test_the_interval_stays_inside_zero_and_one_at_the_extremes():
    full, empty = accuracy.rate(10, 10), accuracy.rate(0, 10)
    assert full["high"] == 1.0 and 0 < full["low"] < 1 and empty["low"] == 0.0 and 0 < empty["high"] < 1


def test_the_report_counts_hits_only_over_evaluated_cases():
    cases = [case(rank=1, minute=0), case(rank=2, top="frontend", minute=1), case(rank=7, top="frontend", minute=2), case(status="no_alert", rank=None, top=None, minute=3),
             case(status="failed", rank=None, top=None, minute=4)]
    summary = accuracy.report(cases, CATALOG, 5)["summary"]
    assert summary["cases"] == 5 and summary["evaluated"] == 3 and summary["no_alert"] == 1 and summary["failed"] == 1
    assert summary["top1"]["hits"] == 1 and summary["top1"]["of"] == 3 and summary["top3"]["hits"] == 2
    assert summary["detection"]["hits"] == 4 and summary["detection"]["of"] == 5
    assert summary["mean_rank"] == (1 + 2 + 7) / 3


def test_a_cause_missing_from_the_ranking_counts_as_a_miss_but_is_still_evaluated():
    summary = accuracy.report([case(rank=None, top="frontend")], CATALOG, 1)["summary"]
    assert summary["evaluated"] == 1 and summary["top1"]["hits"] == 0 and summary["top3"]["hits"] == 0 and summary["mean_rank"] is None


def test_cases_that_are_not_done_are_left_out():
    cases = [case(minute=0), case(minute=1, state="pending", status=None, rank=None), case(minute=2, state="cancelled", status=None, rank=None)]
    assert accuracy.report(cases, CATALOG, 3)["summary"]["cases"] == 1


def test_each_fault_gets_its_own_row_in_catalog_order():
    cases = [case(kind="payment_failure", rank=1, minute=0), case(kind="product_catalog_lock_contention", rank=5, top="frontend", cause="product-catalog", minute=1),
             case(kind="product_catalog_lock_contention", status="no_alert", rank=None, top=None, cause="product-catalog", minute=2)]
    by_fault = accuracy.report(cases, CATALOG, 12)["by_fault"]
    assert [f["kind"] for f in by_fault] == list(CATALOG)
    assert by_fault[0]["evaluated"] == 1 and by_fault[0]["top1"]["hits"] == 1 and by_fault[0]["planned"] == 12
    assert by_fault[1]["evaluated"] == 1 and by_fault[1]["no_alert"] == 1 and by_fault[1]["top1"]["hits"] == 0
    empty = accuracy.report([], CATALOG, 12)["by_fault"]
    assert empty[0]["evaluated"] == 0 and empty[0]["top1"]["rate"] is None


def test_cases_are_listed_newest_first_with_titles_and_iso_dates():
    listing = accuracy.report([case(minute=0), case(kind="product_catalog_lock_contention", cause="product-catalog", minute=5)], CATALOG, 2)["cases"]
    assert [c["title"] for c in listing] == ["Trava no banco do catálogo", "Pagamento falhando"]
    assert listing[0]["finished_at"] == "2026-11-23T01:05:00Z" and listing[0]["id"] == "INV-0006"


def test_an_empty_campaign_reports_zeros_without_dividing_by_zero():
    result = accuracy.report([], CATALOG, 0)
    assert result["summary"]["cases"] == 0 and result["summary"]["top1"]["rate"] is None and result["cases"] == []
