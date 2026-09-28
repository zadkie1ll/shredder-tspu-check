import asyncio
import logging
import time

import httpx

from .domain import Verdict


log = logging.getLogger(__name__)

# Probe sets are kept in sync with monkey-island-website. A one-off sslcert
# result costs about 20 credits: light ~= 200 credits, full ~= 660 credits.
FULL_ASN_PROBE_SPEC = (
    (12389, 3),  # Rostelecom
    (8402, 5),   # Beeline
    (25513, 5),  # MGTS
    (8359, 3),   # MTS
    (3216, 3),   # Beeline
    (20485, 2),  # TTK
    (25490, 1),  # RTK-Yug
    (43727, 1),  # MegaFon
    (12714, 4),  # MegaFon
    (34757, 2),  # Sib Seti
    (29124, 2),  # Iskratelecom
    (12768, 2),  # Dom.ru
)

LIGHT_ASN_PROBE_SPEC = (
    (12389, 2),  # Rostelecom
    (8402, 2),   # Beeline
    (8359, 2),   # MTS
    (12714, 1),  # MegaFon
    (25513, 1),  # MGTS
    (12768, 1),  # Dom.ru
    (20485, 1),  # TTK
)

STAGE_TLS_OK = "tls_ok"
STAGE_TLS_FAIL = "tls_fail"
STAGE_TCP_FAIL = "tcp_fail"
STAGE_TCP_REFUSED = "tcp_refused"
STAGE_UNKNOWN = "unknown"


def classify_stage(row: dict, ok: bool) -> str:
    """Classify the failure stage exactly like Monkey Island."""
    if ok:
        return STAGE_TLS_OK
    error = str(row.get("err") or "").lower()
    if "refused" in error:
        return STAGE_TCP_REFUSED
    if "connect" in error:
        return STAGE_TCP_FAIL
    if row.get("ttc") is not None:
        return STAGE_TLS_FAIL
    if any(word in error for word in ("read", "hello", "tls", "ssl", "handshake")):
        return STAGE_TLS_FAIL
    return STAGE_UNKNOWN


def summarize_results(results: list[dict], minimum_results: int) -> dict:
    rows = [row for row in results if isinstance(row, dict)]
    probes = []
    stages = {}
    ok = 0
    for row in rows:
        reached = any(key in row for key in ("cert", "method", "alert"))
        ok += int(reached)
        stage = classify_stage(row, reached)
        stages[stage] = stages.get(stage, 0) + 1
        probes.append({
            "prb_id": row.get("prb_id"),
            "ok": reached,
            "stage": stage,
            "err": "" if reached else str(row.get("err") or "")[:200],
            "rt_ms": row.get("rt"),
        })
    total = len(rows)
    availability = round(ok * 100 / total) if total else 0
    if total < minimum_results:
        verdict = Verdict.UNCERTAIN
        reason = "insufficient_atlas_results"
    elif availability <= 50:
        verdict = Verdict.BLOCKED
        reason = "ripe_tls_blocked"
    elif availability >= 70:
        verdict = Verdict.CLEAN
        reason = "ripe_tls_reachable"
    else:
        verdict = Verdict.UNCERTAIN
        reason = "ripe_tls_mixed"
    errors = {}
    for row in rows:
        if any(key in row for key in ("cert", "method", "alert")):
            continue
        error = str(row.get("err") or "no_tls_result")[:200]
        errors[str(row.get("prb_id") or "unknown")] = error
    return {
        "verdict": verdict.value,
        "reason": reason,
        "total": total,
        "successes": ok,
        "failures": total - ok,
        "availability": availability,
        "errors": errors,
        "stages": stages,
        "probes": probes,
    }


def build_measurement_payload(node, sni: str, probe_ids: list[int]) -> dict:
    return {
        "definitions": [{
            "target": node.address,
            "description": "shredder tspu confirmation",
            "type": "sslcert",
            "port": node.port,
            "hostname": sni,
            "af": 4,
            "is_public": False,
        }],
        "probes": [{
            "requested": len(probe_ids),
            "type": "probes",
            "value": ",".join(str(value) for value in probe_ids),
        }],
        "is_oneoff": True,
    }


