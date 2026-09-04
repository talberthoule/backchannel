"""The model-call boundary: leak detection, the tripwire, and the prompt log."""

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.services.pii import egress, shield, vault  # noqa: E402
from app.services.pii.recognizers import EMAIL, ORG, PERSON, PHONE  # noqa: E402


def _fake_db():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


class _DbContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _settings(**kw):
    return AsyncMock(return_value=shield.ShieldSettings(**kw))


class LeakDetectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        vault.reset_keys_for_tests()

    async def _seed(self):
        sid = uuid.uuid4()
        db = _fake_db()
        await vault.token_for(db, sid, PERSON, "Sarah Connor")
        await vault.token_for(db, sid, ORG, "Cyberdyne")
        await vault.token_for(db, sid, EMAIL, "sarah@cyberdyne.com")
        await vault.token_for(db, sid, PHONE, "555-867-5309")
        await vault.token_for(db, sid, PERSON, "Ann")  # too short to judge

    async def test_known_values_are_found_by_word_and_by_digits(self):
        await self._seed()
        leaks = egress.find_leaks("Call Sarah Connor at 555 867 5309 or sarah@cyberdyne.com about Cyberdyne.")
        self.assertEqual(
            sorted(leaks), sorted([("Sarah Connor", PERSON), ("Cyberdyne", ORG), ("sarah@cyberdyne.com", EMAIL), ("555-867-5309", PHONE)])
        )

    async def test_tokenized_text_and_near_misses_are_clean(self):
        await self._seed()
        self.assertEqual(egress.find_leaks("[PERSON_1] at [ORG_1]: [EMAIL_1], [PHONE_1]"), [])
        # Whole words with their casing: a lowercase substring is not the name.
        self.assertEqual(egress.find_leaks("the cyberdynes and sarah connors of this world"), [])
        self.assertEqual(egress.find_leaks("Ann met nobody"), [])


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        vault.reset_keys_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(egress, "log_dir", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _seed(self):
        await vault.token_for(_fake_db(), uuid.uuid4(), PERSON, "Sarah Connor")

    async def test_off_and_not_logging_does_nothing(self):
        await self._seed()
        with patch.object(shield, "get_settings_standalone", _settings(enabled=False)):
            await egress.guard("Sarah Connor said hi", model_id="m", source="chat")
        self.assertEqual(egress.recent(), [])

    async def test_a_leaking_prompt_is_refused_logged_and_audited(self):
        await self._seed()
        sid = uuid.uuid4()
        with patch.object(shield, "get_settings_standalone", _settings(enabled=True, prompt_log=True)), \
             patch.object(shield, "record_reveal", AsyncMock()) as audit:
            with self.assertRaises(egress.PiiEgressBlocked) as ctx:
                await egress.guard("Sarah Connor said hi", system="sys", model_id="gemini-x", session_id=sid, source="session_chat")
        self.assertIn("PERSON", str(ctx.exception))
        self.assertIn("Nothing was sent", str(ctx.exception))
        audit.assert_awaited_once_with(sid, "egress-blocked:session_chat", 1)
        entries = egress.recent()
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["blocked"])
        self.assertEqual(entries[0]["leaks"], [{"category": PERSON, "value": "Sarah Connor"}])
        self.assertTrue(entries[0]["prompt"].startswith("sys\n\nSarah Connor"))
        self.assertIsInstance(egress.PiiEgressBlocked("s", "m", []), ValueError)

    async def test_a_clean_prompt_passes_and_is_logged_with_tokens_noted(self):
        await self._seed()
        with patch.object(shield, "get_settings_standalone", _settings(enabled=True, prompt_log=True)):
            await egress.guard("[PERSON_1] said hi", model_id="gemini-x", source="consolidated_analyst")
        entry = egress.recent()[0]
        self.assertFalse(entry["blocked"])
        self.assertTrue(entry["tokens_present"])
        self.assertEqual(entry["source"], "consolidated_analyst")

    async def test_logging_without_the_shield_records_but_never_blocks(self):
        await self._seed()
        with patch.object(shield, "get_settings_standalone", _settings(enabled=False, prompt_log=True)):
            await egress.guard("Sarah Connor said hi", model_id="m", source="chat")
        entry = egress.recent()[0]
        self.assertFalse(entry["blocked"])
        self.assertEqual(entry["leaks"], [])

    async def test_recent_is_newest_first_and_clear_removes_the_file(self):
        with patch.object(shield, "get_settings_standalone", _settings(enabled=False, prompt_log=True)):
            for i in range(3):
                await egress.guard(f"prompt {i}", model_id="m", source="s")
        self.assertEqual([e["prompt"] for e in egress.recent(2)], ["prompt 2", "prompt 1"])
        self.assertEqual(egress.clear(), 1)
        self.assertEqual(egress.recent(), [])

    async def test_llm_entry_points_call_the_guard_before_any_provider(self):
        from app.services import llm

        target = MagicMock(endpoint=None, key="k")
        with patch.object(llm, "_prepare_call", AsyncMock(return_value=target)), \
             patch.object(llm.pii_egress, "guard", AsyncMock(side_effect=egress.PiiEgressBlocked("s", "m", [PERSON]))) as guard, \
             patch.object(llm, "_call_google", AsyncMock()) as google:
            with self.assertRaises(egress.PiiEgressBlocked):
                await llm.generate_text("gemini-x", "Sarah Connor", source="s")
        guard.assert_awaited_once()
        google.assert_not_awaited()

    async def test_llm_retokenizes_a_blocked_session_prompt_before_sending(self):
        from app.services import llm

        sid = uuid.uuid4()
        db = _fake_db()
        await vault.token_for(db, sid, ORG, "AI Studio")
        enabled = shield.ShieldSettings(enabled=True, ner=False)
        target = MagicMock(endpoint=None, key="k")

        with patch.object(shield, "get_settings_standalone", AsyncMock(return_value=enabled)), \
             patch.object(shield, "get_settings", AsyncMock(return_value=enabled)), \
             patch("app.database.async_session", return_value=_DbContext(db)), \
             patch.object(llm, "_prepare_call", AsyncMock(return_value=target)), \
             patch.object(llm, "_call_google", AsyncMock(return_value=("answer", None))) as google:
            answer = await llm.generate_text(
                "gemini-x",
                "Compare AI Studio personas.",
                session_id=sid,
                source="live_chat",
            )

        self.assertEqual("answer", answer)
        self.assertEqual("Compare [ORG_1] personas.", google.await_args.args[1])

    def test_settings_round_trip_the_prompt_log_flag(self):
        parsed = shield.ShieldSettings.from_json(json.dumps({"enabled": True, "prompt_log": True}))
        self.assertTrue(parsed.prompt_log)
        self.assertFalse(shield.ShieldSettings.from_json("{}").prompt_log)


if __name__ == "__main__":
    unittest.main()
