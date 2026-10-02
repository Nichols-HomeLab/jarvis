from __future__ import annotations

import logging
from io import BytesIO

import httpx
from PIL import Image
from backend.schemas import DetectionBox, ScanResult

TOOL_LABELS = [
    "pliers", "needle nose pliers", "locking pliers", "diagonal cutters", "wire strippers",
    "adjustable wrench", "combination wrench", "ratchet", "screwdriver", "drill",
    "impact driver", "impact wrench", "circular saw", "reciprocating saw", "jigsaw",
    "angle grinder", "oscillating tool", "leaf blower", "string trimmer", "hedge trimmer",
    "chainsaw", "pressure washer", "storage box", "storage bin",
]


class DetectorVision:
    """Localise with a dedicated detector; refine each crop without moving its box."""
    def __init__(self, settings, model_client, transport=None):
        self.settings, self.model_client, self.transport = settings, model_client, transport

    async def analyze_snapshot(self, camera, zone, image_bytes, snapshot_path):
        config = next(c for c in self.settings.cameras if c.name == camera)
        labels = config.detection_labels or TOOL_LABELS
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
            response = await client.post(self.settings.detector_url + "/detect",
                files={"file": ("frame.jpg", image_bytes, "image/jpeg")},
                data={"labels": " . ".join(labels), "mode": self.settings.detector_mode,
                      "threshold": str(self.settings.detector_threshold)})
            response.raise_for_status()
            payload = response.json()
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            detections = []
            for raw in payload["detections"]:
                item = DetectionBox.model_validate(raw)
                item.box = [max(0, min(v, width if i%2 == 0 else height)) for i,v in enumerate(item.box)]
                if item.box[2] <= item.box[0] or item.box[3] <= item.box[1]:
                    continue
                detections.append(item)
            for item in sorted(detections, key=lambda x: x.confidence, reverse=True)[:self.settings.crop_identification_limit]:
                crop = image.crop(item.box).convert("RGB")
                crop.thumbnail((768, 768))
                data = BytesIO(); crop.save(data, "JPEG")
                try:
                    assessment = await self.model_client.describe_crop(data.getvalue(), item.label)
                    if assessment:
                        item.description = assessment
                except Exception:
                    logging.getLogger(__name__).exception("Crop identification unavailable; keeping detector label")
        return ScanResult(camera=camera, zone=zone, snapshot_path=snapshot_path,
            detections=detections, image_width=width, image_height=height,
            detector=self.settings.detector_mode, summary=f"{len(detections)} objects detected",
            raw_model_output=payload)