class RipeAtlasClient:
    def __init__(self, settings):
        self.settings = settings
        self._probe_cache: tuple[str, float, list[int]] | None = None
        self._probe_lock = asyncio.Lock()
        self._budget_lock = asyncio.Lock()
        self._reservations: list[tuple[float, int]] = []

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.settings.ripe_atlas_api_key}"}

    async def _probe_ids(self, client: httpx.AsyncClient, light: bool) -> list[int]:
        cache_key = "light" if light else "full"
        async with self._probe_lock:
            if (
                self._probe_cache
                and self._probe_cache[0] == cache_key
                and time.time() - self._probe_cache[1] < 900
            ):
                return list(self._probe_cache[2])
            spec = LIGHT_ASN_PROBE_SPEC if light else FULL_ASN_PROBE_SPEC
            ids = []
            for asn, count in spec:
                response = await client.get(
                    f"{self.settings.ripe_atlas_url}/probes/",
                    params={
                        "asn_v4": asn,
                        "status": 1,
                        "fields": "id",
                        "page_size": count,
                    },
                )
                response.raise_for_status()
                ids.extend(
                    row["id"]
                    for row in response.json().get("results", [])
                    if isinstance(row, dict) and row.get("id")
                )
            ids = list(dict.fromkeys(ids))
            if ids:
                self._probe_cache = (cache_key, time.time(), ids)
            return ids

    async def _reserve_budget(self, client: httpx.AsyncClient, estimated: int) -> bool:
        async with self._budget_lock:
            response = await client.get(
                f"{self.settings.ripe_atlas_url}/credits/", headers=self.headers
            )
            response.raise_for_status()
            spent = int(response.json().get("past_day_credits_spent") or 0)
            cutoff = time.time() - 86400
            self._reservations = [
                item for item in self._reservations if item[0] >= cutoff
            ]
            locally_reserved = sum(item[1] for item in self._reservations)
            # Atlas updates past_day_credits_spent in batches. max() avoids
            # counting the same run twice once it appears in that counter.
            projected = max(spent, locally_reserved) + estimated
            if projected > self.settings.ripe_atlas_daily_budget:
                return False
            self._reservations.append((time.time(), estimated))
            return True

    async def check(self, node, light: bool | None = None) -> dict:
        if not node.server_names:
            return {
                "verdict": Verdict.UNCERTAIN.value,
                "reason": "missing_reality_sni",
                "request_id": "ripe:not-created",
                "permanent_link": "",
                "total": 0,
                "failures": 0,
                "service_errors": 0,
                "errors": {},
            }

        sni = node.server_names[0]
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if light is None:
                light = self.settings.ripe_atlas_light_mode
            probe_ids = await self._probe_ids(client, light)
            if len(probe_ids) < self.settings.ripe_atlas_min_results:
                return {
                    "verdict": Verdict.UNCERTAIN.value,
                    "reason": "insufficient_connected_ru_probes",
                    "request_id": "ripe:not-created",
                    "permanent_link": "",
                    "total": 0,
                    "failures": 0,
                    "service_errors": 0,
                    "errors": {},
                }
            estimated = len(probe_ids) * 20
            if not await self._reserve_budget(client, estimated):
                return {
                    "verdict": Verdict.UNCERTAIN.value,
                    "reason": "ripe_daily_budget_exhausted",
                    "request_id": "ripe:not-created",
                    "permanent_link": "",
                    "total": 0,
                    "failures": 0,
                    "service_errors": 0,
                    "errors": {},
                }
            payload = build_measurement_payload(node, sni, probe_ids)
            response = await client.post(
                f"{self.settings.ripe_atlas_url}/measurements/",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            measurement_id = response.json()["measurements"][0]
            deadline = time.monotonic() + self.settings.ripe_atlas_timeout_seconds
            results = []
            while time.monotonic() < deadline:
                response = await client.get(
                    f"{self.settings.ripe_atlas_url}/measurements/{measurement_id}/results/",
                    headers=self.headers,
                )
                response.raise_for_status()
                results = response.json()
                # Monkey Island waits for the whole explicitly assigned set;
                # partial early responses can invert a 50/70% verdict.
                if len(results) >= len(probe_ids):
                    break
                await asyncio.sleep(self.settings.ripe_atlas_poll_interval_seconds)

        summary = summarize_results(results, self.settings.ripe_atlas_min_results)
        summary.update({
            "request_id": f"ripe:{measurement_id}",
            "permanent_link": f"https://atlas.ripe.net/measurements/{measurement_id}/",
            "service_errors": 0,
            "sni": sni,
            "probe_mode": "light" if light else "full",
        })
        return summary
