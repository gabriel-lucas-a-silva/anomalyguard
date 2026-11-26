import numpy as np
import pandas as pd

START = 1_796_220_000
STEP = 15
BINS = 96
ALERT_BIN = 70
SERVICES = ["ad", "cart", "checkout", "frontend", "frontend-proxy", "payment"]
OP = "oteldemo.PaymentService/Charge"


def times():
    return START + STEP * np.arange(BINS)


def tables(fault_service="payment", seed=7, with_traces=True, with_logs=True):
    rng = np.random.default_rng(seed)
    t = times()
    after = np.arange(BINS) >= ALERT_BIN
    metrics = {"time": t}
    for s in SERVICES:
        metrics[s + "|cpu"] = 30 + rng.normal(0, 1.0, BINS)
        metrics[s + "|mem"] = 1e8 + rng.normal(0, 1e5, BINS)
        metrics[s + "|workload"] = 10 + rng.normal(0, 0.3, BINS)
        metrics[s + "|error"] = np.abs(rng.normal(0.01, 0.005, BINS))
        metrics[s + "|latency_p90"] = 80 + rng.normal(0, 2.0, BINS)
    metrics[fault_service + "|error"] = metrics[fault_service + "|error"] + after * 3.0
    metrics[fault_service + "|latency_p90"] = metrics[fault_service + "|latency_p90"] + after * 400
    metrics["checkout|latency_p90"] = metrics["checkout|latency_p90"] + after * 60
    metrics = pd.DataFrame(metrics)
    logs = {"time": t}
    if with_logs:
        for i, s in enumerate(SERVICES, start=1):
            logs["%s|log_template:%d" % (s, i)] = np.abs(rng.normal(2, 0.5, BINS)).round()
        logs[fault_service + "|log_template:%d" % (SERVICES.index(fault_service) + 1)] = logs[fault_service + "|log_template:%d" % (SERVICES.index(fault_service) + 1)] + after * 25
    err, lat = {"time": t}, {"time": t}
    if with_traces:
        for s in SERVICES:
            err["%s|trace_err:%s" % (s, OP)] = np.abs(rng.normal(0.2, 0.1, BINS))
            lat["%s|trace_lat:%s" % (s, OP)] = 50 + rng.normal(0, 1.5, BINS)
        err[fault_service + "|trace_err:" + OP] = err[fault_service + "|trace_err:" + OP] + after * 5
        lat[fault_service + "|trace_lat:" + OP] = lat[fault_service + "|trace_lat:" + OP] + after * 300
    return {"metrics": metrics, "logs": pd.DataFrame(logs), "trace_err": pd.DataFrame(err), "trace_lat": pd.DataFrame(lat)}


def t_alert():
    return START + STEP * ALERT_BIN
