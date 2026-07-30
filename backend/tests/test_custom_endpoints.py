"""Self-hosted endpoints: storage, the model ids they produce, and routing.

The behaviour that matters here is that a model served by someone's own box
becomes a named, selectable model id and that calls for that id reach that
box - with its own key, and without a cloud provider key ever being required.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from app.models import CustomEndpoint
from app.routers import endpoints as endpoint_router
from app.services import custom_endpoints as ce


class _FakeSession:
    """In-memory stand-in for the custom_endpoints table.

    Applies the model's column defaults on flush, the way a real INSERT does,
    so objects read back the same as they would from PostgreSQL.
    """

    def __init__(self):
        self.rows: dict[str, CustomEndpoint] = {}
        self._pending: list[CustomEndpoint] = []
        self.statements = []

    def add(self, obj):
        self._pending.append(obj)

    async def get(self, _model, key):
        return self.rows.get(key)

    async def delete(self, obj):
        self.rows.pop(obj.id, None)

    async def flush(self):
        for obj in self._pending:
            for column in obj.__table__.columns:
                default = column.default
                if getattr(obj, column.name, None) is not None or default is None:
                    continue
                # SQLAlchemy wraps a zero-argument default in a context-taking
                # callable, so callables are invoked the way an INSERT does.
                setattr(obj, column.name, default.arg(None) if default.is_callable else default.arg)
            self.rows[obj.id] = obj
        self._pending.clear()

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass

    async def execute(self, statement):
        self.statements.append(statement)
        filters_deleted = "custom_endpoints.deleted_at IS NULL" in str(statement)
        ordered = sorted(
            (
                e
                for e in self.rows.values()
                if not filters_deleted or getattr(e, "deleted_at", None) is None
            ),
            key=lambda e: (e.display_order, e.id),
        )
        return _FakeResult(ordered)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _EncryptionCase(unittest.IsolatedAsyncioTestCase):
    """Base for cases that store a key: gives each test its own master key."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ.pop("CREDENTIALS_MASTER_KEY", None)
        from app.services import secrets as secrets_mod

        self.secrets = secrets_mod
        secrets_mod._fernet = None

    def tearDown(self):
        self.secrets._fernet = None
        self.tmp.cleanup()


class ModelIdTests(unittest.TestCase):
    def test_build_and_parse_round_trip(self):
        model_id = ce.build_model_id("lm-studio", "antares-1b")
        self.assertEqual("endpoint:lm-studio:antares-1b", model_id)
        self.assertEqual(("lm-studio", "antares-1b"), ce.parse_model_id(model_id))

    def test_wire_name_keeps_its_own_colons(self):
        # Ollama tags such as llama3.1:8b must survive the split intact.
        model_id = ce.build_model_id("ollama", "llama3.1:8b")
        self.assertEqual(("ollama", "llama3.1:8b"), ce.parse_model_id(model_id))

    def test_registry_ids_are_not_endpoint_models(self):
        for model_id in ("gemini-3.5-flash", "gpt-5.4-mini", "openai-compatible", "local-whisper-base"):
            self.assertFalse(ce.is_endpoint_model(model_id))
            self.assertIsNone(ce.parse_model_id(model_id))

    def test_malformed_ids_parse_to_none(self):
        for model_id in ("endpoint:", "endpoint:lm-studio", "endpoint::model", "endpoint:lm-studio:"):
            self.assertIsNone(ce.parse_model_id(model_id))

    def test_slugify_produces_a_safe_bounded_id(self):
        self.assertEqual("lm-studio-workstation", ce.slugify("LM Studio (workstation)"))
        self.assertEqual("gpu-box-2", ce.slugify("  GPU  box #2  "))
        self.assertLessEqual(len(ce.slugify("a" * 100)), ce.MAX_ENDPOINT_SLUG)


