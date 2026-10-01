# Jarvis Workshop Assistant

A local workshop assistant with voice commands, Frigate camera capture, tool memory, a projector view, research, and controlled Home Assistant actions. The original macOS `server.py` remains in the repository for reference; the Docker stack runs `backend.main`.

## Start

1. Copy `.env.example` to `.env` and set a unique `JARVIS_ACCESS_TOKEN`, your actual Frigate URL, camera names, local model endpoints, and Home Assistant allowlist.
2. Ensure Frigate, your OpenAI-compatible model server, and speech endpoints are reachable from Docker. The bundled SearXNG service handles web search.
3. Run `docker compose up --build`.

Pages:

- `http://localhost:5173/` for voice or typed commands and the orb
- `http://localhost:5173/dashboard.html` for camera scans and memory lookup
- `http://localhost:5173/projector.html` for cards, bounding boxes, and footprints
- `http://localhost:5173/gestures.html` for a dedicated USB gesture camera
- `http://localhost:8000/docs` for the API

The browser uses push to talk. STT and TTS run through the endpoints configured in `.env`. A microphone normally requires localhost or HTTPS in the browser.

## Example Flow

1. Say or type “Scan the pegboard.” Jarvis fetches `/<camera>/latest.jpg` from Frigate, analyzes the frame with the configured vision model, and stores detections in SQLite.
2. Ask “Where are my screwdrivers?” Jarvis searches object memory, gives the last observed zone and time, and sends the stored image and box to the projector page.
3. Ask “Research a Dell R630 and project its footprint.” Jarvis searches through SearXNG, asks the research model for sourced dimensions, and displays an outline. With projector measurements set to zero, this outline is explicitly illustrative.

## Configuration

See [.env.example](.env.example) and [Operations](docs/operations.md). The main variables are `JARVIS_ACCESS_TOKEN`, `FRIGATE_URL`, `JARVIS_CAMERAS_JSON`, `OPENAI_BASE_URL`, `OPENAI_ROUTER_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_RESEARCH_MODEL`, `STT_BASE_URL`, `TTS_BASE_URL`, `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN`, and `HA_ALLOWED_ENTITIES`.

Frigate provides latest frames and event snapshots. Jarvis never needs direct camera credentials or RTSP access. The Home Assistant adapter only accepts explicitly allowed entity IDs; lock, cover, climate, and switch writes require a second confirmation. The LLM cannot supply an arbitrary URL or direct API call.

## What Is Implemented

- Frigate latest frame capture, completed event ingestion through optional MQTT, and event snapshots
- Snapshot based tool detection through a vision model
- SQLite tool locations and last seen lookup
- Websocket projector cards, bounding boxes, and sourced dimension footprints
- Local STT/TTS endpoint integration and browser push to talk
- Small model routing, SearXNG research, and Home Assistant allowlist
- Dedicated hand camera page with local MediaPipe model and pinch/drag events
- HTTP satellite turn endpoint for a future push to talk ESP32 client

## Physical Setup Still Needed

The repo cannot know your camera addresses, entity IDs, model names, projector geometry, or ESP32 pinout. Populate `.env` and connect those devices before testing them. For physical size projection, measure the full displayed browser width and height on the surface and set `PROJECTOR_WIDTH_MM` and `PROJECTOR_HEIGHT_MM`. That simple linear scale does not correct keystone or perspective; do not claim exact physical size without a camera and projector calibration procedure.

Object movement is recorded conservatively. A missing tool after motion is reported as a lost sighting, never as proof that a named person carried it or took it outside. The current system does not train a custom tool detector or continuously analyze video.

## Docs

- [Operations](docs/operations.md)
- [Architecture](docs/target-architecture.md)
- [Hardware and integrations](docs/hardware-and-integrations.md)
- [Roadmap](docs/implementation-roadmap.md)
- [Current state audit](docs/current-state-audit.md)

See [LICENSE](LICENSE) for licensing.
