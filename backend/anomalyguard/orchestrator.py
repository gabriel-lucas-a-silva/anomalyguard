import logging
import threading
from datetime import timedelta

log = logging.getLogger("anomalyguard.orchestrator")


class Orchestrator:
    def __init__(self, store, service, runner, settings, clock):
        self.store = store
        self.service = service
        self.runner = runner
        self.settings = settings
        self.clock = clock
        self.stopped = threading.Event()
        self.thread = None

    def recover(self):
        for row in self.store.interrupted():
            self.service.fail(row["id"], "a análise foi interrompida porque o serviço reiniciou")

    def tick(self):
        for row in self.store.stale(self.clock() - timedelta(seconds=self.settings.stuck_after_s)):
            self.service.fail(row["id"], "nenhum sinal da análise por %d s" % self.settings.stuck_after_s)
        for row in self.store.due(self.clock()):
            if self.store.claim(row["id"]):
                self.runner.submit(row["id"], row["received_at"], row["margin_s"])

    def start(self):
        self.recover()
        self.stopped.clear()
        self.thread = threading.Thread(target=self._loop, name="orchestrator", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _loop(self):
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("orchestrator cycle failed")
            self.stopped.wait(self.settings.poll_s)
