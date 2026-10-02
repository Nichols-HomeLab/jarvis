# Bifrost, Frigate, and Homebox Inventory

## Model gateway

Jarvis calls Bifrost's OpenAI-compatible chat-completions endpoint for routing, research, and snapshot vision. The cluster's documented base URL is `http://bifrost.external.svc.cluster.local:8080/openai`, so Jarvis calls `POST /openai/chat/completions`. Set `BIFROST_BASE_URL` to a URL reachable **from the backend container**. The cluster Service has no public ingress and its DNS name is not available to a local Docker Desktop container; use a secured, network-reachable Bifrost endpoint or a deliberate local tunnel for development. The example `host.docker.internal` address only works if such an endpoint is actually listening there. In-cluster inference requires no gateway key, but Cilium allows only declared AI consumers. A new Jarvis workload would need a NetworkPolicy update before it could connect.

Set `BIFROST_API_KEY` only if your reachable gateway requires a virtual key. Set `BIFROST_ROUTER_MODEL`, `BIFROST_RESEARCH_MODEL`, and `BIFROST_VISION_MODEL` to model routes returned by that gateway's live catalog; the vision route must accept image input. The cluster documents `mac/qwen3-vl-8b-instruct`, but that route depends on the Mac endpoint being awake and reachable. Jarvis now refuses to start without the Bifrost URL and all three routes. Remove obsolete `OPENAI_*` settings from an existing `.env`; they no longer select a fallback provider.

These values do not create or configure Bifrost. Check the [cluster Bifrost runbook](https://git.nicholstech.org/Nichols-HomeLab/k3s-fluxcd/src/branch/main/clusters/external/bifrost/README.md) and Bifrost's [gateway documentation](https://github.com/maximhq/bifrost/blob/dev/docs/quickstart/gateway/setting-up.mdx) before selecting the reachable route.

## Camera sightings

All camera images come from Frigate, not directly from a Reolink RTSP stream. Configure each Frigate camera in `JARVIS_CAMERAS_JSON`. Jarvis captures a latest frame for a manual or periodic scan. Set `AUTO_SCAN_INTERVAL_SECONDS=300` to scan each configured camera approximately every five minutes, or `0` to disable the periodic loop. Completed Frigate MQTT events are also analyzed when `MQTT_HOST` is set. `MIN_DETECTION_CONFIDENCE` filters low-confidence detections before they enter memory. Neither path streams every frame to Bifrost.

The last-seen answer reports the camera, zone, and timestamp of a stored detection. It is not proof that the object remains there. A missing object after motion is not attributed to a person. For automatic sightings to work, the vision route must return JSON detections with image-pixel bounding boxes; test it against a real pegboard frame before trusting locations.

## Homebox inventory

Jarvis reads Homebox v0.26+ `GET /api/v1/entities` for both locations and items, paginates, builds nested paths, and caches them in SQLite. Set `HOMEBOX_URL` to the Homebox origin (without `/api`) and `HOMEBOX_API_KEY` to a key with read access. `HOMEBOX_SYNC_INTERVAL_SECONDS=900` runs a sync approximately every 15 minutes; `0` disables automatic sync. `POST /api/v2/homebox/sync` triggers a manual sync. A failed fetch leaves the previous cache intact. Jarvis never writes to Homebox.

The current `k3s-fluxcd` main branch no longer contains the active Homebox workload; it was moved under `deprecated/`. Its retained storage does not make the application usable. Restore or identify a running Homebox service before setting `HOMEBOX_URL` or claiming live inventory sync. The former `homebox.nicholstech.org` route currently returns 404.

Ask "Where is my screwdriver set?" for a Homebox path when no camera sighting exists, or "What's in the blue parts bin?" for the nested inventory contents. Homebox records are inventory claims, not physical verification. When a high-confidence vision detection includes a sufficiently distinctive Homebox item or location name, Jarvis stores a **tentative** camera-to-inventory label match. That match does not edit Homebox or assert that every listed item is currently inside a box. See Homebox's [entity API migration guide](https://github.com/sysadminsmedia/homebox/blob/main/docs/src/content/docs/en/advanced/entity-merge-upgrade.mdx) for the v0.26 format.

## Image-assisted identification

`POST /api/v2/cameras/{camera}/identify` captures a Frigate frame, runs the configured Bifrost vision route, and sends a text query derived from the strongest detection to SearXNG's image search. The response contains the scan, a cautious text assessment, and candidate source/image URLs. The camera image is **not** uploaded to SearXNG or external sites. The candidate images are not machine-compared with the camera image; inspect them before adopting a specific make or model. The dashboard exposes this flow with an **Identify** button on each camera card.

## Verification

1. Set `.env` URLs, model routes, and keys for the services you actually run. Keep `.env` out of Git.
2. Run `docker compose up --build` and check `/api/v2/health` for configured camera names and gateway status.
3. Open `/dashboard.html`, click **Sync Homebox**, and query a known box. Check that the path and contents match Homebox.
4. Click **Scan** and **Identify** on a camera. Compare the bounding boxes and candidate references to the real scene.
5. Confirm that a repeated scan or completed Frigate event updates last-seen memory. Test a deliberately moved tool; do not infer an actor from a disappeared object.

The background loops run in each backend process. Deploy a single backend worker until a distributed lock or job queue is added.
