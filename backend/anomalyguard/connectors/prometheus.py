import re
import time
import urllib.parse

from .base import (Budget, Connector, FetchResult, Health, MetricSeries, STATUS_OK, STATUS_PARTIAL, SourceError, SourceUnavailable)
from .http import HttpClient
from .service_map import ServiceMap

DEFAULT_EXCLUDE = r"^(otelcol_|otel_sdk_|prometheus_|go_|promhttp_|scrape_|jaeger_|grafana_|opensearch_|process_runtime_go)"


class PrometheusConnector(Connector):
    name = "prometheus"
    kind = "metrics"

    def __init__(self, url, service_map=None, http=None, step=15, exclude=DEFAULT_EXCLUDE, budget_seconds=120, max_failed_ratio=0.2):
        self.url = url.rstrip("/")
        self.map = service_map or ServiceMap.demo()
        self.http = http or HttpClient()
        self.step = step
        self.exclude = re.compile(exclude) if exclude else None
        self.budget_seconds = budget_seconds
        self.max_failed_ratio = max_failed_ratio

    def health(self):
        began = time.monotonic()
        try:
            self.http.request(self.url + "/api/v1/status/buildinfo")
            return Health(self.name, True, int((time.monotonic() - began) * 1000))
        except (SourceUnavailable, SourceError) as e:
            return Health(self.name, False, None, str(e))

    def fetch(self, window, services=None):
        wanted = self.map.in_scope(services)
        budget = Budget(self.budget_seconds)
        names = self.http.request(self.url + "/api/v1/label/__name__/values")["data"]
        result = FetchResult(self.name, self.kind)
        stats = {"metric_names": len(names), "excluded_names": 0, "series": 0, "points": 0, "failed_names": [], "skipped_by_budget": 0}
        for index, name in enumerate(names):
            if self.exclude and self.exclude.match(name):
                stats["excluded_names"] += 1
                continue
            if budget.expired():
                stats["skipped_by_budget"] = len(names) - index
                result.warnings.append("time budget exhausted: %d metric names were not queried" % stats["skipped_by_budget"])
                break
            query = urllib.parse.urlencode({"query": name, "start": window.start_ts(), "end": window.end_ts(), "step": "%ds" % self.step})
            try:
                data = self.http.request(self.url + "/api/v1/query_range?" + query)["data"]["result"]
            except (SourceUnavailable, SourceError, KeyError, TypeError) as e:
                stats["failed_names"].append(name)
                result.warnings.append("metric %s failed: %s" % (name, e))
                continue
            for series in data:
                labels = {k: v for k, v in series["metric"].items() if k != "__name__"}
                service = self.map.resolve("metrics", labels)
                if wanted is not None and service is not None and service not in wanted:
                    continue
                values = tuple((float(t), v) for t, v in series["values"])
                result.records.append(MetricSeries(name, labels, service, values))
                stats["series"] += 1
                stats["points"] += len(values)
        queried = stats["metric_names"] - stats["excluded_names"] - stats["skipped_by_budget"]
        failed = len(stats["failed_names"])
        if queried and failed / queried > self.max_failed_ratio:
            raise SourceUnavailable("%d of %d metric queries failed" % (failed, queried))
        result.status = STATUS_PARTIAL if (failed or stats["skipped_by_budget"]) else STATUS_OK
        result.stats = stats
        return result
