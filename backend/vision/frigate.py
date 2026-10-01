from __future__ import annotations

import httpx


class FrigateClient:
    def __init__(self, base_url: str, token: str = "", user: str = "", password: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.user = user
        self.password = password
        self._session_token = ""

    async def _headers(self) -> dict[str, str]:
        if not self.base_url:
            raise RuntimeError("FRIGATE_URL is not configured")
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self._session_token:
            return {"Authorization": f"Bearer {self._session_token}"}
        if self.user and self.password:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"{self.base_url}/api/login", json={"user": self.user, "password": self.password})
                response.raise_for_status()
                self._session_token = response.cookies.get("frigate_token", "") or response.json().get("token", "")
            if not self._session_token:
                raise RuntimeError("Frigate login returned no token")
            return {"Authorization": f"Bearer {self._session_token}"}
        return {}

    async def _get(self, path: str) -> httpx.Response:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/api/{path}", headers=headers)
            if response.status_code == 401 and self._session_token:
                self._session_token = ""
                response = await client.get(f"{self.base_url}/api/{path}", headers=await self._headers())
            response.raise_for_status()
            return response

    async def latest_frame(self, camera: str) -> bytes:
        response = await self._get(f"{camera}/latest.jpg")
        if not response.headers.get("content-type", "").startswith("image/"):
            raise ValueError("Frigate did not return an image")
        return response.content

    async def event_snapshot(self, event_id: str) -> bytes:
        response = await self._get(f"events/{event_id}/snapshot.jpg?bbox=0")
        if not response.headers.get("content-type", "").startswith("image/"):
            raise ValueError("Frigate event has no snapshot")
        return response.content

    async def event(self, event_id: str) -> dict:
        return (await self._get(f"events/{event_id}")).json()
