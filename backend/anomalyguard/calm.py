import logging
import math
import urllib.parse

from .connectors.base import SourceError, SourceUnavailable
from .connectors.http import HttpClient

ERROR_RATE = 'sum(rate(http_server_request_duration_seconds_count{service_name="frontend",http_response_status_code=~"[45].."}[2m]))'
REQUEST_RATE = 'sum(rate(http_server_request_duration_seconds_count{service_name="frontend"}[2m]))'
FRONTEND_P90 = 'histogram_quantile(0.90, sum by (le) (rate(http_server_request_duration_seconds_bucket{service_name="frontend"}[2m])))'
CATALOG_P90 = 'histogram_quantile(0.90, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{service_name="product-catalog"}[2m])))'

log = logging.getLogger("anomalyguard.calm")

MAX_ERROR_RATE = 0.005
MIN_REQUEST_RATE = 0.5
MAX_FRONTEND_P90_S = 0.5
MAX_CATALOG_P90_MS = 1000.0


class PrometheusProbe:
    def __init__(self, url, http=None):
        self.url = url.rstrip("/")
        self.http = http or HttpClient(timeout=10.0, retries=2)

    def value(self, expression):
        data = self.http.request(self.url + "/api/v1/query?" + urllib.parse.urlencode({"query": expression}))["data"]["result"]
        if not data:
            return None
        number = float(data[0]["value"][1])
        return None if math.isnan(number) else number

    def alerts(self):
        return [a["labels"].get("alertname", "?") for a in self.http.request(self.url + "/api/v1/alerts")["data"]["alerts"]]


class CalmGate:
    def __init__(self, probe, flags, flag_names, clock, required_s):
        self.probe = probe
        self.flags = flags
        self.flag_names = list(flag_names)
        self.clock = clock
        self.required_s = required_s
        self.since = None
        self.reason = None

    def look(self):
        try:
            alerts = self.probe.alerts()
            if alerts:
                return "há alerta ativo (%s)" % ", ".join(sorted(set(alerts)))
            for flag in self.flag_names:
                if self.flags.get(flag) != "off":
                    return "a falha %s está ligada no Demo" % flag
            errors = self.probe.value(ERROR_RATE) or 0.0
            if errors > MAX_ERROR_RATE:
                return "o frontend ainda devolve erros (%.3f por segundo)" % errors
            requests = self.probe.value(REQUEST_RATE)
            if requests is None or requests < MIN_REQUEST_RATE:
                return "pouco tráfego no frontend"
            latency = self.probe.value(FRONTEND_P90)
            if latency is None or latency > MAX_FRONTEND_P90_S:
                return "a latência do frontend ainda está alta"
            catalog = self.probe.value(CATALOG_P90)
            if catalog is not None and catalog > MAX_CATALOG_P90_MS:
                return "o catálogo de produtos ainda está lento"
        except (SourceError, SourceUnavailable, KeyError, TypeError, ValueError) as e:
            return "não consegui consultar o Demo: %s" % e
        except Exception as e:
            return "não consegui consultar o Demo: %s" % type(e).__name__
        return None

    def observe(self):
        previous = self.reason
        self.reason = self.look()
        if self.reason != previous:
            log.info("calm gate: %s", self.reason or "calm again")
        if self.reason is None:
            if self.since is None:
                self.since = self.clock()
        else:
            self.since = None
        return self.reason is None

    def calm_for(self):
        return 0.0 if self.since is None else (self.clock() - self.since).total_seconds()

    def is_calm(self):
        return self.since is not None and self.calm_for() >= self.required_s

    def reset(self):
        self.since = None
