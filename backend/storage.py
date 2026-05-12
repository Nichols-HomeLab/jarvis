from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from backend.schemas import ObjectMemoryRecord, ScanResult, SearchResult


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS object_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_name TEXT NOT NULL,
                    object_category TEXT NOT NULL,
                    description TEXT,
                    camera_name TEXT NOT NULL,
                    zone_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT,
                    direction TEXT,
                    last_seen_at TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    snapshot_path TEXT,
                    clip_path TEXT,
                    raw_model_output TEXT
                );

                CREATE TABLE IF NOT EXISTS object_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_name TEXT NOT NULL,
                    zone_name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    description TEXT,
                    bbox_x1 INTEGER NOT NULL,
                    bbox_y1 INTEGER NOT NULL,
                    bbox_x2 INTEGER NOT NULL,
                    bbox_y2 INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    detected_at TEXT NOT NULL,
                    snapshot_path TEXT
                );

                CREATE TABLE IF NOT EXISTS camera_zones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_name TEXT NOT NULL,
                    zone_name TEXT NOT NULL,
                    description TEXT,
                    polygon TEXT
                );
                """
            )

    def save_scan(self, scan: ScanResult) -> None:
        with self.connect() as conn:
            for detection in scan.detections:
                conn.execute(
                    """
                    INSERT INTO object_detections (
                        camera_name, zone_name, label, description,
                        bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                        confidence, detected_at, snapshot_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan.camera,
                        scan.zone,
                        detection.label,
                        detection.description,
                        detection.box[0],
                        detection.box[1],
                        detection.box[2],
                        detection.box[3],
                        detection.confidence,
                        scan.analyzed_at.isoformat(),
                        scan.snapshot_path,
                    ),
                )

                memory = ObjectMemoryRecord(
                    object_name=detection.description or detection.label,
                    object_category=detection.label,
                    description=detection.description,
                    camera_name=scan.camera,
                    zone_name=scan.zone,
                    action="seen",
                    confidence=detection.confidence,
                    snapshot_path=scan.snapshot_path,
                    last_seen_at=scan.analyzed_at,
                    raw_model_output=scan.raw_model_output,
                )
                self.save_memory(memory, conn)

    def save_memory(self, memory: ObjectMemoryRecord, conn: sqlite3.Connection | None = None) -> None:
        owns_conn = conn is None
        connection = conn
        if connection is None:
            connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                """
                INSERT INTO object_memories (
                    object_name, object_category, description, camera_name,
                    zone_name, action, actor, direction, last_seen_at,
                    confidence, snapshot_path, clip_path, raw_model_output
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.object_name,
                    memory.object_category,
                    memory.description,
                    memory.camera_name,
                    memory.zone_name,
                    memory.action,
                    memory.actor,
                    memory.direction,
                    memory.last_seen_at.isoformat(),
                    memory.confidence,
                    memory.snapshot_path,
                    memory.clip_path,
                    json.dumps(memory.raw_model_output),
                ),
            )
            if owns_conn:
                connection.commit()
        finally:
            if owns_conn:
                connection.close()

    def find_last_seen(self, query: str) -> SearchResult | None:
        like = f"%{query.lower()}%"
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    m.object_name,
                    m.object_category,
                    m.description,
                    m.camera_name,
                    m.zone_name,
                    m.action,
                    m.actor,
                    m.direction,
                    m.confidence,
                    m.last_seen_at,
                    m.snapshot_path,
                    m.clip_path,
                    d.bbox_x1,
                    d.bbox_y1,
                    d.bbox_x2,
                    d.bbox_y2
                FROM object_memories m
                LEFT JOIN object_detections d
                  ON d.camera_name = m.camera_name
                 AND d.zone_name = m.zone_name
                 AND lower(d.label) = lower(m.object_category)
                 AND d.snapshot_path = m.snapshot_path
                WHERE lower(m.object_name) LIKE ?
                   OR lower(m.object_category) LIKE ?
                   OR lower(m.description) LIKE ?
                ORDER BY datetime(m.last_seen_at) DESC
                LIMIT 1
                """,
                (like, like, like),
            ).fetchone()

        if row is None:
            return None

        bbox = None
        if row["bbox_x1"] is not None:
            bbox = [row["bbox_x1"], row["bbox_y1"], row["bbox_x2"], row["bbox_y2"]]

        return SearchResult(
            object_name=row["object_name"],
            object_category=row["object_category"],
            description=row["description"] or "",
            camera_name=row["camera_name"],
            zone_name=row["zone_name"],
            action=row["action"],
            actor=row["actor"],
            direction=row["direction"],
            confidence=float(row["confidence"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            snapshot_path=row["snapshot_path"],
            clip_path=row["clip_path"],
            bbox=bbox,
        )

    def recent_memories(self, limit: int = 20) -> list[SearchResult]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    object_name, object_category, description, camera_name,
                    zone_name, action, actor, direction, confidence,
                    last_seen_at, snapshot_path, clip_path
                FROM object_memories
                ORDER BY datetime(last_seen_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            results.append(
                SearchResult(
                    object_name=row["object_name"],
                    object_category=row["object_category"],
                    description=row["description"] or "",
                    camera_name=row["camera_name"],
                    zone_name=row["zone_name"],
                    action=row["action"],
                    actor=row["actor"],
                    direction=row["direction"],
                    confidence=float(row["confidence"]),
                    last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
                    snapshot_path=row["snapshot_path"],
                    clip_path=row["clip_path"],
                    bbox=None,
                )
            )
        return results
