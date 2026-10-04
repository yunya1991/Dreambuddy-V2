"""浏览器连接层单元测试"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.browser_connector import BrowserConnector, BrowserMode


@pytest.fixture
def connector():
    config = {
        "browser": {
            "chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "cdp_port": 9222,
            "user_data_dir": "",
            "headed": True,
            "launch_args": [
                "--remote-debugging-port=9222",
                "--no-first-run",
            ],
            "viewport": {"width": 1440, "height": 900},
        }
    }
    return BrowserConnector(config)


class TestBrowserConnector:
    """浏览器连接器测试"""

    def test_init(self, connector):
        assert connector._browser_cfg["cdp_port"] == 9222
        assert connector._playwright is None
        assert connector._browser is None

    def test_get_cdp_url(self, connector):
        assert connector.get_cdp_url() == "http://localhost:9222"

    def test_is_chrome_running(self):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            assert BrowserConnector.is_chrome_running(9222) is True

    def test_is_chrome_running_false(self):
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")
            assert BrowserConnector.is_chrome_running(9222) is False

    def test_connect_cdp_mode(self, connector):
        mock_playwright = MagicMock()
        mock_browser = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser

        connector._playwright = mock_playwright

        with patch("core.browser_connector.sync_playwright") as mock_sync:
            mock_sync.return_value.start.return_value = mock_playwright
            result = connector.connect(mode=BrowserMode.CONNECT_CDP)

        assert result == mock_browser
        assert connector._browser == mock_browser
        mock_playwright.chromium.connect_over_cdp.assert_called_once_with(
            "http://localhost:9222"
        )

    def test_connect_cdp_with_custom_url(self, connector):
        mock_playwright = MagicMock()
        mock_browser = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser

        connector._playwright = mock_playwright

        result = connector.connect(mode=BrowserMode.CONNECT_CDP, cdp_url="http://custom:9222")
        mock_playwright.chromium.connect_over_cdp.assert_called_once_with("http://custom:9222")

    def test_connect_unknown_mode(self, connector):
        connector._playwright = MagicMock()
        with pytest.raises(ValueError, match="Unknown browser mode"):
            connector.connect(mode="invalid")

    def test_close_without_connection(self, connector):
        # 不应抛出异常
        connector.close()
        assert connector._browser is None
        assert connector._playwright is None

    def test_new_context_without_browser(self, connector):
        with pytest.raises(RuntimeError, match="Browser not connected"):
            connector.new_context()

    def test_new_context_reuses_existing(self, connector):
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_browser.contexts = [mock_context]
        connector._browser = mock_browser

        result = connector.new_context()
        assert result == mock_context

    def test_new_context_creates_new(self, connector):
        mock_browser = MagicMock()
        mock_browser.contexts = []
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context
        connector._browser = mock_browser

        result = connector.new_context()
        assert result == mock_context
        mock_browser.new_context.assert_called_once()

    def test_wait_for_cdp(self, connector):
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            # 不应抛出异常
            connector._wait_for_cdp(9222, timeout=5)

    def test_wait_for_cdp_timeout(self, connector):
        with patch("requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")
            with pytest.raises(TimeoutError):
                connector._wait_for_cdp(9222, timeout=1)
