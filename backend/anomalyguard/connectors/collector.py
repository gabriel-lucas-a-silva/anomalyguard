from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .base import STATUS_PARTIAL

ESSENTIAL_KINDS = ("metrics",)


@dataclass
class CollectionResult:
    results: dict = field(default_factory=dict)
    missing_sources: list = field(default_factory=list)
    partial_sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def fatal(self):
        return any(self.results[name].kind in ESSENTIAL_KINDS and not self.results[name].usable for name in self.results)

    @property
    def incomplete(self):
        return bool(self.missing_sources or self.partial_sources)

    def records(self, kind):
        for result in self.results.values():
            if result.kind == kind and result.usable:
                return result.records
        return []

    def summary(self):
        return {name: {"status": r.status, "records": len(r.records), "seconds": r.seconds, "error": r.error, "warnings": len(r.warnings)}
                for name, r in self.results.items()}


class Collector:
    def __init__(self, connectors, parallel=True):
        self.connectors = list(connectors)
        self.parallel = parallel

    def collect(self, window, services=None):
        if self.parallel and len(self.connectors) > 1:
            with ThreadPoolExecutor(max_workers=len(self.connectors)) as pool:
                futures = [(c, pool.submit(c.safe_fetch, window, services)) for c in self.connectors]
                fetched = [(c, f.result()) for c, f in futures]
        else:
            fetched = [(c, c.safe_fetch(window, services)) for c in self.connectors]
        out = CollectionResult()
        for connector, result in fetched:
            out.results[connector.name] = result
            if not result.usable:
                out.missing_sources.append(connector.name)
                out.warnings.append("%s: %s (%s)" % (connector.name, result.error, result.status))
            elif result.status == STATUS_PARTIAL:
                out.partial_sources.append(connector.name)
                out.warnings.extend("%s: %s" % (connector.name, w) for w in result.warnings[:5])
        return out

    def health(self):
        return {c.name: c.health() for c in self.connectors}
