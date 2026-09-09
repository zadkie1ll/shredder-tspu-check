import asyncio
from collections import Counter

import httpx


class CheckHostClient:
    def __init__(self, settings):
        self.settings = settings

    async def check(self, address: str) -> dict:
        target = f"{address}:{self.settings.checkhost_port}"
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        async with httpx.AsyncClient(
            base_url=self.settings.checkhost_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        ) as client:
            start = await client.get(
                f"/check-{self.settings.checkhost_type}",
                params={"host": target, "max_nodes": self.settings.checkhost_max_nodes},
            )
            start.raise_for_status()
            request = start.json()
            request_id = request.get("request_id")
            if not request_id:
                raise RuntimeError("Check-Host did not return request_id")
            result = await self._wait_for_result(client, request_id)
            return self._summarize(target, request, result)

    async def _wait_for_result(self, client: httpx.AsyncClient, request_id: str) -> dict:
        deadline = asyncio.get_running_loop().time() + self.settings.checkhost_timeout_seconds
        last = {}
        while asyncio.get_running_loop().time() < deadline:
            response = await client.get(f"/check-result/{request_id}")
            response.raise_for_status()
            last = response.json()
            if last and all(value is not None for value in last.values()):
                return last
            await asyncio.sleep(self.settings.checkhost_poll_interval_seconds)
        return last

    def _summarize(self, target: str, request: dict, raw: dict) -> dict:
        nodes = request.get("nodes", {})
        observations = []
        for checker, value in raw.items():
            meta = nodes.get(checker, [])
            country = meta[1] if len(meta) > 1 else meta[0] if meta else "Unknown"
            item = value[0] if isinstance(value, list) and value else None
            error = item.get("error") if isinstance(item, dict) else "No result"
            reachable = isinstance(item, dict) and (
                not error or error.lower() in {"connection refused", "open or filtered"}
            )
            observations.append({
                "checker": checker,
                "country": country,
                "ok": reachable,
                "reachable": reachable,
                "service_error": bool(error and error.lower() == "connection refused"),
                "error": error,
                "time": item.get("time") if isinstance(item, dict) else None,
            })

        total = len(observations)
        failures = sum(1 for item in observations if not item["reachable"])
        service_errors = sum(1 for item in observations if item["service_error"])
        ratio = failures / total if total else 1.0
        if total == 0:
            verdict = "uncertain"
        elif ratio >= self.settings.checkhost_failure_ratio and total >= 3:
            verdict = "blocked"
        else:
            # Refused proves that the IP is reachable; it is not a TSPU block.
            verdict = "clean"

        if failures:
            transport_state = "timeout_or_network_error"
        elif service_errors:
            transport_state = "service_refused"
        else:
            transport_state = "available"

        return {
            "target": target,
            "verdict": verdict,
            "transport_state": transport_state,
            "request_id": request.get("request_id"),
            "permanent_link": request.get("permanent_link"),
            "total": total,
            "failures": failures,
            "service_errors": service_errors,
            "failure_ratio": round(ratio, 3),
            "errors": dict(Counter(item["error"] for item in observations if item["error"])),
            "observations": observations,
        }
