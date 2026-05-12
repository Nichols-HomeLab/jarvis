# Repo Refactor Plan

## Objective

Turn the current codebase into a maintainable platform for the local outbuilding assistant without losing the parts that already work.

## Baseline Reality

The current implementation is dominated by [server.py](/C:/Users/david/Documents/GitHub/jarvis/server.py) and mixes:

- Voice transport
- Assistant prompting
- TTS
- Task orchestration
- Tool dispatch
- Settings and status endpoints

That is the first structural problem to solve.

## Refactor Priorities

### 1. Introduce Clear Backend Boundaries

Separate:

- transport
- model clients
- tools
- agents
- configuration
- schemas

This should happen before adding too many new integrations.

### 2. Add Provider Abstraction

The code should no longer assume one LLM provider or one TTS provider.

Introduce interfaces for:

- chat or reasoning model
- router model
- vision model
- STT backend
- TTS backend

The implementation can then point to:

- Ollama
- llama.cpp server
- vLLM
- other OpenAI-compatible endpoints

## 3. Split Present And Future Features

Keep the following as reusable baseline features:

- voice WebSocket loop
- orb UI
- memory ideas

Move macOS-specific features behind isolated adapters so they can be removed cleanly later.

## 4. Add New Frontend Surfaces

Planned pages:

- `AssistantOrb`
- `ProjectorDisplay`
- `AdminDashboard`

Planned components:

- `ProjectedCard`
- `DimensionOverlay`
- `GestureCanvas`
- `CameraPreview`

## 5. Add A Safer Tool Registry

Tools should have metadata that supports:

- name
- arguments schema
- risk level
- confirmation requirement
- result shape

This matters before Home Assistant control is added.

## 6. Establish Docs As Source Of Truth

Use the markdown files in [docs](</C:/Users/david/Documents/GitHub/jarvis/docs>) as the project contract during the migration.

## Suggested Near-Term File Evolution

Likely migration path:

```text
server.py
  -> backend/main.py
  -> backend/audio/*
  -> backend/models/*
  -> backend/tools/*
  -> backend/agents/*
  -> backend/schemas/*
```

Frontend direction:

```text
frontend/src/
  pages/
  components/
  websocket/
  gestures/
```

## Definition Of Success

The repo is on the right track when:

- local model routing is configurable
- the projector page exists
- Reolink snapshots can be analyzed
- Home Assistant actions are backend-controlled
- the README no longer describes this project as a Mac-only Claude assistant
