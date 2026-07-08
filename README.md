<p align="center">
  <img src="docs/assets/wordmark.svg" alt="Backchannel" width="440" />
</p>

<p align="center">
  <strong>Real-time meeting transcription and AI insight generation.</strong>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> -
  <a href="#features">Features</a> -
  <a href="#architecture">Architecture</a> -
  <a href="https://backchannel-site.lavender-zebu.workers.dev/docs/">Documentation</a>
</p>

---

Backchannel is a self-hosted, open-source (MIT) AI meeting assistant that
runs on your own hardware -- no bot joins your call, and your audio never
leaves your infrastructure except for the model API calls you configure.

It listens to your meetings and works quietly in the background. It
captures microphone and system audio in the browser, streams it to a FastAPI
backend that builds a live speaker-attributed transcript, and runs a crew of
AI agents over the conversation as it happens -- surfacing the questions you
should ask, the objections you need to handle, and the opportunities and
action items you would otherwise reconstruct from memory afterwards.

## Features

- **Live diarized transcription** -- Silero VAD plus WeSpeaker ResNet152
  speaker embeddings segment speech and attribute every line to a speaker, with
  interim text streaming in seconds ahead of the final transcript
- **Agent-based analysis** -- a consolidated analyst, a low-latency objection
  handler, a synthesizer, and an opportunity specialist run on their own
  triggers and push insights to the UI mid-call
- **Provider-routed models** -- mix Google Gemini and OpenAI models per
  agent, or transcribe fully offline with local ONNX Whisper/Parakeet
  (no API key required)
- **Dual-track audio** -- mic and tab/system audio are captured separately,
  so remote participants get their own speaker identities
- **Import and re-transcription** -- bring in existing transcripts (`.txt`,
  `.md`, `.docx`) or audio files (`.mp3`, `.m4a`, `.wav`, `.ogg`, `.flac`),
  and replay any recorded call through a different transcription model later
- **Meeting context** -- directives (standing or mid-call), uploaded
  documents, speaker roles, and an offerings/knowledge catalog all feed
  agent prompts
- **Exports and chat** -- transcript TXT, insights XLSX, and summary HTML
  exports, plus cross-session Q&A chat over your past meetings
- **Encrypted credentials** -- provider API keys are stored encrypted at
  rest and managed from the Admin panel

## Architecture

![Architecture diagram](architecture.svg)

The browser streams PCM16 16 kHz audio over a WebSocket. The backend
diarizes it, transcribes each segment, persists speaker-attributed
transcript entries to PostgreSQL, and feeds the text to an agent
orchestrator whose insights stream back to the UI over the same socket. A
parallel Gemini Live (or OpenAI Realtime) session provides interim
transcription while the batch pipeline produces the durable record.

Read more in [docs/architecture.md](docs/architecture.md).

## Quickstart

Requires Docker with the Compose plugin. The default pipeline uses a free
[Gemini API key](https://ai.google.dev/) for transcription and agents;
local ONNX Whisper/Parakeet models can transcribe with no key at all.

```bash
git clone https://github.com/talberthoule/backchannel.git
cd backchannel
cp .env.example .env   # set GEMINI_API_KEY (or add keys later in Admin -> API Keys)
docker compose up --build
```

- App: http://localhost:3000
- Backend API: http://localhost:8001 (OpenAPI docs at `/docs`)

On a host with an NVIDIA GPU, enable GPU diarization with the override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Full setup options (local development, migrations, GPU validation) are in
[docs/quickstart.md](docs/quickstart.md) and
[docs/deployment.md](docs/deployment.md).

## Documentation

| Page | What it covers |
| --- | --- |
| [Quickstart](docs/quickstart.md) | Docker Compose, local development, migrations, tests |
| [Architecture](docs/architecture.md) | The live call path end to end, frontend and backend structure |
| [Agent System](docs/agents.md) | Each agent's trigger and purpose, configuration and overrides |
| [Audio Pipeline](docs/audio-pipeline.md) | Capture format, VAD/diarization, transcription routing, audio storage |
| [WebSocket Protocol](docs/websocket-protocol.md) | Binary audio framing and every message type on `/ws/{session_id}` |
| [REST API](docs/rest-api.md) | Endpoint reference for every router |
| [Configuration](docs/configuration.md) | Settings, environment variables, credentials, model registry |
| [Deployment](docs/deployment.md) | Compose services, GPU support, nginx proxying, startup behavior |

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, served by nginx |
| Backend | FastAPI, SQLAlchemy (async), Alembic, PostgreSQL 16 |
| AI providers | Google Gemini (Live + Flash), OpenAI (GPT-5, Realtime) |
| Local inference | Silero VAD, WeSpeaker ResNet152, Whisper/Parakeet via ONNX Runtime |

## License

[MIT](LICENSE)
