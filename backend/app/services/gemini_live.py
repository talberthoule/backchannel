import logging

from google import genai
from google.genai import types

from app.config import settings
from app.services.secrets import resolve_provider_key
from app.services.token_usage import record_token_usage

logger = logging.getLogger(__name__)

GATEWAY_SYSTEM_PROMPT = """You are a silent audio relay. Your only purpose is to listen to a live conversation and enable transcription. Do not speak, do not analyze, do not comment, and do not generate any output. Just listen."""

# Usage accounting for the Live API: one pending usage per session, flushed
# per turn.
#
# What is settled: each turn is one billed generation request whose prompt is
# the whole session context so far. The API reference defines totalTokenCount
# as "total token count for the generation request", and a Google engineer
# answering the billing-mismatch thread on the developer forum (July 2026)
# said to sum the full per-turn context, as reported in promptTokensDetails,
# across turns. The original implementation read the counts as a cumulative
# session counter and stored only the increase between messages, which
# under-reports a talking call badly and dropped any message whose reply was
# shorter than the previous one outright.
#
# What is NOT settled: how often usage_metadata arrives within a turn. The
# reference only says a server message "may have a usageMetadata field", which
# permits either one usage per turn or usage riding on every audio chunk with
# counts that grow as the turn proceeds. Recording every message as-is would
# be right under the first pattern and would multiply each turn by its chunk
# count under the second. The stored rows cannot settle it either way.
#
# So the rule below is correct under both: every usage_metadata REPLACES the
# pending value, and the pending value is recorded once when the turn ends
# (server_content.turn_complete, or interrupted, which also ends a turn), when
# the receive loop exits for any reason, and when the session closes.
# Per-chunk growing counts therefore record once at their final value and a
# single per-turn usage records once. generation_complete is deliberately not
# a flush point: it precedes turn_complete inside the same turn, so flushing
# there and again at turn_complete would record the turn twice under the
# per-chunk pattern. The DEBUG line logged per usage message shows the counts
# and whether turn_complete was set, so one real call can settle the open
# question. Cloud Console remains the billing authority.
_USAGE_SOURCE = "audio_gateway"


def _ends_turn(server_content) -> bool:
    return bool(
        getattr(server_content, "turn_complete", False)
        or getattr(server_content, "interrupted", False)
    )


class GeminiLiveSession:
    def __init__(self, model_override: str | None = None, api_key: str | None = None, session_id=None):
        self._api_key = api_key
        self.client = None
        self.session = None
        self._context_manager = None
        self._model = settings.GEMINI_MODEL if model_override is None else model_override
        self._session_id = session_id
        # The most recent usage_metadata of the turn in progress; see the
        # module comment for the flush rule.
        self._pending_usage = None

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
        self._pending_usage = None
        logger.info("Gemini Live session connected")
        return self.session

    async def send_audio(self, audio_data: bytes):
        if self.session:
            await self.session.send_realtime_input(
                audio=types.Blob(data=audio_data, mime_type="audio/pcm;rate=16000")
            )

    def _note_usage(self, usage_metadata, turn_complete: bool) -> None:
        self._pending_usage = usage_metadata
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Live usage_metadata: prompt=%s response=%s thoughts=%s total=%s turn_complete=%s",
                getattr(usage_metadata, "prompt_token_count", None),
                getattr(usage_metadata, "response_token_count", None),
                getattr(usage_metadata, "thoughts_token_count", None),
                getattr(usage_metadata, "total_token_count", None),
                turn_complete,
            )

    async def _flush_usage(self) -> None:
        """Record the pending usage once and clear it.

        record_token_usage never raises: a malformed usage payload is logged
        there and must not interrupt transcription.
        """
        pending = self._pending_usage
        if pending is None:
            return
        self._pending_usage = None
        await record_token_usage(self._session_id, _USAGE_SOURCE, self._model, pending)

    async def receive_responses(self):
        """Yield input transcription events from the audio stream.

        Gemini 3.1 Flash Live can deliver multiple content parts in a
        single server event (e.g. audio + transcript together).  We
        iterate all parts so nothing is missed.
        """
        if not self.session:
            return
        try:
            async for response in self.session.receive():
                sc = response.server_content
                usage_metadata = getattr(response, "usage_metadata", None)
                if usage_metadata is not None:
                    self._note_usage(usage_metadata, _ends_turn(sc) if sc else False)
                if not sc:
                    continue
                if _ends_turn(sc):
                    await self._flush_usage()

                # --- input transcription (user speech -> text) ---
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
                        # inline_data (audio) is intentionally ignored - gateway is silent
        finally:
            # The loop ends on disconnect, error, or the consumer stopping;
            # a turn cut short still cost its tokens.
            await self._flush_usage()

    async def close(self):
        await self._flush_usage()
        if self._context_manager:
            try:
                await self._context_manager.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Gemini session: {e}")
            self.session = None
            self._context_manager = None
            logger.info("Gemini Live session closed")
