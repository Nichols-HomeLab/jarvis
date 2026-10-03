from __future__ import annotations

import base64
import asyncio
import logging
import httpx
from fastapi.responses import StreamingResponse
from backend.embeddings import MemoryEmbedder
from backend.vision.streaming import CameraStreams
from backend.vision.detector import DetectorVision
import secrets
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Header, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import load_settings
from backend.homebox import HomeboxClient
from backend.auth import SessionGate, COOKIE_NAME
from backend.models.openai_compatible import OpenAICompatibleClient
from backend.projector.hub import ProjectorHub
from backend.audio import LocalAudio
from backend.tools import HomeAssistant, WebSearch
from backend.vision.frigate import FrigateClient
from backend.vision.mqtt_events import FrigateMQTTSubscriber
from backend.schemas import (
    AssistantCommandRequest,
    CameraSnapshot,
    CommandResponse,
    ProjectBoundingBoxRequest,
    ProjectCardRequest,
    ScanResult,
    DimensionRequest,
    GestureEvent,
    IdentificationResult,
)
from backend.service import JarvisLocalService
from backend.storage import Storage
from backend.vision.camera_manager import CameraManager


settings = load_settings()
log = logging.getLogger(__name__)
session_gate = SessionGate(settings.access_token, settings.cors_origins)
storage = Storage(settings.database_url, settings.embedding_dimensions)
if storage.postgres:
    imported = storage.migrate_sqlite(Path("data/jarvis_local.db"))
    if imported:
        log.info("Migrated retained SQLite history: %s", imported)
frigate = FrigateClient(settings.frigate_url, settings.frigate_token, settings.frigate_user, settings.frigate_password)
streams = CameraStreams(frigate, settings.frigate_rtsp_url)
cameras = CameraManager(settings.cameras, settings.camera_snapshot_dir, frigate)
model_client = OpenAICompatibleClient(
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
    vision_model=settings.vision_model,
    router_model=settings.router_model,
    research_model=settings.research_model,
    allow_mock_vision=settings.allow_mock_vision,
)
projector_hub = ProjectorHub()
service = JarvisLocalService(
    settings, storage, cameras, model_client, projector_hub,
    WebSearch(settings.search_url),
    HomeAssistant(settings.home_assistant_url, settings.home_assistant_token, settings.ha_allowed_entities, settings.ha_dangerous_domains),
    HomeboxClient(settings.homebox_url, settings.homebox_api_key),
    embedder=MemoryEmbedder(settings.embedding_model, settings.embedding_cache_dir),
    detector=DetectorVision(settings, model_client) if settings.detector_url else None,
)
audio = LocalAudio(settings.stt_base_url, settings.stt_model, settings.tts_base_url, settings.tts_model, settings.tts_voice, settings.openai_api_key)
_event_locks: set[str] = set()


async def ingest_frigate_event(event_id: str) -> dict[str, object]:
    if storage.has_event(event_id) or event_id in _event_locks:
        return {"event_id": event_id, "status": "already_processed"}
    _event_locks.add(event_id)
    try:
        event = await frigate.event(event_id)
        camera = next((c for c in cameras.list_cameras() if (c.frigate_name or c.name) == event.get("camera")), None)
        if camera is None:
            return {"event_id": event_id, "status": "camera_not_configured"}
        image = await frigate.event_snapshot(event_id)
        target = settings.camera_event_dir / f"{event_id}.jpg"
        target.write_bytes(image)
        analyzer = service.detector or model_client
        scan = await analyzer.analyze_snapshot(camera.name, camera.zone_name, image, service._public_media_path(target.as_posix()))
        service.latest_scans[camera.name] = scan
        scan.detections = [item for item in scan.detections if item.confidence >= settings.min_detection_confidence]
        storage.save_scan(scan)
        storage.link_homebox_scan(scan)
        storage.record_event(event_id)
        return {"event_id": event_id, "detections": len(scan.detections)}
    finally:
        _event_locks.discard(event_id)


subscriber = FrigateMQTTSubscriber(settings, ingest_frigate_event)


async def periodic_scans() -> None:
    while True:
        for camera in cameras.list_cameras():
            try:
                await service.scan_camera(camera.name)
            except Exception:
                log.exception("Automatic scan failed for %s", camera.name)
            await asyncio.sleep(2)
        await asyncio.sleep(settings.auto_scan_interval_seconds)


async def periodic_memory_index():
    while True:
        try:
            count = await service.index_memories()
        except Exception:
            log.exception("Memory embedding indexing failed")
            count = 0
        await asyncio.sleep(1 if count else 15)


