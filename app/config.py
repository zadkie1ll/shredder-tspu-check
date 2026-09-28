from dataclasses import dataclass
import os


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class Settings:
    remnawave_url: str
    remnawave_api_path: str
    remnawave_api_key: str
    remnawave_auth_header: str
    ripe_atlas_url: str
    ripe_atlas_api_key: str
    ripe_atlas_timeout_seconds: int
    ripe_atlas_poll_interval_seconds: int
    ripe_atlas_min_results: int
    ripe_atlas_daily_budget: int
    ripe_atlas_light_mode: bool
    check_concurrency: int
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_message_thread_id: int | None
    check_interval_seconds: int
    request_timeout_seconds: int
    database_path: str
    log_level: str
    run_once: bool

    def validate(self) -> None:
        errors = []
        if not self.remnawave_url:
            errors.append("REMNAWAVE_URL is required")
        if not self.remnawave_api_key:
            errors.append("REMNAWAVE_API_KEY is required")
        for name, value in (
            ("CHECK_INTERVAL_SECONDS", self.check_interval_seconds),
            ("REQUEST_TIMEOUT_SECONDS", self.request_timeout_seconds),
            ("CHECK_CONCURRENCY", self.check_concurrency),
            ("RIPE_ATLAS_TIMEOUT_SECONDS", self.ripe_atlas_timeout_seconds),
            ("RIPE_ATLAS_POLL_INTERVAL_SECONDS", self.ripe_atlas_poll_interval_seconds),
            ("RIPE_ATLAS_MIN_RESULTS", self.ripe_atlas_min_results),
            ("RIPE_ATLAS_DAILY_BUDGET", self.ripe_atlas_daily_budget),
        ):
            if value <= 0:
                errors.append(f"{name} must be positive")
        if errors:
            raise ValueError("; ".join(errors))


def load_settings() -> Settings:
    settings = Settings(
        remnawave_url=os.getenv("REMNAWAVE_URL", "").rstrip("/"),
        remnawave_api_path=os.getenv("REMNAWAVE_API_PATH", "/api/nodes"),
        remnawave_api_key=os.getenv("REMNAWAVE_API_KEY", ""),
        remnawave_auth_header=os.getenv("REMNAWAVE_AUTH_HEADER", "X-API-Key"),
        ripe_atlas_url=os.getenv(
            "RIPE_ATLAS_URL", "https://atlas.ripe.net/api/v2"
        ).rstrip("/"),
        ripe_atlas_api_key=os.getenv("RIPE_ATLAS_API_KEY", ""),
        ripe_atlas_timeout_seconds=_int("RIPE_ATLAS_TIMEOUT_SECONDS", 240),
        ripe_atlas_poll_interval_seconds=_int("RIPE_ATLAS_POLL_INTERVAL_SECONDS", 10),
        ripe_atlas_min_results=_int("RIPE_ATLAS_MIN_RESULTS", 5),
        ripe_atlas_daily_budget=_int("RIPE_ATLAS_DAILY_BUDGET", 60000),
        ripe_atlas_light_mode=_bool("RIPE_ATLAS_LIGHT_MODE", True),
        check_concurrency=_int("CHECK_CONCURRENCY", 12),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        telegram_message_thread_id=(
            int(os.environ["TELEGRAM_MESSAGE_THREAD_ID"])
            if os.getenv("TELEGRAM_MESSAGE_THREAD_ID")
            else None
        ),
        check_interval_seconds=_int("CHECK_INTERVAL_SECONDS", 3600),
        request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 20),
        database_path=os.getenv("DATABASE_PATH", "./data/tspu-monitor.sqlite3"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        run_once=_bool("RUN_ONCE", False),
    )
    settings.validate()
    return settings
