import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.config import CameraConfig, Settings, _parse_cameras
from backend.storage import Storage
from backend.vision.camera_manager import CameraManager


class CameraManagementTests(unittest.TestCase):
    def test_persistence_and_empty_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Storage(root / "jarvis.db")
            configs = [CameraConfig("old", "old")]
            manager = CameraManager(configs, root, None, store)
            manager.remove_camera("old")
            self.assertEqual(configs, [])
            restarted = CameraManager([CameraConfig("old", "old")], root, None, Storage(root / "jarvis.db"))
            self.assertEqual(restarted.list_cameras(), [])
            restarted.add_camera(CameraConfig("bench", "Workshop", frigate_name="Workshop", detection_labels=["drill"]))
            with self.assertRaises(ValueError):
                restarted.add_camera(CameraConfig("bench", "other"))
            restored = CameraManager([], root, None, store)
            self.assertEqual(restored.get_camera("bench").frigate_name, "Workshop")
            self.assertEqual(restored.get_camera("bench").detection_labels, ["drill"])
            self.assertEqual(_parse_cameras(None), [])

    def test_authenticated_api_validation_and_crud(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            media.mkdir()
            settings = Settings(database_url=f"sqlite:///{root / 'api.db'}", media_root=media,
                camera_snapshot_dir=media, access_token="x" * 40, cors_origins=["http://testserver"],
                auto_scan_interval_seconds=0, homebox_sync_interval_seconds=0)
            with patch("backend.config.load_settings", return_value=settings):
                import backend.main as api
            client = TestClient(api.app)
            payload = {"name": "workbench", "frigate_name": "Workshop", "zone_name": "Main bench", "detection_labels": ["drill"]}
            self.assertEqual(client.post("/api/v2/cameras", json=payload).status_code, 401)
            self.assertEqual(client.delete("/api/v2/cameras/workbench").status_code, 401)
            self.assertEqual(client.post("/api/v2/auth/login", json={"token": settings.access_token}).status_code, 200)
            self.assertEqual(client.post("/api/v2/cameras", json=payload, headers={"Origin": "https://evil.example"}).status_code, 403)
            for field, bad in [("name", "../bad"), ("frigate_name", "x?bad"), ("zone_name", "   ")]:
                self.assertEqual(client.post("/api/v2/cameras", json=payload | {field: bad}).status_code, 422)
            self.assertEqual(client.post("/api/v2/cameras", json=payload).status_code, 201)
            self.assertEqual(client.post("/api/v2/cameras", json=payload).status_code, 409)
            self.assertEqual(client.get("/api/v2/cameras").json()[0]["frigate_name"], "Workshop")
            self.assertEqual(api.settings.cameras[0].detection_labels, ["drill"])
            self.assertEqual(client.delete("/api/v2/cameras/workbench").status_code, 200)
            self.assertEqual(client.delete("/api/v2/cameras/workbench").status_code, 404)
            self.assertEqual(client.get("/api/v2/cameras").json(), [])
            self.assertEqual(api.storage.load_cameras([payload]), [])


if __name__ == "__main__":
    unittest.main()
