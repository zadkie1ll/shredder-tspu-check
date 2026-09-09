import asyncio
import logging

from .checkhost import CheckHostClient
from .remnawave import RemnawaveClient
from .storage import Storage
from .telegram import send_alert

log = logging.getLogger(__name__)


def format_alert(node, result: dict) -> str:
    state = "ЗАБЛОКИРОВАН" if result["verdict"] == "blocked" else "СНОВА ДОСТУПЕН"
    errors = ", ".join(f"{key}: {value}" for key, value in result["errors"].items()) or "нет ошибок"
    return (
        f"🚨 TSPU monitor: {state}\n"
        f"Нода: {node.name}\n"
        f"IP: {node.address}\n"
        f"Проверка: {result['request_id']}\n"
        f"Недоступны: {result['failures']}/{result['total']} ({result['failure_ratio']:.0%})\n"
        f"Порт отклонил: {result['service_errors']}\n"
        f"Состояние транспорта: {result['transport_state']}\n"
        f"Причины: {errors}\n"
        f"Отчёт: {result['permanent_link']}"
    )


async def check_all(settings, rw, checkhost, storage) -> None:
    nodes = await rw.list_nodes()
    log.info("loaded %d active nodes from Remnawave", len(nodes))
    for node in nodes:
        try:
            result = await checkhost.check(node.address)
            status = result["verdict"]
            notify = storage.save_check(node, status, result)
            log.info("%s (%s): %s", node.name, node.address, status)
            if notify:
                await send_alert(settings, format_alert(node, result))
        except Exception:
            log.exception("TSPU check failed for %s (%s)", node.name, node.address)


async def run(settings) -> None:
    rw = RemnawaveClient(settings)
    checkhost = CheckHostClient(settings)
    storage = Storage(settings.database_path)
    while True:
        try:
            await check_all(settings, rw, checkhost, storage)
        except Exception:
            log.exception("monitoring cycle failed")
        await asyncio.sleep(settings.check_interval_seconds)
