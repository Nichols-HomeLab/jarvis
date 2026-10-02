# Hybrid memory and dedicated tool detection

Jarvis now separates localisation, identification, inventory facts, and retrieval.

## Camera pipeline

Frigate's existing cameras are used for integration testing. Each configured camera
can supply `detection_labels`; the driveway and doorbell use labels such as car and
person to test coordinates. A future tool camera can omit that override to use the
hand, power, outdoor tool, and storage-container vocabulary in `backend/vision/detector.py`.

1. Capture an immutable full-resolution Frigate snapshot.
2. Send it and the label vocabulary to the dedicated `detector` service.
3. Grounding DINO Tiny returns pixel boxes, object labels, and confidence.
4. Crop each of the most confident objects and send the crop to the existing
   Bifrost vision model to refine its type or read a visible brand/model label.
5. Keep the detector's original box and score. A failed crop assessment leaves
   the basic detection usable. A failed detector request is reported as an error.
6. Persist observations and match sufficiently distinctive Homebox names
   conservatively. A vision match remains tentative; it does not move inventory.

`DETECTOR_MODE=yolo` uses YOLO26n or the weights configured in `YOLO_MODEL`.
The bundled pretrained weights recognise their COCO classes, **not** the full
workshop vocabulary. Use Grounding DINO initially. Review tool-camera annotations,
create train/validation splits in a YOLO dataset, and run
`python detector/train_yolo.py /data/dataset/data.yaml --device cpu` (or a suitable
training GPU). Install the resulting `best.pt` in the detector and set `YOLO_MODEL`.
No custom tool training is claimed before a reviewed dataset exists.

Sources: [Ultralytics YOLO26](https://docs.ultralytics.com/models/yolo26/),
[Grounding DINO processor](https://huggingface.co/docs/transformers/model_doc/grounding-dino).

## Live view

`GET /api/v2/cameras/{name}/stream` requires the same session cookie as the dashboard.
With `FRIGATE_RTSP_URL=rtsp://frigate.random.svc.cluster.local:8554`, FFmpeg reads
Frigate's native RTSP restream and produces browser-compatible MJPEG, without
exposing camera credentials. Without that setting, the server proxies Frigate's
supported MJPEG endpoint. Unknown cameras return 404 and unavailable sources 502.
Processes are stopped on disconnect; at most four viewers are allowed per backend.

The dashboard opens/closes each stream and scans while viewing. Boxes use the
original snapshot dimensions, so they scale with the live image. Their caption
shows the scan time and boxes expire after 45 seconds. These are refreshed snapshot
assessments; there is no claim that a box is tracked between frames. Live scanning
stops when the view closes or the page navigates away.

## Memory

Production uses the shared PostgreSQL primary (`postgresql-ha-imported-rw`) with
pgvector. DatabaseRole and Database resources in Flux provision the Jarvis role,
database, and vector extension. The role has no superuser or database-creation
privileges. Credentials stay in SOPS secrets; health output does not expose a DSN.
SQLite remains supported for isolated local development and contract tests.

`memories` stores stable source identifiers, Markdown-style notes, source payloads,
384-dimensional BGE-small embeddings, embedding model names, and update times.
`memory_links` stores explicit directed relationships:

- Homebox item → `is_inside` → parent box/location
- Vision observation → `seen_in` → camera zone

Homebox sync atomically replaces the inventory and updates notes and parent links.
Removed entries disappear from the current graph. Duplicate IDs or a cyclic
hierarchy fail before the previous cache is erased. Changing a note invalidates its
embedding. The indexing loop embeds changed notes in batches using the bundled CPU
model; unchanged notes keep their vectors. Compare only vectors from the same model.

`GET /api/v2/memories/search?q=...` merges literal matches, linked notes, and pgvector
cosine candidates. Explicit inventory matches rank first, followed by visual/linked
matches and then semantic matches above the similarity threshold. Results include
source, ranking score, inventory path, ancestry, and the original note. Repeated
sightings are deduplicated. A recorded inventory location is distinguished from a
camera observation. Assistant and dashboard searches use this same retrieval path.
If embeddings are unavailable, explicit retrieval remains usable and the failure is
logged; `/api/v2/memories/status` reports whether notes are actually embedded.

On first PostgreSQL startup, the retained `data/jarvis_local.db` history is imported
transactionally and marked in `schema_migrations`. Observation/event identifiers
and original media paths are retained. The source database remains on the PVC.

## Verification

```
python -m pytest tests/test_local_backend.py tests/test_inventory_integrations.py tests/test_hybrid_memory.py
cd frontend && npm ci && npm run build
```

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database to run the same retrieval
contracts against pgvector. Supply credentials through `PGPASSWORD` rather than a
password-bearing test URL. The PostgreSQL fixtures clear their named tables.
Verify production separately: authenticated Homebox sync, an actual camera scan,
multiple changing MJPEG frames, live box rendering, semantic search, and Flux's
observed revision.
