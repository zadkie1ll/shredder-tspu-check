import asyncio
import logging
from collections import Counter

from .domain import AlertKind, Verdict
from .remnawave import RemnawaveClient
from .ripe_atlas import RipeAtlasClient
from .storage import Storage
from .telegram import send_alert

log = logging.getLogger(__name__)


def format_alert(node, result: dict, kind: AlertKind) -> str:
    blocked = kind == AlertKind.BLOCKED
    title = "🚨 ВОЗМОЖНА БЛОКИРОВКА ТСПУ" if blocked else "✅ ДОСТУП ВОССТАНОВЛЕН"
    errors = (
        ", ".join(f"{key}: {value}" for key, value in result["errors"].items())
        or "нет ошибок"
    )
    return (
        f"{title}\n"
        f"Нода: {node.name}\n"
        f"IP: {node.address}\n"
        f"Проверка: {result['request_id']}\n"
        f"Вердикт: {result['verdict']} ({result['reason']})\n"
        f"Учитываемых точек: {result['total']}\n"
        f"Таймауты: {result['failures']}\n"
        f"Connection refused: {result['service_errors']}\n"
        f"Причины: {errors}\n"
        f"Отчёт: {result['permanent_link']}"
    )


async def _check_node(node, atlas, storage, settings, semaphore) -> Verdict:
    async with semaphore:
        try:
            if atlas is None:
                result = {
                    "verdict": Verdict.UNCERTAIN.value,
                    "reason": "ripe_atlas_not_configured",
                    "errors": {},
                    "request_id": "ripe:not-created",
                    "total": 0,
                    "failures": 0,
                    "service_errors": 0,
                    "permanent_link": "",
                }
            else:
                # RIPE Atlas is the primary source, as in Monkey Island.
                # Check-Host no longer gates or changes this measurement.
                result = await atlas.check(node)
            verdict = Verdict(result["verdict"])
            decision = storage.record_check(node, verdict, result)
            log.info(
                "node=%s address=%s verdict=%s reason=%s",
                node.name,
                node.address,
                verdict.value,
                result.get("reason"),
            )
            if decision:
                try:
                    await send_alert(
                        settings, format_alert(node, result, decision.kind)
                    )
                except Exception:
                    # Do not mark delivery: the same alert will be retried on
                    # the next decisive observation.
                    log.exception("alert delivery failed for node=%s", node.name)
                else:
                    storage.mark_alert_delivered(node.uuid, decision.status)
            return verdict
        except Exception:
            log.exception("TSPU check failed for %s (%s)", node.name, node.address)
            return Verdict.UNCERTAIN


async def check_all(settings, rw, atlas, storage) -> dict[str, int]:
    nodes = await rw.list_nodes()
    log.info("loaded %d active nodes from Remnawave", len(nodes))
    semaphore = asyncio.Semaphore(settings.check_concurrency)
    verdicts = await asyncio.gather(
        *(
            _check_node(node, atlas, storage, settings, semaphore)
            for node in nodes
        )
    )
    summary = Counter(verdict.value for verdict in verdicts)
    summary["nodes"] = len(nodes)
    log.info("monitoring cycle finished: %s", dict(summary))
    return dict(summary)


async def run(settings) -> None:
    rw = RemnawaveClient(settings)
    atlas = RipeAtlasClient(settings) if settings.ripe_atlas_api_key else None
    storage = Storage(settings.database_path)
    try:
        while True:
            try:
                await check_all(settings, rw, atlas, storage)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("monitoring cycle failed")
            if settings.run_once:
                return
            await asyncio.sleep(settings.check_interval_seconds)
    finally:
        storage.close()
