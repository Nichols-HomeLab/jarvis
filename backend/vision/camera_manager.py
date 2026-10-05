from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
import uuid

from backend.config import CameraConfig
from backend.schemas import CameraSnapshot
from backend.vision.frigate import FrigateClient
from backend.vision.streaming import CameraStreams


class CameraManager:
    def __init__(self, cameras: list[CameraConfig], snapshot_dir: Path, frigate: FrigateClient, storage=None, streams=None):
        self.streams = streams or CameraStreams(frigate)
        self.storage = storage
        self.configs = cameras
        if storage is not None:
            cameras[:] = [CameraConfig(**item) for item in storage.load_cameras([asdict(c) for c in cameras])]
        self._cameras = {camera.name: camera for camera in cameras if camera.enabled}
        self.snapshot_dir = snapshot_dir
        self.frigate = frigate

    def list_cameras(self) -> list[CameraConfig]:
        return list(self._cameras.values())

    def add_camera(self, camera: CameraConfig) -> None:
        if any(c.name == camera.name for c in self.configs):
            raise ValueError("A camera with this name already exists")
        self._replace([*self.configs, camera])

    def remove_camera(self, camera_name: str) -> None:
        self.get_camera(camera_name)
        self._replace([c for c in self.configs if c.name != camera_name])

    def _replace(self, cameras: list[CameraConfig]) -> None:
        if self.storage is not None:
            self.storage.save_cameras([asdict(c) for c in cameras])
        self.configs[:] = cameras
        self._cameras = {c.name: c for c in cameras if c.enabled}

    def get_camera(self, camera_name: str) -> CameraConfig:
        try:
            return self._cameras[camera_name]
        except KeyError as exc:
            raise KeyError(f"Unknown camera '{camera_name}'") from exc

    async def capture_snapshot(self, camera_name: str) -> CameraSnapshot:
        camera = self.get_camera(camera_name)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = self.snapshot_dir / f"{camera_name}_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
        image = (await self.streams.snapshot(camera.rtsp_url) if camera.rtsp_url
                 else await self.frigate.latest_frame(camera.frigate_name or camera.name))
        target.write_bytes(image)
        return CameraSnapshot(camera=camera_name, snapshot_path=target.as_posix())
