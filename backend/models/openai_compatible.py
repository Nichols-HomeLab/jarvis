from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from PIL import Image
from io import BytesIO

from backend.schemas import ScanResult


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, vision_model: str, router_model: str, research_model: str, allow_mock_vision: bool):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.vision_model = vision_model
        self.router_model = router_model
        self.research_model = research_model
        self.allow_mock_vision = allow_mock_vision

    async def analyze_snapshot(self, camera: str, zone: str, image_bytes: bytes, snapshot_path: str) -> ScanResult:
        if not self.base_url:
            raise RuntimeError("OPENAI_BASE_URL is not configured")

        with Image.open(BytesIO(image_bytes)) as picture:
            width, height = picture.size

        prompt = (
            "You are a workshop vision assistant. Analyze the image and identify visible tools or hardware.\n"
            "Return strict JSON with keys: summary, detections.\n"
            "Each detection must include label, description, box, confidence.\n"
            f"Image size is {width}x{height}. The box format is [x1, y1, x2, y2] in image pixels.\n"
            "Use an empty detections list if nothing confident is visible."
        )

        payload = {
            "model": self.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.1,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
        except Exception:
            if self.allow_mock_vision:
                return self._mock_scan(camera, zone, snapshot_path)
            raise

        parsed = self._parse_json_content(content)
        detections = []
        for candidate in parsed.get("detections", []):
            box = candidate.get("box", [])
            if len(box) != 4:
                continue
            candidate["box"] = [max(0, min(round(float(box[i])), width if i % 2 == 0 else height)) for i in range(4)]
            detections.append(candidate)
        return ScanResult(
            camera=camera,
            zone=zone,
            summary=str(parsed.get("summary", "")),
            detections=detections,
            raw_model_output=parsed,
            snapshot_path=snapshot_path,
        )

    def _parse_json_content(self, content: Any) -> dict[str, Any]:
        if isinstance(content, list):
            text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        else:
            text = str(content)

        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    async def chat(self, model: str, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.1}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])

    def _mock_scan(self, camera: str, zone: str, snapshot_path: str) -> ScanResult:
        return ScanResult(
            camera=camera,
            zone=zone,
            summary="Mock vision mode is enabled. No real detections were returned by the configured model endpoint.",
            detections=[],
            raw_model_output={"mock": True},
            snapshot_path=snapshot_path,
        )
