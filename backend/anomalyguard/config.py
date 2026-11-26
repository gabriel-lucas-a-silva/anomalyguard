import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    prometheus_url: str
    opensearch_url: str
    allowed_origins: tuple
    webhook_token: str
    baseline_s: int = 600
    margin_s: int = 315
    delta_s: int = 180
    data_lag_s: int = 75
    min_operation_calls: int = 10
    group_window_s: int = 300
    poll_s: int = 5
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_model: str = "gemini-3.8-flash"
    narrator_timeout_s: int = 60
    demo_mode: bool = False
    flagd_ui_url: str = "http://flagd-ui:4000"
    demo_duration_s: int = 420
    stuck_after_s: int = 900
    campaign_calm_s: int = 720
    campaign_calm_timeout_s: int = 1800
    campaign_alert_timeout_s: int = 480
    campaign_analysis_timeout_s: int = 900
    campaign_tick_s: int = 15

    @staticmethod
    def from_env(env=None):
        env = os.environ if env is None else env
        origins = env.get("AG_ALLOWED_ORIGINS", "http://127.0.0.1:5174,http://localhost:5174")
        return Settings(
            database_url=env["AG_DATABASE_URL"],
            prometheus_url=env.get("AG_PROMETHEUS_URL", "http://prometheus:9090"),
            opensearch_url=env.get("AG_OPENSEARCH_URL", "http://opensearch:9200"),
            webhook_token=env["AG_WEBHOOK_TOKEN"],
            allowed_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            baseline_s=int(env.get("AG_BASELINE_S", "600")),
            margin_s=int(env.get("AG_MARGIN_S", "315")),
            delta_s=int(env.get("AG_DELTA_S", "180")),
            data_lag_s=int(env.get("AG_DATA_LAG_S", "75")),
            min_operation_calls=int(env.get("AG_MIN_OPERATION_CALLS", "10")),
            group_window_s=int(env.get("AG_GROUP_WINDOW_S", "300")),
            poll_s=int(env.get("AG_POLL_S", "5")),
            gemini_api_key=env.get("AG_GEMINI_API_KEY", "").strip(),
            gemini_model=env.get("AG_GEMINI_MODEL", "gemini-3.5-flash-lite"),
            gemini_fallback_model=env.get("AG_GEMINI_FALLBACK_MODEL", "gemini-3.8-flash"),
            narrator_timeout_s=int(env.get("AG_NARRATOR_TIMEOUT_S", "60")),
            demo_mode=env.get("AG_DEMO_MODE", "false").strip().lower() in ("1", "true", "yes"),
            flagd_ui_url=env.get("AG_FLAGD_UI_URL", "http://flagd-ui:4000"),
            demo_duration_s=int(env.get("AG_DEMO_DURATION_S", "420")),
            stuck_after_s=int(env.get("AG_STUCK_AFTER_S", "900")),
            campaign_calm_s=int(env.get("AG_CAMPAIGN_CALM_S", "720")),
            campaign_calm_timeout_s=int(env.get("AG_CAMPAIGN_CALM_TIMEOUT_S", "1800")),
            campaign_alert_timeout_s=int(env.get("AG_CAMPAIGN_ALERT_TIMEOUT_S", "480")),
            campaign_analysis_timeout_s=int(env.get("AG_CAMPAIGN_ANALYSIS_TIMEOUT_S", "900")),
            campaign_tick_s=int(env.get("AG_CAMPAIGN_TICK_S", "15")),
        )
