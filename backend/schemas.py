from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class DetectionBox(BaseModel):
    label: str
    description: str = ""
    box: list[int] = Field(default_factory=list, min_length=4, max_length=4)
    confidence: float = Field(ge=0, le=1)

    @field_validator("box")
    @classmethod
    def valid_box(cls, value: list[int]) -> list[int]:
        if min(value) < 0 or value[2] <= value[0] or value[3] <= value[1]:
            raise ValueError("box must be positive [x1, y1, x2, y2]")
        return value


class ScanResult(BaseModel):
    image_width: int = 0
    image_height: int = 0
    detector: str = "vlm"
    camera: str
    zone: str
    summary: str = ""
    detections: list[DetectionBox] = Field(default_factory=list)
    raw_model_output: dict[str, Any] = Field(default_factory=dict)
    snapshot_path: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ObjectMemoryRecord(BaseModel):
    object_name: str
    object_category: str
    description: str = ""
    camera_name: str
    zone_name: str
    action: str = "seen"
    actor: str | None = None
    direction: str | None = None
    confidence: float = 0.0
    snapshot_path: str | None = None
    clip_path: str | None = None
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_model_output: dict[str, Any] = Field(default_factory=dict)


class AssistantCommandRequest(BaseModel):
    text: str
    project_result: bool = True


class ProjectBoundingBoxRequest(BaseModel):
    camera: str
    image: str
    boxes: list[DetectionBox]
    title: str = "Tool Location"


class ProjectCardRequest(BaseModel):
    title: str
    content: str
    kind: Literal["summary", "dimension", "note"] = "summary"


class DimensionRequest(BaseModel):
    title: str
    width_mm: float = Field(gt=0, le=10000)
    depth_mm: float = Field(gt=0, le=10000)
    height_mm: float | None = Field(default=None, gt=0, le=10000)
    source: str = ""


class GestureEvent(BaseModel):
    type: Literal["grab", "move", "release", "scale", "clear"]
    x: float = Field(default=0, ge=0, le=1)
    y: float = Field(default=0, ge=0, le=1)
    scale: float = Field(default=1, ge=0.1, le=10)


class SearchResult(BaseModel):
    object_name: str
    object_category: str
    description: str = ""
    camera_name: str
    zone_name: str
    action: str
    actor: str | None = None
    direction: str | None = None
    confidence: float
    last_seen_at: datetime
    snapshot_path: str | None = None
    clip_path: str | None = None
    bbox: list[int] | None = None
    memory_id: int | None = None
    inventory_path: str | None = None
    entity_id: str | None = None
    retrieval_source: str | None = None
    retrieval_score: float = 0
    markdown: str = ""
    relationships: list[str] = Field(default_factory=list)


class CameraSnapshot(BaseModel):
    camera: str
    snapshot_path: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IdentificationResult(BaseModel):
    camera: str
    query: str
    assessment: str
    scan: ScanResult
    image_matches: list[dict[str, str]] = Field(default_factory=list)


class CommandResponse(BaseModel):
    text: str
    route: str
    projector_event_sent: bool = False
    search_result: SearchResult | None = None
    scan_result: ScanResult | None = None
    confirmation_token: str | None = None
