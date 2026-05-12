from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.models.openai_compatible import OpenAICompatibleClient
from backend.projector.hub import ProjectorHub
from backend.schemas import (
    AssistantCommandRequest,
    CommandResponse,
    DetectionBox,
    ObjectMemoryRecord,
    ProjectBoundingBoxRequest,
    ProjectCardRequest,
    ScanResult,
)
from backend.storage import Storage
from backend.vision.camera_manager import CameraManager


class JarvisLocalService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        cameras: CameraManager,
        model_client: OpenAICompatibleClient,
        projector_hub: ProjectorHub,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.cameras = cameras
        self.model_client = model_client
        self.projector_hub = projector_hub

    async def scan_camera(self, camera_name: str) -> ScanResult:
        snapshot = await self.cameras.capture_snapshot(camera_name)
        camera = self.cameras.get_camera(camera_name)
        image_bytes = Path(snapshot.snapshot_path).read_bytes()
        scan = await self.model_client.analyze_snapshot(
            camera=camera_name,
            zone=camera.zone_name,
            image_bytes=image_bytes,
            snapshot_path=self._public_media_path(snapshot.snapshot_path),
        )
        self.storage.save_scan(scan)
        return scan

    def search_tool_memory(self, query: str):
        return self.storage.find_last_seen(query)

    async def project_bounding_box(self, request: ProjectBoundingBoxRequest) -> None:
        await self.projector_hub.broadcast(
            {
                "type": "show_bounding_box",
                "camera": request.camera,
                "image": request.image,
                "title": request.title,
                "boxes": [box.model_dump() for box in request.boxes],
                "sent_at": datetime.utcnow().isoformat(),
            }
        )

    async def project_card(self, request: ProjectCardRequest) -> None:
        await self.projector_hub.broadcast(
            {
                "type": "show_card",
                "title": request.title,
                "content": request.content,
                "kind": request.kind,
                "sent_at": datetime.utcnow().isoformat(),
            }
        )

    async def handle_motion_event(self, camera_name: str, before_delay_seconds: int = 3, after_delay_seconds: int = 5) -> dict[str, Any]:
        before = await self.scan_camera(camera_name)
        await asyncio.sleep(before_delay_seconds)
        during = await self.scan_camera(camera_name)
        await asyncio.sleep(after_delay_seconds)
        after = await self.scan_camera(camera_name)

        before_labels = {item.label.lower(): item for item in before.detections}
        after_labels = {item.label.lower(): item for item in after.detections}
        changes: list[dict[str, Any]] = []

        disappeared = sorted(set(before_labels) - set(after_labels))
        appeared = sorted(set(after_labels) - set(before_labels))

        for label in disappeared:
            detection = before_labels[label]
            memory = ObjectMemoryRecord(
                object_name=detection.description or detection.label,
                object_category=detection.label,
                description=detection.description,
                camera_name=before.camera,
                zone_name=before.zone,
                action="lost_after_motion",
                actor=self.settings.default_actor_name,
                confidence=detection.confidence,
                snapshot_path=before.snapshot_path,
                last_seen_at=datetime.utcnow(),
                raw_model_output={"motion_compare": "disappeared"},
            )
            self.storage.save_memory(memory)
            changes.append(
                {
                    "label": detection.label,
                    "description": detection.description,
                    "change": "disappeared",
                }
            )

        for label in appeared:
            detection = after_labels[label]
            memory = ObjectMemoryRecord(
                object_name=detection.description or detection.label,
                object_category=detection.label,
                description=detection.description,
                camera_name=after.camera,
                zone_name=after.zone,
                action="appeared_after_motion",
                actor=self.settings.default_actor_name,
                confidence=detection.confidence,
                snapshot_path=after.snapshot_path,
                last_seen_at=datetime.utcnow(),
                raw_model_output={"motion_compare": "appeared"},
            )
            self.storage.save_memory(memory)
            changes.append(
                {
                    "label": detection.label,
                    "description": detection.description,
                    "change": "appeared",
                }
            )

        return {
            "camera": camera_name,
            "before": before.model_dump(),
            "during": during.model_dump(),
            "after": after.model_dump(),
            "changes": changes,
        }

    async def handle_command(self, request: AssistantCommandRequest) -> CommandResponse:
        text = request.text.strip()
        lowered = text.lower()

        if "scan the pegboard" in lowered:
            scan = await self.scan_camera("pegboard")
            return CommandResponse(
                text=f"I scanned the pegboard and recorded {len(scan.detections)} detections.",
                route="scan_pegboard",
                scan_result=scan,
            )

        if "scan the workbench" in lowered or "scan my workbench" in lowered:
            scan = await self.scan_camera("workbench")
            return CommandResponse(
                text=f"I scanned the workbench and recorded {len(scan.detections)} detections.",
                route="scan_workbench",
                scan_result=scan,
            )

        if "where are my " in lowered:
            target = lowered.split("where are my ", 1)[1].rstrip(" ?.")
            result = self.search_tool_memory(target)
            if result is None:
                return CommandResponse(
                    text=f"I do not have a later sighting for {target}.",
                    route="tool_memory_search",
                )

            projector_sent = False
            if request.project_result and result.snapshot_path and result.bbox:
                await self.project_bounding_box(
                    ProjectBoundingBoxRequest(
                        camera=result.camera_name,
                        image=result.snapshot_path,
                        title=f"Last seen: {result.object_name}",
                        boxes=[
                            DetectionBox(
                                label=result.object_category,
                                description=result.description or result.object_name,
                                box=result.bbox,
                                confidence=result.confidence,
                            )
                        ],
                    )
                )
                projector_sent = True

            when = result.last_seen_at.strftime("%I:%M %p").lstrip("0")
            return CommandResponse(
                text=(
                    f"I last saw {result.object_name} on the {result.camera_name} camera in {result.zone_name} "
                    f"at {when}.{' I am showing it now.' if projector_sent else ''}"
                ),
                route="tool_memory_search",
                projector_event_sent=projector_sent,
                search_result=result,
            )

        if lowered.startswith("show me where "):
            target = lowered.split("show me where ", 1)[1].rstrip(" ?.")
            result = self.search_tool_memory(target)
            if result is None or not result.snapshot_path or not result.bbox:
                return CommandResponse(
                    text=f"I do not have a projector-ready sighting for {target}.",
                    route="project_bounding_box",
                )

            await self.project_bounding_box(
                ProjectBoundingBoxRequest(
                    camera=result.camera_name,
                    image=result.snapshot_path,
                    title=f"Last seen: {result.object_name}",
                    boxes=[
                        DetectionBox(
                            label=result.object_category,
                            description=result.description or result.object_name,
                            box=result.bbox,
                            confidence=result.confidence,
                        )
                    ],
                )
            )
            return CommandResponse(
                text=f"I am showing {result.object_name} from the latest sighting.",
                route="project_bounding_box",
                projector_event_sent=True,
                search_result=result,
            )

        return CommandResponse(
            text="I do not have an MVP command route for that yet.",
            route="unhandled",
        )

    def record_manual_memory(
        self,
        object_name: str,
        object_category: str,
        camera_name: str,
        zone_name: str,
        description: str = "",
        confidence: float = 1.0,
        snapshot_path: str | None = None,
    ) -> None:
        self.storage.save_memory(
            ObjectMemoryRecord(
                object_name=object_name,
                object_category=object_category,
                description=description,
                camera_name=camera_name,
                zone_name=zone_name,
                action="remembered",
                actor=self.settings.default_actor_name,
                confidence=confidence,
                snapshot_path=snapshot_path,
            )
        )

    def _public_media_path(self, snapshot_path: str) -> str:
        normalized = snapshot_path.replace("\\", "/")
        marker = "data/media/"
        if marker in normalized:
            suffix = normalized.split(marker, 1)[1]
            return f"/media/{suffix}"
        if normalized.startswith("media/"):
            return f"/{normalized}"
        return normalized
