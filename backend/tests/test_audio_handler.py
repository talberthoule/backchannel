import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.ws import audio_handler
from app.ws.audio_handler import _decode_audio_frame


class AudioFrameDecodingTests(unittest.TestCase):
    def test_decodes_prefixed_and_legacy_frames(self):
        self.assertTrue(hasattr(audio_handler, "_decode_audio_frame"))
        decode_audio_frame = audio_handler._decode_audio_frame
        cases = [
            (b"\x00\x01\x02", (0, b"\x01\x02")),
            (b"\x01\x03\x04", (1, b"\x03\x04")),
            (b"\x07\x05\x06", (0, b"\x05\x06")),
            (b"\x08\x09", (0, b"\x08\x09")),
        ]

        for raw_frame, expected in cases:
            with self.subTest(raw_frame=raw_frame):
                self.assertEqual(expected, decode_audio_frame(raw_frame))


class AudioReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_flushes_both_tracks_and_reports_success(self):
        self.assertTrue(hasattr(audio_handler, "_reconnect_audio_pipeline"))
        reconnect_audio_pipeline = audio_handler._reconnect_audio_pipeline
        mic_segment = SimpleNamespace(speaker_id="auto_1", pcm_bytes=b"mic")
        system_segment = SimpleNamespace(speaker_id="auto_2", pcm_bytes=b"system")
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        diarizer = MagicMock()
        system_diarizer = MagicMock()
        transcription_queue = MagicMock()
        orchestrator = MagicMock()
        orchestrator._reconnect_gateway = AsyncMock(return_value=True)

        with patch(
            "app.ws.audio_handler.flush_diarizer_segments",
            side_effect=[[mic_segment], [system_segment]],
        ) as flush_segments:
            reconnected = await reconnect_audio_pipeline(
                websocket,
                diarizer,
                system_diarizer,
                transcription_queue,
                orchestrator,
            )

        self.assertTrue(reconnected)
        flush_segments.assert_has_calls([call(diarizer), call(system_diarizer)])
        self.assertEqual(
            [call("auto_1", b"mic"), call("sys_auto_2", b"system")],
            transcription_queue.add.call_args_list,
        )
        diarizer.reset.assert_called_once_with()
        system_diarizer.reset.assert_called_once_with()
        orchestrator._reconnect_gateway.assert_awaited_once_with()
        websocket.send_json.assert_awaited_once_with(
            {
                "type": "status",
                "data": {
                    "state": "active",
                    "message": "Reconnected to AI",
                },
            }
        )

    async def test_returns_false_when_gateway_reconnect_raises(self):
        self.assertTrue(hasattr(audio_handler, "_reconnect_audio_pipeline"))
        reconnect_audio_pipeline = audio_handler._reconnect_audio_pipeline
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        diarizer = MagicMock()
        transcription_queue = MagicMock()
        orchestrator = MagicMock()
        orchestrator._reconnect_gateway = AsyncMock(
            side_effect=RuntimeError("closed")
        )

        with (
            patch(
                "app.ws.audio_handler.flush_diarizer_segments",
                return_value=[],
            ),
            self.assertLogs("app.ws.audio_handler", level="ERROR"),
        ):
            reconnected = await reconnect_audio_pipeline(
                websocket,
                diarizer,
                None,
                transcription_queue,
                orchestrator,
            )

        self.assertFalse(reconnected)
        diarizer.reset.assert_called_once_with()
        orchestrator._reconnect_gateway.assert_awaited_once_with()
        websocket.send_json.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