async def periodic_homebox_sync() -> None:
    while True:
        try:
            await service.sync_homebox()
        except Exception:
            log.exception("Homebox inventory sync failed")
        await asyncio.sleep(settings.homebox_sync_interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    subscriber.start()
    tasks = [asyncio.create_task(periodic_memory_index())]
    if settings.auto_scan_interval_seconds and cameras.list_cameras():
        tasks.append(asyncio.create_task(periodic_scans()))
    if settings.homebox_sync_interval_seconds and service.homebox.configured:
        tasks.append(asyncio.create_task(periodic_homebox_sync()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        subscriber.stop()

app = FastAPI(title="Jarvis Local Workshop API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def authorize(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path == "/api/v2/health" or path.startswith("/api/v2/auth/"):
        return await call_next(request)
    if path.startswith("/api/v2/events/") or path == "/api/v2/satellite/turn":
        return await call_next(request)
    if not session_gate.valid_request(request):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    if request.method not in {"GET", "HEAD"} and not session_gate.valid_origin(
        request.headers.get("origin"), request.headers.get("host", "")
    ):
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


class LoginRequest(BaseModel):
    token: str


@app.get("/api/v2/auth/session")
async def auth_session(request: Request):
    return {"authenticated": session_gate.valid_request(request)}


@app.post("/api/v2/auth/login")
async def auth_login(request: Request, payload: LoginRequest, response: Response):
    if not session_gate.valid_origin(request.headers.get("origin"), request.headers.get("host", "")):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    if not secrets.compare_digest(payload.token, session_gate.token):
        raise HTTPException(status_code=401, detail="Invalid access token")
    response.set_cookie(COOKIE_NAME, session_gate.cookie_value, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=86400)
    return {"authenticated": True}


@app.post("/api/v2/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(COOKIE_NAME, samesite="strict")
    return {"authenticated": False}

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
        "database": "postgresql" if storage.postgres else "sqlite",
        "memory": storage.memory_stats(),
        "detector": settings.detector_mode if settings.detector_url else "vlm",
        "cameras": [camera.name for camera in cameras.list_cameras()],
        "frigate_configured": bool(settings.frigate_url),
        "stt_configured": bool(settings.stt_base_url),
        "tts_configured": bool(settings.tts_base_url),
        "vision_model": settings.vision_model,
        "model_gateway": "bifrost",
        "homebox_configured": service.homebox.configured,
        "automatic_scan_seconds": settings.auto_scan_interval_seconds,
    }


@app.get("/api/v2/cameras")
async def list_cameras() -> list[dict[str, object]]:
    return [
        {
            "name": camera.name,
            "zone_name": camera.zone_name,
            "frigate_name": camera.frigate_name or camera.name,
            "enabled": camera.enabled,
        }
        for camera in cameras.list_cameras()
    ]


@app.post("/api/v2/cameras/{camera_name}/snapshot", response_model=CameraSnapshot)
async def capture_snapshot(camera_name: str) -> CameraSnapshot:
    try:
        snapshot = await cameras.capture_snapshot(camera_name)
        snapshot.snapshot_path = service._public_media_path(snapshot.snapshot_path)
        return snapshot
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


@app.get("/api/v2/cameras/{camera_name}/stream")
async def camera_stream(camera_name: str):
    try:
        camera = cameras.get_camera(camera_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown camera") from exc
    context = streams.open(camera.frigate_name or camera.name)
    try:
        chunks, content_type = await context.__aenter__()
    except (httpx.HTTPError, RuntimeError, OSError, asyncio.TimeoutError, StopAsyncIteration) as exc:
        raise HTTPException(status_code=502, detail="Camera stream unavailable") from exc
    async def body():
        try:
            async for chunk in chunks:
                yield chunk
        finally:
            await context.__aexit__(None, None, None)
    return StreamingResponse(body(), media_type=content_type,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/v2/cameras/{camera_name}/detections")
async def camera_detections(camera_name: str):
    try:
        cameras.get_camera(camera_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown camera") from exc
    return service.latest_scans.get(camera_name)


@app.get("/api/v2/memories/search")
async def hybrid_memory_search(q: str):
    return await service.hybrid_search(q)


@app.get("/api/v2/memories/status")
async def memory_status():
    return storage.memory_stats()


@app.post("/api/v2/cameras/{camera_name}/identify", response_model=IdentificationResult)
async def identify_camera(camera_name: str, target: str = "") -> IdentificationResult:
    try:
        return await service.identify_camera(camera_name, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Identification failed: {exc}") from exc


@app.post("/api/v2/homebox/sync")
async def sync_homebox() -> dict[str, int]:
    try:
        return await service.sync_homebox()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Homebox sync failed: {exc}") from exc


@app.get("/api/v2/homebox/search")
async def search_homebox(q: str):
    match = storage.find_homebox(q)
    if match is None:
        raise HTTPException(status_code=404, detail="No matching Homebox item or location")
    return match


@app.get("/api/v2/homebox/contents")
async def homebox_contents(q: str):
    box = storage.find_homebox(q, location_only=True)
    if box is None:
        raise HTTPException(status_code=404, detail="No matching Homebox box or location")
    if box.get("alternatives"):
        raise HTTPException(status_code=409, detail={"message": "Multiple locations share this name", "locations": [{"entity_id": box["entity_id"], "path": box["path"]}, *box["alternatives"]]})
    return {"location": box, "contents": storage.homebox_contents(box["entity_id"])}


@app.get("/api/v2/tool-memory/search")
async def search_tool_memory(q: str):
    result = await service.find_tool(q)
    if result is None:
        raise HTTPException(status_code=404, detail="No matching memory found")
    return result


@app.get("/api/v2/tool-memory/recent")
async def recent_memories(limit: int = 20):
    limit = max(1, min(limit, 100))
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


@app.post("/api/v2/projector/dimensions")
async def project_dimensions(request: DimensionRequest) -> dict[str, str]:
    await service.project_dimensions(request)
    return {"status": "ok"}


@app.post("/api/v2/projector/gesture")
async def projector_gesture(request: GestureEvent) -> dict[str, str]:
    await projector_hub.broadcast({"type": "gesture", "action": request.type, "x": request.x, "y": request.y, "scale": request.scale})
    return {"status": "ok"}


@app.post("/api/v2/assistant/confirm/{token}", response_model=CommandResponse)
async def confirm_action(token: str) -> CommandResponse:
    return await service.confirm_action(token)


@app.post("/api/v2/audio/transcribe")
async def transcribe_audio(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read(15_000_001)
    try:
        return {"text": await audio.transcribe(data, file.filename or "audio.webm")}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v2/satellite/turn")
async def satellite_turn(file: UploadFile = File(...), x_jarvis_token: str = Header(default="")) -> dict[str, str]:
    if not settings.satellite_token or not secrets.compare_digest(x_jarvis_token, settings.satellite_token):
        raise HTTPException(status_code=403, detail="Invalid satellite token")
    transcript = await audio.transcribe(await file.read(15_000_001), file.filename or "audio.wav")
    result = await service.handle_command(AssistantCommandRequest(text=transcript))
    speech = await audio.speak(result.text, response_format="wav")
    return {"transcript": transcript, "text": result.text, "audio_wav_base64": base64.b64encode(speech).decode("ascii")}


@app.post("/api/v2/events/frigate/{event_id}")
async def frigate_event(event_id: str, x_jarvis_token: str = Header(default="")):
    if not settings.motion_webhook_token or not secrets.compare_digest(x_jarvis_token, settings.motion_webhook_token):
        raise HTTPException(status_code=403, detail="Invalid event token")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID")
    return await ingest_frigate_event(event_id)


@app.post("/api/v2/events/motion/{camera_name}")
async def motion_event(camera_name: str, request: MotionEventRequest, x_jarvis_token: str = Header(default="")):
    if not settings.motion_webhook_token or not secrets.compare_digest(x_jarvis_token, settings.motion_webhook_token):
        raise HTTPException(status_code=403, detail="Invalid event token")
    if not 0 <= request.before_delay_seconds <= 10 or not 0 <= request.after_delay_seconds <= 10:
        raise HTTPException(status_code=400, detail="Delay must be between 0 and 10 seconds")
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
    if not session_gate.valid_socket(websocket):
        await websocket.close(code=1008)
        return
    await projector_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await projector_hub.disconnect(websocket)


@app.websocket("/ws/voice")
async def voice_socket(websocket: WebSocket) -> None:
    if not session_gate.valid_socket(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "transcript":
                await websocket.send_json({"type": "text", "text": "Send a transcript message."})
                continue
            await websocket.send_json({"type": "status", "state": "thinking"})
            try:
                result = await service.handle_command(AssistantCommandRequest(text=str(message.get("text", ""))))
                await websocket.send_json({"type": "text", "text": result.text, "route": result.route, "confirmation_token": result.confirmation_token})
                try:
                    speech = await audio.speak(result.text)
                    if speech:
                        await websocket.send_json({"type": "audio", "data": base64.b64encode(speech).decode("ascii"), "text": result.text})
                except Exception:
                    await websocket.send_json({"type": "status", "state": "tts_unavailable"})
            except Exception as exc:
                await websocket.send_json({"type": "text", "text": f"Command failed: {exc}"})
            await websocket.send_json({"type": "status", "state": "idle"})
    except WebSocketDisconnect:
        pass
