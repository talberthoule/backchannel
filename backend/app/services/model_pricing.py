"""Published per-token pricing for the models in the registry.

Kept as a parallel table (keyed by model id) rather than inline in
``MODEL_REGISTRY`` so pricing refreshes stay a one-file change and never
touch capability metadata in ``app.config``.

Simplifications (also stated in the UI):
- Standard paid-tier rates only (Gemini "paid tier" / OpenAI standard).
- No long-context surcharges (Gemini Pro rates are the <=200k-token tier).
- No cache-storage rates; cached-input is the discounted read rate only, and
  it is applied to the cached_input_tokens slice of a usage row.
- Audio-token rates are applied to the audio_input_tokens and
  audio_output_tokens slices where published; a model without a published
  audio rate prices its audio tokens at the text rate.

All token rates are USD per 1 million tokens; ``per_minute`` is USD per
minute of audio, for models billed by duration instead. A model mapped to
``None`` is in the registry but has no published pricing of either kind;
the UI renders it as "-" and excludes it from cost estimates.

``tests/test_model_pricing.py`` asserts this table stays in one-to-one
sync with ``MODEL_REGISTRY``, so adding or removing a registry model
without updating this table fails the suite.
"""

# Date the rates below were last verified against BOTH provider pricing
# pages. The Google rows were re-verified against ai.google.dev/gemini-api/
# docs/pricing on 2026-09-01 (cached and audio rates filled in from it); the
# OpenAI pricing page refused the fetch that day (HTTP 403), so the OpenAI
# rows still date from this verification and are worth a sweep before any
# cost figure is quoted externally.
PRICING_AS_OF = "2026-07-23"


def _price(
    input_per_million: float | None,
    output_per_million: float | None,
    cached_input_per_million: float | None = None,
    audio_input_per_million: float | None = None,
    per_minute: float | None = None,
    audio_output_per_million: float | None = None,
) -> dict:
    """A model's published rates.

    Token rates may be None when a model is not billed per token at all; such a
    model must carry ``per_minute`` instead, or it has no usable price. The two
    are additive rather than exclusive so a model billed both ways can be
    represented without another shape.
    """
    return {
        "input_per_million": input_per_million,
        "output_per_million": output_per_million,
        "cached_input_per_million": cached_input_per_million,
        "audio_input_per_million": audio_input_per_million,
        # USD per minute of audio, for duration-billed models (ALP-300).
        "per_minute": per_minute,
        # Audio output tokens: the live gateway answers in audio, which Gemini
        # bills well above the text output rate.
        "audio_output_per_million": audio_output_per_million,
    }


MODEL_PRICING: dict[str, dict | None] = {
    # --- Google (paid tier, standard text rates) ---
    # 3.7 and 3.6 Flash are priced identically. The 1.50/7.50 previously
    # recorded for 3.6 is the rate that takes effect 2027-01-01; the rate in
    # force through 2026-12-31 is half that, so estimates were 2x high.
    # Cached-input is published for both and is filled in here -- ALP-285 notes
    # every Gemini row leaving it None, which blocks measuring cache savings.
    # 3.8 Flash (2026-09-02) is listed at the same rates as 3.7 and 3.6.
    "gemini-3.8-flash": _price(0.75, 3.75, cached_input_per_million=0.075),
    "gemini-3.7-flash": _price(0.75, 3.75, cached_input_per_million=0.075),
    "gemini-3.6-flash": _price(0.75, 3.75, cached_input_per_million=0.075),
    # The 3.x Flash family publishes one input rate for every modality, so
    # audio tokens price at the text rate and audio_input stays None.
    "gemini-3.5-flash": _price(1.50, 9.00, cached_input_per_million=0.15),
    "gemini-3.5-flash-lite": _price(0.30, 2.50, cached_input_per_million=0.03),
    # Not listed on the pricing page as of 2026-09-01; rates unchanged.
    "gemini-3-flash-preview": _price(0.50, 3.00),
    "gemini-3.1-pro-preview": _price(2.00, 12.00, cached_input_per_million=0.20),  # <=200k-token tier
    "gemini-3.1-flash-lite": _price(0.25, 1.50, cached_input_per_million=0.025, audio_input_per_million=0.50),
    # Live model: text rates; audio input bills at 3.00/1M and audio output
    # at 12.00/1M. The gateway's input is nearly all audio and it answers in
    # audio, so before these slices were priced its estimate was 4x low.
    "gemini-3.1-flash-live-preview": _price(
        0.75, 4.50, audio_input_per_million=3.00, audio_output_per_million=12.00
    ),
    "gemini-2.5-flash": _price(0.30, 2.50, cached_input_per_million=0.03, audio_input_per_million=1.00),
    "gemini-2.5-flash-lite": _price(0.10, 0.40, cached_input_per_million=0.01, audio_input_per_million=0.30),
    "gemini-2.5-pro": _price(1.25, 10.00, cached_input_per_million=0.125),  # <=200k-token tier
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
    # gpt-live-transcribe publishes a per-minute rate ($0.017/min of realtime
    # audio) and no per-token one. Token rates stay None rather than 0.0 so a
    # token-shaped payload from this model would price as unknown instead of
    # silently free; what it actually reports is audio duration, which is
    # recorded as token_usage.audio_seconds and priced from per_minute.
    "gpt-live-transcribe": _price(None, None, per_minute=0.017),
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
    "local-parakeet-live": _price(0.0, 0.0),
}


def pricing_for(model_id: str) -> dict | None:
    """Return the pricing dict for a model id, or None when unpriced."""
    return MODEL_PRICING.get(model_id)