class OnPremDetectionTests(unittest.TestCase):
    def test_loopback_and_private_networks_are_on_prem(self):
        for url in (
            "http://localhost:1234/v1",
            "http://127.0.0.1:11434/v1",
            "http://192.168.1.50:8000/v1",
            "http://10.0.0.5/v1",
            "http://172.16.4.4:8000/v1",
            "http://host.docker.internal:1234/v1",
            "http://gpu-box:8000/v1",
            "https://models.acme.internal/v1",
            "http://workstation.local:1234/v1",
        ):
            self.assertTrue(ce.is_on_prem(url), url)

    def test_public_hosts_are_not_on_prem(self):
        # These speak the same protocol but send call data off the network,
        # so Privacy First must keep treating them as cloud.
        for url in ("https://api.together.xyz/v1", "https://api.groq.com/openai/v1", "http://8.8.8.8/v1"):
            self.assertFalse(ce.is_on_prem(url), url)

    def test_alternate_ip_encodings_do_not_bypass_privacy_first(self):
        # Bare-integer, hex, and IPv4-mapped-IPv6 forms of a PUBLIC address must
        # stay cloud: the C resolver still routes them off the network, so a
        # "." not in host shortcut that read them as a LAN hostname would leak.
        for url in (
            "http://134744072/v1",  # decimal 8.8.8.8
            "http://0x08080808/v1",  # hex 8.8.8.8
            "http://[::ffff:8.8.8.8]/v1",  # IPv4-mapped IPv6 8.8.8.8
        ):
            self.assertFalse(ce.is_on_prem(url), url)
        # The same encodings of a loopback/private address stay on-prem, and a
        # genuine single-label LAN hostname is unaffected.
        for url in (
            "http://2130706433/v1",  # decimal 127.0.0.1
            "http://0x7f000001/v1",  # hex 127.0.0.1
            "http://[::ffff:127.0.0.1]/v1",
            "http://gpu-box/v1",
        ):
            self.assertTrue(ce.is_on_prem(url), url)


class ValidationTests(unittest.TestCase):
    def test_base_url_must_be_an_http_url_with_a_host(self):
        for bad in ("", "   ", "localhost:1234/v1", "ftp://box/v1", "http://"):
            with self.assertRaises(ce.EndpointError):
                ce.validate_base_url(bad)

    def test_base_url_is_trimmed_so_paths_join_cleanly(self):
        self.assertEqual("http://localhost:1234/v1", ce.validate_base_url(" http://localhost:1234/v1/ "))

    def test_model_list_is_deduped_and_labelled(self):
        entries = ce.normalize_models(
            ["antares-1b", {"id": " antares-1b "}, {"id": "qwen3", "label": "Qwen 3"}, {"id": ""}, 7]
        )
        self.assertEqual(
            [{"id": "antares-1b", "label": "antares-1b"}, {"id": "qwen3", "label": "Qwen 3"}],
            entries,
        )


