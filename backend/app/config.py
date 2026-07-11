from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://callhelper:changeme@db:5432/callhelper"
    FRONTEND_DIST: str = ""  # path to built frontend; empty = nginx serves it (Docker)
    GEMINI_MODEL: str = "gemini-3.1-flash-live-preview"
    BATCH_TRANSCRIBER_MODEL: str = "gemini-3.5-flash"
    REFINEMENT_MODEL: str = "gemini-3.5-flash"
    REFINEMENT_INTERVAL_SECONDS: int = 45

    # Agent toggles
    AGENT_QUESTION_HUNTER_ENABLED: bool = True
    AGENT_CONSOLIDATED_ENABLED: bool = True  # single call for obs + opp + action items
    AGENT_OBSERVER_ENABLED: bool = True      # sub-filter: include observations
    AGENT_OPPORTUNITY_SCOUT_ENABLED: bool = True  # sub-filter: include opportunities
    AGENT_ACTION_TRACKER_ENABLED: bool = True     # sub-filter: include action items
    AGENT_SYNTHESIZER_ENABLED: bool = True
    AGENT_OPPORTUNITY_SPECIALIST_ENABLED: bool = True

    # Agent timing
    TEXT_AGENT_INTERVAL_SECONDS: int = 40        # consolidated analyst cycle
    OBJECTION_HANDLER_INTERVAL_SECONDS: int = 10  # objection handler fast scan cycle
    OBJECTION_WINDOW_SECONDS: int = 90           # transcript window for objection scans
    SYNTHESIZER_COOLDOWN_SECONDS: int = 75       # min time between synthesizer runs
    SYNTHESIZER_MAX_INTERVAL_SECONDS: int = 120  # fallback max gap for synthesizer
    OPPORTUNITY_SPECIALIST_COOLDOWN_SECONDS: int = 55  # batch window for opp specialist
    KNOWLEDGE_CONTEXT_CHAR_BUDGET: int = 60000  # max chars of knowledge context stuffed into a prompt

    # Speaker diarization settings
    LIVE_DIARIZER: str = "lightweight"
    SPEAKER_SIMILARITY_THRESHOLD: float = 0.68
    MIN_NEW_SPEAKER_MS: int = 4000
    MAX_SPEAKER_PROFILES_PER_TRACK: int = 4
    VAD_THRESHOLD: float = 0.6
    SILENCE_GAP_MS: int = 600
    MAX_SEGMENT_MS: int = 15000
    MIN_SEGMENT_MS: int = 750
    SORTFORMER_WINDOW_MS: int = 15000

    model_config = {"env_file": ".env"}


settings = Settings()


# --- Model Registry ---
# Central catalog of available models and their capabilities.
# Add new models here as they become available.

MODEL_REGISTRY: list[dict] = [
    {
        "id": "gemini-3.5-flash",
        "name": "Gemini 3.5 Flash",
        "provider": "Google",
        "description": "Stable frontier Flash model for agentic, coding, and multimodal analysis tasks",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-3-flash-preview",
        "name": "Gemini 3 Flash Preview",
        "provider": "Google",
        "description": "Preview Gemini 3 Flash model for frontier multimodal reasoning",
        "tier": "preview",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-3.1-pro-preview",
        "name": "Gemini 3.1 Pro",
        "provider": "Google",
        "description": "High-capability preview model for final briefing arbitration",
        "tier": "preview",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-3.1-flash-lite",
        "name": "Gemini 3.1 Flash-Lite",
        "provider": "Google",
        "description": "Stable low-latency, cost-effective multimodal model for high-volume workflows",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "provider": "Google",
        "description": "Stable price-performance model for low-latency, high-volume reasoning tasks",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-2.5-flash-lite",
        "name": "Gemini 2.5 Flash-Lite",
        "provider": "Google",
        "description": "Stable fastest and lowest-cost model in the Gemini 2.5 family",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-2.5-pro",
        "name": "Gemini 2.5 Pro",
        "provider": "Google",
        "description": "Stable deep reasoning model for complex tasks, code, and long-context analysis",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-3.1-flash-live-preview",
        "name": "Gemini 3.1 Flash Live",
        "provider": "Google",
        "description": "Live audio model with native streaming and configurable reasoning",
        "tier": "preview",
        "requires_key": "google",
        "supports_text": False,
        "supports_batch_audio": False,
        "supports_live_audio": True,
    },
    {
        "id": "gpt-5.5",
        "name": "GPT-5.5",
        "provider": "OpenAI",
        "description": "OpenAI flagship model for complex reasoning and professional work",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.4",
        "name": "GPT-5.4",
        "provider": "OpenAI",
        "description": "More affordable OpenAI frontier model for coding and professional work",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.4-mini",
        "name": "GPT-5.4 Mini",
        "provider": "OpenAI",
        "description": "Strong, cost-effective OpenAI mini model for high-volume text tasks",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.4-nano",
        "name": "GPT-5.4 Nano",
        "provider": "OpenAI",
        "description": "Cheapest, fastest GPT-5.4-class model for simple high-volume tasks",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.2",
        "name": "GPT-5.2",
        "provider": "OpenAI",
        "description": "Previous OpenAI frontier model with configurable reasoning",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "local-whisper-base",
        "name": "Whisper Base (Local)",
        "provider": "Local",
        "description": "Local multilingual Whisper transcription via ONNX; no API key, downloads on first use",
        "tier": "stable",
        "requires_key": None,
        "supports_text": False,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "local-parakeet-tdt-0.6b",
        "name": "Parakeet TDT 0.6B (Local)",
        "provider": "Local",
        "description": "Local English NVIDIA Parakeet transcription via ONNX; fast and accurate, no API key",
        "tier": "stable",
        "requires_key": None,
        "supports_text": False,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-realtime-whisper",
        "name": "GPT Realtime Whisper",
        "provider": "OpenAI",
        "description": "Streaming speech-to-text model for realtime interim transcription (text only)",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": False,
        "supports_live_audio": True,
    },
    {
        "id": "gpt-4o-transcribe",
        "name": "GPT-4o Transcribe",
        "provider": "OpenAI",
        "description": "Realtime WebSocket transcription powered by GPT-4o for interim transcripts (text only)",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": False,
        "supports_live_audio": True,
    },
    {
        "id": "gpt-4o-mini-transcribe",
        "name": "GPT-4o Mini Transcribe",
        "provider": "OpenAI",
        "description": "Lower-cost realtime WebSocket transcription for interim transcripts (text only)",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": False,
        "supports_live_audio": True,
    },
]
