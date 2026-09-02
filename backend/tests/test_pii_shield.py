"""PII Shield: recognizers, the vault's token contract, encode/decode, and
the two egress wrappers (REST middleware, WebSocket proxy)."""

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.services.pii import ner, shield, vault  # noqa: E402
from app.services.pii.recognizers import (  # noqa: E402
    ADDRESS, CARD, EMAIL, IP, ORG, PERSON, PHONE, SSN,
    RosterEntry, Span, find_patterns, find_roster, normalize_value, resolve_spans,
)
from app.services.pii.reveal_middleware import PiiRevealMiddleware  # noqa: E402
from app.services.pii.ws import RevealingWebSocket  # noqa: E402

ALL = set(shield.CATEGORIES)


def _fake_db(rows=None):
    """An AsyncSession stand-in whose only query returns ``rows``."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows or [])
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _enabled(**overrides):
    settings = shield.ShieldSettings(enabled=True, ner=False)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


class RecognizerTests(unittest.TestCase):
    def test_structured_identifiers_are_found_with_their_checks(self):
        text = (
            "Reach me at sarah.connor@cyberdyne.com or 555-867-5309, card 4111 1111 1111 1111, "
            "SSN 078-05-1120, server 10.0.0.12, office at 123 Main Street, Suite 400."
        )
        found = {(s.category, s.text) for s in find_patterns(text, ALL)}
        self.assertIn((EMAIL, "sarah.connor@cyberdyne.com"), found)
        self.assertIn((PHONE, "555-867-5309"), found)
        self.assertIn((CARD, "4111 1111 1111 1111"), found)
        self.assertIn((SSN, "078-05-1120"), found)
        self.assertIn((IP, "10.0.0.12"), found)
        self.assertIn((ADDRESS, "123 Main Street, Suite 400"), found)

    def test_ordinary_numbers_are_not_identifiers(self):
        text = "The 2026 budget is $1,200,000 and we meet 10/8; invoice 1234 5678 9012 3456 was paid."
        categories = {s.category for s in find_patterns(text, ALL)}
        # 1234 5678 9012 3456 fails Luhn, so it is not a card.
        self.assertEqual(categories, set())

    def test_introductions_name_people_but_not_greetings(self):
        found = {s.text for s in find_patterns("Hi, my name is Sarah Connor. This is Great news.", {PERSON})}
        self.assertEqual(found, {"Sarah Connor"})

    def test_roster_matches_whole_names_and_capitalized_parts(self):
        roster = [RosterEntry("Bill Brown", PERSON), RosterEntry("Cyberdyne", ORG)]
        text = "Bill Brown said the bill is due; Brown agreed and cyberdyne signed."
        found = [(s.category, s.text) for s in find_roster(text, roster, ALL)]
        self.assertIn((PERSON, "Bill Brown"), found)
        self.assertIn((PERSON, "Brown"), found)
        self.assertIn((ORG, "cyberdyne"), found)
        self.assertNotIn((PERSON, "bill"), found)

    def test_categories_can_be_switched_off(self):
        self.assertEqual(find_patterns("mail me at a@b.co", {PHONE}), [])

    def test_overlaps_keep_the_longest_then_the_stronger_category(self):
        spans = [
            Span(0, 4, PERSON, "Bill", 0.9, "roster"),
            Span(0, 10, PERSON, "Bill Brown", 1.0, "roster"),
            Span(20, 32, PHONE, "555 867 5309", 0.8, "pattern"),
            Span(20, 32, CARD, "555 867 5309", 0.8, "pattern"),
        ]
        kept = resolve_spans(spans)
        self.assertEqual([(s.start, s.end, s.category) for s in kept], [(0, 10, PERSON), (20, 32, CARD)])

    def test_normalization_folds_case_and_separators(self):
        self.assertEqual(normalize_value("555-867-5309", PHONE), "5558675309")
        self.assertEqual(normalize_value("Sarah  Connor", PERSON), "sarah connor")
        self.assertEqual(normalize_value("A@B.co", EMAIL), "a@b.co")


class VaultTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        vault.reset_keys_for_tests()

    async def test_same_value_gets_the_same_token_and_reveals_round_trip(self):
        sid = uuid.uuid4()
        db = _fake_db()
        first = await vault.token_for(db, sid, PERSON, "Sarah Connor")
        again = await vault.token_for(db, sid, PERSON, "sarah connor")
        other = await vault.token_for(db, sid, PERSON, "Bill Brown")
        email = await vault.token_for(db, sid, EMAIL, "sarah@x.com")
        self.assertEqual(first, "[PERSON_1]")
        self.assertEqual(again, first)
        self.assertEqual(other, "[PERSON_2]")
        self.assertEqual(email, "[EMAIL_1]")
        self.assertEqual(db.add.call_count, 3)
        mapping = await vault.reveal_map(db, sid)
        self.assertEqual(mapping, {"[PERSON_1]": "Sarah Connor", "[PERSON_2]": "Bill Brown", "[EMAIL_1]": "sarah@x.com"})

    async def test_stored_row_holds_ciphertext_and_a_keyed_hash_not_the_value(self):
        db = _fake_db()
        await vault.token_for(db, uuid.uuid4(), EMAIL, "sarah@x.com")
        row = db.add.call_args.args[0]
        self.assertNotIn("sarah", row.value_encrypted)
        self.assertNotIn("sarah", row.value_hmac)
        self.assertEqual(len(row.value_hmac), 64)
        self.assertEqual(vault.decrypt(row.value_encrypted), "sarah@x.com")

    async def test_tokens_are_per_session(self):
        db = _fake_db()
        a = await vault.token_for(db, uuid.uuid4(), PERSON, "Sarah Connor")
        b = await vault.token_for(db, uuid.uuid4(), PERSON, "Sarah Connor")
        self.assertEqual(a, b)  # same ordinal, different vaults
        self.assertEqual(db.add.call_count, 2)

    async def test_existing_rows_are_loaded_before_minting(self):
        sid = uuid.uuid4()
        row = SimpleNamespace(
            category=PERSON, ordinal=4, token="[PERSON_4]",
            value_hmac=vault.value_hmac(PERSON, "Sarah Connor"), value_encrypted=vault.encrypt("Sarah Connor"),
        )
        db = _fake_db([row])
        self.assertEqual(await vault.token_for(db, sid, PERSON, "Sarah Connor"), "[PERSON_4]")
        self.assertEqual(await vault.token_for(db, sid, PERSON, "New Person"), "[PERSON_5]")

    def test_token_pattern_accepts_bracketed_and_bare_forms_only(self):
        self.assertTrue(vault.has_tokens("[PERSON_1] met PHONE_2"))
        self.assertFalse(vault.has_tokens("Person 1 met the IP 4 team"))
        self.assertFalse(vault.has_tokens(""))


class ShieldTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        vault.reset_keys_for_tests()
        shield.invalidate_settings_cache()

    async def test_disabled_shield_leaves_text_untouched_and_queries_nothing(self):
        db = _fake_db()
        with patch.object(shield, "get_settings", AsyncMock(return_value=shield.ShieldSettings())):
            self.assertEqual(await shield.protect_text(db, uuid.uuid4(), "call sarah@x.com"), "call sarah@x.com")
        db.execute.assert_not_awaited()

    async def test_protect_then_reveal_round_trips_with_consistent_tokens(self):
        sid = uuid.uuid4()
        db = _fake_db()
        text = "Sarah Connor (sarah@x.com) asked Bill Brown to call 555-867-5309. Sarah agreed."
        speakers = [SimpleNamespace(name="Sarah Connor", display_name=""), SimpleNamespace(name="Bill Brown", display_name="")]
        with patch.object(shield, "get_settings", AsyncMock(return_value=_enabled())), \
             patch.object(shield, "session_roster", AsyncMock(return_value=[RosterEntry(s.name, PERSON) for s in speakers])):
            protected = await shield.protect_text(db, sid, text)
        self.assertEqual(
            protected,
            "[PERSON_1] ([EMAIL_1]) asked [PERSON_2] to call [PHONE_1]. [PERSON_1] agreed.",
        )
        with patch.object(shield, "record_reveal", AsyncMock()) as audit:
            revealed = await shield.reveal_text(db, sid, protected, route="test")
        # A first name matched from the roster stands for the whole person,
        # so it comes back as the full name the roster knows.
        self.assertEqual(revealed, text.replace("Sarah agreed", "Sarah Connor agreed"))
        audit.assert_awaited_once_with(sid, "test", 5)

    async def test_existing_tokens_are_never_re_tokenized(self):
        spans = shield.detect("[PERSON_1] emailed [EMAIL_1] from a@b.co", [], _enabled())
        self.assertEqual([(s.category, s.text) for s in spans], [(EMAIL, "a@b.co")])

    async def test_bare_tokens_from_a_model_reply_still_reveal(self):
        mapping = {"[PERSON_1]": "Sarah Connor"}
        text, count = shield.substitute("PERSON_1 said [PERSON_1] would; [PERSON_9] unknown", mapping)
        self.assertEqual(text, "Sarah Connor said Sarah Connor would; [PERSON_9] unknown")
        self.assertEqual(count, 2)

    async def test_speaker_names_become_tokens_but_generic_labels_do_not(self):
        sid = uuid.uuid4()
        db = _fake_db()
        with patch.object(shield, "get_settings", AsyncMock(return_value=_enabled())):
            self.assertEqual(await shield.protect_name(db, sid, "Participant 2"), "Participant 2")
            self.assertEqual(await shield.protect_name(db, sid, "Unknown"), "Unknown")
            self.assertEqual(await shield.protect_name(db, sid, "Sarah Connor"), "[PERSON_1]")
            self.assertEqual(await shield.protect_name(db, sid, "[PERSON_1]"), "[PERSON_1]")

    async def test_roster_remembers_names_the_vault_already_holds(self):
        # The speaker row now reads "[PERSON_1]"; the roster must still know
        # the person as Bill Brown so "Brown agreed" maps to the same token.
        sid = uuid.uuid4()
        db = _fake_db()  # no Speaker rows come back: the name lives only in the vault
        with patch.object(shield, "get_settings", AsyncMock(return_value=_enabled())):
            self.assertEqual(await shield.protect_name(db, sid, "Bill Brown"), "[PERSON_1]")
            roster = await shield.session_roster(db, sid, _enabled())
            self.assertEqual([(r.value, r.category) for r in roster], [("Bill Brown", PERSON)])
            protected = await shield.protect_text(db, sid, "Brown agreed with Bill Brown.")
        self.assertEqual(protected, "[PERSON_1] agreed with [PERSON_1].")

    def test_the_roster_outranks_the_model_on_a_tie(self):
        spans = [
            Span(0, 5, PERSON, "Brown", 1.0, "ner"),
            Span(0, 5, PERSON, "Brown", 0.9, "roster", canonical="Bill Brown"),
        ]
        self.assertEqual(resolve_spans(spans)[0].value, "Bill Brown")
        # ...and about the category: a protected company stays a company even
        # when the model reads its name as a person.
        spans = [
            Span(0, 9, PERSON, "Cyberdyne", 1.0, "ner"),
            Span(0, 9, ORG, "Cyberdyne", 1.0, "roster"),
        ]
        self.assertEqual(resolve_spans(spans)[0].category, ORG)

    async def test_a_newly_minted_name_joins_the_roster_for_the_next_line(self):
        sid = uuid.uuid4()
        db = _fake_db()
        settings = _enabled()
        with patch.object(shield, "get_settings", AsyncMock(return_value=settings)):
            first = await shield.protect_text(db, sid, "Hi, my name is Sarah Connor.")
            second = await shield.protect_text(db, sid, "Connor will send it; Sarah agreed.")
        self.assertEqual(first, "Hi, my name is [PERSON_1].")
        self.assertEqual(second, "[PERSON_1] will send it; [PERSON_1] agreed.")

    async def test_reveal_payload_walks_nested_structures(self):
        sid = uuid.uuid4()
        db = _fake_db()
        with patch.object(shield, "get_settings", AsyncMock(return_value=_enabled())), \
             patch.object(shield, "session_roster", AsyncMock(return_value=[])):
            await shield.protect_text(db, sid, "mail a@b.co")
        payload = {"items": [{"text": "mail [EMAIL_1]", "n": 3}], "note": None}
        revealed = await shield.reveal_payload(db, sid, payload, audit=False)
        self.assertEqual(revealed, {"items": [{"text": "mail a@b.co", "n": 3}], "note": None})

    async def test_settings_round_trip_and_reject_unknown_categories(self):
        parsed = shield.ShieldSettings.from_json(json.dumps({
            "enabled": True, "categories": ["PERSON", "BOGUS"], "ner": False,
            "protected_terms": [{"value": " Acme ", "category": "ORG"}, {"value": "", "category": "ORG"}, {"value": "x", "category": "NOPE"}],
        }))
        self.assertTrue(parsed.enabled)
        self.assertEqual(parsed.categories, ["PERSON"])
        self.assertFalse(parsed.ner)
        self.assertEqual(parsed.protected_terms, [{"value": "Acme", "category": "ORG"}])
        self.assertEqual(shield.ShieldSettings.from_json("not json").enabled, False)

    async def test_preview_numbers_tokens_without_touching_the_vault(self):
        db = _fake_db()
        with patch.object(shield, "get_settings", AsyncMock(return_value=_enabled(protected_terms=[{"value": "Acme", "category": ORG}]))):
            result = await shield.preview(db, "Acme hired a@b.co and c@d.co; Acme again.")
        self.assertEqual(result["protected"], "[ORG_1] hired [EMAIL_1] and [EMAIL_2]; [ORG_1] again.")
        self.assertEqual([f["source"] for f in result["findings"]][:1], ["roster"])
        db.add.assert_not_called()


class EgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        vault.reset_keys_for_tests()

    async def _seed(self, sid):
        db = _fake_db()
        await vault.token_for(db, sid, PERSON, "Sarah Connor")
        return db

    async def test_middleware_reveals_session_scoped_json_and_fixes_content_length(self):
        sid = uuid.uuid4()
        await self._seed(sid)
        body = json.dumps([{"text": "[PERSON_1] spoke"}]).encode()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body[:5], "more_body": True})
            await send({"type": "http.response.body", "body": body[5:], "more_body": False})

        sent = []
        scope = {"type": "http", "path": f"/api/sessions/{sid}/transcripts", "method": "GET"}
        with patch("app.database.async_session", lambda: _AsyncCtx(_fake_db())), \
             patch.object(shield, "record_reveal", AsyncMock()):
            await PiiRevealMiddleware(app)(scope, None, lambda m: _collect(sent, m))
        out = b"".join(m["body"] for m in sent if m["type"] == "http.response.body")
        self.assertEqual(json.loads(out), [{"text": "Sarah Connor spoke"}])
        headers = dict(sent[0]["headers"])
        self.assertEqual(headers[b"content-length"], str(len(out)).encode())

    async def test_middleware_reveals_each_session_in_the_list_by_its_own_id(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        db = _fake_db()
        await vault.token_for(db, a, PERSON, "Sarah Connor")
        await vault.token_for(db, b, PERSON, "Bill Brown")
        body = json.dumps([{"id": str(a), "name": "[PERSON_1]"}, {"id": str(b), "name": "[PERSON_1]"}]).encode()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body, "more_body": False})

        sent = []
        with patch("app.database.async_session", lambda: _AsyncCtx(_fake_db())), \
             patch.object(shield, "record_reveal", AsyncMock()):
            await PiiRevealMiddleware(app)({"type": "http", "path": "/api/sessions", "method": "GET"}, None, lambda m: _collect(sent, m))
        out = json.loads(b"".join(m["body"] for m in sent if m["type"] == "http.response.body"))
        self.assertEqual([s["name"] for s in out], ["Sarah Connor", "Bill Brown"])

    async def test_middleware_passes_through_other_paths_and_non_json(self):
        sid = uuid.uuid4()
        await self._seed(sid)
        payload = b"[PERSON_1]"

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": payload, "more_body": False})

        for path in (f"/api/sessions/{sid}/transcript-export", "/api/chat"):
            sent = []
            await PiiRevealMiddleware(app)({"type": "http", "path": path, "method": "GET"}, None, lambda m: _collect(sent, m))
            self.assertEqual(sent[-1]["body"], payload)

    async def test_websocket_proxy_reveals_json_and_delegates_the_rest(self):
        sid = uuid.uuid4()
        await self._seed(sid)
        inner = MagicMock()
        inner.send_json = AsyncMock()
        inner.receive_bytes = AsyncMock(return_value=b"x")
        inner.close = AsyncMock()
        sock = RevealingWebSocket(inner, sid)
        with patch("app.database.async_session", lambda: _AsyncCtx(_fake_db())), \
             patch.object(shield, "record_reveal", AsyncMock()) as audit:
            await sock.send_json({"type": "transcript", "data": {"text": "[PERSON_1] here"}})
            await sock.send_json({"type": "status", "data": {"state": "ok"}})
            self.assertEqual(await sock.receive_bytes(), b"x")
            await sock.close()
        inner.send_json.assert_any_await({"type": "transcript", "data": {"text": "Sarah Connor here"}}, "text")
        inner.send_json.assert_any_await({"type": "status", "data": {"state": "ok"}}, "text")
        audit.assert_awaited_once_with(sid, "ws", 1)


class _AsyncCtx:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


async def _collect(sink, message):
    sink.append(message)


class NerTests(unittest.TestCase):
    def test_wordpiece_splits_with_continuations_and_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            vocab = Path(tmp) / "vocab.txt"
            vocab.write_text("\n".join(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "Sarah", "Con", "##nor", ",", "hello"]) + "\n", encoding="utf-8")
            tokenizer = ner.WordPiece(vocab)
        self.assertEqual(tokenizer.words("Sarah Connor, hello"), [(0, 5, "Sarah"), (6, 12, "Connor"), (12, 13, ","), (14, 19, "hello")])
        self.assertEqual(tokenizer.encode_word("Connor"), [5, 6])
        self.assertEqual(tokenizer.encode_word("zzz"), [tokenizer.unk])

    def test_entities_merge_continuations_and_split_on_new_begins(self):
        import numpy as np

        model = ner.NerModel.__new__(ner.NerModel)
        model.labels = ["O", "B-MISC", "I-MISC", "B-PER", "I-PER", "B-ORG", "I-ORG", "B-LOC", "I-LOC"]
        tokenizer = MagicMock()
        tokenizer.cls, tokenizer.sep = 101, 102
        model.tokenizer = tokenizer
        text = "Sarah Connor met Bill at Acme"
        chunk = [(0, 5, [1]), (6, 12, [2, 3]), (13, 16, [4]), (17, 21, [5]), (22, 24, [6]), (25, 29, [7])]
        # One row per piece incl. CLS/SEP: labels by first piece of each word.
        rows = ["O", "B-PER", "I-PER", "I-PER", "O", "B-PER", "O", "B-ORG", "O"]
        probs = np.zeros((len(rows), 9))
        for i, label in enumerate(rows):
            probs[i, model.labels.index(label)] = 0.9
        model._run = lambda ids: probs
        spans = model._entities_for(text, chunk)
        self.assertEqual([(s.category, s.text) for s in spans], [(PERSON, "Sarah Connor"), (PERSON, "Bill"), (ORG, "Acme")])


if __name__ == "__main__":
    unittest.main()
