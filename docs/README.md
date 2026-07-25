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
[README](../README.md). For how Backchannel differs from the other meeting
assistants people evaluate, the public site's
[comparison hub](https://backchannel.page/open-source-meeting-assistants/)
indexes every open-source and commercial comparison.

For desktop operations, [Releasing](releasing.md) and the private R2 manifests
are authoritative. GitHub releases retain public source tags and notes without
executable files. The Cloudflare Access-protected operator console separates
Early access request/consent approval and rejection, Users identity/security
commands, and Authorization Latest/explicit-version grants. Authorization is
stored in `release_access_policies` plus `release_account_versions`; the old
`/api/admin/access/*` routes are removed. Recipient accounts, grants, sessions,
and access events live in D1, not the local application's PostgreSQL database.

## Contents

| Page | What it covers |
| --- | --- |
| [Quickstart](quickstart.md) | Running with Docker Compose, local development, database migrations, tests |
| [Getting API Keys](api-keys.md) | Creating a Google Gemini or OpenAI key and connecting it under Admin -> API Keys |
| [Architecture](architecture.md) | The live call path end to end, frontend structure, backend key files |
| [Agent System](agents.md) | The orchestrator, each agent's trigger and purpose, configuration and overrides |
| [Audio Pipeline](audio-pipeline.md) | Capture format, VAD and diarization, batch transcription routing, audio storage |
| [WebSocket Protocol](websocket-protocol.md) | Binary audio framing and every JSON message type on `/ws/{session_id}` |
| [REST API](rest-api.md) | Endpoint reference for all routers, grouped by resource |
| [Configuration](configuration.md) | Settings, environment variables, encrypted credentials, the model registry |
| [Deployment](deployment.md) | Docker Compose plus the ordered D1, R2, Worker, Turnstile, and release-access production gate |
| [Releasing](releasing.md) | Authoritative private-R2 publication, migration, verification, and recovery procedure |

## Reading order

If you are new to the codebase, read [Quickstart](quickstart.md) to get the
stack running, then [Architecture](architecture.md) for the mental model, then
[Agent System](agents.md) -- most feature work touches one of those three
areas. The protocol and API pages are references to consult as needed.

Release-access documentation changes must pass:

```bash
cd docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
node --test *.test.js
npm run build
```
