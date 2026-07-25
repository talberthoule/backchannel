"""Published per-token pricing for the models in the registry.

Kept as a parallel table (keyed by model id) rather than inline in
``MODEL_REGISTRY`` so pricing refreshes stay a one-file change and never
touch capability metadata in ``app.config``.

Simplifications (also stated in the UI):
- Standard paid-tier text rates only (Gemini "paid tier" / OpenAI standard).
- No long-context surcharges (Gemini Pro rates are the <=200k-token tier).
- No cache-storage rates; cached-input is the discounted read rate only.
- Audio-token input rates are recorded where published (live/transcribe
  models) but cost estimates in the app use the text-tier input rate.

All rates are USD per 1 million tokens. A model mapped to ``None`` is in
the registry but has no published per-token pricing; the UI renders it as
"-" and excludes it from cost estimates.

``tests/test_model_pricing.py`` asserts this table stays in one-to-one
sync with ``MODEL_REGISTRY``, so adding or removing a registry model
without updating this table fails the suite.
"""

# Date the rates below were verified against provider pricing pages.
PRICING_AS_OF = "2026-07-23"


def _price(
    input_per_million: float,
    output_per_million: float,
    cached_input_per_million: float | None = None,
    audio_input_per_million: float | None = None,
) -> dict:
    return {
        "input_per_million": input_per_million,
        "output_per_million": output_per_million,
        "cached_input_per_million": cached_input_per_million,
        "audio_input_per_million": audio_input_per_million,
    }


MODEL_PRICING: dict[str, dict | None] = {
    # --- Google (paid tier, standard text rates) ---
    "gemini-3.6-flash": _price(1.50, 7.50),
    "gemini-3.5-flash": _price(1.50, 9.00),
    "gemini-3.5-flash-lite": _price(0.30, 2.50),
    "gemini-3-flash-preview": _price(0.50, 3.00),
    "gemini-3.1-pro-preview": _price(2.00, 12.00),  # <=200k-token tier
    "gemini-3.1-flash-lite": _price(0.25, 1.50),
    # Live model: text rates; audio input is billed at 3.00/1M.
    "gemini-3.1-flash-live-preview": _price(0.75, 4.50, audio_input_per_million=3.00),
    "gemini-2.5-flash": _price(0.30, 2.50),
    "gemini-2.5-flash-lite": _price(0.10, 0.40),
    "gemini-2.5-pro": _price(1.25, 10.00),  # <=200k-token tier
    # --- OpenAI (standard tier) ---
    "gpt-5.6-sol": _price(5.00, 30.00, cached_input_per_million=0.50),
    "gpt-5.6-terra": _price(2.50, 15.00, cached_input_per_million=0.25),
    "gpt-5.6-luna": _price(1.00, 6.00, cached_input_per_million=0.10),
    "gpt-5.5": _price(5.00, 30.00, cached_input_per_million=0.50),
    "gpt-5.4": _price(2.50, 15.00, cached_input_per_million=0.25),
    "gpt-5.4-mini": _price(0.75, 4.50, cached_input_per_million=0.075),
    "gpt-5.4-nano": _price(0.20, 1.25, cached_input_per_million=0.02),
    # Transcribe models take audio input only, so the input rate IS the
    # audio-token rate; output is text.
    "gpt-4o-transcribe": _price(2.50, 10.00, audio_input_per_million=2.50),
    "gpt-4o-mini-transcribe": _price(1.25, 5.00, audio_input_per_million=1.25),
    # No published per-token price for the realtime Whisper transcription
    # variant; kept in the table (as None) so the registry-sync test still
    # covers it and the UI shows "-".
    "gpt-realtime-whisper": None,
    # Audio-capable chat models (Chat Completions input_audio path). Text
    # rates from the per-model pages; gpt-audio-1.5 audio input is billed at
    # 32.00/1M audio tokens. The gpt-audio-mini page publishes no separate
    # audio-token rate, so only its text rates are recorded.
    "gpt-audio-1.5": _price(2.50, 10.00, audio_input_per_million=32.00),
    "gpt-audio-mini": _price(0.60, 2.40),
    # Self-hosted OpenAI-compatible endpoint: the rate depends entirely on
    # what the operator points it at (free local server, or a paid proxy), so
    # there is no publishable per-token price.
    "openai-compatible": None,
    # --- Local ONNX models: no API cost ---
    "local-whisper-base": _price(0.0, 0.0),
    "local-parakeet-tdt-0.6b": _price(0.0, 0.0),
}


def pricing_for(model_id: str) -> dict | None:
    """Return the pricing dict for a model id, or None when unpriced."""
    return MODEL_PRICING.get(model_id)