class StorageTests(_EncryptionCase):
    async def test_create_lists_and_exposes_named_models(self):
        db = _FakeSession()
        await ce.create_endpoint(
            db,
            name="LM Studio",
            base_url="http://localhost:1234/v1/",
            models=[{"id": "antares-1b"}],
        )
        endpoints = await ce.list_endpoints(db)
        self.assertEqual(["lm-studio"], [e.id for e in endpoints])
        self.assertEqual("http://localhost:1234/v1", endpoints[0].base_url)

        models = await ce.endpoint_models(db)
        self.assertEqual(1, len(models))
        entry = models[0]
        self.assertEqual("endpoint:lm-studio:antares-1b", entry["id"])
        self.assertEqual("antares-1b", entry["name"])
        self.assertEqual("LM Studio", entry["provider"])
        self.assertTrue(entry["supports_text"])
        self.assertTrue(entry["runs_locally"])
        self.assertTrue(entry["key_available"])
        self.assertIsNone(entry["requires_key"])
        self.assertFalse(entry["supports_batch_audio"])
        self.assertFalse(entry["supports_live_audio"])

    async def test_second_endpoint_with_the_same_name_gets_its_own_slug(self):
        db = _FakeSession()
        await ce.create_endpoint(db, name="LM Studio", base_url="http://localhost:1234/v1")
        await ce.create_endpoint(db, name="LM Studio", base_url="http://gpu-box:1234/v1")
        self.assertEqual(["lm-studio", "lm-studio-2"], sorted(db.rows))

    async def test_collision_suffix_never_exceeds_the_slug_cap(self):
        db = _FakeSession()
        ids = []
        for index in range(11):
            endpoint = await ce.create_endpoint(
                db,
                name="x" * ce.MAX_ENDPOINT_SLUG,
                base_url=f"http://gpu-box-{index}:1234/v1",
            )
            ids.append(endpoint.id)
            self.assertLessEqual(len(endpoint.id), ce.MAX_ENDPOINT_SLUG)
        self.assertEqual(11, len(set(db.rows)))
        self.assertTrue(ids[-1].endswith("-11"))

    async def test_remote_endpoint_models_are_not_marked_local(self):
        db = _FakeSession()
        await ce.create_endpoint(
            db, name="Hosted", base_url="https://api.together.xyz/v1", models=["mixtral"]
        )
        self.assertFalse((await ce.endpoint_models(db))[0]["runs_locally"])

    async def test_disabled_endpoints_offer_no_models(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(
            db, name="LM Studio", base_url="http://localhost:1234/v1", models=["antares-1b"]
        )
        await ce.update_endpoint(db, endpoint, enabled=False)
        self.assertEqual([], await ce.endpoint_models(db))

    async def test_an_over_long_model_id_is_rejected_before_it_reaches_the_column(self):
        db = _FakeSession()
        with self.assertRaises(ce.EndpointError):
            await ce.create_endpoint(
                db, name="Box", base_url="http://localhost:1234/v1", models=["m" * 200]
            )

    async def test_stored_key_is_encrypted_and_never_returned(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(
            db,
            name="Proxy",
            base_url="https://proxy.acme.internal/v1",
            api_key="sk-secret-value",
            models=["gpt-oss"],
        )
        self.assertNotIn("sk-secret-value", endpoint.api_key)
        payload = ce.to_dict(endpoint)
        self.assertTrue(payload["has_api_key"])
        self.assertNotIn("api_key", payload)
        self.assertNotIn("sk-secret-value", str(payload))

        target = await ce.resolve_target(db, "endpoint:proxy:gpt-oss")
        self.assertEqual("sk-secret-value", target.api_key)
        self.assertEqual("gpt-oss", target.model)
        self.assertEqual("https://proxy.acme.internal/v1", target.base_url)

    async def test_clearing_the_key_makes_the_endpoint_keyless_again(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(
            db, name="Box", base_url="http://localhost:1234/v1", api_key="sk-x", models=["m"]
        )
        await ce.update_endpoint(db, endpoint, api_key="")
        self.assertEqual("", endpoint.api_key)
        self.assertFalse(ce.to_dict(endpoint)["has_api_key"])
        self.assertEqual("", (await ce.resolve_target(db, "endpoint:box:m")).api_key)

    async def test_changing_the_address_clears_the_recorded_test_result(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(db, name="Box", base_url="http://localhost:1234/v1")
        await ce.record_probe(db, endpoint, True, "Connected. 1 model(s) available.")
        self.assertEqual("ok", endpoint.last_status)
        await ce.update_endpoint(db, endpoint, base_url="http://gpu-box:1234/v1")
        self.assertEqual("", endpoint.last_status)
        self.assertIsNone(endpoint.last_checked_at)

    async def test_editing_other_fields_keeps_the_recorded_test_result(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(db, name="Box", base_url="http://localhost:1234/v1")
        await ce.record_probe(db, endpoint, True, "Connected.")
        await ce.update_endpoint(db, endpoint, name="Workstation")
        self.assertEqual("ok", endpoint.last_status)

    async def test_privacy_first_rejects_moving_an_endpoint_off_prem(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(db, name="Box", base_url="http://localhost:1234/v1")
        with (
            mock.patch(
                "app.services.custom_endpoints.get_local_only",
                new=mock.AsyncMock(return_value=True),
            ),
            self.assertRaisesRegex(ce.EndpointError, "Privacy First"),
        ):
            await ce.update_endpoint(
                db,
                endpoint,
                base_url="https://api.together.xyz/v1",
            )
        self.assertEqual("http://localhost:1234/v1", endpoint.base_url)

    async def test_off_prem_move_requires_confirmation_when_privacy_first_is_off(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(db, name="Box", base_url="http://localhost:1234/v1")
        with mock.patch(
            "app.services.custom_endpoints.get_local_only",
            new=mock.AsyncMock(return_value=False),
        ):
            with self.assertRaisesRegex(ce.EndpointError, "confirm_off_prem"):
                await ce.update_endpoint(
                    db,
                    endpoint,
                    base_url="https://api.together.xyz/v1",
                )
            await ce.update_endpoint(
                db,
                endpoint,
                base_url="https://api.together.xyz/v1",
                confirm_off_prem=True,
            )
        self.assertEqual("https://api.together.xyz/v1", endpoint.base_url)

    async def test_deleted_endpoint_is_hidden_and_its_slug_is_not_reused(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(
            db,
            name="Box",
            base_url="http://localhost:1234/v1",
            api_key="sk-secret",
            models=["m"],
        )
        await ce.delete_endpoint(db, endpoint)
        self.assertIsNotNone(getattr(endpoint, "deleted_at", None))
        self.assertEqual("", endpoint.api_key)
        self.assertEqual([], await ce.list_endpoints(db))
        self.assertIsNone(await ce.get_endpoint(db, endpoint.id))
        self.assertIsNone(await ce.endpoint_model_entry(db, "endpoint:box:m"))
        replacement = await ce.create_endpoint(
            db,
            name="Box",
            base_url="http://gpu-box:1234/v1",
            models=["m"],
        )
        self.assertEqual("box-2", replacement.id)

    async def test_resolution_distinguishes_deleted_from_never_existing(self):
        db = _FakeSession()
        endpoint = await ce.create_endpoint(
            db, name="Box", base_url="http://localhost:1234/v1", models=["m"]
        )
        deleted_at = datetime(2026, 7, 28, 6, 45, tzinfo=timezone.utc)
        endpoint.deleted_at = deleted_at
        with self.assertRaisesRegex(
            ce.EndpointError,
            r"Box.*deleted.*2026-07-28T06:45:00\+00:00",
        ):
            await ce.resolve_target(db, "endpoint:box:m")
        self.assertIsNone(await ce.resolve_target(db, "endpoint:never-existed:m"))

    async def test_name_is_required(self):
        db = _FakeSession()
        with self.assertRaises(ce.EndpointError):
            await ce.create_endpoint(db, name="  ", base_url="http://localhost:1234/v1")


class SelectableEverywhereTests(_EncryptionCase):
    """Routers validate submitted model ids; endpoint models must pass.

    Both the agent model picker and meeting chat used to check the static
    registry only, which silently rejected every self-hosted model.
    """

    async def _endpoint(self, db, **kwargs):
        return await ce.create_endpoint(
            db,
            name=kwargs.pop("name", "LM Studio"),
            base_url=kwargs.pop("base_url", "http://localhost:1234/v1"),
            models=kwargs.pop("models", ["antares-1b"]),
            **kwargs,
        )

    async def test_a_served_model_reports_text_support(self):
        db = _FakeSession()
        await self._endpoint(db)
        entry = await ce.endpoint_model_entry(db, "endpoint:lm-studio:antares-1b")
        self.assertTrue(entry["supports_text"])
        self.assertFalse(entry["supports_batch_audio"])
        self.assertFalse(entry["supports_live_audio"])
        self.assertEqual("endpoint:lm-studio:antares-1b", entry["id"])

    async def test_a_model_the_endpoint_does_not_serve_is_rejected(self):
        db = _FakeSession()
        await self._endpoint(db)
        self.assertIsNone(await ce.endpoint_model_entry(db, "endpoint:lm-studio:not-listed"))
        self.assertIsNone(await ce.endpoint_model_entry(db, "endpoint:nope:antares-1b"))

    async def test_resolution_stays_lenient_for_an_already_stored_model(self):
        # Removing a model from the list must not break an agent mid-call; the
        # call still reaches the server, which decides whether it knows it.
        db = _FakeSession()
        endpoint = await self._endpoint(db)
        await ce.update_endpoint(db, endpoint, models=["qwen3"])
        target = await ce.resolve_target(db, "endpoint:lm-studio:antares-1b")
        self.assertEqual("antares-1b", target.model)

    async def test_a_disabled_endpoints_models_are_rejected(self):
        db = _FakeSession()
        endpoint = await self._endpoint(db)
        await ce.update_endpoint(db, endpoint, enabled=False)
        self.assertIsNone(await ce.endpoint_model_entry(db, "endpoint:lm-studio:antares-1b"))

    async def test_registry_ids_are_not_claimed_by_the_endpoint_lookup(self):
        db = _FakeSession()
        await self._endpoint(db)
        self.assertIsNone(await ce.endpoint_model_entry(db, "gemini-3.5-flash"))


class RouterTests(_EncryptionCase):
    async def test_edit_forwards_an_off_prem_confirmation(self):
        db = _FakeSession()
        await ce.create_endpoint(
            db,
            name="Box",
            base_url="http://localhost:1234/v1",
            models=["m"],
        )
        body = endpoint_router.EndpointPatch(
            base_url="https://api.together.xyz/v1",
            confirm_off_prem=True,
        )
        with mock.patch(
            "app.services.custom_endpoints.get_local_only",
            new=mock.AsyncMock(return_value=False),
        ):
            payload = await endpoint_router.edit("box", body, db)
        self.assertEqual("https://api.together.xyz/v1", payload["base_url"])


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_served_model_names_come_back_for_the_add_form(self):
        payload = {"data": [{"id": "antares-1b"}, {"id": "qwen3-8b"}, {"no_id": True}]}
        response = mock.Mock(json=mock.Mock(return_value=payload), raise_for_status=mock.Mock())
        client = mock.AsyncMock()
        client.__aenter__.return_value.get = mock.AsyncMock(return_value=response)
        with mock.patch.object(ce.httpx, "AsyncClient", mock.Mock(return_value=client)):
            ok, message, served = await ce.probe("http://localhost:1234/v1")
        self.assertTrue(ok)
        self.assertEqual(["antares-1b", "qwen3-8b"], served)
        self.assertIn("2 model(s)", message)

    async def test_a_keyless_endpoint_sends_no_authorization_header(self):
        self.assertEqual({}, ce.auth_headers(""))
        self.assertEqual({"Authorization": "Bearer sk-x"}, ce.auth_headers("sk-x"))

    async def test_an_unreachable_server_reports_the_address_it_tried(self):
        client = mock.AsyncMock()
        client.__aenter__.return_value.get = mock.AsyncMock(
            side_effect=ce.httpx.ConnectError("refused")
        )
        with mock.patch.object(ce.httpx, "AsyncClient", mock.Mock(return_value=client)):
            ok, message, served = await ce.probe("http://localhost:1234/v1")
        self.assertFalse(ok)
        self.assertIn("http://localhost:1234/v1", message)
        self.assertEqual([], served)

    async def test_an_invalid_url_fails_without_a_request(self):
        ok, message, served = await ce.probe("localhost:1234")
        self.assertFalse(ok)
        self.assertIn("http://", message)


if __name__ == "__main__":
    unittest.main()
