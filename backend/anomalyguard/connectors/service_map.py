import json
import re

DEMO_SERVICES = ["ad", "cart", "checkout", "currency", "email", "frontend", "frontend-proxy", "image-provider", "payment",
                 "product-catalog", "quote", "recommendation", "shipping", "valkey-cart", "astronomy-db"]

DEMO_IGNORED = {"flagd", "flagd-ui", "frontend-web", "jaeger", "load-generator", "otelcol-contrib", "telemetry-docs",
                "opamp-server", "grafana", "prometheus", "alertmanager", "opensearch", "otel-collector", "webhook-receiver"}

LABEL_KEYS = {
    "metrics": ["service_name", "container_name", "job"],
    "traces": ["serviceName", "service_name"],
    "logs": ["service.name", "service_name"],
    "alert": ["service", "service_name", "service.name", "app", "job", "container_name"],
}

_PREFIX = re.compile(r"^[^/]+/")


def normalize(raw):
    if raw is None:
        return None
    name = str(raw).strip().lower().replace("_", "-")
    name = _PREFIX.sub("", name)
    return name or None


class ServiceMap:
    def __init__(self, services=None, aliases=None, ignored=None, label_keys=None):
        self.services = list(services if services is not None else DEMO_SERVICES)
        self.aliases = {normalize(k): normalize(v) for k, v in (aliases or {}).items()}
        self.ignored = {normalize(i) for i in (ignored if ignored is not None else DEMO_IGNORED)}
        self.label_keys = {**LABEL_KEYS, **(label_keys or {})}
        self._known = set(self.services)

    @staticmethod
    def demo():
        return ServiceMap()

    @staticmethod
    def from_json(text):
        data = json.loads(text)
        return ServiceMap(data.get("services"), data.get("aliases"), data.get("ignored"), data.get("label_keys"))

    def canonical(self, raw):
        name = normalize(raw)
        if name is None or name in self.ignored:
            return None
        name = self.aliases.get(name, name)
        return name if name in self._known else None

    def resolve(self, source, labels):
        for key in self.label_keys.get(source, []):
            value = _lookup(labels, key)
            if value is None:
                continue
            service = self.canonical(value)
            if service is not None:
                return service
        return None

    def resolve_alert(self, labels):
        return self.resolve("alert", labels)

    def spellings(self, canonical):
        out = {canonical}
        out.update(alias for alias, target in self.aliases.items() if target == canonical)
        return sorted(out)

    def in_scope(self, services):
        if services is None:
            return None
        wanted = set()
        for s in services:
            c = self.canonical(s)
            if c is None:
                raise ValueError("unknown service: %r" % (s,))
            wanted.add(c)
        return wanted


def _lookup(labels, key):
    if key in labels:
        return labels[key]
    node = labels
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node if not isinstance(node, dict) else None
