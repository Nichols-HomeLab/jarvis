from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx


class WebSearch:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url
        self.transport = transport

    async def search(self, query: str) -> list[dict[str, str]]:
        if not self.base_url:
            raise RuntimeError("SEARXNG_URL is not configured")
        async with httpx.AsyncClient(timeout=20.0, transport=self.transport) as client:
            response = await client.get(f"{self.base_url}/search", params={"q": query, "format": "json"})
            response.raise_for_status()
        results = []
        for item in response.json().get("results", [])[:5]:
            url = str(item.get("url", ""))
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            results.append({"title": str(item.get("title", ""))[:200], "snippet": str(item.get("content", ""))[:600], "url": url})
        return results

    async def image_search(self, query: str) -> list[dict[str, str]]:
        if not self.base_url:
            raise RuntimeError("SEARXNG_URL is not configured")
        async with httpx.AsyncClient(timeout=20.0, transport=self.transport) as client:
            response = await client.get(
                f"{self.base_url}/search",
                params={"q": query, "categories": "images", "format": "json"},
            )
            response.raise_for_status()
        matches = []
        for item in response.json().get("results", [])[:8]:
            page_url = str(item.get("url") or "")
            image_url = str(item.get("img_src") or item.get("thumbnail_src") or "")
            if urlparse(page_url).scheme not in {"http", "https"}:
                continue
            if image_url and urlparse(image_url).scheme not in {"http", "https"}:
                image_url = ""
            matches.append({"title": str(item.get("title") or "")[:200], "url": page_url, "image_url": image_url})
        return matches


class HomeAssistant:
    def __init__(self, base_url: str, token: str, allowed_entities: list[str], dangerous_domains: list[str]):
        self.base_url = base_url
        self.token = token
        self.allowed_entities = set(allowed_entities)
        self.dangerous_domains = set(dangerous_domains)

    def validate(self, entity_id: str, service: str) -> None:
        if not self.base_url or not self.token:
            raise RuntimeError("Home Assistant is not configured")
        if entity_id not in self.allowed_entities:
            raise ValueError(f"Entity {entity_id} is not in HA_ALLOWED_ENTITIES")
        if not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", entity_id) or not re.fullmatch(r"[a-z_]+", service):
            raise ValueError("Invalid entity or service")

    async def state(self, entity_id: str) -> dict:
        self.validate(entity_id, "read")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            return response.json()

    async def call(self, entity_id: str, service: str, data: dict | None = None) -> list[dict]:
        self.validate(entity_id, service)
        domain = entity_id.split(".", 1)[0]
        if service not in {"turn_on", "turn_off", "toggle", "set_temperature", "open_cover", "close_cover", "lock", "unlock"}:
            raise ValueError("Service is not allowed")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"entity_id": entity_id, **(data or {})},
            )
            response.raise_for_status()
            return response.json()

    def needs_confirmation(self, entity_id: str, service: str) -> bool:
        return entity_id.split(".", 1)[0] in self.dangerous_domains or service in {"unlock", "open_cover", "set_temperature"}
