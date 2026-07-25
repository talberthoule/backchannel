from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    # Base URL for every OpenAI-shaped chat call. The default is the hosted
    # OpenAI API, so an unset env var reproduces the previous hardcoded value
    # exactly. The persisted llm.openai_compatible.base_url app setting
    # overrides this for the openai-compatible provider only.
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    # Optional key for the openai-compatible provider; local servers such as
    # Ollama and LM Studio need none, so an empty value is valid.
    OPENAI_COMPATIBLE_API_KEY: str = ""
    # Wire model name for the openai-compatible provider (e.g. "llama3.1:8b").
    # The llm.openai_compatible.model_id app setting takes precedence.
    OPENAI_COMPATIBLE_MODEL_ID: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://callhelper:changeme@db:5432/callhelper"
    FRONTEND_DIST: str = ""  # path to built frontend; empty = nginx serves it (Docker)
    GEMINI_MODEL: str = "gemini-3.1-flash-live-preview"
    BATCH_TRANSCRIBER_MODEL: str = "gemini-3.5-flash-lite"
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
    SPEAKER_COHERENCE_WINDOW_MS: int = 3000
    SPEAKER_COHERENCE_THRESHOLD: float = 0.40
    MIN_NEW_SPEAKER_MS: int = 4000
    MAX_SPEAKER_PROFILES_PER_TRACK: int = 4
    VAD_THRESHOLD: float = 0.6
    SILENCE_GAP_MS: int = 600
    MAX_SEGMENT_MS: int = 15000
    MIN_SEGMENT_MS: int = 750
    SORTFORMER_WINDOW_MS: int = 15000

    # extra="ignore": a .env with unrelated keys (compose database settings,
    # legacy entries) must not crash startup.
    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


# --- Model Registry ---
# Central catalog of available models and their capabilities.
# Add new models here as they become available.

MODEL_REGISTRY: list[dict] = [
    {
        "id": "gemini-3.5-flash-lite",
        "name": "Gemini 3.5 Flash-Lite",
        "provider": "Google",
        "description": "Stable low-latency model for high-throughput, cost-effective multimodal tasks",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gemini-3.6-flash",
        "name": "Gemini 3.6 Flash",
        "provider": "Google",
        "description": "Stable frontier-speed model for agentic, coding, and multimodal reasoning tasks",
        "tier": "stable",
        "requires_key": "google",
        "supports_text": True,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
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
        "id": "gpt-5.6-sol",
        "name": "GPT-5.6 Sol",
        "provider": "OpenAI",
        "description": "OpenAI frontier GPT-5.6 model for complex professional work",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.6-terra",
        "name": "GPT-5.6 Terra",
        "provider": "OpenAI",
        "description": "GPT-5.6 model that balances intelligence and cost (mini tier)",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.6-luna",
        "name": "GPT-5.6 Luna",
        "provider": "OpenAI",
        "description": "Cost-optimized GPT-5.6 model for high-volume tasks (nano tier)",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": True,
        "supports_batch_audio": False,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-5.5",
        "name": "GPT-5.5",
        "provider": "OpenAI",
        "description": "OpenAI model for advanced coding and professional work",
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
    # Any OpenAI-compatible chat server (Ollama, LM Studio, vLLM, LiteLLM).
    # One stable registry id stands in for whatever model the server exposes:
    # the base URL and the wire model name are configured in Admin -> API Keys
    # (see services/llm_endpoint.py). requires_key is None because local
    # servers accept unauthenticated calls, so this entry never gets locked
    # out of the agent model pickers.
    {
        "id": "openai-compatible",
        "name": "OpenAI-Compatible Endpoint",
        "provider": "OpenAI-Compatible",
        "description": "Self-hosted OpenAI-compatible chat server (Ollama, LM Studio, vLLM, LiteLLM); set its base URL and model id in Admin -> API Keys",
        "tier": "stable",
        "requires_key": None,
        "supports_text": True,
        "supports_batch_audio": False,
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
        "description": "GPT-4o speech-to-text for batch segment transcription and realtime interim transcripts",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": True,
        "supports_live_audio": True,
    },
    {
        "id": "gpt-4o-mini-transcribe",
        "name": "GPT-4o Mini Transcribe",
        "provider": "OpenAI",
        "description": "Lower-cost GPT-4o mini speech-to-text for batch segments and realtime interim transcripts",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": True,
        "supports_live_audio": True,
    },
    # Audio-capable OpenAI chat models: batch transcription goes through
    # /v1/chat/completions with an input_audio content part (see
    # OpenAIChatTranscriber). The GPT-5.6/5.5/5.4 text models are NOT batch
    # options: their model pages list audio as "Not supported".
    {
        "id": "gpt-audio-1.5",
        "name": "GPT Audio 1.5",
        "provider": "OpenAI",
        "description": "OpenAI audio chat model; batch segment transcription via Chat Completions audio input",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
    {
        "id": "gpt-audio-mini",
        "name": "GPT Audio Mini",
        "provider": "OpenAI",
        "description": "Cost-efficient OpenAI audio chat model for batch segment transcription",
        "tier": "stable",
        "requires_key": "openai",
        "supports_text": False,
        "supports_batch_audio": True,
        "supports_live_audio": False,
    },
]
