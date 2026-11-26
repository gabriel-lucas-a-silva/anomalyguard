import time

from .base import Connector, FetchResult, Health, LogRecord, STATUS_OK, STATUS_PARTIAL, SourceError, SourceUnavailable, iso
from .http import HttpClient
from .service_map import ServiceMap


class OpenSearchConnector(Connector):
    name = "opensearch"
    kind = "logs"

    def __init__(self, url, service_map=None, http=None, index="otel-logs-*", page=5000, max_pages=200):
        self.url = url.rstrip("/")
        self.map = service_map or ServiceMap.demo()
        self.http = http or HttpClient()
        self.index = index
        self.page = page
        self.max_pages = max_pages

    def health(self):
        began = time.monotonic()
        try:
            self.http.request(self.url + "/_cluster/health")
            return Health(self.name, True, int((time.monotonic() - began) * 1000))
        except (SourceUnavailable, SourceError) as e:
            return Health(self.name, False, None, str(e))

    def _record(self, hit):
        s = hit["_source"]
        resource = s.get("resource") or {}
        raw = resource.get("service.name") or (resource.get("service") or {}).get("name")
        severity = s.get("severity") or {}
        return LogRecord(s.get("@timestamp"), self.map.canonical(raw), severity.get("text"), severity.get("number"), s.get("body"),
                         s.get("traceId") or None, s.get("spanId") or None)

    def fetch(self, window, services=None):
        wanted = self.map.in_scope(services)
        query = {"range": {"@timestamp": {"gte": iso(window.start_ts()), "lt": iso(window.end_ts())}}}
        body = {"size": self.page, "sort": [{"@timestamp": "asc"}], "track_total_hits": True,
                "_source": ["@timestamp", "body", "severity", "traceId", "spanId", "resource"], "query": query}
        result = FetchResult(self.name, self.kind)
        stats = {"logs": 0, "pages": 0, "dropped_out_of_scope": 0, "expected": None}
        response = self.http.request("%s/%s/_search?scroll=2m" % (self.url, self.index), body)
        scroll_id = response.get("_scroll_id")
        try:
            while stats["pages"] < self.max_pages:
                hits = response["hits"]["hits"]
                if not hits:
                    break
                stats["pages"] += 1
                for hit in hits:
                    record = self._record(hit)
                    if wanted is not None and record.service is not None and record.service not in wanted:
                        stats["dropped_out_of_scope"] += 1
                        continue
                    result.records.append(record)
                    stats["logs"] += 1
                response = self.http.request(self.url + "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id})
                scroll_id = response.get("_scroll_id", scroll_id)
            else:
                result.warnings.append("page limit of %d reached; logs may be missing" % self.max_pages)
        finally:
            try:
                self.http.request(self.url + "/_search/scroll", {"scroll_id": scroll_id}, method="DELETE")
            except (SourceUnavailable, SourceError):
                pass
        stats["expected"] = self.http.request("%s/%s/_count" % (self.url, self.index), {"query": query})["count"]
        retrieved = stats["logs"] + stats["dropped_out_of_scope"]
        if retrieved != stats["expected"]:
            result.warnings.append("retrieved %d of %d expected log records" % (retrieved, stats["expected"]))
        result.status = STATUS_OK if not result.warnings else STATUS_PARTIAL
        result.stats = stats
        return result
