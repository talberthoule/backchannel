import logging

from google import genai
from google.genai import types

from app.config import settings
from app.services.secrets import resolve_provider_key
from app.services.token_usage import normalize_usage, record_token_usage

logger = logging.getLogger(__name__)

GATEWAY_SYSTEM_PROMPT = """You are a silent audio relay. Your only purpose is to listen to a live conversation and enable transcription. Do not speak, do not analyze, do not comment, and do not generate any output. Just listen."""


def _usage_delta(current: tuple[int, int, int], previous: tuple[int, int, int]) -> tuple[int, int, int]:
    if any(current[index] < previous[index] for index in range(3)):
        return 0, 0, 0
    return tuple(current[index] - previous[index] for index in range(3))


class GeminiLiveSession:
    def __init__(self, model_override: str | None = None, api_key: str | None = None, session_id=None):
        self._api_key = api_key
        self.client = None
        self.session = None
        self._context_manager = None
        self._model = model_override or settings.GEMINI_MODEL
        self._session_id = session_id
        self._last_usage = (0, 0, 0)

    async def connect(self):
        if self.client is None:
            key = self._api_key or await resolve_provider_key("google")
            self.client = genai.Client(api_key=key)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=GATEWAY_SYSTEM_PROMPT)]
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )
        self._context_manager = self.client.aio.live.connect(
            model=self._model,
            config=config,
        )
        self.session = await self._context_manager.__aenter__()
        self._last_usage = (0, 0, 0)
        logger.info("Gemini Live session connected")
        return self.session

    async def send_audio(self, audio_data: bytes):
        if self.session:
            await self.session.send_realtime_input(
                audio=types.Blob(data=audio_data, mime_type="audio/pcm;rate=16000")
            )

    async def receive_responses(self):
        """Yield input transcription events from the audio stream.

        Gemini 3.1 Flash Live can deliver multiple content parts in a
        single server event (e.g. audio + transcript together).  We
        iterate all parts so nothing is missed.
        """
        if not self.session:
            return
        async for response in self.session.receive():
            try:
                usage = normalize_usage(getattr(response, "usage_metadata", None))
            except Exception:
                logger.exception("Failed to parse Gemini Live token usage")
                usage = None
            if usage is not None:
                delta = _usage_delta(usage, self._last_usage)
                self._last_usage = usage
                await record_token_usage(
                    self._session_id,
                    "audio_gateway",
                    self._model,
                    {"input_tokens": delta[0], "output_tokens": delta[1], "total_tokens": delta[2]},
                )
            sc = response.server_content
            if not sc:
                continue

            # --- input transcription (user speech → text) ---
            has_input_tx = hasattr(sc, 'input_transcription') and bool(sc.input_transcription)
            if has_input_tx:
                text = sc.input_transcription.text
                logger.info(f"Live input_transcription: {repr(text)[:120]}")
                if text and text.strip():
                    from app.services.batch_transcriber import _is_hallucination
                    if _is_hallucination(text):
                        logger.info(f"Filtered hallucinated input transcription: '{text[:80]}'")
                    else:
                        yield {"type": "transcript", "data": text}

            # --- model turn parts (3.1 may bundle audio + text) ---
            if hasattr(sc, 'model_turn') and sc.model_turn:
                for part in sc.model_turn.parts or []:
                    if hasattr(part, 'text') and part.text and part.text.strip():
                        logger.debug(f"Unexpected model text in gateway: '{part.text[:80]}'")
                    # inline_data (audio) is intentionally ignored — gateway is silent

    async def close(self):
        if self._context_manager:
            try:
                await self._context_manager.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Gemini session: {e}")
            self.session = None
            self._context_manager = None
            logger.info("Gemini Live session closed")
