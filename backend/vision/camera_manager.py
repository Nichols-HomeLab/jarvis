from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from backend.config import CameraConfig
from backend.schemas import CameraSnapshot
from backend.vision.frigate import FrigateClient


class CameraManager:
    def __init__(self, cameras: list[CameraConfig], snapshot_dir: Path, frigate: FrigateClient):
        self._cameras = {camera.name: camera for camera in cameras if camera.enabled}
        self.snapshot_dir = snapshot_dir
        self.frigate = frigate

    def list_cameras(self) -> list[CameraConfig]:
        return list(self._cameras.values())

    def get_camera(self, camera_name: str) -> CameraConfig:
        try:
            return self._cameras[camera_name]
        except KeyError as exc:
            raise KeyError(f"Unknown camera '{camera_name}'") from exc

    async def capture_snapshot(self, camera_name: str) -> CameraSnapshot:
        camera = self.get_camera(camera_name)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = self.snapshot_dir / f"{camera_name}_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        target.write_bytes(await self.frigate.latest_frame(camera.frigate_name or camera.name))
        return CameraSnapshot(camera=camera_name, snapshot_path=target.as_posix())
