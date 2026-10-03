from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from backend.schemas import ObjectMemoryRecord, ScanResult, SearchResult
from backend.homebox import HomeboxEntity


class DatabaseConnection:
    """One transaction API; queries below use portable SQL and bound values."""
    def __init__(self, raw, postgres):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, parameters=()):
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self.raw.execute(sql, parameters)

    def executemany(self, sql, rows):
        if self.postgres:
            sql = sql.replace("?", "%s")
            with self.raw.cursor() as cursor:
                cursor.executemany(sql, rows)
        else:
            self.raw.executemany(sql, rows)

    def executescript(self, sql):
        if self.postgres:
            sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            for statement in sql.split(";"):
                if statement.strip():
                    self.raw.execute(statement)
        else:
            self.raw.executescript(sql)


class Storage:
    def __init__(self, database_url: str | Path, embedding_dimensions: int = 384):
        self.postgres = str(database_url).startswith(("postgresql://", "postgres://"))
        self.database_url = str(database_url)
        self.db_path = Path(str(database_url).removeprefix("sqlite:///")) if not self.postgres else None
        self.embedding_dimensions = embedding_dimensions
        if not 1 <= embedding_dimensions <= 2000:
            raise ValueError("Embedding dimensions must be between 1 and 2000")
        if self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[DatabaseConnection]:
        raw = psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10) if self.postgres else sqlite3.connect(self.db_path)
        if not self.postgres:
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
        try:
            yield DatabaseConnection(raw, self.postgres)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            if self.postgres:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
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

            vector_type = f"vector({self.embedding_dimensions})" if self.postgres else "TEXT"
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    embedding {vector_type},
                    embedding_model TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_links (
                    source_id BIGINT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    target_id BIGINT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, relation_type),
                    CHECK (source_id <> target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_id);
            """)

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
            conn.execute("DELETE FROM memory_links WHERE source_id IN (SELECT id FROM memories WHERE source = 'homebox')")
            existing = conn.execute("SELECT id, source_key FROM memories WHERE source = 'homebox'").fetchall()
            for row in existing:
                if row["source_key"].removeprefix("homebox:") not in by_id:
                    conn.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
            ids = {}
            for e in entities:
                path = path_for(e)
                result = SearchResult(object_name=e.name, object_category="location" if e.is_location else "inventory",
                    description=e.description, camera_name="", zone_name=path, action="inventory", confidence=1,
                    last_seen_at=datetime.now(timezone.utc), inventory_path=path, entity_id=e.entity_id)
                ids[e.entity_id] = self._upsert_node(conn, "homebox:" + e.entity_id, "homebox", e.name,
                    result.object_category, f"# {e.name}\n\n{e.description}\n\nLocation: {path}", result.model_dump_json())
            for e in entities:
                if e.parent_id in ids:
                    self._link(conn, ids[e.entity_id], ids[e.parent_id], "is_inside")
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
            path_rows = conn.execute("SELECT * FROM homebox_inventory WHERE lower(path)=? AND (?=0 OR is_location=1)", (query, int(location_only))).fetchall()
            row = path_rows[0] if path_rows else None
            for term in ([] if row is not None else variants):
                row = conn.execute(
                    """SELECT * FROM homebox_inventory
                       WHERE (lower(name) LIKE ? ESCAPE '!' OR lower(description) LIKE ? ESCAPE '!')
                         AND (? = 0 OR is_location = 1)
                       ORDER BY CASE WHEN lower(name) = ? THEN 0 ELSE 1 END,
                                CASE WHEN is_location = 0 THEN 0 ELSE 1 END, length(path)
                       LIMIT 1""",
                    (self._pattern(term), self._pattern(term), int(location_only), term),
                ).fetchone()
                if row is not None:
                    break
        if row is None:
            return None
        result = dict(row)
        with self.connect() as conn:
            alternatives = ([r for r in path_rows if r["entity_id"] != result["entity_id"]] if path_rows else
                conn.execute("SELECT entity_id, path FROM homebox_inventory WHERE lower(name)=? AND entity_id <> ?", (result["name"].lower(), result["entity_id"])).fetchall())
            result["alternatives"] = [dict(r) for r in alternatives]
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
                longest = max(len(item["name"]) for item in candidates)
                candidates = [item for item in candidates if len(item["name"]) == longest]
                if len(candidates) != 1:
                    continue  # identical labels cannot establish which inventory instance was seen
                entity = candidates[0]
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

    def save_memory(self, memory: ObjectMemoryRecord, conn: DatabaseConnection | None = None) -> None:
        if conn is None:
            with self.connect() as connection:
                self.save_memory(memory, connection)
            return
        conn.execute("""INSERT INTO object_memories (
            object_name, object_category, description, camera_name, zone_name, action,
            actor, direction, last_seen_at, confidence, snapshot_path, clip_path, raw_model_output
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (memory.object_name, memory.object_category, memory.description, memory.camera_name,
             memory.zone_name, memory.action, memory.actor, memory.direction,
             memory.last_seen_at.isoformat(), memory.confidence, memory.snapshot_path,
             memory.clip_path, json.dumps(memory.raw_model_output)))
        self._remember(conn, memory)

    def _remember(self, conn, memory):
        result = SearchResult(**memory.model_dump(exclude={"raw_model_output"}))
        bbox = conn.execute("""SELECT bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM object_detections
            WHERE snapshot_path = ? AND label = ? AND description = ? ORDER BY id DESC LIMIT 1""",
            (memory.snapshot_path, memory.object_category, memory.description)).fetchone()
        if bbox:
            result.bbox = [bbox[f"bbox_{axis}"] for axis in ("x1", "y1", "x2", "y2")]
        key = "vision:" + hashlib.sha256(f"{memory.camera_name}:{memory.zone_name}:{memory.object_name.lower()}".encode()).hexdigest()
        current = conn.execute("SELECT payload FROM memories WHERE source_key = ?", (key,)).fetchone()
        if current and SearchResult.model_validate_json(current["payload"]).last_seen_at > memory.last_seen_at:
            return  # historical imports must not replace a more recent sighting
        node = self._upsert_node(conn, key, "vision", memory.object_name, memory.object_category,
            f"# {memory.object_name}\n\n{memory.description}\n\nSeen in: {memory.zone_name} ({memory.camera_name})", result.model_dump_json())
        zone = self._upsert_node(conn, f"zone:{memory.camera_name}:{memory.zone_name}", "zone", memory.zone_name,
            "location", f"# {memory.zone_name}\n\nCamera: {memory.camera_name}", "{}")
        self._link(conn, node, zone, "seen_in")

    def find_last_seen(self, query: str) -> SearchResult | None:
        normalized = query.strip().lower()
        variants = {normalized, normalized.rstrip("s") if normalized.endswith("s") and not normalized.endswith("ss") else normalized}
        patterns = [self._pattern(part) for part in variants if part]
        if not patterns:
            return None
        where = " OR ".join("(lower(m.object_name) LIKE ? ESCAPE '!' OR lower(m.object_category) LIKE ? ESCAPE '!' OR lower(m.description) LIKE ? ESCAPE '!')" for _ in patterns)
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
                ORDER BY m.last_seen_at DESC
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
                ORDER BY last_seen_at DESC
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
            conn.execute("INSERT INTO processed_camera_events (event_id, processed_at) VALUES (?, ?) ON CONFLICT (event_id) DO NOTHING", (event_id, datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _parse_time(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value)
        return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)

    @staticmethod
    def _pattern(text: str) -> str:
        return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"

    def _upsert_node(self, conn, key, source, title, category, markdown, payload):
        row = conn.execute("""INSERT INTO memories (source_key, source, title, category, markdown, payload, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_key) DO UPDATE SET title=excluded.title, category=excluded.category,
                embedding=CASE WHEN memories.markdown=excluded.markdown THEN memories.embedding ELSE NULL END,
                markdown=excluded.markdown, payload=excluded.payload, updated_at=excluded.updated_at
            RETURNING id""", (key, source, title, category, markdown, payload, datetime.now(timezone.utc).isoformat())).fetchone()
        return row["id"]

    @staticmethod
    def _link(conn, source, target, relation):
        conn.execute("INSERT INTO memory_links VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (source, target, relation))

    def pending_embeddings(self, model: str, limit: int = 64) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id, markdown FROM memories WHERE embedding IS NULL OR embedding_model <> ? LIMIT ?", (model, limit)).fetchall()
        return [dict(row) for row in rows]

    def set_embedding(self, memory_id: int, markdown: str, vector: list[float], model: str):
        if len(vector) != self.embedding_dimensions or not all(math.isfinite(x) for x in vector) or not any(vector):
            raise ValueError("Invalid memory embedding")
        with self.connect() as conn:
            # Do not attach an old embedding if a concurrent sync changed the note.
            conn.execute("UPDATE memories SET embedding = ?, embedding_model = ? WHERE id = ? AND markdown = ?",
                         (json.dumps(vector), model, memory_id, markdown))

    def hybrid_search(self, query: str, vector: list[float] | None = None, model: str = "", limit: int = 10, min_similarity: float = 0.5) -> list[SearchResult]:
        words = re.findall(r"[\w-]+", query.lower())
        words = [w for w in words if w not in {"find", "something", "similar", "like", "to", "a", "an", "the", "my", "in", "inside", "where", "is", "are", "me"}]
        if not words:
            return []
        # Every meaningful query word must match; escape SQL wildcards.
        groups, params = [], []
        for word in words:
            variants = [word, word[:-1]] if word.endswith("s") and not word.endswith("ss") else [word]
            groups.append("(" + " OR ".join("lower(title || ' ' || markdown) LIKE ? ESCAPE '!'" for _ in variants) + ")")
            params.extend(self._pattern(w) for w in variants)
        candidates = {}
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM memories WHERE " + " AND ".join(groups), tuple(params)).fetchall()
            for row in rows:
                if row["source"] == "zone":
                    linked = conn.execute("SELECT m.* FROM memories m JOIN memory_links l ON m.id=l.source_id WHERE l.target_id=?", (row["id"],)).fetchall()
                    for child in linked:
                        candidates[child["id"]] = (dict(child), 1.5, {"structured"})
                else:
                    score = 3.0 if row["source"] == "homebox" else 2.0
                    candidates[row["id"]] = (dict(row), score, {"structured"})
            if vector is not None:
                if len(vector) != self.embedding_dimensions or not all(math.isfinite(x) for x in vector) or not any(vector):
                    raise ValueError("Invalid query embedding")
                if self.postgres:
                    rows = conn.execute("""SELECT *, 1 - (embedding <=> ?::vector) AS similarity FROM memories
                        WHERE embedding IS NOT NULL AND embedding_model=? AND source <> 'zone'
                        ORDER BY embedding <=> ?::vector LIMIT ?""", (json.dumps(vector), model, json.dumps(vector), limit * 3)).fetchall()
                else:
                    rows = [dict(r) for r in conn.execute("SELECT * FROM memories WHERE embedding IS NOT NULL AND embedding_model=? AND source <> 'zone'", (model,)).fetchall()]
                    norm = math.sqrt(sum(x*x for x in vector))
                    for row in rows:
                        other = json.loads(row["embedding"])
                        row["similarity"] = sum(a*b for a,b in zip(vector, other)) / (norm * math.sqrt(sum(x*x for x in other)))
                for row in rows:
                    similarity = float(row["similarity"])
                    if similarity < min_similarity:
                        continue
                    if row["id"] in candidates:
                        prior, score, sources = candidates[row["id"]]
                        candidates[row["id"]] = (prior, score + similarity * 0.1, sources | {"vector"})
                    else:
                        candidates[row["id"]] = (dict(row), similarity, {"vector"})
            results = []
            for row, score, sources in candidates.values():
                result = SearchResult.model_validate_json(row["payload"])
                result.memory_id = row["id"]
                result.retrieval_source = "hybrid" if len(sources) > 1 else next(iter(sources))
                result.retrieval_score = score
                result.markdown = row["markdown"]
                links = conn.execute("""WITH RECURSIVE parents(id, depth) AS (
                    SELECT target_id, 1 FROM memory_links WHERE source_id=? AND relation_type='is_inside'
                    UNION ALL SELECT l.target_id, p.depth+1 FROM memory_links l JOIN parents p ON l.source_id=p.id
                        WHERE l.relation_type='is_inside' AND p.depth < 20)
                    SELECT m.title FROM memories m JOIN parents p ON m.id=p.id ORDER BY p.depth DESC""", (row["id"],)).fetchall()
                result.relationships = [r["title"] for r in links]
                if result.entity_id:
                    item = self.find_homebox(result.object_name)
                    if item and item["entity_id"] == result.entity_id and item.get("visual_sighting"):
                        sighting = item["visual_sighting"]
                        result.camera_name, result.snapshot_path, result.bbox = sighting["camera"], sighting["snapshot_path"], sighting["box"]
                results.append(result)
        results.sort(key=lambda r: (r.retrieval_score, r.last_seen_at), reverse=True)
        # A repeated camera sighting must not crowd out other candidates.
        unique = {}
        inventory_names = {r.object_name.lower() for r in results if r.entity_id}
        for result in results:
            name = result.object_name.lower()
            if not result.entity_id and name in inventory_names:
                continue
            unique.setdefault(result.entity_id or name, result)
        return list(unique.values())[:limit]

    def memory_stats(self) -> dict:
        with self.connect() as conn:
            return {"backend": "postgresql" if self.postgres else "sqlite",
                "memories": conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"],
                "embedded": conn.execute("SELECT COUNT(*) AS n FROM memories WHERE embedding IS NOT NULL").fetchone()["n"],
                "links": conn.execute("SELECT COUNT(*) AS n FROM memory_links").fetchone()["n"]}

    def migrate_sqlite(self, path: Path) -> dict[str, int]:
        """Import the retained local database once, without deleting it."""
        if not self.postgres or not path.is_file():
            return {}
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            if conn.execute("SELECT 1 FROM schema_migrations WHERE name='sqlite-import-v1'").fetchone():
                return {}
            source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            source.row_factory = sqlite3.Row
            counts = {}
            try:
                tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ("object_memories", "object_detections", "camera_zones", "processed_camera_events", "homebox_inventory", "homebox_visual_sightings"):
                    if table not in tables:
                        continue
                    rows = source.execute(f"SELECT * FROM {table}").fetchall()
                    counts[table] = len(rows)
                    for row in rows:
                        columns = list(row.keys())
                        conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) ON CONFLICT DO NOTHING", tuple(row))
                    if table not in {"processed_camera_events", "homebox_inventory"}:
                        conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {table}")
                if "object_memories" in tables:
                    for row in source.execute("SELECT * FROM object_memories ORDER BY last_seen_at"):
                        record = dict(row); record.pop("id")
                        record["raw_model_output"] = json.loads(record["raw_model_output"] or "{}")
                        self._remember(conn, ObjectMemoryRecord.model_validate(record))
                conn.execute("INSERT INTO schema_migrations VALUES ('sqlite-import-v1', ?)", (datetime.now(timezone.utc).isoformat(),))
            finally:
                source.close()
        if "homebox_inventory" in tables:
            with self.connect() as conn:
                rows = conn.execute("SELECT * FROM homebox_inventory").fetchall()
            self.replace_homebox_inventory([HomeboxEntity(r["entity_id"], r["name"], r["description"], r["parent_id"], bool(r["is_location"]), r["quantity"]) for r in rows])
        return counts
