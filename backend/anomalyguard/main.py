import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from .api import create_app
from .calm import CalmGate, PrometheusProbe
from .campaign import CampaignEngine
from .config import Settings
from .connectors import build_collector
from .demo import CATALOG, DemoIncidents
from .events import EventHub
from .flags import FlagClient
from .gemini import GeminiClient
from .narrator import ModelSpec, Narrator
from .orchestrator import Orchestrator
from .runner import Runner
from .service import Investigations
from .store import PostgresStore


def utc_now():
    return datetime.now(timezone.utc)


def build_app():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    store = PostgresStore(settings.database_url, utc_now)
    hub = EventHub()
    service = Investigations(store, hub, settings, utc_now)
    collector = build_collector(settings.prometheus_url, settings.opensearch_url)
    client = GeminiClient(settings.gemini_api_key, timeout=settings.narrator_timeout_s) if settings.gemini_api_key else None
    specs = [ModelSpec(settings.gemini_model), ModelSpec(settings.gemini_fallback_model, max_tokens=1200, thinking_budget=0)]
    narrator = Narrator(client, specs)
    runner = Runner(service, collector, settings, narrator)
    orchestrator = Orchestrator(store, service, runner, settings, utc_now)

    flags = FlagClient(settings.flagd_ui_url)
    demo = DemoIncidents(store, flags, settings, utc_now) if settings.demo_mode else None
    campaigns = None
    if demo:
        gate = CalmGate(PrometheusProbe(settings.prometheus_url), flags, [fault["flag"] for fault in CATALOG.values()], utc_now, settings.campaign_calm_s)
        campaigns = CampaignEngine(store, demo, gate, hub, settings, utc_now)
        runner.campaigns = campaigns

    @asynccontextmanager
    async def lifespan(app):
        if demo:
            demo.recover()
        orchestrator.start()
        if campaigns:
            campaigns.start_thread()
        try:
            yield
        finally:
            if campaigns:
                campaigns.stop_thread()
            orchestrator.stop()

    return create_app(service, store, hub, settings, lifespan, demo, client is not None, runner, campaigns)
