from datetime import datetime, timezone

import pytest

from anomalyguard.alerts import InvalidAlert, margin_from, normalize, parse_webhook
from tests.helpers import raw_alert


def test_a_firing_alert_is_normalized():
    alert = normalize(raw_alert())
    assert alert.status == "firing"
    assert alert.alert_name == "FrontendHighErrorRate"
    assert alert.service == "frontend"
    assert alert.starts_at == datetime(2026, 11, 22, 2, 6, 40, tzinfo=timezone.utc)
    assert alert.ends_at is None


def test_nanosecond_timestamps_from_the_alertmanager_are_accepted():
    raw = raw_alert()
    raw["startsAt"] = "2026-11-22T02:06:40.123456789Z"
    assert normalize(raw).starts_at == datetime(2026, 11, 22, 2, 6, 40, 123456, tzinfo=timezone.utc)


def test_a_resolved_alert_needs_an_end_time():
    with pytest.raises(InvalidAlert, match="endsAt"):
        normalize(raw_alert(status="resolved"))


def test_a_resolved_alert_with_an_end_time_is_accepted():
    from tests.helpers import START
    from datetime import timedelta
    alert = normalize(raw_alert(status="resolved", ends_at=START + timedelta(minutes=5)))
    assert alert.status == "resolved" and alert.ends_at is not None


@pytest.mark.parametrize("change", [
    lambda r: r.update(status="pending"),
    lambda r: r.pop("startsAt"),
    lambda r: r.update(startsAt="ontem"),
    lambda r: r.update(startsAt="2026-11-22T02:06:40"),
    lambda r: r.update(labels={"service": "frontend"}),
    lambda r: r.update(labels="x"),
])
def test_invalid_alerts_are_rejected(change):
    raw = raw_alert()
    change(raw)
    with pytest.raises(InvalidAlert):
        normalize(raw)


def test_the_fingerprint_is_derived_from_the_labels_when_missing():
    raw = raw_alert()
    raw.pop("fingerprint")
    assert normalize(raw).fingerprint == "alertname=FrontendHighErrorRate|service=frontend"


def test_a_missing_service_label_becomes_unknown():
    raw = raw_alert()
    raw["labels"] = {"alertname": "X"}
    assert normalize(raw).service == "desconhecido"


def test_the_margin_comes_from_the_alert_annotations():
    annotations = {"export_interval_s": "60", "rate_window_s": "120", "for_s": "60", "eval_interval_s": "15"}
    assert margin_from(annotations) == 315


def test_the_margin_is_unknown_when_an_annotation_is_missing():
    assert margin_from({"export_interval_s": "60"}) is None


def test_the_webhook_body_needs_the_alerts_list():
    with pytest.raises(InvalidAlert):
        parse_webhook({"alerts": "x"})
    assert len(parse_webhook({"alerts": [raw_alert(), raw_alert(fingerprint="fp-2")]})) == 2
