"""P5-1 云端通道：令牌管理与分段探活测试。"""

from __future__ import annotations

import io
import os
import socket
import ssl
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cloud_channel  # noqa: E402
import dreambuddy  # noqa: E402

TOKEN = "partner-token-abcdef-123456"  # secret-scan: allow


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Ctx:
    def wrap_socket(self, *args, **kwargs):
        return _Conn()


def _patch_network():
    return [
        mock.patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]),
        mock.patch.object(socket, "create_connection", return_value=_Conn()),
        mock.patch.object(ssl, "create_default_context", return_value=_Ctx()),
    ]


class TokenTest(unittest.TestCase):
    def test_extract_token_from_env_line_and_raw(self):
        self.assertEqual(cloud_channel.extract_token("PARTNER_TOKEN=abc12345\n"), "abc12345")
        self.assertEqual(cloud_channel.extract_token("  abc12345 \n"), "abc12345")
        self.assertEqual(cloud_channel.extract_token("# comment\n"), "")

    def test_validate_rejects_short_or_illegal(self):
        with self.assertRaises(ValueError):
            cloud_channel.validate_token("short")
        with self.assertRaises(ValueError):
            cloud_channel.validate_token("bad token with spaces")
        self.assertEqual(cloud_channel.validate_token(TOKEN), TOKEN)

    def test_write_token_sets_mode_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "partner.env"
            cloud_channel.write_token(TOKEN, out)
            self.assertIn("PARTNER_TOKEN={}".format(TOKEN), out.read_text(encoding="utf-8"))
            mode = os.stat(out).st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_token_status_reads_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partner.env"
            cloud_channel.write_token(TOKEN, path)
            with mock.patch.dict(os.environ, {"DREAMBUDDY_PARTNER_ENV": str(path)}, clear=True):
                status = cloud_channel.token_status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["source"], "file")

    def test_token_status_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ, {"DREAMBUDDY_PARTNER_ENV": str(Path(tmp) / "absent.env")}, clear=True
            ):
                status = cloud_channel.token_status()
            self.assertFalse(status["configured"])
            self.assertEqual(status["source"], "none")


class ProbeTest(unittest.TestCase):
    def setUp(self):
        patches = _patch_network()
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_probe_ok(self):
        result = cloud_channel.probe("https://partner.example/api/v1", http_get=lambda url, t: 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "http")
        self.assertEqual(result["http_status"], 200)

    def test_probe_401_means_reachable(self):
        result = cloud_channel.probe("https://partner.example/api/v1", http_get=lambda url, t: 401)
        self.assertTrue(result["ok"])
        self.assertTrue(result["auth_required"])

    def test_probe_5xx_is_failure(self):
        result = cloud_channel.probe("https://partner.example/api/v1", http_get=lambda url, t: 503)
        self.assertFalse(result["ok"])
        self.assertIn("5xx", result["error"])

    def test_probe_http_error_object(self):
        def _raise(url, timeout):
            raise urllib.error.HTTPError(url, 404, "not found", None, None)

        result = cloud_channel.probe("https://partner.example/api/v1", http_get=_raise)
        self.assertTrue(result["ok"])
        self.assertEqual(result["http_status"], 404)

    def test_probe_network_error(self):
        def _raise(url, timeout):
            raise urllib.error.URLError("refused")

        result = cloud_channel.probe("https://partner.example/api/v1", http_get=_raise)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "http")

    def test_probe_dns_failure(self):
        with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("dns")):
            result = cloud_channel.probe("https://partner.example/api/v1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "dns")


class StatusCliTest(unittest.TestCase):
    def test_status_without_token_reports_e_cloud_auth(self):
        buffer = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                os.environ, {"DREAMBUDDY_PARTNER_ENV": str(Path(tmp) / "absent.env")}, clear=True
            ),
            redirect_stdout(buffer),
        ):
            code = cloud_channel.main(["status", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("E_CLOUD_AUTH", buffer.getvalue())

    def test_status_with_token_and_probe_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partner.env"
            cloud_channel.write_token(TOKEN, path)
            buffer = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"DREAMBUDDY_PARTNER_ENV": str(path)}, clear=True),
                mock.patch.object(
                    cloud_channel,
                    "probe",
                    return_value={"ok": True, "stage": "http", "http_status": 404},
                ),
                redirect_stdout(buffer),
            ):
                code = cloud_channel.main(["status", "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"ok": true', buffer.getvalue())

    def test_token_set_cli_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "audit.env"
            source.write_text("PARTNER_TOKEN={}\n".format(TOKEN), encoding="utf-8")
            out = Path(tmp) / "partner.env"
            code = cloud_channel.main(["token", "set", "--file", str(source), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())
            self.assertIn(TOKEN, out.read_text(encoding="utf-8"))


class EndpointGuardTest(unittest.TestCase):
    def test_quotes_rejects_cloud_endpoint(self):
        with self.assertRaises(SystemExit) as ctx:
            dreambuddy.apply_endpoint("cloud", ["--symbols", "--window"], [])
        self.assertIn("E_UNSUPPORTED", str(ctx.exception))

    def test_declared_action_gets_endpoint_flag(self):
        argv = dreambuddy.apply_endpoint("cloud", ["--series", "--endpoint"], [])
        self.assertEqual(argv[-2:], ["--endpoint", "cloud"])


if __name__ == "__main__":
    unittest.main()
