import asyncio
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import runtime_activity


class RuntimeActivityTests(unittest.TestCase):
    def setUp(self):
        runtime_activity.release_shutdown()

    def tearDown(self):
        runtime_activity.release_shutdown()

    def test_active_work_blocks_shutdown_and_reservation_blocks_new_work(self):
        with runtime_activity.track("audio import"):
            self.assertEqual(runtime_activity.busy_reason(), "audio import")
            self.assertFalse(runtime_activity.reserve_shutdown())

        self.assertTrue(runtime_activity.reserve_shutdown())
        self.assertEqual(runtime_activity.busy_reason(), "update installation")
        with self.assertRaises(runtime_activity.ShutdownReserved):
            with runtime_activity.track("analysis"):
                self.fail("reserved shutdown accepted new work")

    def test_reservation_expires_without_a_timer_thread(self):
        with patch.object(runtime_activity.time, "monotonic", side_effect=[100.0, 161.0, 161.0]):
            self.assertTrue(runtime_activity.reserve_shutdown(timeout_seconds=60))
            self.assertEqual(runtime_activity.busy_reason(), "")
            with runtime_activity.track("briefing"):
                self.assertEqual(runtime_activity.busy_reason(), "briefing")

    def test_request_tracker_covers_the_complete_yield_lifetime(self):
        async def exercise():
            dependency = runtime_activity.request_tracker("artifact export")()
            await anext(dependency)
            self.assertEqual(runtime_activity.busy_reason(), "artifact export")
            await dependency.aclose()
            self.assertEqual(runtime_activity.busy_reason(), "")

        asyncio.run(exercise())

    def test_long_running_http_routes_use_the_shared_tracker(self):
        from app.main import app

        expected = {
            "/api/sessions/{session_id}/analyze": "analysis",
            "/api/sessions/{session_id}/artifacts/transcript-export": "artifact export",
            "/api/sessions/{session_id}/artifacts/questions-export": "artifact export",
            "/api/sessions/{session_id}/artifacts/summary-export": "artifact export",
            "/api/sessions/{session_id}/import/transcript": "import",
            "/api/sessions/{session_id}/import/audio": "import",
            "/api/sessions/{session_id}/retranscribe": "retranscription",
            "/api/sessions/{session_id}/synthesis/refresh": "briefing synthesis",
        }
        routes = {
            route.path: route
            for route in app.routes
            if hasattr(route, "dependencies")
        }

        async def exercise():
            for path, reason in expected.items():
                dependency = routes[path].dependencies[0].dependency()
                await anext(dependency)
                self.assertEqual(runtime_activity.busy_reason(), reason)
                await dependency.aclose()

        asyncio.run(exercise())
        self.assertEqual(runtime_activity.busy_reason(), "")

    def test_new_call_websocket_is_rejected_while_shutdown_is_reserved(self):
        from app.ws.audio_handler import audio_websocket

        class Socket:
            def __init__(self):
                self.closed = None

            async def close(self, code, reason):
                self.closed = (code, reason)

        socket = Socket()
        self.assertTrue(runtime_activity.reserve_shutdown())
        asyncio.run(audio_websocket(socket, uuid.uuid4()))
        self.assertEqual(socket.closed[0], 1013)
        self.assertIn("update", socket.closed[1].lower())

    def test_first_local_model_load_is_rejected_during_shutdown_reservation(self):
        from app.services import local_transcriber

        model_id = "local-whisper-base"
        local_transcriber._loaded.pop(model_id, None)
        fake_onnx = SimpleNamespace(load_model=lambda *_: object())
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules, {"onnx_asr": fake_onnx}
        ), patch.object(local_transcriber, "data_dir", return_value=Path(temp_dir)):
            self.assertTrue(runtime_activity.reserve_shutdown())
            with self.assertRaises(runtime_activity.ShutdownReserved):
                local_transcriber._load_model(model_id)
        self.assertNotIn(model_id, local_transcriber._loaded)


if __name__ == "__main__":
    unittest.main()
