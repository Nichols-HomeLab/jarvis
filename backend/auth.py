from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlsplit

from fastapi import Request, WebSocket


COOKIE_NAME = "jarvis_session"


class SessionGate:
    def __init__(self, token: str, origins: list[str]):
        if len(token) < 32 or token.startswith("replace-"):
            raise ValueError("JARVIS_ACCESS_TOKEN must be a unique random value of at least 32 characters")
        self.token = token
        self.cookie_value = hashlib.sha256(("jarvis-session-v1:" + token).encode()).hexdigest()
        self.origins = {origin.rstrip("/") for origin in origins if origin != "*"}

    def authenticated(self, cookie: str | None) -> bool:
        return bool(cookie) and secrets.compare_digest(cookie, self.cookie_value)

    def valid_origin(self, origin: str | None, host: str) -> bool:
        if not origin:
            return True
        parsed = urlsplit(origin)
        return origin.rstrip("/") in self.origins or (parsed.scheme in {"http", "https"} and parsed.netloc == host)

    def valid_request(self, request: Request) -> bool:
        return self.authenticated(request.cookies.get(COOKIE_NAME))

    def valid_socket(self, websocket: WebSocket) -> bool:
        return self.authenticated(websocket.cookies.get(COOKIE_NAME)) and self.valid_origin(
            websocket.headers.get("origin"), websocket.headers.get("host", "")
        )
