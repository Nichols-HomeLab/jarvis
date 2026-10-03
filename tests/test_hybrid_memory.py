import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from backend.homebox import HomeboxEntity
from backend.schemas import ObjectMemoryRecord, ScanResult, DetectionBox
from backend.storage import Storage
from backend.vision.streaming import CameraStreams
from backend.vision.frigate import FrigateClient
from backend.vision.detector import DetectorVision
from backend.config import Settings, CameraConfig


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    if request.param == "postgresql":
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
        storage = Storage(url, 3)
        with storage.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS schema_migrations")
            for table in ("memory_links", "memories", "object_detections", "object_memories", "homebox_inventory", "homebox_visual_sightings", "processed_camera_events"):
                conn.execute(f"DELETE FROM {table}")
    else:
        storage = Storage(tmp_path / "test.db", 3)
    return storage


def test_inventory_precision_wins_over_semantic_similarity_and_updates_links(store):
    entities = [HomeboxEntity("shop", "Workshop", "", None, True, 0),
        HomeboxEntity("box", "Blue Box", "", "shop", True, 0),
        HomeboxEntity("tool", "Red Screwdriver", "Flat head turning screws", "box", False, 1)]
    store.replace_homebox_inventory(entities)
    notes = store.pending_embeddings("test")
    for row in notes:
        store.set_embedding(row["id"], row["markdown"], [1., 0., 0.], "test")
    store.save_memory(ObjectMemoryRecord(object_name="Red Screwdriver", object_category="screwdriver",
        camera_name="cam", zone_name="bench", confidence=.9))
    visual = next(r for r in store.pending_embeddings("test") if "Red Screwdriver" in r["markdown"])
    store.set_embedding(visual["id"], visual["markdown"], [0., 1., 0.], "test")
    found = store.hybrid_search("red screwdriver", [0., 1., 0.], "test")
    assert found[0].inventory_path == "Workshop / Blue Box / Red Screwdriver"
    assert found[0].relationships == ["Workshop", "Blue Box"]
    assert found[0].retrieval_source == "structured"
    assert len(found) == 1
    entities[2].parent_id = "shop"
    store.replace_homebox_inventory(entities)
    assert store.hybrid_search("red screwdriver")[0].relationships == ["Workshop"]
    assert any("Red Screwdriver" in r["markdown"] for r in store.pending_embeddings("test"))


def test_semantic_query_with_no_literal_match_and_model_isolation(store):
    store.replace_homebox_inventory([HomeboxEntity("tool", "Screwdriver", "", None, False, 1)])
    node = store.pending_embeddings("test")[0]
    store.set_embedding(node["id"], node["markdown"], [1., 0., 0.], "test")
    assert store.hybrid_search("turn threaded fasteners") == []
    assert store.hybrid_search("turn threaded fasteners", [1., 0., 0.], "test")[0].object_name == "Screwdriver"
    assert store.hybrid_search("turn threaded fasteners", [1., 0., 0.], "different") == []
    assert store.hybrid_search("turn threaded fasteners", [0., 1., 0.], "test") == []
    with pytest.raises(ValueError):
        store.set_embedding(node["id"], node["markdown"], [1.], "test")


def test_sync_cycle_does_not_erase_last_good_inventory(store):
    store.replace_homebox_inventory([HomeboxEntity("t", "Hammer", "", None, False, 1)])
    with pytest.raises(ValueError):
        store.replace_homebox_inventory([HomeboxEntity("a", "A", "", "b", True, 0), HomeboxEntity("b", "B", "", "a", True, 0)])
    assert store.find_homebox("Hammer") is not None
    assert store.hybrid_search("Hammer")[0].object_name == "Hammer"


def test_structured_zone_links_bbox_and_event_idempotence(store):
    store.save_scan(ScanResult(camera="cam", zone="Workbench", snapshot_path="/media/a.jpg",
        detections=[DetectionBox(label="pliers", description="needle nose pliers", box=[2, 3, 10, 20], confidence=.9)]))
    result = store.hybrid_search("Workbench")[0]
    assert result.bbox == [2, 3, 10, 20]
    assert result.camera_name == "cam"
    store.record_event("event1"); store.record_event("event1")
    assert store.has_event("event1")
    assert len(store.recent_memories()) == 1


def test_stream_upstream_error_is_not_a_successful_video():
    def respond(request):
        return httpx.Response(404, json={"detail": "missing"})
    streams = CameraStreams(FrigateClient("http://frigate"), transport=httpx.MockTransport(respond))
    async def run():
        with pytest.raises(httpx.HTTPStatusError):
            async with streams.open("Driveway"):
                pass
        assert streams.active == 0
    asyncio.run(run())


