import asyncio
import logging
import time

import httpx

from .domain import Verdict


log = logging.getLogger(__name__)

# Small but operator-diverse Russian set. A one-off sslcert result costs
# 20 credits, so the complete confirmation costs at most 200 credits/SNI.
LIGHT_ASN_PROBE_SPEC = (
    (12389, 2),  # Rostelecom
    (8402, 2),   # Beeline
    (8359, 2),   # MTS
    (12714, 1),  # MegaFon
    (25513, 1),  # MGTS
    (12768, 1),  # Dom.ru
    (20485, 1),  # TTK
)


def summarize_results(results: list[dict], minimum_results: int) -> dict:
    rows = [row for row in results if isinstance(row, dict)]
    ok = sum(any(key in row for key in ("cert", "method", "alert")) for row in rows)
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
        self._probe_cache: tuple[float, list[int]] | None = None
        self._budget_lock = asyncio.Lock()
        self._reserved_credits = 0

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.settings.ripe_atlas_api_key}"}

    async def _probe_ids(self, client: httpx.AsyncClient) -> list[int]:
        if self._probe_cache and time.time() - self._probe_cache[0] < 900:
            return list(self._probe_cache[1])
        ids = []
        for asn, count in LIGHT_ASN_PROBE_SPEC:
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
            self._probe_cache = (time.time(), ids)
        return ids

    async def _reserve_budget(self, client: httpx.AsyncClient, estimated: int) -> bool:
        async with self._budget_lock:
            response = await client.get(
                f"{self.settings.ripe_atlas_url}/credits/", headers=self.headers
            )
            response.raise_for_status()
            spent = int(response.json().get("past_day_credits_spent") or 0)
            if spent + self._reserved_credits + estimated > self.settings.ripe_atlas_daily_budget:
                return False
            self._reserved_credits += estimated
            return True

    async def check(self, node) -> dict:
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
            probe_ids = await self._probe_ids(client)
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
                if len(results) >= min(len(probe_ids), self.settings.ripe_atlas_min_results):
                    break
                await asyncio.sleep(self.settings.ripe_atlas_poll_interval_seconds)

        summary = summarize_results(results, self.settings.ripe_atlas_min_results)
        summary.update({
            "request_id": f"ripe:{measurement_id}",
            "permanent_link": f"https://atlas.ripe.net/measurements/{measurement_id}/",
            "service_errors": 0,
            "sni": sni,
        })
        return summary
