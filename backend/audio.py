from __future__ import annotations

import httpx


class LocalAudio:
    def __init__(self, stt_url: str, stt_model: str, tts_url: str, tts_model: str, voice: str, api_key: str):
        self.stt_url = stt_url
        self.stt_model = stt_model
        self.tts_url = tts_url
        self.tts_model = tts_model
        self.voice = voice
        self.api_key = api_key

    async def transcribe(self, data: bytes, filename: str = "audio.webm") -> str:
        if not self.stt_url:
            raise RuntimeError("STT_BASE_URL is not configured")
        if len(data) > 15_000_000:
            raise ValueError("Audio exceeds 15 MB")
        mime = "audio/wav" if filename.lower().endswith(".wav") else "audio/webm"
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{self.stt_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.stt_model},
                files={"file": (filename, data, mime)},
            )
            response.raise_for_status()
            return str(response.json().get("text", "")).strip()

    async def speak(self, text: str, response_format: str = "mp3") -> bytes:
        if not self.tts_url:
            return b""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.tts_url}/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.tts_model, "voice": self.voice, "input": text[:4000], "response_format": response_format},
            )
            response.raise_for_status()
            return response.content
