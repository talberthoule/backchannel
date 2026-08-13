import os

from pydantic import field_validator
from pydantic_settings import BaseSettings


def _default_embed_threads(cpu_count: int | None) -> int:
    """Bounded intra-op pool size for the speaker embedding model.

    Half the cores, so the model never takes the whole machine; at least one,
    because ORT reads 0 as "use every core" and that default is precisely what
    this setting exists to avoid (an unknown or single-core count must not
    silently reinstate it); at most four, because measured parallel efficiency
    collapses past that - 28 threads spent 77% of their CPU on pool overhead
    rather than arithmetic. The cap also makes ORT's blindness to container
    CPU quotas a non-issue (ALP-289).
    """
    return min(4, max(1, (cpu_count or 1) // 2))


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
    # How long to wait on a chat-completions reply. Hosted models answer in
    # seconds; a self-hosted model on CPU can take minutes on a long briefing
    # prompt, so it gets its own far larger ceiling (ALP-154). Raising the
    # hosted value instead would make a genuinely stuck cloud call hang.
    LLM_TIMEOUT_SECONDS: float = 120
    LLM_SELF_HOSTED_TIMEOUT_SECONDS: float = 900
    # Completion budget sent to self-hosted servers. Left unset, the server's
    # own default decides, and LM Studio's truncated a briefing mid-JSON at
    # ~1900 tokens. Hosted providers keep their defaults.
    LLM_SELF_HOSTED_MAX_TOKENS: int = 8192
    # Hosted providers used to run uncapped. A degenerate reply then ran to the
    # provider's own ceiling and was discarded unparsed: 47k-63k output tokens
    # per incident, 22 percent of one session's entire bill, for nothing. This
    # is roughly thirteen times the observed healthy median output, so it
    # bounds the failure without touching a successful call (ALP-295).
    LLM_HOSTED_MAX_TOKENS: int = 4096
    # Thinking bills at output rates. Structured reconciliation is closer to
    # classification than open reasoning, but answer detection is genuinely
    # inferential, so this leaves room rather than zeroing it (ALP-296).
    # Negative disables the override and restores provider defaults.
    LLM_JSON_THINKING_BUDGET: int = 512
    LLM_JSON_TEMPERATURE: float = 0.2
    DATABASE_URL: str = "postgresql+asyncpg://callhelper:changeme@db:5432/callhelper"
    FRONTEND_DIST: str = ""  # path to built frontend; empty = nginx serves it (Docker)
    GEMINI_MODEL: str = "gemini-3.1-flash-live-preview"
    BATCH_TRANSCRIBER_MODEL: str = "local-whisper-base"
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
    # How long an unanswered insight keeps its full record in the synthesizer
    # prompt. Past this it becomes a compact stub that merge/answer can still
    # target by id. Raising it costs tokens quadratically with call length.
    SYNTHESIZER_WORKING_SET_SECONDS: int = 600
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

    # ONNX Runtime thread pools for the two diarizer models. Left at ORT's
    # default - one intra-op thread per core - both models spend most of their
    # CPU in pool overhead rather than arithmetic. Measured on 28 cores: the
    # VAD is a 2.3MB LSTM over a 512-sample frame with nothing to parallelize,
    # and the default cost 0.53ms CPU per frame against 0.11ms at a single
    # thread to buy back about 9% of wall time. The embedding model does
    # parallelize, but not 28 ways: the default drew 19 cores' worth of CPU
    # for one 5s segment at 5% parallel efficiency. Bounding it trades some
    # wall time for roughly a quarter of the CPU - see _embed_session_options
    # in services/speaker_diarizer.py (ALP-289).
    DIARIZER_VAD_ONNX_THREADS: int = 1
    DIARIZER_EMBED_ONNX_THREADS: int = _default_embed_threads(os.cpu_count())
    # ORT's intra-op pool spin-waits after a call returns so the next one
    # starts sooner. Embeddings arrive seconds apart, so that spin is charged
    # to whatever runs next - which is the VAD: 894ms of CPU burned during a
    # 300ms idle gap, gone entirely with spinning off. The VAD keeps the
    # default; at one thread there is no pool to idle and disabling it
    # measured slightly worse (ALP-289).
    DIARIZER_EMBED_ONNX_SPIN: bool = False

    @field_validator("DIARIZER_VAD_ONNX_THREADS", "DIARIZER_EMBED_ONNX_THREADS")
    @classmethod
    def _clamp_onnx_threads(cls, value: int) -> int:
        """Keep an operator override out of ORT's default pool.

        Setting 0 is the natural way to write "let ORT choose", and that is
        exactly the one-thread-per-core behavior these settings exist to
        avoid; negatives are accepted by ORT and measure worse still. If the
        computed default is worth a floor, so is a supplied one (ALP-289).
        """
        return max(1, value)

    # extra="ignore": a .env with unrelated keys (compose database settings,
    # legacy entries) must not crash startup.
    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


# --- Model Registry ---
# Central catalog of available models and their capabilities.
# Add new models here as they become available.

DEFAULT_MODEL_RECOMMENDATION_ROLES: dict[str, tuple[str, ...]] = {
    "gemini-3.1-flash-live-preview": ("audio_gateway",),
    "gemini-3.6-flash": (
        "consolidated_analyst",
        "synthesizer",
        "opportunity_specialist",
        "strategic_signals",
        "brief_meeting_lens",
        "brief_discovery_lens",
        "brief_arbiter",
        "live_ask",
    ),
    "gemini-3.5-flash-lite": ("objection_handler", "batch_transcription"),
    "gpt-realtime-whisper": ("audio_gateway",),
    "gpt-5.6-terra": (
        "consolidated_analyst",
        "synthesizer",
        "strategic_signals",
        "brief_meeting_lens",
        "brief_discovery_lens",
        "live_ask",
    ),
    "gpt-5.6-luna": ("objection_handler", "opportunity_specialist"),
    "gpt-5.6-sol": ("brief_arbiter",),
    "gpt-4o-mini-transcribe": ("batch_transcription",),
}

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
    {
        # On-device interim captions (ALP-147): a rolling-commit local captioner,
        # not a cloud streaming session. CPU-heavy; the fit test projects whether
        # this machine can sustain it (Live captions feasibility).
        "id": "local-parakeet-live",
        "name": "Parakeet Live (Local, experimental)",
        "provider": "Local",
        "description": "Experimental on-device live captions: transcribes short audio chunks with local Parakeet ONNX. No cloud; works under Privacy First. CPU-heavy - check the fit test's live-caption feasibility first.",
        "tier": "experimental",
        "requires_key": None,
        "supports_text": False,
        "supports_batch_audio": False,
        "supports_live_audio": True,
    },
    # Any OpenAI-compatible chat server (Ollama, LM Studio, vLLM, LiteLLM).
    # One stable registry id stands in for whatever model the server exposes:
    # the base URL and the wire model name are configured in Admin -> Connections
    # (see services/llm_endpoint.py). requires_key is None because local
    # servers accept unauthenticated calls, so this entry never gets locked
    # out of the agent model pickers.
    {
        "id": "openai-compatible",
        "name": "OpenAI-Compatible Endpoint",
        "provider": "OpenAI-Compatible",
        "description": "Self-hosted OpenAI-compatible chat server (Ollama, LM Studio, vLLM, LiteLLM); set its base URL and model id in Admin -> Connections",
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
