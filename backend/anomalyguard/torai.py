import time
import warnings

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler, StandardScaler

from RCAEval.e2e.torai import _rcd_multimodal
from RCAEval.io.time_series import drop_constant, preprocess

DATASET = "torai-ob"
SOURCES = ("metric", "log", "trace_lat", "trace_err")
TOP_FINE = 10

warnings.filterwarnings("ignore")


def _severity(normal, anomal, trace_error=False, drop_tail=False):
    scores = []
    for column in normal.columns:
        a, b = normal[column].to_numpy(), anomal[column].to_numpy()
        if drop_tail:
            a = a[:-2]
        if a.size == 0:
            continue
        scaler = StandardScaler().fit(a.reshape(-1, 1))
        score = float(np.max(np.abs(scaler.transform(b.reshape(-1, 1))[:, 0])))
        if trace_error and scaler.mean_ == 0 and scaler.var_ == 0:
            score *= 1e9
        scores.append((column, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    total = sum(s for _, s in scores)
    return [(c, s / total) for c, s in scores]


def _add_up(fine):
    out = {}
    for column, score in fine:
        service = column.split("_")[0]
        out[service] = out.get(service, 0.0) + score
    return sorted(out.items(), key=lambda x: x[1], reverse=True)


def _highest(fine):
    if not fine:
        return []
    fine = sorted(fine, key=lambda x: x[1], reverse=True)
    coarse = [(fine[0][0].split("_")[0], fine[0][1])]
    for column, score in fine[1:]:
        service = column.split("_")[0]
        if service not in [s for s, _ in coarse]:
            coarse.append((service, score))
    total = sum(s for _, s in coarse)
    return [(s, v / total) for s, v in coarse]


def analyze(payload, inject_time):
    began = time.monotonic()
    metric, logts = payload["metric"], payload["logts"]
    traces_err, traces_lat = payload.get("tracets_err", pd.DataFrame()), payload.get("tracets_lat", pd.DataFrame())
    has_traces = traces_err is not None and len(traces_err) > 0

    metric = metric.iloc[::15, :]
    normal_metric = preprocess(data=metric[metric["time"] < inject_time], dataset=DATASET)
    anomal_metric = preprocess(data=metric[metric["time"] >= inject_time], dataset=DATASET)
    common = [c for c in normal_metric.columns if c in anomal_metric.columns]
    normal_metric, anomal_metric = normal_metric[common], anomal_metric[common]

    logts = drop_constant(logts)
    normal_logs = logts[logts["time"] < inject_time].drop(columns=["time"])
    anomal_logs = logts[logts["time"] >= inject_time].drop(columns=["time"])

    if has_traces:
        prepared = {}
        for name, frame in (("err", traces_err), ("lat", traces_lat)):
            frame = drop_constant(frame.ffill().fillna(0))
            prepared[name] = (frame[frame["time"] < inject_time].drop(columns=["time"]), frame[frame["time"] >= inject_time].drop(columns=["time"]), frame)
        traces_err, traces_lat = prepared["err"][2], prepared["lat"][2]

    fine = {"metric": _severity(normal_metric, anomal_metric), "log": _severity(normal_logs, anomal_logs),
            "trace_err": [], "trace_lat": []}
    if has_traces:
        fine["trace_err"] = _severity(prepared["err"][0], prepared["err"][1], trace_error=True, drop_tail=True)
        fine["trace_lat"] = _severity(prepared["lat"][0], prepared["lat"][1])

    by_source = {
        "metric": _add_up(fine["metric"]), "log": _highest(fine["log"]),
        "trace_lat": _add_up(fine["trace_lat"]), "trace_err": _add_up(fine["trace_err"]),
    }
    matrix = pd.DataFrame({k: pd.Series([s for _, s in v], index=[c for c, _ in v]) for k, v in by_source.items()}).fillna(0)
    services = matrix.index.to_list()
    X = matrix.to_numpy()

    bic = []
    for n in range(1, X.shape[0] + 1):
        bic.append(GaussianMixture(n_components=n, covariance_type="full", max_iter=50, random_state=0).fit(X).bic(X))
    best = int(np.argmin(bic)) + 1
    estimator = GaussianMixture(n_components=best, covariance_type="full", max_iter=50, random_state=0).fit(X)
    labels = estimator.predict(X)
    mean_score = np.mean(X, axis=1)

    cluster_scores = sorted(((c, float(np.mean(mean_score[labels == c]))) for c in set(labels)), key=lambda x: x[1], reverse=True)
    ranks, clusters = [], []
    for position, (cluster, score) in enumerate(cluster_scores, start=1):
        members = [services[i] for i in np.where(labels == cluster)[0]]
        member_scores = mean_score[labels == cluster]
        ordered = [m for m, _ in sorted(zip(members, member_scores), key=lambda x: x[1], reverse=True)]
        refined = False
        if len(members) == 1:
            ranks.append(members[0])
        else:
            prefixes = tuple(members)
            sub_metric = metric.loc[:, metric.columns.str.startswith(prefixes)].copy()
            sub_metric["time"] = metric["time"]
            sub_logs = logts.loc[:, logts.columns.str.startswith(prefixes)].copy()
            sub_logs["time"] = logts["time"]
            sub_err = sub_lat = None
            if has_traces:
                sub_err = traces_err.loc[:, traces_err.columns.str.startswith(prefixes)].copy()
                sub_err["time"] = traces_err["time"]
                sub_lat = traces_lat.loc[:, traces_lat.columns.str.startswith(prefixes)].copy()
                sub_lat["time"] = traces_lat["time"]
            rcd = _rcd_multimodal(data={"metric": sub_metric, "logts": sub_logs, "tracets_err": sub_err, "tracets_lat": sub_lat},
                                  inject_time=inject_time, dataset=DATASET)
            inner = []
            for r in [s.split("_")[0] for s in rcd["ranks"]]:
                if r not in inner:
                    inner.append(r)
            if len(inner) == len(members):
                ranks.extend(inner)
                refined = True
            else:
                ranks.extend(ordered)
        clusters.append({"id": position, "score": round(score, 6), "services": ranks[len(ranks) - len(members):], "size": len(members), "refined": refined})

    cluster_of = {s: c["id"] for c in clusters for s in c["services"]}
    severity = {s: {src: round(float(matrix.loc[s, src]), 6) for src in SOURCES} for s in services}
    top = {src: [[col, round(score, 6)] for col, score in fine[src][:TOP_FINE]] for src in SOURCES}
    return {"ranks": ranks, "severity": severity, "service_score": {s: round(float(mean_score[i]), 6) for i, s in enumerate(services)},
            "clusters": clusters, "cluster_of": cluster_of, "n_clusters": best, "fine": top,
            "indicators": indicators_by_service(column_scores(payload, inject_time)),
            "timings_ms": {"analysis": int((time.monotonic() - began) * 1000)}}


INDICATOR_MIN_SCORE = 3.0
INDICATORS_PER_SERVICE = 3


def _robust_scores(normal, anomal, source, drop_tail=False):
    scores = []
    for column in normal.columns:
        a, b = normal[column].to_numpy(), anomal[column].to_numpy()
        if drop_tail:
            a = a[:-2]
        if a.size == 0 or b.size == 0:
            continue
        scaler = RobustScaler().fit(a.reshape(-1, 1))
        scores.append((column, float(np.max(scaler.transform(b.reshape(-1, 1))[:, 0])), source))
    return scores


def column_scores(payload, inject_time):
    metric, logts = payload["metric"], payload["logts"]
    traces_err, traces_lat = payload.get("tracets_err", pd.DataFrame()), payload.get("tracets_lat", pd.DataFrame())
    has_traces = traces_err is not None and len(traces_err) > 0

    metric = metric.iloc[::15, :]
    normal_metric = preprocess(data=metric[metric["time"] < inject_time], dataset=DATASET)
    anomal_metric = preprocess(data=metric[metric["time"] >= inject_time], dataset=DATASET)
    common = [c for c in normal_metric.columns if c in anomal_metric.columns]
    scores = _robust_scores(normal_metric[common], anomal_metric[common], "metric")

    logts = drop_constant(logts)
    scores += _robust_scores(logts[logts["time"] < inject_time].drop(columns=["time"]), logts[logts["time"] >= inject_time].drop(columns=["time"]), "log")

    if has_traces:
        for frame, source, drop_tail in ((traces_err, "trace_err", True), (traces_lat, "trace_lat", False)):
            frame = drop_constant(frame.ffill().fillna(0))
            scores += _robust_scores(frame[frame["time"] < inject_time].drop(columns=["time"]), frame[frame["time"] >= inject_time].drop(columns=["time"]), source, drop_tail)

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def indicators_by_service(scores, per_service=INDICATORS_PER_SERVICE, min_score=INDICATOR_MIN_SCORE):
    out = {}
    for column, score, source in scores:
        if score < min_score:
            break
        service = column.split("_")[0]
        picked = out.setdefault(service, [])
        if len(picked) < per_service:
            picked.append({"column": column, "source": source, "score": round(score, 6)})
    return out
