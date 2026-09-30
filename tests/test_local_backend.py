import asyncio
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image
from backend.auth import SessionGate

from backend.config import CameraConfig, Settings
from backend.projector.hub import ProjectorHub
from backend.schemas import AssistantCommandRequest, DetectionBox, ScanResult
from backend.service import JarvisLocalService
from backend.storage import Storage
from backend.vision.camera_manager import CameraManager
from backend.vision.mqtt_events import completed_event_id


class FakeFrigate:
    async def latest_frame(self, camera):
        image = Image.new("RGB", (800, 600), "gray")
        output = BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()


class FakeVision:
    async def analyze_snapshot(self, camera, zone, image_bytes, snapshot_path):
        return ScanResult(
            camera=camera,
            zone=zone,
            snapshot_path=snapshot_path,
            summary="Screwdrivers on pegboard",
            detections=[DetectionBox(label="screwdriver", description="red screwdriver set", box=[40, 20, 110, 210], confidence=0.9)],
        )


class FakeModel(FakeVision):
    def __init__(self, route):
        self.route = route

    async def chat(self, model, messages, json_mode=False):
        if model == "router":
            return json.dumps(self.route)
        return json.dumps({
            "title": "Server", "width_mm": 430, "depth_mm": 700, "height_mm": 44,
            "summary": "Approximate 1U chassis", "source": "https://example.com/dimensions",
        })


class FakeSearch:
    async def search(self, query):
        return [{"title": "Dimensions", "snippet": "430 mm wide, 700 mm deep", "url": "https://example.com/dimensions"}]


class FakeHA:
    def __init__(self):
        self.calls = []

    def validate(self, entity_id, service):
        if entity_id != "switch.homelab":
            raise ValueError("Not allowed")

    def needs_confirmation(self, entity_id, service):
        return True

    async def call(self, entity_id, service):
        self.calls.append((entity_id, service))


class LocalFlowTests(unittest.TestCase):
    def test_session_gate(self):
        gate = SessionGate("a" * 40, ["http://localhost:5173"])
        self.assertFalse(gate.authenticated(None))
        self.assertTrue(gate.authenticated(gate.cookie_value))
        self.assertFalse(gate.authenticated("wrong"))
        self.assertTrue(gate.valid_origin("http://localhost:5173", "backend:8000"))
        self.assertFalse(gate.valid_origin("https://evil.example", "backend:8000"))
        with self.assertRaises(ValueError):
            SessionGate("replace-with-token", [])

    def test_frigate_mqtt_only_completed_events(self):
        self.assertIsNone(completed_event_id(b'{"type":"update","after":{"id":"123.4-a"}}'))
        self.assertEqual(completed_event_id(b'{"type":"end","after":{"id":"123.4-a"}}'), "123.4-a")
        self.assertIsNone(completed_event_id(b'{"type":"end","after":{"id":"../admin"}}'))

    def test_frigate_scan_memory_and_projector(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(media_root=root / "media", camera_snapshot_dir=root / "media" / "current", cameras=[CameraConfig(name="pegboard", zone_name="upper_left", frigate_name="pegboard")])
            settings.camera_snapshot_dir.mkdir(parents=True)
            storage = Storage(root / "test.db")
            cameras = CameraManager(settings.cameras, settings.camera_snapshot_dir, FakeFrigate())
            hub = ProjectorHub()
            service = JarvisLocalService(settings, storage, cameras, FakeVision(), hub)

            async def run():
                scan = await service.scan_camera("pegboard")
                self.assertEqual(len(scan.detections), 1)
                self.assertTrue(scan.snapshot_path.startswith("/media/"))
                found = storage.find_last_seen("screwdrivers")
                self.assertIsNotNone(found)
                self.assertEqual(found.bbox, [40, 20, 110, 210])
                answer = await service.handle_command(AssistantCommandRequest(text="Where are my screwdrivers?"))
                self.assertTrue(answer.projector_event_sent)
                self.assertEqual(hub.last_event["type"], "show_bounding_box")
                self.assertEqual(hub.last_event["boxes"][0]["box"], [40, 20, 110, 210])

            asyncio.run(run())

    def test_research_dimensions_and_home_assistant_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(media_root=root / "media", router_model="router", research_model="research", ha_allowed_entities=["switch.homelab"])
            storage = Storage(root / "test.db")
            hub = ProjectorHub()
            ha = FakeHA()
            service = JarvisLocalService(settings, storage, CameraManager([], root, FakeFrigate()), FakeModel({"intent": "research_project", "query": "server dimensions"}), hub, FakeSearch(), ha)

            async def run():
                result = await service.handle_command(AssistantCommandRequest(text="Project the server dimensions"))
                self.assertTrue(result.projector_event_sent)
                self.assertEqual(hub.last_event["type"], "show_dimensions")
                service.model_client.route = {"intent": "ha_action", "entity_id": "switch.homelab", "service": "turn_off"}
                pending = await service.handle_command(AssistantCommandRequest(text="Turn off homelab switch"))
                self.assertEqual(pending.route, "confirmation_required")
                self.assertEqual(ha.calls, [])
                confirmed = await service.confirm_action(pending.confirmation_token)
                self.assertEqual(confirmed.route, "home_assistant_action")
                self.assertEqual(ha.calls, [("switch.homelab", "turn_off")])
                again = await service.confirm_action(pending.confirmation_token)
                self.assertEqual(again.route, "confirmation_expired")

            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
