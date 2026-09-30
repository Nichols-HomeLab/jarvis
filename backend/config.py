from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class CameraConfig:
    name: str
    zone_name: str
    enabled: bool = True
    frigate_name: str | None = None


@dataclass(slots=True)
class Settings:
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: str = "dummy"
    router_model: str = "gemma3n:e4b"
    vision_model: str = "qwen2.5vl:7b"
    research_model: str = "qwen2.5:7b"
    default_actor_name: str = "David"
    database_url: str = "sqlite:///data/jarvis_local.db"
    media_root: Path = Path("data/media")
    camera_snapshot_dir: Path = Path("data/media/current")
    camera_event_dir: Path = Path("data/media/events")
    cameras: list[CameraConfig] = field(default_factory=list)
    allow_mock_vision: bool = False
    search_url: str = ""
    home_assistant_url: str = ""
    home_assistant_token: str = ""
    ha_allowed_entities: list[str] = field(default_factory=list)
    ha_dangerous_domains: list[str] = field(default_factory=lambda: ["lock", "cover", "climate", "switch"])
    stt_base_url: str = ""
    stt_model: str = "whisper-1"
    tts_base_url: str = ""
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    motion_webhook_token: str = ""
    projector_width_mm: float = 0
    projector_height_mm: float = 0
    frigate_url: str = ""
    frigate_token: str = ""
    frigate_user: str = ""
    frigate_password: str = ""
    satellite_token: str = ""
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    mqtt_topic_prefix: str = "frigate"
    access_token: str = ""

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix):])
        return Path(self.database_url)


def _parse_cameras(raw_value: str | None) -> list[CameraConfig]:
    if not raw_value:
        return [
            CameraConfig(
                name="pegboard",
                zone_name="pegboard",
                frigate_name="pegboard",
            ),
            CameraConfig(
                name="workbench",
                zone_name="main_workbench",
                frigate_name="workbench",
            ),
        ]

    data: list[dict[str, Any]] = json.loads(raw_value)
    cameras: list[CameraConfig] = []
    for item in data:
        cameras.append(
            CameraConfig(
                name=item["name"],
                zone_name=item.get("zone_name", item["name"]),
                enabled=bool(item.get("enabled", True)),
                frigate_name=item.get("frigate_name", item["name"]),
            )
        )
    return cameras


def load_settings() -> Settings:
    _load_dotenv()

    media_root = Path(os.getenv("MEDIA_ROOT", "data/media"))
    snapshot_dir = media_root / "current"
    event_dir = media_root / "events"

    settings = Settings(
        app_env=os.getenv("APP_ENV", "development"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        cors_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()],
        openai_base_url=os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
        openai_api_key=os.getenv("OPENAI_API_KEY", "dummy"),
        router_model=os.getenv("OPENAI_ROUTER_MODEL", "gemma3n:e4b"),
        vision_model=os.getenv("OPENAI_VISION_MODEL", "qwen2.5vl:7b"),
        research_model=os.getenv("OPENAI_RESEARCH_MODEL", "qwen2.5:7b"),
        default_actor_name=os.getenv("DEFAULT_ACTOR_NAME", "David"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///data/jarvis_local.db"),
        media_root=media_root,
        camera_snapshot_dir=snapshot_dir,
        camera_event_dir=event_dir,
        cameras=_parse_cameras(os.getenv("JARVIS_CAMERAS_JSON")),
        allow_mock_vision=_env_bool("ALLOW_MOCK_VISION", False),
        search_url=os.getenv("SEARXNG_URL", "").rstrip("/"),
        home_assistant_url=os.getenv("HOME_ASSISTANT_URL", "").rstrip("/"),
        home_assistant_token=os.getenv("HOME_ASSISTANT_TOKEN", ""),
        ha_allowed_entities=[x.strip() for x in os.getenv("HA_ALLOWED_ENTITIES", "").split(",") if x.strip()],
        stt_base_url=os.getenv("STT_BASE_URL", "").rstrip("/"),
        stt_model=os.getenv("STT_MODEL", "whisper-1"),
        tts_base_url=os.getenv("TTS_BASE_URL", "").rstrip("/"),
        tts_model=os.getenv("TTS_MODEL", "tts-1"),
        tts_voice=os.getenv("TTS_VOICE", "alloy"),
        motion_webhook_token=os.getenv("MOTION_WEBHOOK_TOKEN", ""),
        projector_width_mm=float(os.getenv("PROJECTOR_WIDTH_MM", "0")),
        projector_height_mm=float(os.getenv("PROJECTOR_HEIGHT_MM", "0")),
        frigate_url=os.getenv("FRIGATE_URL", "").rstrip("/"),
        frigate_token=os.getenv("FRIGATE_TOKEN", ""),
        frigate_user=os.getenv("FRIGATE_USER", ""),
        frigate_password=os.getenv("FRIGATE_PASSWORD", ""),
        satellite_token=os.getenv("SATELLITE_TOKEN", ""),
        mqtt_host=os.getenv("MQTT_HOST", ""),
        mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
        mqtt_user=os.getenv("MQTT_USER", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        mqtt_topic_prefix=os.getenv("MQTT_TOPIC_PREFIX", "frigate"),
        access_token=os.getenv("JARVIS_ACCESS_TOKEN", ""),
    )

    settings.media_root.mkdir(parents=True, exist_ok=True)
    settings.camera_snapshot_dir.mkdir(parents=True, exist_ok=True)
    settings.camera_event_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
