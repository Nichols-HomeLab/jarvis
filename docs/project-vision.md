# Project Vision

## Goal

Build a self-hosted Jarvis assistant for a desk, workshop, and outbuilding environment using this repository as a starting point rather than a finished solution.

The target system should let a user walk around the space and issue commands such as:

> "Hey Jarvis, research a Dell R630 and project the size of it."

Jarvis should eventually be able to:

- Listen for voice commands
- Convert audio to text locally
- Route requests to the right model and toolchain
- Search the web when needed
- Use a Reolink camera for visual context
- Project cards, diagrams, and object outlines onto a wall or desk
- Integrate with Home Assistant
- Support future ESP32 mic/speaker satellites
- Support future gesture-based projector interaction

## Product Principles

- Local-first where practical
- OpenAI-compatible model endpoints behind a backend abstraction
- Backend-enforced tool execution
- Safe hardware control boundaries
- Incremental rollout from simple voice loop to richer multimodal interaction

## Target Example Flow

Command:

> "Hey Jarvis, research a Dell R630 and project the size of it."

Expected behavior:

1. Wake word or push-to-talk captures audio.
2. STT converts speech to text.
3. A small router model classifies the request.
4. The backend decides that web search and projector output are needed.
5. A research model gathers dimensions.
6. Jarvis speaks a concise summary.
7. The projector display renders a size card or outline.

## End State

The final system should feel like a persistent assistant for the physical workspace, not just a browser chatbot with speech.
