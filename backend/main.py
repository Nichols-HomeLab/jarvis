from __future__ import annotations

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import load_settings
from backend.models.openai_compatible import OpenAICompatibleClient
from backend.projector.hub import ProjectorHub
from backend.schemas import (
    AssistantCommandRequest,
    CameraSnapshot,
    CommandResponse,
    ProjectBoundingBoxRequest,
    ProjectCardRequest,
    ScanResult,
)
from backend.service import JarvisLocalService
from backend.storage import Storage
from backend.vision.camera_manager import CameraManager


settings = load_settings()
storage = Storage(settings.database_path)
cameras = CameraManager(settings.cameras, settings.camera_snapshot_dir)
model_client = OpenAICompatibleClient(
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
    vision_model=settings.vision_model,
    router_model=settings.router_model,
    research_model=settings.research_model,
    allow_mock_vision=settings.allow_mock_vision,
)
projector_hub = ProjectorHub()
service = JarvisLocalService(settings, storage, cameras, model_client, projector_hub)

app = FastAPI(title="Jarvis Local Workshop API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(settings.media_root)), name="media")


class ManualMemoryRequest(BaseModel):
    object_name: str
    object_category: str
    camera_name: str
    zone_name: str
    description: str = ""
    confidence: float = 1.0
    snapshot_path: str | None = None


class MotionEventRequest(BaseModel):
    before_delay_seconds: int = 3
    after_delay_seconds: int = 5


@app.get("/api/v2/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "database": settings.database_path.as_posix(),
        "cameras": [camera.name for camera in cameras.list_cameras()],
        "openai_base_url": settings.openai_base_url,
        "vision_model": settings.vision_model,
    }


@app.get("/api/v2/cameras")
async def list_cameras() -> list[dict[str, object]]:
    return [
        {
            "name": camera.name,
            "zone_name": camera.zone_name,
            "snapshot_url": camera.snapshot_url,
            "rtsp_url": camera.rtsp_url,
            "enabled": camera.enabled,
        }
        for camera in cameras.list_cameras()
    ]


@app.post("/api/v2/cameras/{camera_name}/snapshot", response_model=CameraSnapshot)
async def capture_snapshot(camera_name: str) -> CameraSnapshot:
    try:
        return await cameras.capture_snapshot(camera_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Snapshot capture failed: {exc}") from exc


@app.post("/api/v2/scan/{camera_name}", response_model=ScanResult)
async def scan_camera(camera_name: str) -> ScanResult:
    try:
        return await service.scan_camera(camera_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vision scan failed: {exc}") from exc


@app.get("/api/v2/tool-memory/search")
async def search_tool_memory(q: str):
    result = service.search_tool_memory(q)
    if result is None:
        raise HTTPException(status_code=404, detail="No matching memory found")
    return result


@app.get("/api/v2/tool-memory/recent")
async def recent_memories(limit: int = 20):
    return storage.recent_memories(limit=limit)


@app.post("/api/v2/tool-memory/manual")
async def record_manual_memory(request: ManualMemoryRequest) -> dict[str, str]:
    service.record_manual_memory(
        object_name=request.object_name,
        object_category=request.object_category,
        camera_name=request.camera_name,
        zone_name=request.zone_name,
        description=request.description,
        confidence=request.confidence,
        snapshot_path=request.snapshot_path,
    )
    return {"status": "ok"}


@app.post("/api/v2/projector/bounding-box")
async def project_bounding_box(request: ProjectBoundingBoxRequest) -> dict[str, str]:
    await service.project_bounding_box(request)
    return {"status": "ok"}


@app.post("/api/v2/projector/card")
async def project_card(request: ProjectCardRequest) -> dict[str, str]:
    await service.project_card(request)
    return {"status": "ok"}


@app.post("/api/v2/events/reolink-motion/{camera_name}")
async def reolink_motion_event(camera_name: str, request: MotionEventRequest):
    try:
        return await service.handle_motion_event(
            camera_name=camera_name,
            before_delay_seconds=request.before_delay_seconds,
            after_delay_seconds=request.after_delay_seconds,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Motion event handling failed: {exc}") from exc


@app.post("/api/v2/assistant/command", response_model=CommandResponse)
async def assistant_command(request: AssistantCommandRequest) -> CommandResponse:
    return await service.handle_command(request)


@app.websocket("/ws/projector")
async def projector_socket(websocket: WebSocket) -> None:
    await projector_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await projector_hub.disconnect(websocket)
