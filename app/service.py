import asyncio
import logging
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from .domain import Verdict
from .remnawave import RemnawaveClient
from .ripe_atlas import RipeAtlasClient
from .storage import Storage
from .telegram import send_message

log = logging.getLogger(__name__)


def format_cycle_report(observations: list[tuple]) -> str:
    order = {Verdict.BLOCKED: 0, Verdict.CLEAN: 1, Verdict.UNCERTAIN: 2}
    labels = {
        Verdict.BLOCKED: "🚫 ДА",
        Verdict.CLEAN: "✅ НЕТ",
        Verdict.UNCERTAIN: "❔ НЕТ ДАННЫХ",
    }
    counts = Counter(verdict for _, verdict, _ in observations)
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M МСК")
    lines = [
        f"🛡 Проверка блокировок · {now}",
        "",
        f"🚫 Заблокировано: {counts[Verdict.BLOCKED]}",
        f"✅ Доступно: {counts[Verdict.CLEAN]}",
        f"❔ Нет данных: {counts[Verdict.UNCERTAIN]}",
        "",
    ]
    for node, verdict, _ in sorted(
        observations, key=lambda item: (order[item[1]], item[0].name.lower())
    ):
        lines.append(f"{labels[verdict]} · {node.name} · {node.address}")
    return "\n".join(lines)


async def _check_node(node, atlas, storage, settings, semaphore) -> tuple:
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
                result = await atlas.check(node)
            verdict = Verdict(result["verdict"])
            # A new/old blocked episode gets a daily full 33-probe check.
            # Routine hourly checks stay on the sustainable 10-probe set.
            if (
                atlas is not None
                and verdict == Verdict.BLOCKED
                and storage.needs_full_confirmation(node)
            ):
                # Ensure the node row exists before attaching confirmation
                # metadata (important on the first ever cycle).
                storage.record_check(node, verdict, result)
                full_result = await atlas.check(node, light=False)
                verdict = Verdict(full_result["verdict"])
                result = full_result
                storage.record_full_confirmation(node, verdict)
            storage.record_check(node, verdict, result)
            if verdict == Verdict.CLEAN:
                storage.clear_full_confirmation(node.uuid)
            log.info(
                "node=%s address=%s verdict=%s reason=%s",
                node.name,
                node.address,
                verdict.value,
                result.get("reason"),
            )
            return node, verdict, result
        except Exception:
            log.exception("TSPU check failed for %s (%s)", node.name, node.address)
            return node, Verdict.UNCERTAIN, {"reason": "internal_error"}


async def check_all(settings, rw, atlas, storage) -> dict[str, int]:
    nodes = await rw.list_nodes()
    log.info("loaded %d active nodes from Remnawave", len(nodes))
    semaphore = asyncio.Semaphore(settings.check_concurrency)
    observations = await asyncio.gather(
        *(
            _check_node(node, atlas, storage, settings, semaphore)
            for node in nodes
        )
    )
    summary = Counter(verdict.value for _, verdict, _ in observations)
    summary["nodes"] = len(nodes)
    log.info("monitoring cycle finished: %s", dict(summary))
    try:
        await send_message(settings, format_cycle_report(observations))
    except Exception:
        log.exception("cycle report delivery failed")
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
