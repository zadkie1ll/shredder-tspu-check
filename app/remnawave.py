from typing import Any
import httpx

from .domain import Node


def _extract_node_items(payload: Any) -> list[dict]:
    current = payload
    for _ in range(5):
        if isinstance(current, list):
            return [item for item in current if isinstance(item, dict)]
        if not isinstance(current, dict):
            return []
        nested = next(
            (
                current[key]
                for key in ("nodes", "items", "response", "data")
                if key in current
            ),
            None,
        )
        if nested is None or nested is current:
            return []
        current = nested
    return []


def parse_nodes(payload: Any) -> list[Node]:
    nodes = {}
    for raw in _extract_node_items(payload):
        if any(raw.get(key) is True for key in ("is_disabled", "isDisabled")):
            continue
        address = raw.get("address") or raw.get("host") or raw.get("hostname")
        uuid = raw.get("uuid") or raw.get("id")
        if not uuid or not address:
            continue
        node = Node(
            str(uuid),
            str(raw.get("name") or raw.get("remark") or address),
            str(address).strip(),
        )
        nodes[node.uuid] = node
    return list(nodes.values())


class RemnawaveClient:
    def __init__(self, settings):
        self.settings = settings

    async def list_nodes(self) -> list[Node]:
        if not self.settings.remnawave_url or not self.settings.remnawave_api_key:
            raise RuntimeError("REMNAWAVE_URL and REMNAWAVE_API_KEY are required")

        headers = {self.settings.remnawave_auth_header: self.settings.remnawave_api_key}
        url = f"{self.settings.remnawave_url}/{self.settings.remnawave_api_path.lstrip('/')}"
        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()

        return parse_nodes(payload)
