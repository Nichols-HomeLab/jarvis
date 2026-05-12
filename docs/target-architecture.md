# Target Architecture

## High-Level System

```text
[ESP32 Satellites / Browser Mic / Desk Client]
                    |
                    v
         [Wake Word / Push-To-Talk Layer]
                    |
                    v
             [Jarvis Core API]
                    |
      +-------------+-------------+-------------+-------------+
      |             |             |             |             |
      v             v             v             v             v
    [STT]       [Router]     [Research]      [Vision]    [TTS]
      |             |             |             |             |
      +-------------+------+------+-------------+-------------+
                    |
                    v
               [Tool Layer]
                    |
      +-------------+-------------+-------------+-------------+
      |             |             |             |             |
      v             v             v             v             v
 [Web Search]   [Projector]   [Reolink]   [Home Assistant] [Memory]
```

## Core Architectural Rules

- The LLM decides intent, not direct hardware commands.
- The backend validates and executes all tools.
- Every external capability should be wrapped in a narrow, typed tool layer.
- Small routing models and heavier reasoning models should be separated.
- Vision should start with snapshot processing rather than continuous video analysis.

## Recommended Backend Module Direction

Suggested structure for the refactor:

```text
backend/
  main.py
  config.py

  audio/
    stt.py
    tts.py
    wakeword.py

  models/
    llm_client.py
    router.py
    vision_client.py

  agents/
    command_router.py
    research_agent.py
    vision_agent.py

  tools/
    web_search.py
    projector.py
    reolink.py
    home_assistant.py
    memory.py

  schemas/
    actions.py
    messages.py
    tool_calls.py
```

## Model Roles

### Router Model

Use a small, fast model for classification and tool selection.

Candidate classes:

- Gemma 3n E4B
- Gemma 3 4B
- Small Qwen instruct model

Expected output:

```json
{
  "intent": "research_and_project",
  "needs_web": true,
  "needs_camera": false,
  "needs_projector": true,
  "needs_home_assistant": false,
  "needs_vision": false,
  "preferred_model": "research_model",
  "tools": ["web_search", "project_dimension_overlay"]
}
```

### Research Model

Use for:

- Web research summaries
- Product comparisons
- Technical reasoning
- Longer planning tasks

### Vision Model

Use for:

- Reolink snapshot analysis
- Object lookup in still images
- Desk and workbench scene descriptions

## Tool Layer

Representative tool surface:

```text
web_search(query)
get_reolink_snapshot(camera)
describe_camera_scene(camera)
project_card(title, content, layout)
project_image(path_or_url)
project_dimension_overlay(object_name, width, height, depth)
home_assistant_get_state(entity_id)
home_assistant_call_service(domain, service, data)
speak(text)
```

## Projector Design

The projector should be a fullscreen browser view, for example:

```text
http://jarvis.local/projector
```

The backend should publish display events over WebSocket. The page renders:

- Cards
- Images
- Diagrams
- Dimension overlays
- Future draggable objects

## Gesture Design

Gesture control should be introduced only after the projector page is stable.

First gesture targets:

- Pinch to grab
- Drag to move projected object
- Release to drop
- Two-hand scale
- Swipe to dismiss

## Calibration

True-to-size projection should be explicitly treated as a later phase. Before calibration, the system can still render approximate and useful scale visuals.
