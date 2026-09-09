from dataclasses import dataclass
from typing import Any
import httpx


@dataclass(frozen=True)
class Node:
    uuid: str
    name: str
    address: str


class RemnawaveClient:
    def __init__(self, settings):
        self.settings = settings

    async def list_nodes(self) -> list[Node]:
        if not self.settings.remnawave_url or not self.settings.remnawave_api_key:
            raise RuntimeError("REMNAWAVE_URL and REMNAWAVE_API_KEY are required")

        headers = {self.settings.remnawave_auth_header: self.settings.remnawave_api_key}
        url = f"{self.settings.remnawave_url}/{self.settings.remnawave_api_path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, list):
            raw_nodes = payload
        else:
            raw_nodes = payload.get("response", payload.get("data", payload))
            if isinstance(raw_nodes, dict):
                raw_nodes = raw_nodes.get("nodes", raw_nodes.get("items", []))

        nodes = []
        for raw in raw_nodes or []:
            if not isinstance(raw, dict) or raw.get("is_disabled") is True:
                continue
            address = raw.get("address") or raw.get("host") or raw.get("hostname")
            uuid = raw.get("uuid")
            if not uuid or not address:
                continue
            nodes.append(Node(str(uuid), str(raw.get("name") or raw.get("remark") or address), str(address)))
        return nodes

