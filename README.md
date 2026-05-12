# Jarvis

Local-first voice assistant for a desk, workshop, and outbuilding setup.

This repository currently contains the original Jarvis-style FastAPI + Vite voice assistant baseline, but the project direction for this fork is different: convert it from a macOS and cloud-dependent personal assistant into a self-hosted assistant that can listen, research, see through a Reolink camera, and project information onto a wall or desk.

## Project Direction

Target experience:

- Voice-first interaction
- Local or self-hosted model routing where possible
- Browser-based projector display
- Reolink snapshot vision
- Home Assistant integration through safe backend tools
- Future ESP32 mic/speaker satellites
- Future hand-gesture interaction for projected objects

Example command:

> "Hey Jarvis, research a Dell R630 and project the size of it."

## Implemented MVP Additions

This repo now includes a parallel local-first MVP stack under [backend](</C:/Users/david/Documents/GitHub/jarvis/backend>) and new frontend pages in [frontend](</C:/Users/david/Documents/GitHub/jarvis/frontend>) for the workshop vision flow.

Implemented pieces:

- Env-driven local backend config
- OpenAI-compatible model endpoint support
- SQLite-backed tool and object memory
- Camera snapshot capture for configured cameras
- Vision scan endpoint for pegboard or workbench snapshots
- Tool memory search endpoint
- Projector websocket event stream
- Projector page with bounding-box overlay rendering
- Vision dashboard page for scans, searches, and command execution
- Dockerfiles and `docker-compose.yml` for the new stack

Current MVP commands:

- `Jarvis, scan the pegboard`
- `Jarvis, scan the workbench`
- `Jarvis, where are my screwdrivers?`
- `Jarvis, show me where the screwdrivers are`

## Current Repo Status

Today, this repo is still much closer to the original implementation than the target system. The current codebase is centered around:

- FastAPI backend in [server.py](/C:/Users/david/Documents/GitHub/jarvis/server.py)
- Vite/TypeScript frontend in [frontend](</C:/Users/david/Documents/GitHub/jarvis/frontend>)
- WebSocket voice loop
- Anthropic API for reasoning
- Fish Audio for TTS
- Apple Calendar, Mail, and Notes integrations
- macOS-oriented automation and desktop awareness

That means this fork should be treated as a migration project, not as a finished outbuilding assistant.

## Documentation Map

- [Project Vision](</C:/Users/david/Documents/GitHub/jarvis/docs/project-vision.md>)
- [Current State Audit](</C:/Users/david/Documents/GitHub/jarvis/docs/current-state-audit.md>)
- [Target Architecture](</C:/Users/david/Documents/GitHub/jarvis/docs/target-architecture.md>)
- [Hardware And Integrations](</C:/Users/david/Documents/GitHub/jarvis/docs/hardware-and-integrations.md>)
- [Implementation Roadmap](</C:/Users/david/Documents/GitHub/jarvis/docs/implementation-roadmap.md>)
- [Repo Refactor Plan](</C:/Users/david/Documents/GitHub/jarvis/docs/repo-refactor-plan.md>)

## Recommended Build Strategy

Do not try to jump directly to gesture-controlled true-size projection. The practical order for this repo is:

1. Replace Anthropic with a local OpenAI-compatible model client.
2. Replace Fish Audio with a local TTS engine.
3. Stabilize the voice loop around local STT and TTS.
4. Add a projector display page and projector event channel.
5. Add web search as a backend tool.
6. Add Reolink snapshot-based vision.
7. Add Home Assistant read and control tools with safety levels.
8. Add ESP32 satellite support.
9. Add gesture interaction and calibration.

## Baseline Local Development

If you want to inspect or run the current baseline before refactoring it:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm install
npm run dev
```

In a second terminal:

```bash
python server.py
```

This starts the current implementation, not the final local-first architecture described in the docs.

## Docker Quick Start

The new local-first MVP is intended to run with Docker Compose and a repo-root `.env`.

1. Copy [.env.example](/C:/Users/david/Documents/GitHub/jarvis/.env.example) to `.env`.
2. Set `OPENAI_BASE_URL` to your local OpenAI-compatible endpoint.
3. Set `OPENAI_VISION_MODEL`, `OPENAI_ROUTER_MODEL`, and camera snapshot URLs.
4. Start the stack:

```bash
docker compose up --build
```

Endpoints:

- Frontend orb: `http://localhost:5173/`
- Vision dashboard: `http://localhost:5173/dashboard.html`
- Projector view: `http://localhost:5173/projector.html`
- Local workshop API: `http://localhost:8000/api/v2/health`

If you do not have a live vision model ready yet, keep `ALLOW_MOCK_VISION=true` so the scan pipeline still runs without hard-failing.

## Immediate Repo Priorities

- Break the monolithic backend into clearer modules.
- Introduce config for multiple model backends.
- Separate current macOS-specific actions from future local/self-hosted tools.
- Add `docs/` as the source of truth for the migration.
- Keep the orb UI, WebSocket pattern, and general action/tool architecture where they still fit.

## Constraints To Respect

- The LLM should not directly control hardware.
- Every hardware or service action should go through validated backend tools.
- Dangerous actions must require confirmation.
- Reolink vision should start with snapshots, not continuous live video to an LLM.
- The first projector implementation can be visually approximate before calibration.

## What To Keep From This Repo

- FastAPI backend pattern
- Browser frontend pattern
- WebSocket communication model
- Voice assistant interaction loop
- Orb-based assistant presentation
- Memory and action concepts where they still fit

## What To Replace

- Anthropic-specific reasoning calls
- Fish Audio TTS
- Apple Calendar, Mail, and Notes assumptions
- macOS desktop control as a core feature
- Claude Code oriented task flow as the center of the product

## License

See [LICENSE](/C:/Users/david/Documents/GitHub/jarvis/LICENSE).
