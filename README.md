# Jarvis Workshop Assistant

A local workshop assistant with voice commands, Frigate camera capture, tool memory, a projector view, research, and controlled Home Assistant actions. The original macOS `server.py` remains in the repository for reference; the Docker stack runs `backend.main`.

## Start

1. Copy `.env.example` to `.env` and set a unique `JARVIS_ACCESS_TOKEN`, the reachable Bifrost and Frigate URLs, camera names, and Home Assistant allowlist.
2. Configure router, research, and vision provider/model routes in Bifrost. Ensure Bifrost and speech endpoints are reachable from Docker. The bundled SearXNG service handles web and image search.
3. Run `docker compose up --build`.

Pages:

- `http://localhost:5173/` for voice or typed commands and the orb
- `http://localhost:5173/dashboard.html` for camera scans and memory lookup
- `http://localhost:5173/projector.html` for cards, bounding boxes, and footprints
- `http://localhost:5173/gestures.html` for a dedicated USB gesture camera
- `http://localhost:8000/docs` for the API

The browser uses push to talk. STT and TTS run through the endpoints configured in `.env`. A microphone normally requires localhost or HTTPS in the browser.

## Example Flow

1. Say or type “Scan the pegboard.” Jarvis fetches `/<camera>/latest.jpg` from Frigate, analyzes the frame with the configured vision model, and stores detections in hybrid memory.
2. Ask “Where are my screwdrivers?” Jarvis searches object memory, gives the last observed zone and time, and sends the stored image and box to the projector page.
3. Ask “Research a Dell R630 and project its footprint.” Jarvis searches through SearXNG, asks the research model for sourced dimensions, and displays an outline. With projector measurements set to zero, this outline is explicitly illustrative.
4. Ask “What is in the blue parts bin?” Jarvis answers from its read-only Homebox inventory cache, including nested items. Ask “Identify the tool on the workbench” for a fresh Frigate snapshot, Bifrost vision analysis, and web image candidates.

## Configuration

See [.env.example](.env.example) and [Operations](docs/operations.md). Configure `BIFROST_BASE_URL` and all three `BIFROST_*_MODEL` routes before startup; Jarvis refuses to fall back to a different model provider. Set `BIFROST_API_KEY` only when required. Configure `FRIGATE_URL` and `JARVIS_CAMERAS_JSON` for cameras; `HOMEBOX_URL` and `HOMEBOX_API_KEY` are optional until Homebox is running again.

Frigate provides latest frames and event snapshots. Jarvis can read Frigate’s RTSP restream without direct camera credentials. The Home Assistant adapter only accepts explicitly allowed entity IDs; lock, cover, climate, and switch writes require a second confirmation. The LLM cannot supply an arbitrary URL or direct API call.

## What Is Implemented

- Frigate latest frame capture, completed event ingestion through optional MQTT, and event snapshots
- Snapshot based tool detection through a vision model
- Configurable periodic Frigate scans and completed-event ingestion for automatic sightings
- PostgreSQL/pgvector semantic retrieval and explicit Markdown-style inventory relationships
- Grounding DINO / YOLO detector service with crop-based VLM identification
- Native Frigate RTSP live view with refreshed bounding boxes
- Read-only Homebox inventory sync, nested box contents, and tentative camera-to-box label matches
- Image-assisted identification with SearXNG image candidates; camera images stay on the local model path
- Websocket projector cards, bounding boxes, and sourced dimension footprints
- Local STT/TTS endpoint integration and browser push to talk
- Small model routing, SearXNG research, and Home Assistant allowlist
- Dedicated hand camera page with local MediaPipe model and pinch/drag events
- HTTP satellite turn endpoint for a future push to talk ESP32 client

## Physical Setup Still Needed

The repo cannot know your camera addresses, entity IDs, model names, projector geometry, or ESP32 pinout. Populate `.env` and connect those devices before testing them. For physical size projection, measure the full displayed browser width and height on the surface and set `PROJECTOR_WIDTH_MM` and `PROJECTOR_HEIGHT_MM`. That simple linear scale does not correct keystone or perspective; do not claim exact physical size without a camera and projector calibration procedure.

Object movement is recorded conservatively. A missing tool after motion is reported as a lost sighting, never as proof that a named person carried it or took it outside. Homebox contents are inventory records, not proof of current physical presence. Camera-to-box links are tentative name/label matches. The system does not train a custom detector or continuously analyze video.

## Docs

- [Hybrid memory, live view, and dedicated detection](docs/hybrid-memory-and-detection.md)

- [Operations](docs/operations.md)
- [Bifrost, Frigate, and Homebox inventory](docs/bifrost-homebox-inventory.md)
- [Architecture](docs/target-architecture.md)
- [Hardware and integrations](docs/hardware-and-integrations.md)
- [Roadmap](docs/implementation-roadmap.md)
- [Current state audit](docs/current-state-audit.md)

See [LICENSE](LICENSE) for licensing.
