# Implementation Roadmap

## Phase 1: Basic Local Jarvis

Goal:

Voice in, route locally, speak back.

Tasks:

- Replace Anthropic-specific model calls with an OpenAI-compatible client abstraction
- Add local STT
- Add local TTS
- Preserve the existing orb UI where possible
- Introduce basic routing structure

Success test:

> "Hey Jarvis, what are you running on?"

## Phase 2: Web Search And Projector

Goal:

Research and display on command.

Tasks:

- Add `web_search` tool
- Add projector page
- Add display event channel
- Add `project_card`
- Add `project_dimension_overlay`

Success test:

> "Hey Jarvis, research a Dell R630 and project the size of it."

## Phase 3: Reolink Vision

Goal:

Snapshot-based visual context.

Tasks:

- Add Reolink snapshot tool
- Add vision model client
- Add `describe_camera_scene`
- Add camera preview to admin or debug UI

Success test:

> "Hey Jarvis, what is on my workbench?"

## Phase 4: Home Assistant

Goal:

Safe smart-environment control.

Tasks:

- Add Home Assistant client
- Start with read-only operations
- Add light, scene, and projector actions
- Add confirmation layer for dangerous operations

Success test:

> "Hey Jarvis, turn on work mode."

## Phase 5: ESP32 Satellite

Goal:

Voice interaction away from the primary desk machine.

Tasks:

- Build one ESP32-S3 node
- Add audio streaming endpoint
- Start with push-to-talk
- Add wake word later

Success test:

Speak from across the outbuilding and receive a spoken reply.

## Phase 6: Gesture And Interactive Projection

Goal:

Manipulate projected objects with hands.

Tasks:

- Add hand tracking
- Add gesture canvas or interaction layer
- Detect pinch and drag
- Move projected overlays
- Add optional calibration path

Success test:

Project a server footprint and drag it with a pinch gesture.

## Development Order

Recommended priority:

1. Local LLM replacement
2. Voice loop stabilization
3. Web search
4. Projector display
5. Reolink vision
6. Home Assistant
7. ESP32 satellites
8. Hand tracking
9. True-to-size calibration
