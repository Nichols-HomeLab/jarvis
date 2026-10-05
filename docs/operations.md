# Operations

See [Bifrost, Frigate, and Homebox Inventory](bifrost-homebox-inventory.md) for the automatic scanning and box-contents workflow.

## Access Control

Set `JARVIS_ACCESS_TOKEN` to a unique random value of at least 32 characters before starting the backend. Each browser page prompts for it once and receives an HTTP-only, one-day session cookie. API, media, and WebSocket access require that session. Configure `CORS_ORIGINS` with the exact browser origins used from other hosts, including scheme and port. Frigate webhooks and satellites use their separate `MOTION_WEBHOOK_TOKEN` and `SATELLITE_TOKEN`, not the browser token. Do not expose the Vite development server or the Frigate/MQTT endpoints to the public internet; use a trusted LAN or a TLS reverse proxy. Change the access token to invalidate all browser sessions.

## Direct RTSP cameras

Open the Vision Dashboard and use **Add camera**. Enter a Jarvis name, the full
camera URL such as `rtsp://user:password@camera:554/stream`, a zone, and optional
detection labels. Percent-encode special characters in the username or password.
Jarvis uses FFmpeg over RTSP/TCP for both snapshots and browser MJPEG live view.
No Frigate entry is needed. Live views show periodically refreshed detection
boxes; they are observations rather than per-frame tracking.

Camera URLs persist in the active database, are masked while entered, and never
appear in camera-list or validation responses. `JARVIS_CAMERAS_JSON` can seed an
empty database with `rtsp_url` entries; subsequent changes use the dashboard.
An empty list remains empty across restarts. Camera removal stops future scans,
and the live-view process is reaped when the browser closes or refreshes a view.

## Optional legacy Frigate integration

Set `FRIGATE_URL` to an internal Frigate endpoint, such as `http://frigate:5000`, or to the authenticated port `8971` behind HTTPS. If authentication is enabled, provide `FRIGATE_TOKEN` or `FRIGATE_USER` and `FRIGATE_PASSWORD`. Use camera names exactly as Frigate exposes them in `JARVIS_CAMERAS_JSON`; `name` is Jarvis's command name, `frigate_name` is the Frigate camera ID, and `zone_name` is the spoken location.

The server calls Frigate's [latest frame endpoint](https://docs.frigate.video/integrations/api/latest-frame-camera-name-latest-extension-get/) for scans and its [event snapshot endpoint](https://docs.frigate.video/integrations/api/event-snapshot-events-event-id-snapshot-jpg-get/) for event ingestion. Frigate may return a preview frame when a camera is offline, so confirm camera availability before relying on a recent sighting.

For automatic event ingestion, set `MQTT_HOST` and optionally `MQTT_USER`, `MQTT_PASSWORD`, and `MQTT_TOPIC_PREFIX`. Jarvis subscribes to Frigate's [tracked object events](https://docs.frigate.video/integrations/mqtt/) and processes only completed events. Duplicate event IDs are ignored. Alternatively, POST an event ID to `/api/v2/events/frigate/{event_id}` with `X-Jarvis-Token` matching `MOTION_WEBHOOK_TOKEN`. Jarvis fetches the image through Frigate and stores detections. It does not attribute object movement to a person from a single event image.

## Models And Voice

`BIFROST_BASE_URL` must point at a reachable Bifrost OpenAI-compatible endpoint. Jarvis refuses to start if it or any of the three Bifrost model routes is missing; legacy `OPENAI_*` settings no longer select another provider. The cluster's internal route is `http://bifrost.external.svc.cluster.local:8080/openai`, not `/v1`; it cannot be used directly from local Docker Desktop. Configure `BIFROST_API_KEY` when needed, and set the router, research, and vision model IDs separately. Vision requires image input support. Responses that cannot be parsed or validated fail the scan; mock vision is disabled by default.

`STT_BASE_URL` must serve `POST /audio/transcriptions`. `TTS_BASE_URL` must serve `POST /audio/speech`, including MP3 for the browser and WAV for satellites. These endpoints can be separate local services. If they are not configured, typed commands still work and the browser receives text responses.

## Web And Home Assistant

The included SearXNG container serves JSON search and image results to the backend. Camera images stay on the local model path; only a text description is used for image search. The assistant sends short snippets to the research model and includes source URLs. Research results should be checked before using dimensions to make a physical fit decision.

Set `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN`, and an exact comma-separated `HA_ALLOWED_ENTITIES` list. Unlisted entities fail validation. Risky writes return a short-lived confirmation token to the browser; the Confirm button submits it once. There is no generic arbitrary service or URL execution tool.

## Projector And Gestures

Open the projector page fullscreen on the projector host. `PROJECTOR_WIDTH_MM` and `PROJECTOR_HEIGHT_MM` are the measured width and height of the visible browser viewport on the physical surface. With either value unset, the footprint remains illustrative.

The gesture page uses a separate USB camera and a locally served MediaPipe hand model. Open the projector as `/projector.html?calibrate=1` and the gesture page on the camera host. Click **Calibrate corners**, then click the four marked projector corners in the camera video in order: top left, top right, bottom right, bottom left. The saved four-point mapping converts camera coordinates to projector coordinates. Pinching moves the current dimension outline. Install frontend dependencies and run `npm run prepare:gestures` for local development; the frontend Dockerfile prepares the assets during build. Pointer drag on the projector page works without a camera.

## Satellites

`POST /api/v2/satellite/turn` accepts a multipart WAV file and an `X-Jarvis-Token` header matching `SATELLITE_TOKEN`. It returns the transcript, answer, and base64 WAV response. This is a push to talk protocol for an ESP32-S3 or another client. Audio capture, I2S pin mapping, and playback firmware depend on the selected board and peripherals and must be supplied for that hardware.

## Verification

Run `python -m unittest tests.test_local_backend tests.test_inventory_integrations -v` after installing `backend/requirements.txt`, then run `npm run build` in `frontend`. The integration tests use fake Frigate and Homebox responses, so they verify wiring without claiming hardware or model accuracy.