def test_detector_crop_refinement_preserves_original_coordinates():
    from PIL import Image
    from io import BytesIO
    image = Image.new("RGB", (640, 480)); data = BytesIO(); image.save(data, "JPEG")
    class Model:
        async def describe_crop(self, crop, label):
            with Image.open(BytesIO(crop)) as picture:
                assert picture.size == (80, 100)
            return "Needle nose pliers, brand unknown"
    def respond(request):
        assert request.url.path == "/detect"
        return httpx.Response(200, json={"detections": [{"label":"pliers", "description":"pliers", "box":[10, 20, 90, 120], "confidence":.9}]})
    settings = Settings(detector_url="http://detector", cameras=[CameraConfig("bench", "bench")])
    vision = DetectorVision(settings, Model(), httpx.MockTransport(respond))
    scan = asyncio.run(vision.analyze_snapshot("bench", "bench", data.getvalue(), "/media/a.jpg"))
    assert scan.detections[0].box == [10, 20, 90, 120]
    assert scan.detections[0].description.startswith("Needle nose")
    assert (scan.image_width, scan.image_height) == (640, 480)


def test_retained_sqlite_import_is_idempotent_and_keeps_bbox(store, tmp_path):
    if not store.postgres:
        pytest.skip("Migration target is PostgreSQL")
    source = Storage(tmp_path / "old.db", 3)
    source.save_scan(ScanResult(camera="cam", zone="bench", snapshot_path="/media/old.jpg",
        detections=[DetectionBox(label="wrench", description="blue wrench", box=[10, 20, 90, 150], confidence=.8)]))
    source.record_event("retained-event")
    counts = store.migrate_sqlite(source.db_path)
    assert counts["object_memories"] == 1
    assert store.has_event("retained-event")
    assert store.hybrid_search("wrench")[0].bbox == [10, 20, 90, 150]
    assert store.migrate_sqlite(source.db_path) == {}
    assert len(store.recent_memories()) == 1


def test_identical_inventory_names_keep_distinct_locations_and_do_not_get_false_visual_links(store):
    store.replace_homebox_inventory([
        HomeboxEntity("shop-a", "Garage", "", None, True, 0),
        HomeboxEntity("shop-b", "Workshop", "", None, True, 0),
        HomeboxEntity("box-a", "Blue Parts Bin", "", "shop-a", True, 0),
        HomeboxEntity("box-b", "Blue Parts Bin", "", "shop-b", True, 0),
        HomeboxEntity("one", "Red Screwdriver", "", "box-a", False, 1),
        HomeboxEntity("two", "Red Screwdriver", "", "box-b", False, 1)])
    results = store.hybrid_search("red screwdriver")
    assert {r.entity_id for r in results} == {"one", "two"}
    scan = ScanResult(camera="cam", zone="bench", snapshot_path="/media/a.jpg",
        detections=[DetectionBox(label="bin", description="Blue Parts Bin", box=[1, 2, 10, 20], confidence=.9)])
    assert store.link_homebox_scan(scan) == 0
    assert len(store.find_homebox("Blue Parts Bin")["alternatives"]) == 1

    box = store.find_homebox("Workshop / Blue Parts Bin", location_only=True)
    assert box["entity_id"] == "box-b" and not box["alternatives"]
    from backend.service import JarvisLocalService
    from backend.schemas import AssistantCommandRequest
    service = JarvisLocalService(Settings(), store, None, None, None)
    answer = asyncio.run(service.find_tool("red screwdriver"))
    assert answer.inventory_path is None and answer.bbox is None
    assert {item["entity_id"] for item in answer.alternative_locations} == {"one", "two"}
    answer = asyncio.run(service.handle_command(AssistantCommandRequest(text="What's in Workshop / Blue Parts Bin?")))
    assert answer.route == "homebox_contents" and "Red Screwdriver" in answer.text


def test_crop_assessment_is_description_not_an_inventory_identity(store):
    for assessment in ("Image too dark; brand unknown", "No readable label; model unknown"):
        store.save_scan(ScanResult(camera="cam", zone="bench", snapshot_path="/media/a.jpg",
            detections=[DetectionBox(label="drill", description=assessment, box=[1, 2, 10, 20], confidence=.9)]))
    found = store.hybrid_search("drill")
    assert len(found) == 1 and found[0].object_name == "drill"
    assert found[0].description == "No readable label; model unknown"
    assert found[0].bbox == [1, 2, 10, 20]


def test_disconnect_cancellation_reaps_stream_process(monkeypatch):
    import anyio
    import sys
    processes = []
    spawn = asyncio.create_subprocess_exec
    async def fake_ffmpeg(*args, **kwargs):
        process = await spawn(sys.executable, "-u", "-c",
            "import sys,time\nwhile True:\n sys.stdout.buffer.write(b'\\xff\\xd8frame\\xff\\xd9'); sys.stdout.buffer.flush(); time.sleep(.02)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_ffmpeg)
    streams = CameraStreams(FrigateClient("http://frigate"), "rtsp://frigate:8554")
    async def run():
        with anyio.CancelScope() as scope:
            async with streams.open("cam") as (frames, _):
                assert b"image/jpeg" in await anext(frames)
                scope.cancel()
                await anyio.sleep(0)
        assert streams.active == 0
        assert processes[0].returncode is not None
    anyio.run(run)
