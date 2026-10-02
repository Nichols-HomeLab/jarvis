from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.homebox import HomeboxClient
from backend.tools import HomeAssistant, WebSearch
from backend.models.openai_compatible import OpenAICompatibleClient
from backend.projector.hub import ProjectorHub
from backend.schemas import (
    AssistantCommandRequest,
    CommandResponse,
    DetectionBox,
    DimensionRequest,
    IdentificationResult,
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
        web_search: WebSearch | None = None,
        home_assistant: HomeAssistant | None = None,
        homebox: HomeboxClient | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.cameras = cameras
        self.model_client = model_client
        self.projector_hub = projector_hub
        self.web_search = web_search or WebSearch(settings.search_url)
        self.home_assistant = home_assistant or HomeAssistant(settings.home_assistant_url, settings.home_assistant_token, settings.ha_allowed_entities, settings.ha_dangerous_domains)
        self.homebox = homebox or HomeboxClient(settings.homebox_url, settings.homebox_api_key)
        self.pending_actions: dict[str, tuple[float, str, str]] = {}

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
        scan.detections = [
            detection for detection in scan.detections
            if detection.confidence >= self.settings.min_detection_confidence
        ]
        self.storage.save_scan(scan)
        self.storage.link_homebox_scan(scan)
        return scan

    async def sync_homebox(self) -> dict[str, int]:
        entities = await self.homebox.inventory()
        return {"entities": self.storage.replace_homebox_inventory(entities)}

    async def identify_camera(self, camera_name: str, target: str = "") -> IdentificationResult:
        scan = await self.scan_camera(camera_name)
        detections = [
            item for item in scan.detections
            if not target or target.lower() in f"{item.label} {item.description}".lower()
        ]
        if not detections:
            return IdentificationResult(
                camera=camera_name, query=target, scan=scan,
                assessment="I could not identify a matching object in this snapshot.",
            )
        detection = max(detections, key=lambda item: item.confidence)
        query = f"{detection.description or detection.label} tool identification".strip()
        matches = await self.web_search.image_search(query)
        references = "\n".join(f"{item['title']} [{item['url']}]" for item in matches[:5])
        assessment = await self.model_client.chat(self.settings.research_model, [
            {"role": "system", "content": "Assess a tentative workshop object identification using only the visual description and web result titles. Do not claim the web images were visually compared. Be brief, label uncertainty, and include a source URL if useful."},
            {"role": "user", "content": f"Camera detection: {detection.label}; description: {detection.description}; confidence: {detection.confidence:.2f}. Web results:\n{references or 'none'}"},
        ])
        return IdentificationResult(
            camera=camera_name, query=query, assessment=assessment, scan=scan, image_matches=matches,
        )

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
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def project_card(self, request: ProjectCardRequest) -> None:
        await self.projector_hub.broadcast(
            {
                "type": "show_card",
                "title": request.title,
                "content": request.content,
                "kind": request.kind,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def project_dimensions(self, request: DimensionRequest) -> None:
        await self.projector_hub.broadcast({
            "type": "show_dimensions", **request.model_dump(),
            "calibrated_width_mm": self.settings.projector_width_mm,
            "calibrated_height_mm": self.settings.projector_height_mm,
        })

    async def confirm_action(self, token: str) -> CommandResponse:
        pending = self.pending_actions.pop(token, None)
        if pending is None or pending[0] < time.monotonic():
            return CommandResponse(text="That confirmation expired. Please request the action again.", route="confirmation_expired")
        _, entity_id, action = pending
        await self.home_assistant.call(entity_id, action)
        return CommandResponse(text=f"I sent {action} to {entity_id}.", route="home_assistant_action")

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
                actor=None,
                confidence=detection.confidence,
                snapshot_path=before.snapshot_path,
                last_seen_at=before.analyzed_at,
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
                actor=None,
                confidence=detection.confidence,
                snapshot_path=after.snapshot_path,
                last_seen_at=after.analyzed_at,
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

        contents_match = re.search(r"(?:what(?:'s| is) in|what do i have in|show contents of) (?:my |the )?(.+?)[?.!]*$", lowered)
        if contents_match:
            target = contents_match.group(1).rstrip(" ?.! ")
            box = self.storage.find_homebox(target, location_only=True)
            if box is None:
                return CommandResponse(text=f"Homebox has no synced box or location matching {target}.", route="homebox_contents")
            contents = self.storage.homebox_contents(box["entity_id"])
            names = ", ".join(item["name"] for item in contents if not item["is_location"])
            camera_note = ""
            if box.get("visual_sighting"):
                sighting = box["visual_sighting"]
                camera_note = f" I tentatively matched its label on {sighting['camera']} in {sighting['zone']}."
            return CommandResponse(
                text=f"Homebox lists {names or 'no items'} in {box['path']}.{camera_note} Contents are inventory data, not camera-confirmed.",
                route="homebox_contents",
            )

        if lowered.startswith(("identify ", "what is this", "what's this")):
            camera_name = next((camera.name for camera in self.cameras.list_cameras() if camera.name in lowered), None)
            camera_name = camera_name or ("workbench" if any(camera.name == "workbench" for camera in self.cameras.list_cameras()) else None)
            if camera_name is None:
                return CommandResponse(text="No camera is configured for identification.", route="camera_identification_error")
            try:
                result = await self.identify_camera(camera_name)
                return CommandResponse(text=result.assessment, route="camera_identification", scan_result=result.scan)
            except Exception as exc:
                return CommandResponse(text=f"Camera identification failed: {exc}", route="camera_identification_error")

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

        location_match = re.search(r"where (?:are|is) (?:my |the )?(.+?)[?.!]*$", lowered)
        if location_match:
            target = location_match.group(1).rstrip(" ?.! ")
            result = self.search_tool_memory(target)
            if result is None:
                inventory = self.storage.find_homebox(target)
                if inventory is not None:
                    sighting = inventory.get("visual_sighting")
                    camera_note = f" A vision scan tentatively matched its label in {sighting['zone']} on {sighting['camera']}." if sighting else " I do not have a camera-confirmed sighting."
                    return CommandResponse(
                        text=f"Homebox lists {inventory['name']} at {inventory['path']}.{camera_note}",
                        route="homebox_search",
                    )
                return CommandResponse(
                    text=f"I do not have a later sighting for {target}.",
                    route="tool_memory_search",
                )

            projector_sent = False
            if request.project_result and result.action != "lost_after_motion" and result.snapshot_path and result.bbox:
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

            when = result.last_seen_at.astimezone(timezone.utc).strftime("%I:%M %p UTC").lstrip("0")
            if result.action == "lost_after_motion":
                return CommandResponse(
                    text=f"I last saw {result.object_name} on {result.camera_name} at {when}. It was not detected in a later snapshot after motion. I cannot tell where it went.",
                    route="tool_memory_search", search_result=result,
                )
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
            target = lowered.split("show me where ", 1)[1].removeprefix("the ").removeprefix("my ").rstrip(" ?.")
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

        if lowered.startswith("remember ") and " is on " in lowered:
            divider = lowered.index(" is on ")
            object_name, zone = text[9:divider], text[divider + 7:]
            self.record_manual_memory(object_name.strip(), object_name.strip().lower(), "manual", zone.strip().rstrip("."))
            return CommandResponse(text=f"I recorded {object_name.strip()} on {zone.strip()}.", route="manual_memory")

        try:
            route = await self._route(text)
        except Exception as exc:
            return CommandResponse(text=f"The local router is unavailable: {exc}", route="router_error")

        intent = route.get("intent")
        if intent in {"research", "research_project"}:
            try:
                sources = await self.web_search.search(str(route.get("query") or text))
                if not sources:
                    return CommandResponse(text="The search returned no results.", route="research")
                context = "\n".join(f"{item['title']}: {item['snippet']} [{item['url']}]" for item in sources)
                if intent == "research_project":
                    raw = await self.model_client.chat(self.settings.research_model, [
                        {"role": "system", "content": "Use only cited search snippets. Return JSON: title, width_mm, depth_mm, height_mm, summary, source. Use 0 for dimensions that cannot be verified."},
                        {"role": "user", "content": f"Request: {text}\nSources:\n{context}"},
                    ], json_mode=True)
                    details = json.loads(raw)
                    if float(details.get("width_mm", 0)) <= 0 or float(details.get("depth_mm", 0)) <= 0:
                        return CommandResponse(text="I found search results but could not verify both dimensions, so I cannot project a footprint.", route="research_project")
                    dimension = DimensionRequest(
                        title=str(details.get("title") or text), width_mm=float(details["width_mm"]),
                        depth_mm=float(details["depth_mm"]), height_mm=float(details["height_mm"]) if details.get("height_mm") else None,
                        source=str(details.get("source") or sources[0]["url"]),
                    )
                    await self.project_dimensions(dimension)
                    return CommandResponse(text=f"{details.get('summary', dimension.title)} I am showing the footprint now.", route="research_project", projector_event_sent=True)
                answer = await self.model_client.chat(self.settings.research_model, [
                    {"role": "system", "content": "Answer briefly using only the supplied search snippets. Include a source URL. Say when evidence is insufficient."},
                    {"role": "user", "content": f"{text}\n{context}"},
                ])
                return CommandResponse(text=answer, route="research")
            except Exception as exc:
                return CommandResponse(text=f"Research failed: {exc}", route="research_error")

        if intent in {"ha_read", "ha_action"}:
            entity_id = str(route.get("entity_id", ""))
            action = str(route.get("service", ""))
            try:
                if intent == "ha_read":
                    state = await self.home_assistant.state(entity_id)
                    return CommandResponse(text=f"{entity_id} is {state.get('state', 'unknown')}.", route="home_assistant_read")
                self.home_assistant.validate(entity_id, action)
                if self.home_assistant.needs_confirmation(entity_id, action):
                    token = secrets.token_urlsafe(12)
                    self.pending_actions[token] = (time.monotonic() + 60, entity_id, action)
                    return CommandResponse(text=f"Confirm {action} on {entity_id} within 60 seconds.", route="confirmation_required", confirmation_token=token)
                await self.home_assistant.call(entity_id, action)
                return CommandResponse(text=f"I sent {action} to {entity_id}.", route="home_assistant_action")
            except Exception as exc:
                return CommandResponse(text=f"Home Assistant action failed: {exc}", route="home_assistant_error")

        if intent == "conversation":
            answer = await self.model_client.chat(self.settings.research_model, [
                {"role": "system", "content": "You are Jarvis, a concise workshop assistant. Do not claim to have used tools or seen cameras unless a tool result is present."},
                {"role": "user", "content": text},
            ])
            return CommandResponse(text=answer, route="conversation")

        return CommandResponse(
            text="I do not have an MVP command route for that yet.",
            route="unhandled",
        )

    async def _route(self, text: str) -> dict[str, str]:
        entities = sorted(self.settings.ha_allowed_entities)
        prompt = (
            "Classify this request. Return only JSON with intent, query, entity_id, service. "
            "Allowed intents: conversation, research, research_project, ha_read, ha_action. "
            "Use research_project only for requested dimensions or projection. "
            "Use ha_* only for an exact entity from this allowlist: " + ", ".join(entities) + ". "
            "Do not invent entities. Allowed services: turn_on, turn_off, toggle, set_temperature, open_cover, close_cover, lock, unlock."
        )
        raw = await self.model_client.chat(self.settings.router_model, [
            {"role": "system", "content": prompt}, {"role": "user", "content": text},
        ], json_mode=True)
        route = json.loads(raw)
        if route.get("intent") not in {"conversation", "research", "research_project", "ha_read", "ha_action"}:
            return {"intent": "conversation"}
        return route

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
        relative = Path(snapshot_path).resolve().relative_to(self.settings.media_root.resolve())
        return f"/media/{relative.as_posix()}"
