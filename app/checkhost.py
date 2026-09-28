import asyncio
from collections import Counter

import httpx

from .domain import Verdict


def _matches(country: str, targets: tuple[str, ...]) -> bool:
    normalized = country.lower()
    return any(target in normalized for target in targets)


def classify_observations(
    observations: list[dict],
    ru_targets: tuple[str, ...],
    control_targets: tuple[str, ...],
) -> tuple[Verdict, str]:
    """Classify only evidence that distinguishes filtering from an outage."""
    ru = [item for item in observations if _matches(item["country"], ru_targets)]
    controls = [
        item for item in observations if _matches(item["country"], control_targets)
    ]
    if not ru:
        return Verdict.UNCERTAIN, "no_ru_probes"
    if any(item["reachable"] for item in ru):
        return Verdict.CLEAN, "ru_reachable"
    if not controls:
        return Verdict.UNCERTAIN, "no_control_probes"
    if all(item["is_timeout"] for item in ru) and any(
        item["reachable"] for item in controls
    ):
        return Verdict.BLOCKED, "ru_timeout_control_reachable"
    return Verdict.UNCERTAIN, "insufficient_evidence"


class CheckHostClient:
    def __init__(self, settings):
        self.settings = settings

    async def check(self, address: str, port: int | None = None) -> dict:
        target = f"{address}:{port or self.settings.checkhost_port}"
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

    async def _wait_for_result(
        self, client: httpx.AsyncClient, request_id: str
    ) -> dict:
        deadline = (
            asyncio.get_running_loop().time() + self.settings.checkhost_timeout_seconds
        )
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
        raw = raw if isinstance(raw, dict) else {}
        nodes = request.get("nodes", {})
        observations = []
        for checker in dict.fromkeys([*nodes, *raw]):
            value = raw.get(checker)
            meta = nodes.get(checker, [])
            country = meta[1] if len(meta) > 1 else meta[0] if meta else "Unknown"
            item = value[0] if isinstance(value, list) and value else None
            error = item.get("error") if isinstance(item, dict) else "No result"
            normalized_error = error.lower() if isinstance(error, str) else ""
            is_refused = normalized_error == "connection refused"
            reachable = isinstance(item, dict) and (not error or is_refused)
            is_timeout = isinstance(item, dict) and any(
                marker in normalized_error for marker in ("timeout", "timed out")
            )
            observations.append(
                {
                    "checker": checker,
                    "country": country,
                    "ok": reachable,
                    "reachable": reachable,
                    "service_error": is_refused,
                    "is_timeout": is_timeout,
                    "error": error,
                    "time": item.get("time") if isinstance(item, dict) else None,
                }
            )

        verdict, reason = classify_observations(
            observations,
            self.settings.checkhost_ru_targets,
            self.settings.checkhost_control_targets,
        )
        selected = [
            item
            for item in observations
            if _matches(
                item["country"],
                self.settings.checkhost_ru_targets
                + self.settings.checkhost_control_targets,
            )
        ]
        total = len(selected)
        failures = sum(1 for item in selected if item["is_timeout"])
        service_errors = sum(1 for item in selected if item["service_error"])
        ratio = failures / total if total else 1.0

        if failures:
            transport_state = "timeout_or_network_error"
        elif service_errors:
            transport_state = "service_refused"
        else:
            transport_state = "available"

        return {
            "target": target,
            "verdict": verdict.value,
            "reason": reason,
            "transport_state": transport_state,
            "request_id": request.get("request_id"),
            "permanent_link": request.get("permanent_link"),
            "total": total,
            "failures": failures,
            "service_errors": service_errors,
            "failure_ratio": round(ratio, 3),
            "ru_targets": list(self.settings.checkhost_ru_targets),
            "control_targets": list(self.settings.checkhost_control_targets),
            "all_observations": len(observations),
            "errors": dict(
                Counter(item["error"] for item in observations if item["error"])
            ),
            "observations": observations,
        }
