import math

import numpy as np

TOP = 3
PER_SERVICE = 2
NORMAL_SECONDS = 300
MAX_RATIO = 1000
MIN_RATIO = 1.2
NEUTRAL_SIGNAL = "Sem sinal forte"
NEUTRAL_DETAIL = "nenhum indicador se afastou do normal"

METRIC_LABELS = {
    "cpu": "CPU",
    "mem": "Memória",
    "workload": "Volume de chamadas",
    "error": "Taxa de erros",
    "latency_p90": "Latência",
    "diskio": "Disco",
}


def signal_label(indicator):
    if indicator.startswith("trace_err:"):
        return "Erros nos traces"
    if indicator.startswith("trace_lat:"):
        return "Latência dos traces"
    if indicator.startswith("log_template:"):
        return "Logs fora do padrão"
    return METRIC_LABELS.get(indicator, indicator)


def kind_of(indicator):
    if indicator.startswith("trace_err:"):
        return "trace_err"
    if indicator.startswith("trace_lat:"):
        return "trace_lat"
    if indicator.startswith("log_template:"):
        return "log"
    return "metric"


METRIC_UNITS = {
    "cpu": (1.0, "%"),
    "mem": (1e-6, " MB"),
    "diskio": (1e-6, " MB/s"),
    "latency_p90": (1.0, " ms"),
    "workload": (1.0, " chamadas/s"),
    "error": (1.0, " erros/s"),
}
KIND_UNITS = {
    "trace_err": (1.0, " erros a cada 15 s"),
    "trace_lat": (1.0, " ms"),
    "log": (1.0, " ocorrências a cada 15 s"),
}


def unit_for(indicator, kind):
    if kind == "metric":
        return METRIC_UNITS.get(indicator, (1.0, ""))
    return KIND_UNITS[kind]


def format_number(value):
    if value == 0:
        return "0"
    magnitude = abs(value)
    text = "%.0f" % value if magnitude >= 10 else "%.1f" % value if magnitude >= 1 else "%.2f" % value
    return text.replace(".", ",")


def describe_ratio(ratio):
    if ratio >= MAX_RATIO:
        return "mais de 1.000 vezes o normal"
    return "%s %s o normal" % (format_number(ratio), "vez" if ratio < 2 else "vezes")


def describe_change(normal_median, incident_max, unit=""):
    if abs(normal_median) <= 1e-9:
        return "de 0 para %s%s" % (format_number(incident_max), unit)
    ratio = incident_max / normal_median
    if ratio < MIN_RATIO:
        return "pouco acima do normal"
    if ratio >= MAX_RATIO:
        return "mais de 1.000 vezes acima do normal"
    return "%s %s acima do normal" % (format_number(ratio), "vez" if ratio < 2 else "vezes")


def window_values(frame, column, t_alert_epoch, margin_s, delta_s):
    times, values = frame["time"], frame[column]
    cutoff = t_alert_epoch - margin_s
    normal = values[(times < cutoff) & (times >= cutoff - NORMAL_SECONDS)].dropna().to_numpy(dtype=float)
    incident = values[(times >= t_alert_epoch) & (times < t_alert_epoch + delta_s)].dropna().to_numpy(dtype=float)
    return normal, incident


def dominant_kind(severity):
    if not severity:
        return None
    return max(severity, key=lambda source: severity[source])


def best_by_kind(service, prepared, t_alert_epoch, margin_s, delta_s):
    tables = prepared.tables()
    best = {}
    for indicator, entry in prepared.catalog.get(service, {}).items():
        normal, incident = window_values(tables[entry["table"]], entry["column"], t_alert_epoch, margin_s, delta_s)
        if normal.size == 0 or incident.size == 0:
            continue
        median, peak = float(np.median(normal)), float(np.max(incident))
        strength = (peak - median) / (float(np.std(normal)) + 1e-9)
        if strength <= 0:
            continue
        kind = kind_of(indicator)
        if kind not in best or strength > best[kind][0]:
            best[kind] = (strength, indicator, median, peak)
    return best


def evidence_items(service, severity, prepared, t_alert_epoch, margin_s, delta_s, limit=PER_SERVICE):
    best = best_by_kind(service, prepared, t_alert_epoch, margin_s, delta_s)
    dominant = dominant_kind(severity)
    ordered = sorted(best, key=lambda kind: (kind != dominant, -best[kind][0]))
    items = []
    for kind in ordered[:limit]:
        _, indicator, median, peak = best[kind]
        ratio = peak / median if abs(median) > 1e-9 else None
        factor, unit = unit_for(indicator, kind)
        items.append({"service": service, "kind": kind, "indicator": indicator, "signal": signal_label(indicator), "unit": unit,
                      "normal_median": round(median, 4), "incident_max": round(peak, 4),
                      "normal_display": round(median * factor, 4), "incident_display": round(peak * factor, 4),
                      "ratio": round(ratio, 4) if ratio is not None else None})
    return items


def evidence_text(item):
    unit = item.get("unit", "")
    text = "%s: %s. Normal (mediana): %s%s. No incidente (máximo): %s%s." % (
        item["service"], item["signal"], format_number(item["normal_display"]), unit, format_number(item["incident_display"]), unit)
    ratio = item["ratio"]
    if ratio is not None and ratio >= MIN_RATIO and not math.isinf(ratio):
        text += " Variação: %s." % describe_ratio(ratio)
    return text


def item_detail(item):
    return describe_change(item["normal_display"], item["incident_display"], item.get("unit", ""))


def build_suspects(analysis, prepared, t_alert_epoch, margin_s, delta_s, top=TOP):
    suspects, evidence = [], []
    for rank, service in enumerate(analysis["ranks"][:top], start=1):
        score = round(float(analysis["service_score"].get(service, 0.0)), 4)
        items = evidence_items(service, analysis.get("severity", {}).get(service), prepared, t_alert_epoch, margin_s, delta_s)
        ids = []
        for item in items:
            entry = dict(item, id=len(evidence) + 1)
            entry["text"] = evidence_text(entry)
            evidence.append(entry)
            ids.append(entry["id"])
        first = items[0] if items else None
        suspects.append({
            "rank": rank, "service": service, "torai_score": score, "share": score,
            "signal": first["signal"] if first else NEUTRAL_SIGNAL,
            "detail": item_detail(first) if first else NEUTRAL_DETAIL,
            "evidence_ids": ids,
        })
    return suspects, evidence
