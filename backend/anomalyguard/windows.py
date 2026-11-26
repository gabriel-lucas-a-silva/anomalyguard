from dataclasses import dataclass
from datetime import timedelta

from .connectors.base import Window


@dataclass(frozen=True)
class Plan:
    t_alert: object
    baseline_s: int
    margin_s: int
    delta_s: int

    @property
    def baseline_end(self):
        return self.t_alert - timedelta(seconds=self.margin_s)

    @property
    def baseline_start(self):
        return self.baseline_end - timedelta(seconds=self.baseline_s)

    @property
    def anomaly_end(self):
        return self.t_alert + timedelta(seconds=self.delta_s)

    def collection_window(self):
        return Window(self.baseline_start, self.anomaly_end)

    def data_ready_at(self, lag_s):
        return self.anomaly_end + timedelta(seconds=lag_s)
