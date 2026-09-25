"""The workspace transcription language reaches every transcription path (ALP-399).

One setting, "auto" or an ISO 639-1 code: local Whisper gets onnx-asr's
`language=`, the OpenAI speech-to-text endpoint and Realtime session get a
`language` field, Gemini Live gets `language_codes`, and the prompt-driven
transcribers (Gemini batch, OpenAI chat audio) get a sentence in the prompt.
"auto" sends nothing anywhere. Also covers the transcript filters for scripts
written without spaces and Whisper's non-English silence hallucinations.
"""

import math
import os
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import numpy as np
from cryptography.fernet import Fernet
from fastapi import HTTPException

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.routers import diagnostics  # noqa: E402
from app.services import local_transcriber, openai_transcriber, transcription_runtime  # noqa: E402
from app.services.agents.orchestrator import AgentOrchestrator  # noqa: E402
from app.services.batch_transcriber import BatchTranscriber, filter_transcript_text  # noqa: E402
from app.services.gemini_live import GeminiLiveSession  # noqa: E402
from app.services.local_transcriber import LocalTranscriber, create_transcriber  # noqa: E402
from app.services.openai_realtime import OpenAIRealtimeSession, _session_update_payload  # noqa: E402
from app.services.openai_transcriber import OpenAIChatTranscriber, OpenAITranscriber  # noqa: E402
from app.services.transcription_language import (  # noqa: E402
    AUTO_LANGUAGE,
    SETTING_TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_LANGUAGES,
    language_code_or_none,
    language_options,
    normalize_language,
    prompt_language_hint,
)

# Whisper's language tokens (openai/whisper tokenizer.LANGUAGES). onnx-asr
# looks up f"<|{code}|>" and raises KeyError on anything else, so every code
# the Admin picker offers must be one of these.
WHISPER_LANGUAGE_CODES = frozenset(
    "en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro "
    "da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu "
    "is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo "
    "uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue".split()
)


def _speech_pcm(sample_rate: int = 16000) -> bytes:
    samples = [
        int(0.25 * 32767 * math.sin(2 * math.pi * 440 * i / sample_rate))
        for i in range(sample_rate)
    ]
    return np.array(samples, dtype=np.int16).tobytes()


class LanguageListTests(unittest.TestCase):
    def test_every_offered_code_is_a_whisper_language(self):
        self.assertTrue(set(TRANSCRIPTION_LANGUAGES) <= WHISPER_LANGUAGE_CODES)

    def test_normalize_accepts_known_codes_and_falls_back_to_auto(self):
        self.assertEqual("de", normalize_language("DE "))
        self.assertEqual(AUTO_LANGUAGE, normalize_language(""))
        self.assertEqual(AUTO_LANGUAGE, normalize_language(None))
        self.assertEqual(AUTO_LANGUAGE, normalize_language("xx"))
        self.assertIsNone(language_code_or_none("auto"))
        self.assertEqual("ja", language_code_or_none("ja"))

    def test_options_lead_with_auto_detect(self):
        options = language_options()
        self.assertEqual(AUTO_LANGUAGE, options[0]["code"])
        self.assertEqual(len(TRANSCRIPTION_LANGUAGES) + 1, len(options))

    def test_prompt_hint_names_the_language_and_forbids_translation(self):
        self.assertEqual("", prompt_language_hint("auto"))
        hint = prompt_language_hint("de")
        self.assertIn("German", hint)
        self.assertIn("do not translate", hint)


