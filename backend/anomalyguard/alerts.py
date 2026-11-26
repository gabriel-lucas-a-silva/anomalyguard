import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

MARGIN_KEYS = ("export_interval_s", "rate_window_s", "for_s", "eval_interval_s")
MARGIN_PADDING_S = 60
UNKNOWN_SERVICE = "desconhecido"
MAX_ENTRIES = 50
MAX_VALUE_LENGTH = 2000


class InvalidAlert(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalAlert:
    fingerprint: str
    status: str
    alert_name: str
    service: str
    labels: dict
    annotations: dict
    starts_at: datetime
    ends_at: Optional[datetime]


def parse_instant(value, field):
    if not isinstance(value, str) or not value.strip():
        raise InvalidAlert("campo %s ausente" % field)
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise InvalidAlert("campo %s inválido: %s" % (field, value))
    if parsed.tzinfo is None:
        raise InvalidAlert("campo %s sem fuso horário: %s" % (field, value))
    return parsed.astimezone(timezone.utc)


def string_map(value, field):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidAlert("campo %s precisa ser um objeto" % field)
    if len(value) > MAX_ENTRIES:
        raise InvalidAlert("campo %s tem entradas demais" % field)
    out = {}
    for key, item in value.items():
        text = str(item)
        if len(text) > MAX_VALUE_LENGTH:
            raise InvalidAlert("valor grande demais em %s.%s" % (field, key))
        out[str(key)] = text
    return out


def normalize(raw):
    if not isinstance(raw, dict):
        raise InvalidAlert("o alerta não é um objeto")
    status = raw.get("status")
    if status not in ("firing", "resolved"):
        raise InvalidAlert("status inválido: %r" % (status,))
    labels = string_map(raw.get("labels"), "labels")
    annotations = string_map(raw.get("annotations"), "annotations")
    alert_name = labels.get("alertname", "").strip()
    if not alert_name:
        raise InvalidAlert("rótulo alertname ausente")
    starts_at = parse_instant(raw.get("startsAt"), "startsAt")
    ends_at = None
    if raw.get("endsAt"):
        candidate = parse_instant(raw["endsAt"], "endsAt")
        ends_at = candidate if candidate.year > 1 and candidate >= starts_at else None
    if status == "resolved" and ends_at is None:
        raise InvalidAlert("alerta resolvido sem endsAt válido")
    fingerprint = str(raw.get("fingerprint") or "").strip()
    if not fingerprint:
        fingerprint = "|".join("%s=%s" % (k, labels[k]) for k in sorted(labels))
    service = labels.get("service") or labels.get("service_name") or UNKNOWN_SERVICE
    return CanonicalAlert(fingerprint, status, alert_name, service, labels, annotations, starts_at, ends_at)


def parse_webhook(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
        raise InvalidAlert("o corpo precisa ter a lista alerts")
    return [normalize(item) for item in payload["alerts"]]


def margin_from(annotations, padding=MARGIN_PADDING_S):
    try:
        return sum(int(annotations[key]) for key in MARGIN_KEYS) + padding
    except (KeyError, ValueError, TypeError):
        return None
