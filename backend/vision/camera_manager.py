from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx

from backend.config import CameraConfig
from backend.schemas import CameraSnapshot


class CameraManager:
    def __init__(self, cameras: list[CameraConfig], snapshot_dir: Path):
        self._cameras = {camera.name: camera for camera in cameras if camera.enabled}
        self.snapshot_dir = snapshot_dir

    def list_cameras(self) -> list[CameraConfig]:
        return list(self._cameras.values())

    def get_camera(self, camera_name: str) -> CameraConfig:
        try:
            return self._cameras[camera_name]
        except KeyError as exc:
            raise KeyError(f"Unknown camera '{camera_name}'") from exc

    async def capture_snapshot(self, camera_name: str) -> CameraSnapshot:
        camera = self.get_camera(camera_name)
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(camera.snapshot_url, auth=(camera.username, camera.password) if camera.username else None)
            response.raise_for_status()

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        target = self.snapshot_dir / f"{camera_name}_{timestamp}.jpg"
        target.write_bytes(response.content)
        return CameraSnapshot(camera=camera_name, snapshot_path=target.as_posix())
