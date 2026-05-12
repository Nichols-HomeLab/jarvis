from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DetectionBox(BaseModel):
    label: str
    description: str = ""
    box: list[int] = Field(default_factory=list, min_length=4, max_length=4)
    confidence: float = 0.0


class ScanResult(BaseModel):
    camera: str
    zone: str
    summary: str = ""
    detections: list[DetectionBox] = Field(default_factory=list)
    raw_model_output: dict[str, Any] = Field(default_factory=dict)
    snapshot_path: str
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


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
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
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


class CameraSnapshot(BaseModel):
    camera: str
    snapshot_path: str
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class CommandResponse(BaseModel):
    text: str
    route: str
    projector_event_sent: bool = False
    search_result: SearchResult | None = None
    scan_result: ScanResult | None = None
