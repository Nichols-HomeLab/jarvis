import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.config import CameraConfig, Settings, load_settings
from backend.homebox import HomeboxClient, HomeboxEntity
from backend.projector.hub import ProjectorHub
from backend.schemas import AssistantCommandRequest, DetectionBox, ScanResult
from backend.service import JarvisLocalService
from backend.storage import Storage
from backend.tools import WebSearch
from backend.vision.camera_manager import CameraManager
from tests.test_local_backend import FakeFrigate


class FakeVision:
    async def analyze_snapshot(self, camera, zone, image_bytes, snapshot_path):
        return ScanResult(
            camera=camera, zone=zone, snapshot_path=snapshot_path,
            detections=[DetectionBox(
                label="bin", description="blue parts bin", box=[10, 20, 100, 120], confidence=0.91,
            )],
        )

    async def chat(self, model, messages, json_mode=False):
        return "It may be a blue parts bin; compare the referenced images before trusting the ID."


class FakeImageSearch:
    def __init__(self):
        self.queries = []

    async def image_search(self, query):
        self.queries.append(query)
        return [{"title": "Parts bin", "url": "https://example.com/bin", "image_url": "https://example.com/bin.jpg"}]


class InventoryIntegrationTests(unittest.TestCase):
    def test_bifrost_settings_override_legacy_model_url(self):
        with patch.dict("os.environ", {
            "BIFROST_BASE_URL": "http://bifrost:8080/v1",
            "BIFROST_API_KEY": "test-key",
            "BIFROST_ROUTER_MODEL": "ollama/router",
            "BIFROST_RESEARCH_MODEL": "ollama/research",
            "BIFROST_VISION_MODEL": "ollama/vision",
            "OPENAI_BASE_URL": "http://old:11434/v1",
        }):
            settings = load_settings()
        self.assertEqual(settings.openai_base_url, "http://bifrost:8080/v1")
        self.assertEqual(settings.openai_api_key, "test-key")
        self.assertEqual(settings.vision_model, "ollama/vision")

    def test_missing_bifrost_configuration_fails_closed(self):
        with patch.dict("os.environ", {"BIFROST_BASE_URL": "", "OPENAI_BASE_URL": "http://old:11434/v1"}):
            with self.assertRaisesRegex(ValueError, "BIFROST_BASE_URL is required"):
                load_settings()

    def test_homebox_paginated_inventory_and_box_contents(self):
        requests = []

        def respond(request):
            requests.append(request)
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            self.assertEqual(request.url.path, "/api/v1/entities")
            is_location = request.url.params["isLocation"] == "true"
            page = int(request.url.params["page"])
            if is_location:
                items = [{"id": "shop", "name": "Workshop", "entityType": {"isLocation": True}},
                         {"id": "bin", "name": "Blue Parts Bin", "parent": {"id": "shop"}, "entityType": {"isLocation": True}}]
            else:
                items = [{"id": "screw", "name": "Screwdriver Set", "parent": {"id": "bin"}, "quantity": 2}]
            return httpx.Response(200, json={"items": items if page == 1 else [], "pageSize": 200, "total": len(items)})

        client = HomeboxClient("http://homebox:7745", "test-key", httpx.MockTransport(respond))
        entities = asyncio.run(client.inventory())
        self.assertEqual(len(requests), 2)
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "inventory.db")
            self.assertEqual(storage.replace_homebox_inventory(entities), 3)
            item = storage.find_homebox("screwdriver")
            self.assertEqual(item["path"], "Workshop / Blue Parts Bin / Screwdriver Set")
            self.assertEqual(storage.find_homebox("screwdrivers")["entity_id"], "screw")
            box = storage.find_homebox("blue parts bin", location_only=True)
            self.assertEqual([item["name"] for item in storage.homebox_contents(box["entity_id"])], ["Screwdriver Set"])

    def test_visual_box_match_and_homebox_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            snapshots = media / "current"
            snapshots.mkdir(parents=True)
            storage = Storage(root / "test.db")
            storage.replace_homebox_inventory([
                HomeboxEntity("shop", "Workshop", "", None, True, 0),
                HomeboxEntity("bin", "Blue Parts Bin", "", "shop", True, 0),
                HomeboxEntity("screw", "Screwdriver Set", "", "bin", False, 1),
            ])
            settings = Settings(media_root=media, camera_snapshot_dir=snapshots, cameras=[
                CameraConfig(name="workbench", zone_name="north_shelf", frigate_name="workbench")
            ])
            service = JarvisLocalService(
                settings, storage, CameraManager(settings.cameras, snapshots, FakeFrigate()),
                FakeVision(), ProjectorHub(),
            )

            async def run():
                await service.scan_camera("workbench")
                box = storage.find_homebox("Blue Parts Bin")
                self.assertEqual(box["visual_sighting"]["zone"], "north_shelf")
                answer = await service.handle_command(AssistantCommandRequest(text="What's in the Blue Parts Bin?"))
                self.assertIn("Screwdriver Set", answer.text)
                self.assertIn("tentatively", answer.text)

            asyncio.run(run())

    def test_image_search_filters_unsafe_urls(self):
        def respond(request):
            self.assertEqual(request.url.params["categories"], "images")
            return httpx.Response(200, json={"results": [
                {"title": "Tool", "url": "https://example.com/tool", "img_src": "https://example.com/tool.jpg"},
                {"title": "Unsafe", "url": "javascript:alert(1)", "img_src": "data:image/png;base64,abc"},
            ]})

        search = WebSearch("http://searxng:8080", httpx.MockTransport(respond))
        results = asyncio.run(search.image_search("blue tool"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["image_url"], "https://example.com/tool.jpg")

    def test_identification_uses_text_query_and_returns_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            snapshots = media / "current"
            snapshots.mkdir(parents=True)
            settings = Settings(media_root=media, camera_snapshot_dir=snapshots, cameras=[
                CameraConfig(name="workbench", zone_name="workbench", frigate_name="workbench")
            ])
            search = FakeImageSearch()
            service = JarvisLocalService(
                settings, Storage(root / "test.db"),
                CameraManager(settings.cameras, snapshots, FakeFrigate()),
                FakeVision(), ProjectorHub(), web_search=search,
            )

            async def run():
                result = await service.identify_camera("workbench")
                self.assertEqual(len(result.image_matches), 1)
                self.assertEqual(search.queries, ["blue parts bin tool identification"])
                self.assertIn("may be", result.assessment)

            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
