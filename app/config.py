from dataclasses import dataclass
import os


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


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
    checkhost_failure_ratio: float
    checkhost_geo_targets: tuple[str, ...]
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_message_thread_id: int | None
    check_interval_seconds: int
    request_timeout_seconds: int
    database_path: str
    log_level: str


def load_settings() -> Settings:
    return Settings(
        remnawave_url=os.getenv("REMNAWAVE_URL", "").rstrip("/"),
        remnawave_api_path=os.getenv("REMNAWAVE_API_PATH", "/api/nodes"),
        remnawave_api_key=os.getenv("REMNAWAVE_API_KEY", ""),
        remnawave_auth_header=os.getenv("REMNAWAVE_AUTH_HEADER", "X-API-Key"),
        checkhost_url=os.getenv("CHECKHOST_URL", "https://check-host.net").rstrip("/"),
        checkhost_type=os.getenv("CHECKHOST_TYPE", "tcp"),
        checkhost_port=_int("CHECKHOST_PORT", 443),
        checkhost_max_nodes=_int("CHECKHOST_MAX_NODES", 10),
        checkhost_timeout_seconds=_int("CHECKHOST_TIMEOUT_SECONDS", 120),
        checkhost_poll_interval_seconds=_int("CHECKHOST_POLL_INTERVAL_SECONDS", 3),
        checkhost_failure_ratio=float(os.getenv("CHECKHOST_FAILURE_RATIO", "0.6")),
        checkhost_geo_targets=tuple(
            item.strip().lower()
            for item in os.getenv(
                "CHECKHOST_GEO_TARGETS",
                "Romania|Russia|Serbia",
            ).split("|")
            if item.strip()
        ),
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
    )
