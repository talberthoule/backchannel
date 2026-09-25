"""The workspace's transcription language (ALP-399).

One setting, "auto" or an ISO 639-1 code, reaches every transcription path:
local Whisper takes it as onnx-asr's `language=`, the OpenAI speech-to-text
endpoint and Realtime session take it as `language`, Gemini Live takes it as
`language_codes`, and the prompt-driven transcribers (Gemini batch, OpenAI
chat audio) get it as a sentence in the prompt. "auto" sends nothing, which
leaves every provider on its own language detection.

The list is limited to codes every path accepts. Whisper selects its decoder
with a `<|xx|>` token and raises on a code it does not know, so each entry is
one of Whisper's languages, and each is also a valid BCP-47 tag (Gemini) and
ISO 639-1 code (OpenAI). English-only models (Parakeet v2) ignore it.
The setting is stored under SETTING_TRANSCRIPTION_LANGUAGE and read into
TranscriptionRuntimeConfig.language (transcription_runtime).
"""

SETTING_TRANSCRIPTION_LANGUAGE = "transcription.language"
AUTO_LANGUAGE = "auto"

# Ordered for the Admin picker: English, then the languages Parakeet v3 and
# the VibeVoice models also cover, then the rest alphabetically by name.
TRANSCRIPTION_LANGUAGES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "et": "Estonian",
    "fi": "Finnish",
    "el": "Greek",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "ms": "Malay",
    "mt": "Maltese",
    "no": "Norwegian",
    "ro": "Romanian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "vi": "Vietnamese",
}


def normalize_language(value: object) -> str:
    """A supported ISO 639-1 code, or "auto" for anything else (including blank)."""
    code = str(value or "").strip().lower()
    return code if code in TRANSCRIPTION_LANGUAGES else AUTO_LANGUAGE


def is_supported_language(value: str) -> bool:
    return value == AUTO_LANGUAGE or value in TRANSCRIPTION_LANGUAGES


def language_code_or_none(value: object) -> str | None:
    """The code to send to a provider, or None when detection should run."""
    code = normalize_language(value)
    return None if code == AUTO_LANGUAGE else code


def prompt_language_hint(value: object) -> str:
    """A sentence for prompt-driven transcribers; empty for auto-detection.

    Transcribe, never translate: a German call must come back in German, and a
    speaker who switches to English mid-sentence stays in English.
    """
    code = language_code_or_none(value)
    if code is None:
        return ""
    name = TRANSCRIPTION_LANGUAGES[code]
    return (
        f" The speech is mostly in {name}. Write it in the language actually "
        "spoken; do not translate."
    )


def language_options() -> list[dict[str, str]]:
    """The Admin picker's choices, auto-detect first."""
    return [{"code": AUTO_LANGUAGE, "name": "Detect automatically"}] + [
        {"code": code, "name": name} for code, name in TRANSCRIPTION_LANGUAGES.items()
    ]
