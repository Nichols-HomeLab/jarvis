from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class HomeboxEntity:
    entity_id: str
    name: str
    description: str
    parent_id: str | None
    is_location: bool
    quantity: int


class HomeboxClient:
    """Read-only Homebox v0.26+ inventory adapter."""

    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def inventory(self) -> list[HomeboxEntity]:
        if not self.configured:
            raise RuntimeError("HOMEBOX_URL and HOMEBOX_API_KEY are required")
        entities: list[HomeboxEntity] = []
        async with httpx.AsyncClient(timeout=20.0, transport=self.transport) as client:
            for is_location in (True, False):
                for page in range(1, 101):
                    response = await client.get(
                        f"{self.base_url}/api/v1/entities",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        params={"isLocation": str(is_location).lower(), "page": page, "pageSize": 200},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                        raise ValueError("Unexpected Homebox entities response")
                    for raw in payload["items"]:
                        parent = raw.get("parent") or {}
                        entity_type = raw.get("entityType") or {}
                        entity_id = str(raw.get("id") or "")
                        name = str(raw.get("name") or "").strip()
                        if not entity_id or not name:
                            continue
                        entities.append(HomeboxEntity(
                            entity_id=entity_id,
                            name=name,
                            description=str(raw.get("description") or ""),
                            parent_id=str(parent.get("id")) if isinstance(parent, dict) and parent.get("id") else None,
                            is_location=bool(entity_type.get("isLocation", is_location)),
                            quantity=int(raw.get("quantity") or 0),
                        ))
                    if page * int(payload.get("pageSize") or 200) >= int(payload.get("total") or 0):
                        break
                else:
                    raise RuntimeError("Homebox inventory exceeds 100 pages")
        return entities
