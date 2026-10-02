from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from backend.schemas import ObjectMemoryRecord, ScanResult, SearchResult
from backend.homebox import HomeboxEntity


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

                CREATE TABLE IF NOT EXISTS processed_camera_events (
                    event_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS homebox_inventory (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    parent_id TEXT,
                    is_location INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS homebox_visual_sightings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    zone_name TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    bbox_x1 INTEGER NOT NULL,
                    bbox_y1 INTEGER NOT NULL,
                    bbox_x2 INTEGER NOT NULL,
                    bbox_y2 INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_homebox_visual_entity
                    ON homebox_visual_sightings(entity_id, observed_at DESC);
                """
            )

    def replace_homebox_inventory(self, entities: list[HomeboxEntity]) -> int:
        by_id = {entity.entity_id: entity for entity in entities}
        if len(by_id) != len(entities):
            raise ValueError("Homebox returned duplicate entity IDs")

        def path_for(entity: HomeboxEntity) -> str:
            names = [entity.name]
            visited = {entity.entity_id}
            parent_id = entity.parent_id
            while parent_id and parent_id in by_id:
                if parent_id in visited:
                    raise ValueError("Homebox location hierarchy contains a cycle")
                visited.add(parent_id)
                parent = by_id[parent_id]
                names.append(parent.name)
                parent_id = parent.parent_id
            return " / ".join(reversed(names))

        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (e.entity_id, e.name, e.description, e.parent_id, int(e.is_location), e.quantity, path_for(e), now)
            for e in entities
        ]
        with self.connect() as conn:
            conn.execute("DELETE FROM homebox_inventory")
            conn.executemany(
                "INSERT INTO homebox_inventory (entity_id, name, description, parent_id, is_location, quantity, path, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def find_homebox(self, query: str, location_only: bool = False) -> dict | None:
        query = query.strip().lower()
        if not query:
            return None
        variants = [query]
        if query.endswith("es"):
            variants.append(query[:-2])
        if query.endswith("s") and not query.endswith("ss"):
            variants.append(query[:-1])
        with self.connect() as conn:
            row = None
            for term in variants:
                row = conn.execute(
                    """SELECT * FROM homebox_inventory
                       WHERE (instr(lower(name), ?) > 0 OR instr(lower(description), ?) > 0)
                         AND (? = 0 OR is_location = 1)
                       ORDER BY CASE WHEN lower(name) = ? THEN 0 ELSE 1 END,
                                CASE WHEN is_location = 0 THEN 0 ELSE 1 END, length(path)
                       LIMIT 1""",
                    (term, term, int(location_only), term),
                ).fetchone()
                if row is not None:
                    break
        if row is None:
            return None
        result = dict(row)
        with self.connect() as conn:
            sighting = conn.execute(
                "SELECT * FROM homebox_visual_sightings WHERE entity_id = ? ORDER BY observed_at DESC LIMIT 1",
                (result["entity_id"],),
            ).fetchone()
        if sighting is not None:
            result["visual_sighting"] = {
                "camera": sighting["camera_name"],
                "zone": sighting["zone_name"],
                "snapshot_path": sighting["snapshot_path"],
                "box": [sighting["bbox_x1"], sighting["bbox_y1"], sighting["bbox_x2"], sighting["bbox_y2"]],
                "confidence": sighting["confidence"],
                "observed_at": sighting["observed_at"],
            }
        return result

    def link_homebox_scan(self, scan: ScanResult) -> int:
        with self.connect() as conn:
            entities = conn.execute("SELECT entity_id, name FROM homebox_inventory").fetchall()
            matched = 0
            for detection in scan.detections:
                if detection.confidence < 0.75:
                    continue
                description = f"{detection.label} {detection.description}".lower()
                candidates = [
                    entity for entity in entities
                    if len(entity["name"].strip()) >= 4
                    and (len(entity["name"].split()) >= 2 or any(char.isdigit() for char in entity["name"]))
                    and re.search(r"\b" + re.escape(entity["name"].lower()) + r"\b", description)
                ]
                if not candidates:
                    continue
                entity = max(candidates, key=lambda item: len(item["name"]))
                conn.execute(
                    """INSERT INTO homebox_visual_sightings
                       (entity_id, camera_name, zone_name, snapshot_path,
                        bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, observed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entity["entity_id"], scan.camera, scan.zone, scan.snapshot_path,
                     *detection.box, detection.confidence, scan.analyzed_at.isoformat()),
                )
                matched += 1
            return matched

    def homebox_contents(self, parent_id: str, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """WITH RECURSIVE descendants(entity_id, depth) AS (
                     SELECT entity_id, 1 FROM homebox_inventory WHERE parent_id = ?
                     UNION ALL
                     SELECT h.entity_id, d.depth + 1 FROM homebox_inventory h
                     JOIN descendants d ON h.parent_id = d.entity_id WHERE d.depth < 10
                   )
                   SELECT h.entity_id, h.name, h.path, h.quantity, h.is_location
                   FROM homebox_inventory h JOIN descendants d ON h.entity_id = d.entity_id
                   ORDER BY h.path LIMIT ?""",
                (parent_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
        normalized = query.strip().lower()
        variants = {normalized, normalized.rstrip("s") if normalized.endswith("s") and not normalized.endswith("ss") else normalized}
        patterns = [f"%{part}%" for part in variants if part]
        if not patterns:
            return None
        where = " OR ".join("(lower(m.object_name) LIKE ? OR lower(m.object_category) LIKE ? OR lower(m.description) LIKE ?)" for _ in patterns)
        with self.connect() as conn:
            row = conn.execute(
                f"""
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
                WHERE {where}
                ORDER BY datetime(m.last_seen_at) DESC
                LIMIT 1
                """,
                tuple(value for pattern in patterns for value in (pattern, pattern, pattern)),
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
            last_seen_at=self._parse_time(row["last_seen_at"]),
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
                    last_seen_at=self._parse_time(row["last_seen_at"]),
                    snapshot_path=row["snapshot_path"],
                    clip_path=row["clip_path"],
                    bbox=None,
                )
            )
        return results

    def has_event(self, event_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM processed_camera_events WHERE event_id = ?", (event_id,)).fetchone() is not None

    def record_event(self, event_id: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO processed_camera_events (event_id, processed_at) VALUES (?, ?)", (event_id, datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _parse_time(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value)
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
