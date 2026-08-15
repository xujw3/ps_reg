import base64
import socketserver
import threading
import unittest
from unittest import mock

from backend.automation import session as browser_session
from backend.integrations import network_checks
from backend.registration import engine as gr


class ProxyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.original_config = dict(gr.config)

    def tearDown(self):
        gr.config.clear()
        gr.config.update(self.original_config)
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "en-US",
        )

    def test_camoufox_registration_keeps_configured_proxy(self):
        browser_session.configure(
            get_proxies=lambda: {
                "http": "http://127.0.0.1:7897",
                "https": "http://127.0.0.1:7897",
            },
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "en-US",
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertEqual(options["proxy"], {"server": "http://127.0.0.1:7897"})

    def test_camoufox_registration_uses_authenticated_http_proxy(self):
        browser_session.configure(
            get_proxies=lambda: {
                "http": "http://proxy-user:proxy-password@proxy.example.com:7897",
                "https": "http://proxy-user:proxy-password@proxy.example.com:7897",
            },
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "en-US",
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertEqual(
            options["proxy"],
            {
                "server": "http://proxy.example.com:7897",
                "username": "proxy-user",
                "password": "proxy-password",
            },
        )

    def test_camoufox_decodes_percent_encoded_http_credentials(self):
        browser_session.configure(
            get_proxies=lambda: {
                "https": "http://user%40mail:p%40ss%3Aword@proxy.example.com:7897"
            },
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "en-US",
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertEqual(
            options["proxy"],
            {
                "server": "http://proxy.example.com:7897",
                "username": "user@mail",
                "password": "p@ss:word",
            },
        )

    def test_http_client_sends_encoded_proxy_credentials_as_basic_auth(self):
        captured = {}

        class ProxyHandler(socketserver.StreamRequestHandler):
            def handle(self):
                lines = []
                while True:
                    line = self.rfile.readline().decode("iso-8859-1").rstrip("\r\n")
                    if not line:
                        break
                    lines.append(line)
                for line in lines[1:]:
                    if line.lower().startswith("proxy-authorization:"):
                        captured["authorization"] = line.split(":", 1)[1].strip()
                self.wfile.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 2\r\n"
                    b"Connection: close\r\n\r\nOK"
                )

        with socketserver.TCPServer(("127.0.0.1", 0), ProxyHandler) as proxy_server:
            thread = threading.Thread(target=proxy_server.handle_request, daemon=True)
            thread.start()
            port = proxy_server.server_address[1]
            proxy = f"http://user%40mail:p%40ss%3Aword@127.0.0.1:{port}"
            with mock.patch.object(gr, "registration_log"):
                response = gr.http_get(
                    "http://registration.test/probe",
                    proxies={"http": proxy},
                    timeout=5,
                )
            thread.join(timeout=5)

        expected = "Basic " + base64.b64encode(b"user@mail:p@ss:word").decode("ascii")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured.get("authorization"), expected)

    def test_actual_http_route_log_deduplicates_query_variants(self):
        logs = []
        with mock.patch.object(gr, "registration_log", side_effect=logs.append):
            gr.reset_network_route_logs()
            gr._log_actual_http_route(
                "get",
                "https://accounts.x.ai/sign-up?step=1",
                proxies={"https": "http://127.0.0.1:7897"},
            )
            gr._log_actual_http_route(
                "GET",
                "https://accounts.x.ai/sign-up?step=2",
                proxies={"https": "http://127.0.0.1:7897"},
            )
            gr._log_actual_http_route("GET", "http://mail.test/api/emails", proxies={})

        self.assertEqual(len(logs), 2)
        self.assertIn("GET https://accounts.x.ai/sign-up -> 代理 http://127.0.0.1:7897", logs[0])
        self.assertIn("GET http://mail.test/api/emails -> 直连（不使用代理）", logs[1])

    def test_actual_http_route_log_redacts_proxy_credentials(self):
        logs = []
        proxy = "http://proxy-user:p%40ss@proxy.example.com:7897"
        with mock.patch.object(gr, "registration_log", side_effect=logs.append):
            gr.reset_network_route_logs()
            gr._log_actual_http_route(
                "GET",
                "https://accounts.x.ai/sign-up",
                proxies={"https": proxy},
            )

        self.assertEqual(len(logs), 1)
        self.assertNotIn("proxy-user", logs[0])
        self.assertNotIn("p%40ss", logs[0])
        self.assertIn("代理 http://***:***@proxy.example.com:7897", logs[0])

    def test_default_http_wrappers_disable_environment_and_project_proxy(self):
        gr.config["proxy"] = "http://127.0.0.1:7897"
        for method, request_fn in (
            ("GET", gr.http_get),
            ("POST", gr.http_post),
            ("DELETE", gr.http_delete),
        ):
            with self.subTest(method=method):
                response = mock.Mock()
                session = mock.MagicMock()
                session.__enter__.return_value = session
                session.__exit__.return_value = False
                session.request.return_value = response
                raw_request = session.request
                with mock.patch.object(
                    gr.requests, "Session", return_value=session
                ) as factory:
                    result = request_fn("http://mail-service.test/api")
                self.assertIs(result, response)
                factory.assert_called_once_with(trust_env=False)
                raw_request.assert_called_once_with(
                    method,
                    "http://mail-service.test/api",
                    proxies={},
                    timeout=15,
                )

    def test_ps_connectivity_check_explicitly_uses_configured_proxy(self):
        response = mock.Mock(status_code=200, text="<!doctype html>", headers={})
        http_get = mock.Mock(return_value=response)
        proxy = "http://127.0.0.1:7897"
        _, ok, detail = network_checks.check_ps_signup(
            proxy, "https://dashboard.proxyscrape.com/v2", http_get
        )
        self.assertTrue(ok, detail)
        self.assertEqual(
            http_get.call_args.kwargs["proxies"],
            {"http": proxy, "https": proxy},
        )
        self.assertIn(
            "/sign-up",
            http_get.call_args.args[0],
        )

if __name__ == "__main__":
    unittest.main()
