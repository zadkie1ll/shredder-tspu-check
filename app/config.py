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


def _list(name: str, default: str) -> tuple[str, ...]:
    return tuple(
        item.strip().lower()
        for item in os.getenv(name, default).split("|")
        if item.strip()
    )


@dataclass(frozen=True)
class Settings:
    remnawave_url: str
    remnawave_api_path: str
    remnawave_api_key: str
    remnawave_auth_header: str
    checkhost_url: str
    checkhost_type: str
    checkhost_port: int
    checkhost_max_nodes: int
    checkhost_timeout_seconds: int
    checkhost_poll_interval_seconds: int
    checkhost_ru_targets: tuple[str, ...]
    checkhost_control_targets: tuple[str, ...]
    ripe_atlas_url: str
    ripe_atlas_api_key: str
    ripe_atlas_timeout_seconds: int
    ripe_atlas_poll_interval_seconds: int
    ripe_atlas_min_results: int
    ripe_atlas_daily_budget: int
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
        if not 0 < self.checkhost_port < 65536:
            errors.append("CHECKHOST_PORT must be between 1 and 65535")
        if self.checkhost_type != "tcp":
            errors.append("CHECKHOST_TYPE must be tcp")
        for name, value in (
            ("CHECKHOST_MAX_NODES", self.checkhost_max_nodes),
            ("CHECKHOST_TIMEOUT_SECONDS", self.checkhost_timeout_seconds),
            ("CHECKHOST_POLL_INTERVAL_SECONDS", self.checkhost_poll_interval_seconds),
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
        if not self.checkhost_ru_targets:
            errors.append("CHECKHOST_RU_TARGETS must not be empty")
        if not self.checkhost_control_targets:
            errors.append("CHECKHOST_CONTROL_TARGETS must not be empty")
        if errors:
            raise ValueError("; ".join(errors))


def load_settings() -> Settings:
    settings = Settings(
        remnawave_url=os.getenv("REMNAWAVE_URL", "").rstrip("/"),
        remnawave_api_path=os.getenv("REMNAWAVE_API_PATH", "/api/nodes"),
        remnawave_api_key=os.getenv("REMNAWAVE_API_KEY", ""),
        remnawave_auth_header=os.getenv("REMNAWAVE_AUTH_HEADER", "X-API-Key"),
        checkhost_url=os.getenv("CHECKHOST_URL", "https://check-host.net").rstrip("/"),
        checkhost_type=os.getenv("CHECKHOST_TYPE", "tcp"),
        checkhost_port=_int("CHECKHOST_PORT", 443),
        checkhost_max_nodes=_int("CHECKHOST_MAX_NODES", 50),
        checkhost_timeout_seconds=_int("CHECKHOST_TIMEOUT_SECONDS", 120),
        checkhost_poll_interval_seconds=_int("CHECKHOST_POLL_INTERVAL_SECONDS", 3),
        checkhost_ru_targets=_list("CHECKHOST_RU_TARGETS", "Russia"),
        checkhost_control_targets=_list("CHECKHOST_CONTROL_TARGETS", "Romania|Serbia"),
        ripe_atlas_url=os.getenv(
            "RIPE_ATLAS_URL", "https://atlas.ripe.net/api/v2"
        ).rstrip("/"),
        ripe_atlas_api_key=os.getenv("RIPE_ATLAS_API_KEY", ""),
        ripe_atlas_timeout_seconds=_int("RIPE_ATLAS_TIMEOUT_SECONDS", 240),
        ripe_atlas_poll_interval_seconds=_int("RIPE_ATLAS_POLL_INTERVAL_SECONDS", 10),
        ripe_atlas_min_results=_int("RIPE_ATLAS_MIN_RESULTS", 5),
        ripe_atlas_daily_budget=_int("RIPE_ATLAS_DAILY_BUDGET", 55000),
        check_concurrency=_int("CHECK_CONCURRENCY", 5),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        telegram_message_thread_id=(
            int(os.environ["TELEGRAM_MESSAGE_THREAD_ID"])
            if os.getenv("TELEGRAM_MESSAGE_THREAD_ID")
            else None
        ),
        check_interval_seconds=_int("CHECK_INTERVAL_SECONDS", 900),
        request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 20),
        database_path=os.getenv("DATABASE_PATH", "./data/tspu-monitor.sqlite3"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        run_once=_bool("RUN_ONCE", False),
    )
    settings.validate()
    return settings
