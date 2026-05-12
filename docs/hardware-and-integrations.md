# Hardware And Integrations

## Current Hardware

### AI Server

- NVIDIA V100 16 GB
- 64 GB RAM

Implication:

- Good fit for routing models, Whisper-class STT, local TTS, and snapshot-based vision
- Not ideal for very large or always-on realtime multimodal models

### Camera

- Reolink camera

Recommended first use:

- Snapshot capture
- Optional recent clip retrieval later
- Avoid full-time video-to-LLM streaming in the first implementation

### Projector

The projector should be treated as a browser client rendering a dedicated projector page.

Expected responsibilities:

- Show search results
- Show dimension cards
- Show diagrams
- Show object footprints and overlays
- Eventually support gesture interaction

### ESP32 Satellites

Future node direction:

- ESP32-S3
- I2S microphone
- I2S amplifier
- Small speaker
- Optional button
- Optional LED ring

Role:

- Capture audio
- Stream audio to server
- Receive TTS audio back
- Not run the LLM locally

## Reolink Integration Direction

Planned functions:

- `get_reolink_snapshot(camera="outbuilding")`
- `get_reolink_recent_clip(camera="outbuilding", seconds=10)`
- `describe_camera_scene(camera="outbuilding")`
- `find_object_on_camera(camera="outbuilding", object="multimeter")`

First milestone:

- Single snapshot request and vision description

## Home Assistant Integration Direction

Primary use cases:

- Lights
- Scenes
- Projector outlet or power control
- Speakers
- Sensors
- Camera entities
- Safe automations

Preferred approach:

- MCP integration if it fits your broader stack
- Otherwise REST and WebSocket API clients behind a dedicated backend tool adapter

## Safety Levels

### Level 1: Read Only

No confirmation required.

- Web search
- Camera snapshots
- Sensor reads
- Light state reads

### Level 2: Safe Control

Usually no confirmation required.

- Turn lights on and off
- Set scenes
- Turn projector on and off
- Show projector content

### Level 3: Dangerous Actions

Require explicit confirmation.

- Unlock doors
- Open garage doors
- Shut down servers
- Control high-power relays
- Major HVAC changes

## Voice Pipeline Direction

Recommended order:

1. Push-to-talk
2. Local STT
3. Local TTS
4. Wake word
5. Satellite streaming

This reduces early complexity and keeps the core backend testable.