class RuntimeConfigTests(unittest.IsolatedAsyncioTestCase):
    async def _config_with(self, stored: dict):
        async def fake_get(_db, key, default=""):
            return stored.get(key, default)

        gateway = MagicMock(model_id="")
        with mock.patch.object(transcription_runtime, "get_app_setting", fake_get), \
             mock.patch.object(transcription_runtime, "get_local_only", AsyncMock(return_value=False)), \
             mock.patch.object(transcription_runtime, "_get_audio_gateway_config", AsyncMock(return_value=gateway)), \
             mock.patch.object(transcription_runtime, "shield_enabled", AsyncMock(return_value=False)):
            return await transcription_runtime.get_transcription_runtime_config(MagicMock())

    async def test_language_defaults_to_auto(self):
        config = await self._config_with({})
        self.assertEqual(AUTO_LANGUAGE, config.language)
        self.assertEqual(AUTO_LANGUAGE, config.to_dict()["language"])
        self.assertEqual(AUTO_LANGUAGE, config.to_dict()["language_options"][0]["code"])

    async def test_stored_language_is_read_and_junk_falls_back(self):
        self.assertEqual("de", (await self._config_with({SETTING_TRANSCRIPTION_LANGUAGE: "de"})).language)
        self.assertEqual(AUTO_LANGUAGE, (await self._config_with({SETTING_TRANSCRIPTION_LANGUAGE: "klingon"})).language)

    async def test_set_language_validates_and_normalizes(self):
        db = MagicMock()
        db.commit = AsyncMock()
        saved = AsyncMock()
        with mock.patch.object(transcription_runtime, "set_app_setting", saved), \
             mock.patch.object(transcription_runtime, "get_transcription_runtime_config", AsyncMock(return_value="cfg")):
            await transcription_runtime.set_transcription_language(db, " FR ")
            saved.assert_awaited_once_with(db, SETTING_TRANSCRIPTION_LANGUAGE, "fr")
            saved.reset_mock()
            await transcription_runtime.set_transcription_language(db, "")
            saved.assert_awaited_once_with(db, SETTING_TRANSCRIPTION_LANGUAGE, AUTO_LANGUAGE)
            with self.assertRaises(ValueError):
                await transcription_runtime.set_transcription_language(db, "xx")

    async def test_patch_endpoint_sets_language_and_rejects_unknown_codes(self):
        runtime = transcription_runtime.TranscriptionRuntimeConfig("m", "", "d", language="de")
        with mock.patch.object(diagnostics, "get_transcription_runtime_config", AsyncMock(return_value=runtime)), \
             mock.patch.object(diagnostics, "set_transcription_language", AsyncMock(return_value=runtime)) as setter:
            result = await diagnostics.update_transcription_config(
                diagnostics.BatchTranscriberUpdate(language="de"), db=MagicMock()
            )
            setter.assert_awaited_once()
            self.assertEqual("de", result["language"])
        with mock.patch.object(diagnostics, "get_transcription_runtime_config", AsyncMock(return_value=runtime)), \
             mock.patch.object(diagnostics, "set_transcription_language", AsyncMock(side_effect=ValueError("bad"))):
            with self.assertRaises(HTTPException) as ctx:
                await diagnostics.update_transcription_config(
                    diagnostics.BatchTranscriberUpdate(language="xx"), db=MagicMock()
                )
            self.assertEqual(400, ctx.exception.status_code)


class LocalWhisperTests(unittest.IsolatedAsyncioTestCase):
    async def _recognize_kwargs(self, model_id: str, language: str) -> dict:
        model = MagicMock()
        model.recognize.return_value = "guten morgen zusammen"
        with patch.object(local_transcriber, "_load_model", return_value=model):
            await create_transcriber(model_id, language=language).transcribe_segment(_speech_pcm())
        return model.recognize.call_args.kwargs

    async def test_whisper_gets_the_language(self):
        self.assertEqual({"language": "de"}, await self._recognize_kwargs("local-whisper-base", "de"))

    async def test_auto_leaves_whisper_detecting(self):
        self.assertEqual({}, await self._recognize_kwargs("local-whisper-base", "auto"))

    async def test_english_only_parakeet_gets_no_language(self):
        self.assertEqual({}, await self._recognize_kwargs("local-parakeet-tdt-0.6b", "de"))

    def test_factory_passes_language_to_local(self):
        self.assertEqual({"language": "ja"}, LocalTranscriber("local-whisper-base", language="ja")._recognize_kwargs)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._payload)


class OpenAIBatchTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, transcriber):
        with patch.object(openai_transcriber, "resolve_provider_key", AsyncMock(return_value="sk-test")), \
             patch.object(openai_transcriber, "record_token_usage", AsyncMock()):
            return await transcriber.transcribe_segment(_speech_pcm())

    async def test_speech_to_text_endpoint_gets_the_language_field(self):
        http = _FakeHttp({"text": "hola a todos"})
        await self._run(OpenAITranscriber("gpt-4o-transcribe", client=http, language="es"))
        self.assertEqual("es", http.calls[0]["data"]["language"])

    async def test_speech_to_text_endpoint_omits_language_for_auto(self):
        http = _FakeHttp({"text": "hello there everyone"})
        await self._run(OpenAITranscriber("gpt-4o-transcribe", client=http, language="auto"))
        self.assertNotIn("language", http.calls[0]["data"])

    async def test_chat_audio_prompt_carries_the_language(self):
        http = _FakeHttp({"choices": [{"message": {"content": "bonjour tout le monde"}}]})
        await self._run(OpenAIChatTranscriber("gpt-audio-1.5", client=http, language="fr"))
        text_part = http.calls[0]["json"]["messages"][0]["content"][1]["text"]
        self.assertIn("French", text_part)

    def test_factory_routes_language_to_openai_transcribers(self):
        self.assertEqual("pt", create_transcriber("gpt-4o-transcribe", language="pt")._language)
        self.assertIn("Portuguese", create_transcriber("gpt-audio-1.5", language="pt")._prompt)


class GeminiBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_carries_the_language(self):
        captured = {}

        async def generate_content(model, contents):
            captured["prompt"] = contents[0].parts[1].text
            return SimpleNamespace(text="buongiorno a tutti", usage_metadata=None)

        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
        with patch("app.services.batch_transcriber.record_token_usage", AsyncMock()):
            await BatchTranscriber(model_id="gemini-3.5-flash", client=client, language="it").transcribe_segment(
                _speech_pcm()
            )
        self.assertIn("Italian", captured["prompt"])

    def test_auto_keeps_the_original_prompt(self):
        prompt = create_transcriber("gemini-3.5-flash", language="auto")._prompt
        self.assertTrue(prompt.endswith("output an empty string."))


class LiveGatewayTests(unittest.TestCase):
    def test_gemini_live_sets_language_codes(self):
        config = GeminiLiveSession(model_override="gemini-3.1-flash-live-preview", language="ko")._live_config()
        self.assertEqual(["ko"], config.input_audio_transcription.language_codes)

    def test_gemini_live_auto_leaves_detection_on(self):
        config = GeminiLiveSession(model_override="gemini-3.1-flash-live-preview", language="auto")._live_config()
        self.assertIsNone(config.input_audio_transcription.language_codes)

    def test_openai_realtime_payload_carries_language(self):
        transcription = _session_update_payload("gpt-live-transcribe", "de")["session"]["audio"]["input"]["transcription"]
        self.assertEqual({"model": "gpt-live-transcribe", "language": "de"}, transcription)
        bare = _session_update_payload("gpt-live-transcribe")["session"]["audio"]["input"]["transcription"]
        self.assertEqual({"model": "gpt-live-transcribe"}, bare)
        self.assertEqual("de", OpenAIRealtimeSession(model_override="gpt-live-transcribe", language="de")._language)

    def _gateway(self, model_id: str, language: str):
        config = MagicMock(enabled=True, model_id=model_id, prompt="", interval_seconds=15, sub_types="", lenses="")
        with (
            patch("app.services.agents.orchestrator.ConsolidatedAnalystAgent", return_value=MagicMock()),
            patch("app.services.agents.orchestrator.ObjectionHandlerAgent", return_value=MagicMock()),
        ):
            orchestrator = AgentOrchestrator(
                session_id=uuid4(),
                websocket=AsyncMock(),
                directives=[],
                doc_summaries="",
                active_questions=[],
                speakers=[],
                agent_configs={"audio_gateway": config},
                admitted_models={model_id},
                transcription_language=language,
            )
        return orchestrator.audio_gateway

    def test_orchestrator_hands_the_language_to_cloud_gateways(self):
        self.assertEqual("es", self._gateway("gemini-3.1-flash-live-preview", "es")._language)
        self.assertEqual("es", self._gateway("gpt-live-transcribe", "es")._language)


class UnspacedScriptFilterTests(unittest.TestCase):
    def test_chinese_and_japanese_sentences_without_spaces_are_kept(self):
        chinese = "\u6211\u4eec\u4e0b\u5468\u4e8c\u5f00\u59cb\u8bd5\u70b9"  # "we start the pilot next Tuesday"
        japanese = "\u6765\u9031\u306e\u706b\u66dc\u65e5\u306b\u59cb\u3081\u307e\u3059"  # "we start next Tuesday"
        thai = "\u0e40\u0e23\u0e32\u0e08\u0e30\u0e40\u0e23\u0e34\u0e48\u0e21\u0e1e\u0e23\u0e38\u0e48\u0e07\u0e19\u0e35\u0e49"
        for text in (chinese, japanese, thai):
            self.assertEqual(text, filter_transcript_text(text))

    def test_three_characters_are_enough_and_fewer_are_not(self):
        self.assertEqual("\u6211\u540c\u610f", filter_transcript_text("\u6211\u540c\u610f"))  # "I agree"
        self.assertIsNone(filter_transcript_text("\u597d\u7684"))  # "okay"
        self.assertIsNone(filter_transcript_text("\u55ef"))  # "mm"

    def test_spaced_languages_still_need_two_words(self):
        self.assertIsNone(filter_transcript_text("Genau"))
        self.assertEqual("Genau so", filter_transcript_text("Genau so"))

    def test_known_non_english_whisper_hallucinations_are_dropped(self):
        for text in (
            "Untertitel im Auftrag des ZDF, 2021",
            "Subt\u00edtulos realizados por la comunidad de Amara.org",
            "Sous-titres r\u00e9alis\u00e9s par la communaut\u00e9 d'Amara.org",
            "Legendas pela comunidade Amara.org",
            "\u3054\u8996\u8074\u3042\u308a\u304c\u3068\u3046\u3054\u3056\u3044\u307e\u3057\u305f",
            "\uc2dc\uccad\ud574 \uc8fc\uc154\uc11c \uac10\uc0ac\ud569\ub2c8\ub2e4",
            "\u8c22\u8c22\u89c2\u770b",
        ):
            self.assertIsNone(filter_transcript_text(text), text.encode("unicode_escape"))


if __name__ == "__main__":
    unittest.main()
