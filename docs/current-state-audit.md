# Current State Audit

## Summary

This repo already has a useful foundation, but it is not yet aligned with the local outbuilding assistant design.

The main strengths are:

- Existing FastAPI backend
- Existing WebSocket voice loop
- Existing browser frontend and orb UI
- Existing memory and action concepts

The main mismatch areas are:

- Anthropic-specific model calls
- Fish Audio TTS dependency
- AppleScript and macOS integrations
- Desktop-centric assumptions instead of room, camera, projector, and Home Assistant tooling

## Current Backend Shape

The backend is still concentrated mostly in [server.py](/C:/Users/david/Documents/GitHub/jarvis/server.py), which currently handles several concerns together:

- WebSocket session management
- Intent classification
- LLM prompting
- TTS calls
- Task management
- REST endpoints
- Action dispatch

This is workable for the original project but becomes a maintenance problem for the planned local-first system.

## Current Frontend Shape

The frontend is in [frontend](</C:/Users/david/Documents/GitHub/jarvis/frontend>) and already provides a usable baseline:

- Orb visualization
- Browser microphone capture
- WebSocket connectivity
- Audio playback
- Settings surface

What it does not yet include:

- Projector page
- Admin dashboard for cameras, tools, and model routing
- Gesture interaction surface
- Dimension overlay rendering

## Existing Integrations To Migrate Away From

The current codebase depends on:

- Anthropic API
- Fish Audio TTS
- Apple Calendar integration
- Apple Mail integration
- Apple Notes integration
- macOS automation patterns in `actions.py`

These should either be removed, isolated behind adapters, or deprecated as the repo is refactored.

## Existing Ideas Worth Keeping

- FastAPI app structure
- WebSocket message pattern
- Voice interaction loop
- Memory concepts in [memory.py](/C:/Users/david/Documents/GitHub/jarvis/memory.py)
- Tool and action registry direction
- Orb-based assistant identity

## Main Technical Debt

- Monolithic server file
- Provider-specific logic mixed with app logic
- UI and backend terminology still anchored to the original product
- Missing documentation for migration targets
- No formal separation between safe, low-risk, and dangerous actions

## Practical Conclusion

This repo should be treated as a migration baseline with reusable pieces, not as a near-complete implementation of the outbuilding system.
