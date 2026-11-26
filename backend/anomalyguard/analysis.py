import time
from dataclasses import dataclass, field
from datetime import datetime

from . import adapt, snapshot, torai
from .prepare import Grid, prepare
from .suspects import build_suspects
from .windows import Plan

MIN_COVERAGE = 0.5

SOURCE_LABELS = {"metric": "metrics", "log": "logs", "trace_err": "traces", "trace_lat": "traces"}


class AnalysisError(Exception):
    pass


@dataclass
class AnalysisResult:
    suspects: list
    timings_ms: dict
    missing_sources: list
    warnings: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    ranking: list = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)


def translate(analysis, inverse, origins):
    def back(service):
        return inverse.get(service, service)

    indicators = {}
    for service, picked in analysis["indicators"].items():
        entries = []
        for item in picked:
            original = origins[item["source"]].get(item["column"])
            if original is not None:
                entries.append({"indicator": original.split("|", 1)[1], "source": SOURCE_LABELS[item["source"]], "score": item["score"]})
        indicators[back(service)] = entries
    return {
        "ranks": [back(s) for s in analysis["ranks"]],
        "service_score": {back(s): v for s, v in analysis["service_score"].items()},
        "severity": {back(s): v for s, v in analysis["severity"].items()},
        "indicators": indicators,
    }


def coverage(frame, start_ts, end_ts):
    rows = frame[(frame["time"] >= start_ts) & (frame["time"] < end_ts)]
    values = rows.drop(columns=["time"])
    if rows.empty or values.shape[1] == 0:
        return 0.0
    return float(values.notna().any(axis=1).mean())


def check_coverage(prepared, plan):
    metrics = prepared.tables()["metrics"]
    periods = (
        ("normal", plan.baseline_start.timestamp(), plan.baseline_end.timestamp()),
        ("depois do alerta", plan.t_alert.timestamp(), plan.anomaly_end.timestamp()),
    )
    for label, start, end in periods:
        found = coverage(metrics, start, end)
        if found < MIN_COVERAGE:
            raise AnalysisError("dados insuficientes: só %d%% do período %s tem métricas (o mínimo é %d%%)" % (round(found * 100), label, round(MIN_COVERAGE * 100)))


def full_ranking(analysis):
    return [{"position": position, "service": service, "score": round(float(analysis["service_score"].get(service, 0.0)), 4)}
            for position, service in enumerate(analysis["ranks"], start=1)]


def analyze_full(tables, prepared, t_alert_epoch, plan):
    payload, inject_time, inverse, info = adapt.build_inputs(tables, t_alert_epoch, plan.margin_s, plan.delta_s)
    origins = info.pop("origins")
    analysis = translate(torai.analyze(payload, inject_time), inverse, origins)
    suspects, evidence = build_suspects(analysis, prepared, t_alert_epoch, plan.margin_s, plan.delta_s)
    return suspects, evidence, full_ranking(analysis)


def analyze_tables(tables, prepared, t_alert_epoch, plan):
    suspects, evidence, _ = analyze_full(tables, prepared, t_alert_epoch, plan)
    return suspects, evidence


SOURCE_NAMES = {"metrics": "métricas", "logs": "logs", "traces": "traces"}


def build_limitations(suspects, prepared, missing_sources):
    limitations = ["Fonte indisponível: %s." % source for source in missing_sources]
    for suspect in suspects:
        coverage = prepared.coverage.get(suspect["service"], {})
        for source, name in SOURCE_NAMES.items():
            if not coverage.get(source, False):
                limitations.append("Sem %s para %s." % (name, suspect["service"]))
    return limitations


def replay_analysis(payload, on_stage=None, clock=time.monotonic):
    notify = on_stage or (lambda state, tag, message: None)
    prepared, saved = snapshot.thaw(payload)
    t_alert = datetime.fromisoformat(saved["t_alert"])
    plan = Plan(t_alert, saved["baseline_s"], saved["margin_s"], saved["delta_s"])
    timings = {}
    notify("analyzing", "análise", "Calculando a severidade de cada serviço sobre os dados gravados")
    began = clock()
    try:
        suspects, evidence, ranking = analyze_full(prepared.tables(), prepared, t_alert.timestamp(), plan)
    except adapt.InsufficientData as e:
        raise AnalysisError("dados insuficientes: %s" % e)
    except (ValueError, IndexError) as e:
        raise AnalysisError("o TORAI não conseguiu analisar estes dados: %s" % e)
    timings["torai"] = int((clock() - began) * 1000)
    return AnalysisResult(suspects, timings, [], [], evidence, build_limitations(suspects, prepared, []), ranking, payload)


def run_analysis(collector, t_alert, settings, on_stage=None, clock=time.monotonic):
    notify = on_stage or (lambda state, tag, message: None)
    plan = Plan(t_alert, settings.baseline_s, settings.margin_s, settings.delta_s)
    timings = {}

    notify("collecting", "coleta", "Coletando métricas e logs do ambiente")
    began = clock()
    window = plan.collection_window()
    collection = collector.collect(window)
    if collection.fatal:
        raise AnalysisError("uma fonte essencial está indisponível: " + "; ".join(collection.warnings))
    timings["collect"] = int((clock() - began) * 1000)

    notify("preparing", "preparo", "Montando as séries por serviço")
    began = clock()
    prepared = prepare(collection, Grid(window.start_ts(), window.end_ts()), settings.min_operation_calls)
    timings["prepare"] = int((clock() - began) * 1000)

    check_coverage(prepared, plan)

    notify("analyzing", "análise", "Calculando a severidade de cada serviço")
    began = clock()
    try:
        suspects, evidence, ranking = analyze_full(prepared.tables(), prepared, t_alert.timestamp(), plan)
    except adapt.InsufficientData as e:
        raise AnalysisError("dados insuficientes: %s" % e)
    except (ValueError, IndexError) as e:
        raise AnalysisError("o TORAI não conseguiu analisar estes dados: %s" % e)
    timings["torai"] = int((clock() - began) * 1000)
    missing = list(collection.missing_sources)
    return AnalysisResult(suspects, timings, missing, list(prepared.warnings), evidence, build_limitations(suspects, prepared, missing), ranking,
                          snapshot.freeze(prepared, plan))
