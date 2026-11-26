import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"
STATUS_FAILED = "failed"


class SourceUnavailable(Exception):
    pass


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("window end must be after its start")

    @property
    def seconds(self):
        return (self.end - self.start).total_seconds()

    def start_ts(self):
        return self.start.timestamp()

    def end_ts(self):
        return self.end.timestamp()

    @staticmethod
    def from_iso(start, end):
        return Window(parse_iso(start), parse_iso(end))


def parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class Health:
    source: str
    ok: bool
    latency_ms: Optional[int] = None
    detail: str = ""


@dataclass
class FetchResult:
    source: str
    kind: str
    status: str = STATUS_OK
    records: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    error: Optional[str] = None
    seconds: float = 0.0

    @property
    def usable(self):
        return self.status in (STATUS_OK, STATUS_PARTIAL)


class Budget:
    def __init__(self, seconds, clock=time.monotonic):
        self.deadline = clock() + seconds if seconds else None
        self.clock = clock

    def expired(self):
        return self.deadline is not None and self.clock() >= self.deadline


class Connector(ABC):
    name = ""
    kind = ""

    @abstractmethod
    def health(self) -> Health:
        ...

    @abstractmethod
    def fetch(self, window: Window, services: Optional[Sequence[str]] = None) -> FetchResult:
        ...

    def safe_fetch(self, window, services=None):
        began = time.monotonic()
        try:
            result = self.fetch(window, services)
        except SourceUnavailable as e:
            result = FetchResult(self.name, self.kind, STATUS_UNAVAILABLE, error=str(e))
        except SourceError as e:
            result = FetchResult(self.name, self.kind, STATUS_FAILED, error=str(e))
        except Exception as e:
            result = FetchResult(self.name, self.kind, STATUS_FAILED, error="unexpected error: %s: %s" % (type(e).__name__, e))
        result.seconds = round(time.monotonic() - began, 3)
        return result


@dataclass(frozen=True)
class MetricSeries:
    name: str
    labels: dict
    service: Optional[str]
    values: tuple

    def to_dict(self):
        return {"name": self.name, "labels": self.labels, "service": self.service, "values": [list(v) for v in self.values]}


@dataclass(frozen=True)
class Span:
    trace: str
    span: str
    parent: Optional[str]
    service: Optional[str]
    operation: str
    start_us: int
    duration_us: int
    error: bool
    http: Any = None
    grpc: Any = None
    kind: Optional[str] = None

    def to_dict(self):
        return dict(self.__dict__)


@dataclass(frozen=True)
class LogRecord:
    ts: str
    service: Optional[str]
    severity: Optional[str]
    severity_number: Optional[int]
    body: Any
    trace: Optional[str] = None
    span: Optional[str] = None

    def to_dict(self):
        return dict(self.__dict__)
