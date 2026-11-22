"""P5-R：verify_live 冒烟测试（无网络，mock 客户端）。"""

from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cloud_client  # noqa: E402
import verify_live  # noqa: E402


class VerifyLiveTest(unittest.TestCase):
    def test_skip_when_not_configured(self):
        buffer = StringIO()
        with mock.patch.object(cloud_client, "config", return_value={"complete": False}):
            with redirect_stdout(buffer):
                code = verify_live.main()
        self.assertEqual(code, 0)
        self.assertIn("SKIP", buffer.getvalue())

    def test_ok_with_read_tools(self):
        buffer = StringIO()
        conf = {"complete": True, "base": "https://cloud.example/mcp"}
        tools = [{"name": "read_one", "write": False}, {"name": "write_one", "write": True}]
        with (
            mock.patch.object(cloud_client, "config", return_value=conf),
            mock.patch.object(cloud_client, "fetch_tools", return_value=tools),
        ):
            with redirect_stdout(buffer):
                code = verify_live.main()
        self.assertEqual(code, 0)
        self.assertIn("read=1 write=1", buffer.getvalue())

    def test_fail_on_cloud_error(self):
        conf = {"complete": True, "base": "https://cloud.example/mcp"}

        def boom():
            raise cloud_client.CloudError("E_CLOUD_AUTH", "bad token")

        with (
            mock.patch.object(cloud_client, "config", return_value=conf),
            mock.patch.object(cloud_client, "fetch_tools", side_effect=boom),
            redirect_stdout(StringIO()),
        ):
            code = verify_live.main()
        self.assertEqual(code, 1)

    def test_fail_without_read_tools(self):
        conf = {"complete": True, "base": "https://cloud.example/mcp"}
        tools = [{"name": "write_only", "write": True}]
        with (
            mock.patch.object(cloud_client, "config", return_value=conf),
            mock.patch.object(cloud_client, "fetch_tools", return_value=tools),
            redirect_stdout(StringIO()),
        ):
            code = verify_live.main()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
