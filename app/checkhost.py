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
            normalized_error = error.lower() if isinstance(error, str) else "no result"
            is_refused = normalized_error == "connection refused"
            is_timeout = not isinstance(item, dict) or any(
                marker in normalized_error
                for marker in ("timeout", "timed out", "no result")
            )
            observations.append({
                "checker": checker,
                "country": country,
                "ok": reachable,
                "reachable": reachable,
                "service_error": is_refused,
                "is_timeout": is_timeout,
                "error": error,
                "time": item.get("time") if isinstance(item, dict) else None,
            })

        selected = [
            item for item in observations
            if any(target in item["country"].lower() for target in self.settings.checkhost_geo_targets)
        ]
        selected_timeouts = sum(1 for item in selected if item["is_timeout"])
        selected_refused = sum(1 for item in selected if item["service_error"])
        selected_total = len(selected)
        missing_targets = [
            target for target in self.settings.checkhost_geo_targets
            if not any(target in item["country"].lower() for item in observations)
        ]

        # A timeout from any monitored geo is a block. Refused means the IP is
        # reachable and is therefore not a TSPU block.
        if not selected:
            verdict = "uncertain"
        elif selected_timeouts:
            verdict = "blocked"
        else:
            verdict = "clean"

        total = selected_total
        failures = selected_timeouts
        service_errors = selected_refused
        ratio = failures / total if total else 1.0

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
            "selected_geo_targets": list(self.settings.checkhost_geo_targets),
            "missing_geo_targets": missing_targets,
            "all_observations": len(observations),
            "errors": dict(Counter(item["error"] for item in observations if item["error"])),
            "observations": observations,
        }
