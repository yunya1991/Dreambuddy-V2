"""浏览器连接层 — 多种浏览器连接模式

三种模式：
1. PLAYWRIGHT_CHROMIUM（默认）：使用 Playwright 内置 Chromium，沙箱内可用
2. CONNECT_CDP：通过 CDP 连接沙箱外已运行的真实 Chrome，复用登录态
3. LAUNCH_CHROME：启动真实 Chrome（需在沙箱外运行或配置沙箱规则）

沙箱限制说明：
- TRAE IDE 沙箱限制 Chrome 访问 ~/Library/Application Support/Google/Chrome/
- 因此 LAUNCH_CHROME 模式在沙箱内会失败，需使用 start_chrome.sh 在沙箱外启动
- PLAYWRIGHT_CHROMIUM 是沙箱内的唯一可用方案
- CONNECT_CDP 连接沙箱外的 Chrome，可复用登录态和真实指纹
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

logger = logging.getLogger("real_env.browser_connector")


class BrowserMode(Enum):
    """浏览器运行模式"""
    PLAYWRIGHT_CHROMIUM = "playwright_chromium"  # Playwright 内置 Chromium（沙箱内可用，默认）
    CONNECT_CDP = "connect_cdp"  # 通过 CDP 连接已运行的真实 Chrome
    LAUNCH_HEADED = "launch_headed"  # 启动带界面的真实 Chrome（需沙箱外）
    LAUNCH_HEADLESS = "launch_headless"  # 启动 headless 真实 Chrome（需沙箱外）


class BrowserConnector:
    """浏览器连接器 — 管理真实 Chrome 浏览器的连接与生命周期"""

    def __init__(self, config: dict):
        self._config = config
        self._browser_cfg = config.get("browser", {})
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._chrome_process: Optional[subprocess.Popen] = None
        self._user_data_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def connect(self, mode: BrowserMode = BrowserMode.PLAYWRIGHT_CHROMIUM,
                cdp_url: Optional[str] = None) -> Browser:
        """连接或启动浏览器，返回 Browser 实例。

        Args:
            mode: 浏览器运行模式
                  - PLAYWRIGHT_CHROMIUM: Playwright 内置 Chromium（沙箱内可用，默认）
                  - CONNECT_CDP: 连接沙箱外已运行的真实 Chrome
                  - LAUNCH_HEADED/LAUNCH_HEADLESS: 启动真实 Chrome（需沙箱外）
            cdp_url: CDP 连接地址（仅 CONNECT_CDP 模式需要）

        Returns:
            Playwright Browser 实例
        """
        if self._playwright is None:
            self._playwright = sync_playwright().start()

        if mode == BrowserMode.PLAYWRIGHT_CHROMIUM:
            return self._launch_playwright_chromium()
        elif mode == BrowserMode.CONNECT_CDP:
            return self._connect_via_cdp(cdp_url)
        elif mode == BrowserMode.LAUNCH_HEADED:
            return self._launch_chrome(headed=True)
        elif mode == BrowserMode.LAUNCH_HEADLESS:
            return self._launch_chrome(headed=False)
        else:
            raise ValueError(f"Unknown browser mode: {mode}")

    def new_context(self, **kwargs) -> BrowserContext:
        """创建新的浏览器上下文。

        如果是 CDP 连接模式，复用默认上下文；否则创建新上下文。
        """
        if self._browser is None:
            raise RuntimeError("Browser not connected. Call connect() first.")

        # CDP 连接模式下，使用浏览器已有的上下文（包含登录态）
        if self._browser.contexts:
            self._context = self._browser.contexts[0]
            logger.info("Reusing existing browser context (with login state)")
        else:
            viewport = self._browser_cfg.get("viewport", {"width": 1440, "height": 900})
            self._context = self._browser.new_context(
                viewport=viewport,
                **kwargs,
            )
            logger.info("Created new browser context")

        return self._context

    def new_page(self) -> Page:
        """创建新页面。"""
        if self._context is None:
            self.new_context()
        return self._context.new_page()

    def close(self):
        """关闭浏览器连接，清理资源。"""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._chrome_process:
            try:
                self._chrome_process.terminate()
                self._chrome_process.wait(timeout=5)
            except Exception:
                try:
                    self._chrome_process.kill()
                except Exception:
                    pass
            self._chrome_process = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("Browser connector closed")

    def get_cdp_url(self) -> str:
        """获取当前 CDP 连接地址。"""
        port = self._browser_cfg.get("cdp_port", 9222)
        return f"http://localhost:{port}"

    # ------------------------------------------------------------------
    # Playwright Chromium 模式 — 沙箱内可用（默认）
    # ------------------------------------------------------------------
    def _launch_playwright_chromium(self) -> Browser:
        """启动 Playwright 内置 Chromium。

        优势：
        - 沙箱内可用，不受 TRAE 文件系统沙箱限制
        - 启动快，无需额外配置
        - 适合自动化测试

        劣势：
        - 不是真实 Chrome，可能被反爬虫检测
        - 无法复用用户登录态
        """
        headed = self._browser_cfg.get("headed", False)
        viewport = self._browser_cfg.get("viewport", {"width": 1440, "height": 900})

        logger.info("Launching Playwright Chromium (headed=%s)", headed)

        self._browser = self._playwright.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        logger.info("Playwright Chromium launched")
        return self._browser

    # ------------------------------------------------------------------
    # CDP 连接模式 — 连接已运行的 Chrome（复用登录态）
    # ------------------------------------------------------------------
    def _connect_via_cdp(self, cdp_url: Optional[str] = None) -> Browser:
        """通过 CDP 连接已运行的 Chrome。

        前提：Chrome 已用 --remote-debugging-port=9222 启动。
        优势：复用用户登录态、cookie、扩展，不受沙箱限制。
        """
        if cdp_url is None:
            cdp_url = self.get_cdp_url()

        logger.info("Connecting to Chrome via CDP: %s", cdp_url)
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
            logger.info("Connected to Chrome via CDP successfully")
            return self._browser
        except Exception as e:
            logger.error(
                "Failed to connect to Chrome via CDP: %s. "
                "Please start Chrome with --remote-debugging-port=%s",
                e, self._browser_cfg.get("cdp_port", 9222),
            )
            raise

    # ------------------------------------------------------------------
    # 独立启动模式 — 启动真实 Chrome 进程
    # ------------------------------------------------------------------
    def _launch_chrome(self, headed: bool = True) -> Browser:
        """启动独立 Chrome 进程并通过 CDP 连接。

        优势：
        - 启动真实 Chrome（非 Playwright 内置 Chromium）
        - 带真实用户指纹，可通过反爬虫检测
        - headed 模式下有完整浏览器界面
        """
        chrome_path = self._browser_cfg.get(
            "chrome_path",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        port = self._browser_cfg.get("cdp_port", 9222)
        user_data_dir = self._browser_cfg.get("user_data_dir", "")

        # 如果未指定用户数据目录，使用项目内临时目录
        # 关键：必须在工作目录内，避免 TRAE 沙箱限制 ~/Library 等系统目录
        if not user_data_dir:
            project_dir = Path(__file__).parent.parent
            user_data_dir = str(project_dir / ".chrome-data" / f"session_{os.getpid()}")
            os.makedirs(user_data_dir, exist_ok=True)
        self._user_data_dir = user_data_dir

        # 构建启动参数
        # 关键：禁用 Crashpad/Breakpad，避免 Chrome 访问 TRAE 沙箱限制的默认目录
        crash_dir = os.path.join(user_data_dir, "crashpad")
        os.makedirs(crash_dir, exist_ok=True)

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            f"--crash-dumps-dir={crash_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            # 禁用崩溃报告，避免访问沙箱限制的 ~/Library/Application Support/Google/Chrome/
            "--disable-crashpad",
            "--disable-breakpad",
            "--disable-features=Crashpad",
            "--no-crash-upload",
            # 禁用其他可能访问受限目录的功能
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-sync",
            "--metrics-recording-only",
            "--disable-default-apps",
            "--no-service-autorun",
        ]

        if not headed:
            args.append("--headless=new")

        # 添加自定义启动参数
        extra_args = self._browser_cfg.get("launch_args", [])
        for arg in extra_args:
            if arg not in args:
                args.append(arg)

        logger.info("Launching Chrome: %s", " ".join(args[:3]) + " ...")

        # 启动 Chrome 进程
        self._chrome_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 等待 Chrome 启动并监听 CDP 端口
        self._wait_for_cdp(port, timeout=30)

        # 通过 CDP 连接
        cdp_url = f"http://localhost:{port}"
        self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        logger.info("Launched and connected to Chrome (headed=%s)", headed)
        return self._browser

    def _wait_for_cdp(self, port: int, timeout: int = 30):
        """等待 Chrome CDP 端口就绪。"""
        import requests

        url = f"http://localhost:{port}/json/version"
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    logger.info("Chrome CDP port %s ready", port)
                    return
            except Exception:
                pass
            time.sleep(0.5)

        raise TimeoutError(
            f"Chrome CDP port {port} not ready after {timeout}s"
        )

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def is_chrome_running(port: int = 9222) -> bool:
        """检测 Chrome 是否已在指定端口运行 CDP。"""
        import requests

        try:
            resp = requests.get(f"http://localhost:{port}/json/version", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    @property
    def browser(self) -> Optional[Browser]:
        return self._browser

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context

    # ------------------------------------------------------------------
    # Browser Use 适配层 — 为 AI Agent 引擎提供 Browser 实例
    # ------------------------------------------------------------------
    def get_browser_use_browser(self, mode: BrowserMode = None):
        """创建并返回 Browser Use 的 Browser 实例（供 AI Agent 使用）。

        ⚠️ 新版 browser-use API 漂移修复（v2.x+）：
        - BrowserConfig → BrowserProfile
        - Browser(config=profile) → Browser(browser_profile=profile)
        - Browser 类实际返回 BrowserSession 实例
        - Browser.from_system_chrome() 实际将 profile 拷贝到 temp dir，可绕过沙箱限制

        三种创建方式：
        1. FROM_SYSTEM_CHROME: Browser.from_system_chrome() 复用系统 Chrome profile
           优势：复用登录态、cookie、扩展（profile 拷贝到 temp dir，沙箱可用）
        2. PLAYWRIGHT_CHROMIUM: Browser() 默认，用 Playwright Chromium
           优势：沙箱内可用，无依赖
        3. CONNECT_CDP: Browser 连接已启动的 Chrome（CDP）
           前提：Chrome 已用 --remote-debugging-port 启动

        Args:
            mode: Browser 模式（None 则用 config 中的默认 mode）

        Returns:
            Browser Use 的 BrowserSession 实例
        """
        try:
            # API 漂移修复：BrowserConfig → BrowserProfile
            from browser_use import Browser, BrowserProfile
        except ImportError as e:
            raise ImportError(
                "browser-use is not installed. Install with: pip install browser-use"
            ) from e

        if mode is None:
            mode_str = self._browser_cfg.get("browser_use_mode", "from_system_chrome")
        else:
            mode_str = mode.value if isinstance(mode, BrowserMode) else str(mode)

        # 已缓存则直接返回
        cache_key = f"_bu_browser_{mode_str}"
        if hasattr(self, cache_key) and getattr(self, cache_key) is not None:
            return getattr(self, cache_key)

        logger.info("Creating Browser Use Browser (mode=%s)", mode_str)

        if mode_str in ("from_system_chrome", "system_chrome"):
            # 复用系统 Chrome profile（推荐，复用登录态）
            # 新版：profile 拷贝到 temp dir，可绕过 TRAE 沙箱限制
            # 文档：https://docs.browser-use.com/open-source/customize/browser/real-browser
            try:
                bu_browser = Browser.from_system_chrome()
                logger.info("Browser Use Browser created from system Chrome")
            except Exception as e:
                logger.warning(
                    "from_system_chrome failed: %s. "
                    "Falling back to default Playwright Chromium.", e
                )
                bu_browser = self._create_default_bu_browser(Browser, BrowserProfile)
        elif mode_str in ("playwright_chromium", "default"):
            bu_browser = self._create_default_bu_browser(Browser, BrowserProfile)
            logger.info("Browser Use Browser created with Playwright Chromium")
        elif mode_str in ("connect_cdp", "cdp"):
            # 连接已启动的 Chrome
            # 新版 API：profile 用 BrowserProfile，Browser 用 browser_profile= 接收
            cdp_url = self.get_cdp_url()
            profile = BrowserProfile(cdp_url=cdp_url)
            bu_browser = Browser(browser_profile=profile)
            logger.info("Browser Use Browser created via CDP: %s", cdp_url)
        else:
            logger.warning("Unknown browser_use_mode '%s', using default", mode_str)
            bu_browser = self._create_default_bu_browser(Browser, BrowserProfile)

        # 缓存
        setattr(self, cache_key, bu_browser)
        return bu_browser

    def _create_default_bu_browser(self, Browser, BrowserProfile):
        """创建默认 Browser Use Browser（Playwright Chromium）。

        新版 API：Browser(browser_profile=BrowserProfile(...))
        """
        headed = self._browser_cfg.get("headed", False)
        viewport = self._browser_cfg.get("viewport", {"width": 1440, "height": 900})

        profile_kwargs = {
            "headless": not headed,
            "viewport": viewport,
        }
        try:
            profile = BrowserProfile(**profile_kwargs)
            return Browser(browser_profile=profile)
        except TypeError:
            # 版本兼容：参数名可能不同
            logger.warning("BrowserProfile kwargs incompatible, using defaults")
            return Browser()

    def close_browser_use(self):
        """关闭 Browser Use Browser 实例（如有）。"""
        for attr in dir(self):
            if attr.startswith("_bu_browser_"):
                bu = getattr(self, attr, None)
                if bu is not None:
                    try:
                        # Browser Use Browser 的 close 方法
                        if hasattr(bu, "close"):
                            # 可能是 async
                            import asyncio
                            try:
                                asyncio.get_event_loop().run_until_complete(bu.close())
                            except RuntimeError:
                                # 已有 event loop，用 create_task
                                pass
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug("Browser Use close error: %s", e)
                    setattr(self, attr, None)
        logger.info("Browser Use browsers closed")
