<p align="center">
  <img src="assets/wordmark.svg" alt="Backchannel" width="420" />
</p>

# Backchannel Documentation

Backchannel is a real-time meeting analysis app. A React frontend captures
microphone (and optionally tab/system) audio, streams it to a FastAPI backend
over WebSocket, and the backend produces a speaker-attributed transcript while
a set of provider-routed AI agents surface questions, observations,
opportunities, objections, and action items as the conversation happens.

This folder is the deeper technical reference behind the top-level
[README](../README.md).

## Contents

| Page | What it covers |
| --- | --- |
| [Quickstart](quickstart.md) | Running with Docker Compose, local development, database migrations, tests |
| [Architecture](architecture.md) | The live call path end to end, frontend structure, backend key files |
| [Agent System](agents.md) | The orchestrator, each agent's trigger and purpose, configuration and overrides |
| [Audio Pipeline](audio-pipeline.md) | Capture format, VAD and diarization, batch transcription routing, audio storage |
| [WebSocket Protocol](websocket-protocol.md) | Binary audio framing and every JSON message type on `/ws/{session_id}` |
| [REST API](rest-api.md) | Endpoint reference for all routers, grouped by resource |
| [Configuration](configuration.md) | Settings, environment variables, encrypted credentials, the model registry |
| [Deployment](deployment.md) | Docker Compose services, GPU support, nginx proxying, startup behavior |

## Reading order

If you are new to the codebase, read [Quickstart](quickstart.md) to get the
stack running, then [Architecture](architecture.md) for the mental model, then
[Agent System](agents.md) -- most feature work touches one of those three
areas. The protocol and API pages are references to consult as needed.
