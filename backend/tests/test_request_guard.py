"""Host and Origin guarding of the unauthenticated local API."""

import os
import unittest
from unittest import mock

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.services import request_guard


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    @app.post("/api/mutate")
    async def mutate():
        return {"changed": True}

    @app.websocket("/ws/echo")
    async def echo(ws: WebSocket):
        await ws.accept()
        await ws.send_text("hi")
        await ws.close()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=request_guard.cors_allowed_origins(),
        allow_origin_regex=request_guard.CORS_ORIGIN_REGEX,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(request_guard.RequestGuardMiddleware)
    return app


class HostRuleTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop(request_guard.ALLOWED_HOSTS_ENV, None)
        os.environ.pop(request_guard.ALLOWED_ORIGINS_ENV, None)

    def tearDown(self):
        self.env.stop()

    def test_loopback_names_and_ports(self):
        for host in ("localhost", "localhost:3000", "127.0.0.1:8474", "[::1]:8000", "LOCALHOST", "app.localhost:5173"):
            with self.subTest(host=host):
                self.assertTrue(request_guard.host_header_allowed(host))

    def test_ip_literals_cannot_be_rebound_so_they_pass(self):
        for host in ("192.168.1.5:3000", "10.0.0.7", "[fe80::1]:3000"):
            with self.subTest(host=host):
                self.assertTrue(request_guard.host_header_allowed(host))

    def test_compose_service_name_passes(self):
        self.assertTrue(request_guard.host_header_allowed("backend:8000"))

    def test_foreign_and_missing_hosts_fail(self):
        for host in ("evil.example", "evil.example:8474", "", "localhost.evil.example", "not a host"):
            with self.subTest(host=host):
                self.assertFalse(request_guard.host_header_allowed(host))

    def test_environment_allowlist_and_wildcard(self):
        os.environ[request_guard.ALLOWED_HOSTS_ENV] = "backchannel.lan, Meeting-Box.internal"
        self.assertTrue(request_guard.host_header_allowed("backchannel.lan:3000"))
        self.assertTrue(request_guard.host_header_allowed("meeting-box.internal"))
        self.assertFalse(request_guard.host_header_allowed("evil.example"))
        os.environ[request_guard.ALLOWED_HOSTS_ENV] = "*"
        self.assertTrue(request_guard.host_header_allowed("evil.example"))


class OriginRuleTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop(request_guard.ALLOWED_HOSTS_ENV, None)
        os.environ.pop(request_guard.ALLOWED_ORIGINS_ENV, None)

    def tearDown(self):
        self.env.stop()

    def test_local_origins_pass(self):
        for origin in ("http://localhost:3000", "http://127.0.0.1:8474", "http://[::1]:8000", "http://192.168.1.5:3000"):
            with self.subTest(origin=origin):
                self.assertTrue(request_guard.origin_allowed(origin))

    def test_foreign_null_and_malformed_origins_fail(self):
        for origin in ("https://evil.example", "null", "", "ftp://localhost", "http://evil.example/localhost"):
            with self.subTest(origin=origin):
                self.assertFalse(request_guard.origin_allowed(origin))

    def test_environment_origins(self):
        os.environ[request_guard.ALLOWED_ORIGINS_ENV] = "https://tools.example"
        self.assertTrue(request_guard.origin_allowed("https://tools.example"))
        self.assertFalse(request_guard.origin_allowed("https://evil.example"))
        self.assertEqual(["https://tools.example"], request_guard.cors_allowed_origins())
        os.environ[request_guard.ALLOWED_ORIGINS_ENV] = "*"
        self.assertTrue(request_guard.origin_allowed("https://evil.example"))
        self.assertEqual([], request_guard.cors_allowed_origins())

    def test_allowed_hosts_also_admit_origins(self):
        os.environ[request_guard.ALLOWED_HOSTS_ENV] = "backchannel.lan"
        self.assertTrue(request_guard.origin_allowed("http://backchannel.lan:3000"))


class MiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop(request_guard.ALLOWED_HOSTS_ENV, None)
        os.environ.pop(request_guard.ALLOWED_ORIGINS_ENV, None)
        self.client = TestClient(_build_app(), base_url="http://localhost")

    def tearDown(self):
        self.env.stop()

    def test_legitimate_hosts_are_served(self):
        for host in ("localhost:8474", "127.0.0.1:8001", "192.168.1.5:3000", "backend:8000"):
            with self.subTest(host=host):
                response = self.client.get("/api/ping", headers={"Host": host})
                self.assertEqual(200, response.status_code)

    def test_rebound_host_is_rejected_before_routing(self):
        response = self.client.get("/api/ping", headers={"Host": "attacker.example:8474"})
        self.assertEqual(400, response.status_code)
        self.assertNotIn("ok", response.text)

    def test_websocket_with_foreign_host_is_refused(self):
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws/echo", headers={"Host": "attacker.example"}):
                pass

    def test_websocket_with_local_host_connects(self):
        with self.client.websocket_connect("/ws/echo", headers={"Host": "localhost:8474"}) as ws:
            self.assertEqual("hi", ws.receive_text())

    def test_websocket_from_foreign_origin_is_refused_even_with_loopback_host(self):
        # A hostile page can always put a loopback URL in new WebSocket(...);
        # the browser still stamps the page's own Origin on the handshake.
        for origin in ("https://attacker.example", "null"):
            with self.subTest(origin=origin):
                with self.assertRaises(Exception):
                    with self.client.websocket_connect(
                        "/ws/echo", headers={"Host": "127.0.0.1:8474", "Origin": origin}
                    ):
                        pass

    def test_websocket_from_every_legitimate_frontend_origin_connects(self):
        origins = {
            "http://localhost:3000": "nginx or Vite",
            "http://localhost": "nginx on port 80",
            "http://192.168.1.5:3000": "nginx reached by LAN address",
            "http://localhost:8474": "desktop launcher",
            "http://127.0.0.1:8474": "desktop tray",
        }
        for origin, label in origins.items():
            with self.subTest(origin=origin, label=label):
                with self.client.websocket_connect(
                    "/ws/echo", headers={"Host": "localhost:8474", "Origin": origin}
                ) as ws:
                    self.assertEqual("hi", ws.receive_text())

    # The test client hard-codes ws://testserver for handshakes whatever the
    # base_url, so every websocket case names its Host explicitly.
    def test_websocket_without_origin_connects(self):
        # Non-browser clients (tests, scripts) send no Origin at all.
        with self.client.websocket_connect("/ws/echo", headers={"Host": "localhost:8474"}) as ws:
            self.assertEqual("hi", ws.receive_text())

    def test_websocket_from_environment_origin_connects(self):
        os.environ[request_guard.ALLOWED_ORIGINS_ENV] = "https://tools.example"
        client = TestClient(_build_app(), base_url="http://localhost")
        with client.websocket_connect(
            "/ws/echo", headers={"Host": "localhost:8474", "Origin": "https://tools.example"}
        ) as ws:
            self.assertEqual("hi", ws.receive_text())

    def test_cross_origin_mutation_is_rejected(self):
        response = self.client.post("/api/mutate", headers={"Origin": "https://attacker.example"})
        self.assertEqual(403, response.status_code)
        response = self.client.post("/api/mutate", headers={"Origin": "null"})
        self.assertEqual(403, response.status_code)

    def test_same_origin_and_dev_origin_mutations_pass(self):
        for origin in ("http://localhost:8474", "http://localhost:3000", "http://127.0.0.1:5173"):
            with self.subTest(origin=origin):
                response = self.client.post("/api/mutate", headers={"Origin": origin})
                self.assertEqual(200, response.status_code)
                self.assertEqual(origin, response.headers.get("access-control-allow-origin"))

    def test_mutation_without_origin_passes(self):
        # curl, the launcher's own health probe, and other non-browser clients.
        self.assertEqual(200, self.client.post("/api/mutate").status_code)

    def test_cross_origin_read_gets_no_cors_grant(self):
        response = self.client.get("/api/ping", headers={"Origin": "https://attacker.example"})
        self.assertEqual(200, response.status_code)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_preflight_from_foreign_origin_is_refused(self):
        response = self.client.options(
            "/api/mutate",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertNotEqual(200, response.status_code)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_preflight_from_local_origin_is_granted(self):
        response = self.client.options(
            "/api/mutate",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("http://localhost:3000", response.headers.get("access-control-allow-origin"))
        self.assertIsNone(response.headers.get("access-control-allow-credentials"))

    def test_environment_origin_is_granted_by_both_layers(self):
        os.environ[request_guard.ALLOWED_ORIGINS_ENV] = "https://tools.example"
        client = TestClient(_build_app(), base_url="http://localhost")
        response = client.post("/api/mutate", headers={"Origin": "https://tools.example"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("https://tools.example", response.headers.get("access-control-allow-origin"))


class AppWiringTests(unittest.TestCase):
    def test_main_app_installs_the_guard_outermost_and_restricts_cors(self):
        from app.main import app

        classes = [m.cls for m in app.user_middleware]
        self.assertIn(request_guard.RequestGuardMiddleware, classes)
        self.assertIn(CORSMiddleware, classes)
        # add_middleware prepends, so index 0 is the outermost layer.
        self.assertIs(request_guard.RequestGuardMiddleware, classes[0])
        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        self.assertNotIn("*", cors.kwargs.get("allow_origins", []))
        self.assertEqual(request_guard.CORS_ORIGIN_REGEX, cors.kwargs.get("allow_origin_regex"))
        self.assertFalse(cors.kwargs.get("allow_credentials"))


if __name__ == "__main__":
    unittest.main()
