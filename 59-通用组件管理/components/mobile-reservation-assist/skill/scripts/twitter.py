"""X（推特）网页端发布适配器：Playwright 持久化登录 + 本地定时队列。

定位：桌面侧网页自动化，不依赖手机端 uiautomator2。
- 登录态保存在 `<state_dir>/twitter/profile`，与日常 Chrome 隔离
- 只做「打开写作框 → 输入 → 发布」，不处理私信、关注、点赞
- 定时由 store 队列 + launchd 每分钟 tick 驱动；单条原子认领，禁止重复发布
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CN_TZ = timezone(timedelta(hours=8))
HOME_URL = "https://x.com/home"
LOGIN_URL = "https://x.com/login"
COMPOSE_URL = "https://x.com/compose/post"

TEXTAREA = '[data-testid="tweetTextarea_0"]'
TOAST = '[data-testid="toast"]'
DIALOG_TEXTAREA = '[role="dialog"] [data-testid="tweetTextarea_0"]'
LOGGED_IN_MARKERS = '[data-testid="SideNav_AccountSwitcher_Button"], ' + TEXTAREA
FILE_INPUT = 'input[data-testid="fileInput"]'
# X 会拦截 HeadlessChrome 的默认 UA，必须使用常规 Chrome UA
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

CHROME_ROOT = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
COOKIE_HOSTS = (".x.com", "x.com", ".twitter.com", "twitter.com")
WEBKIT_EPOCH_OFFSET = 11644473600  # 1601-01-01 → 1970-01-01（秒）


class TwitterError(RuntimeError):
    """推文发射失败（未登录/页面结构变化/网络异常）。"""


def profile_dir(base: Path) -> Path:
    directory = Path(base) / "twitter" / "profile"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# --- 从本机 Chrome 导入登录 cookie -----------------------------------------
def _aes():
    try:
        from Crypto.Cipher import AES
    except ImportError as exc:  # pragma: no cover - 环境缺失
        raise TwitterError("未安装 pycryptodome：python3 -m pip install pycryptodome") from exc
    return AES


def chrome_storage_key() -> bytes:
    """从 Keychain 读取 Chrome Safe Storage，派生 AES-128 密钥。"""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TwitterError("读取 Keychain 失败：{}".format(exc)) from exc
    password = (result.stdout or "").strip()
    if result.returncode != 0 or not password:
        raise TwitterError("未取到 Chrome Safe Storage：请允许终端访问钥匙串后重试")
    return hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, 16)


def decrypt_cookie(blob: bytes, host: str, key: bytes) -> str:
    """解密 Chrome cookie；兼容 v10/v11 与新版 SHA256(host) 前缀。"""
    if not blob:
        return ""
    if blob[:3] in (b"v10", b"v11"):
        AES = _aes()
        raw = AES.new(key, AES.MODE_CBC, b" " * 16).decrypt(blob[3:])
        if raw and 1 <= raw[-1] <= 16:
            raw = raw[:-raw[-1]]
        digest = hashlib.sha256(host.encode()).digest()
        if raw.startswith(digest):
            raw = raw[len(digest):]
        return raw.decode("utf-8", "replace")
    return blob.decode("utf-8", "replace")


def _chrome_cookie_dbs() -> list[Path]:
    candidates = [CHROME_ROOT / "Default" / "Cookies"]
    candidates.extend(sorted(CHROME_ROOT.glob("Profile */Cookies")))
    return [path for path in candidates if path.is_file()]


def _cookie_rows(db_path: Path) -> list[sqlite3.Row]:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        shutil.copy2(db_path, copy)
        for suffix in ("-wal", "-shm"):
            extra = Path(str(db_path) + suffix)
            if extra.exists():
                shutil.copy2(extra, Path(str(copy) + suffix))
        conn = sqlite3.connect(str(copy))
        conn.row_factory = sqlite3.Row
        try:
            marks = ",".join("?" for _ in COOKIE_HOSTS)
            return conn.execute(
                "SELECT host_key, name, encrypted_value, path, expires_utc, is_secure,"
                " is_httponly, samesite FROM cookies WHERE host_key IN ({})".format(marks),
                COOKIE_HOSTS,
            ).fetchall()
        finally:
            conn.close()


def _playwright_cookie(row: sqlite3.Row, key: bytes, now: float | None = None) -> dict | None:
    value = decrypt_cookie(bytes(row["encrypted_value"]), row["host_key"], key)
    if not value:
        return None
    raw_expires = int(row["expires_utc"] or 0)
    expires = -1 if raw_expires <= 0 else int(raw_expires / 1_000_000 - WEBKIT_EPOCH_OFFSET)
    if expires > 0 and expires < (now or time.time()):
        return None
    cookie = {
        "name": row["name"],
        "value": value,
        "domain": row["host_key"],
        "path": row["path"] or "/",
        "expires": expires,
        "httpOnly": bool(row["is_httponly"]),
        "secure": bool(row["is_secure"]),
    }
    same_site = {0: "None", 1: "Lax", 2: "Strict"}.get(
        int(row["samesite"]) if row["samesite"] is not None else -1
    )
    if same_site:
        cookie["sameSite"] = same_site
    return cookie


def chrome_cookies(now: float | None = None) -> list[dict]:
    """读取本机 Chrome 全部 profile 的 x.com/twitter.com cookie（去重取最晚过期）。"""
    dbs = _chrome_cookie_dbs()
    if not dbs:
        raise TwitterError("未找到 Chrome cookie 数据库：请确认本机 Chrome 已登录 x.com")
    key = chrome_storage_key()
    found: dict[tuple[str, str], dict] = {}
    for db_path in dbs:
        try:
            rows = _cookie_rows(db_path)
        except (sqlite3.Error, OSError):
            continue
        for row in rows:
            cookie = _playwright_cookie(row, key, now=now)
            if not cookie:
                continue
            dedupe_key = (cookie["domain"], cookie["name"])
            previous = found.get(dedupe_key)
            if not previous or cookie["expires"] > previous["expires"]:
                found[dedupe_key] = cookie
    return list(found.values())


def parse_schedule(at: str = "", in_: str = "", now: datetime | None = None) -> int:
    """把 --at / --in 解析成毫秒时间戳（东八区）。"""
    now = now or datetime.now(CN_TZ)
    raw_at = str(at or "").strip()
    raw_in = str(in_ or "").strip()
    if raw_at and raw_in:
        raise ValueError("--at 与 --in 只能二选一")
    if raw_in:
        match = re.fullmatch(r"(\d+)\s*([smhd])", raw_in)
        if not match:
            raise ValueError("--in 格式应为 30m / 2h / 1d")
        amount, unit = int(match.group(1)), match.group(2)
        delta = {
            "s": timedelta(seconds=amount),
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return int((now + delta).timestamp() * 1000)
    if not raw_at:
        return int(now.timestamp() * 1000)

    text = raw_at.replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            target = datetime.strptime(text, fmt).replace(tzinfo=CN_TZ)
            return int(target.timestamp() * 1000)
        except ValueError:
            continue
    match = re.fullmatch(r"(今天|明天|后天)?\s*(\d{1,2}):(\d{2})", text)
    if match:
        offset = {"今天": 0, "明天": 1, "后天": 2}.get(match.group(1) or "今天", 0)
        target = (now + timedelta(days=offset)).replace(
            hour=int(match.group(2)), minute=int(match.group(3)), second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return int(target.timestamp() * 1000)
    raise ValueError("--at 格式应为 'YYYY-MM-DD HH:MM'、'HH:MM' 或 '明天 09:00'")


def fmt_time(ms: int) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000, CN_TZ).strftime("%Y-%m-%d %H:%M")


class TwitterWeb:
    """Playwright 持久化上下文封装；一个实例对应一次浏览器会话。"""

    def __init__(self, base: Path, headless: bool = True, timeout_ms: int = 30000) -> None:
        self.base = Path(base)
        self.headless = headless
        self.timeout_ms = int(timeout_ms)
        self._pw = None
        self._ctx = None
        self._page = None

    # --- 生命周期 ---------------------------------------------------------
    def __enter__(self) -> "TwitterWeb":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 环境缺失
            raise TwitterError("未安装 playwright：python3 -m pip install playwright") from exc
        self._pw = sync_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]
        kwargs = dict(
            user_data_dir=str(profile_dir(self.base)),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            user_agent=USER_AGENT,
            args=args,
        )
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception:
            # 兜底：系统 Chrome 不可用时退回 Playwright 自带 Chromium
            self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    def close(self) -> None:
        for closer in (self._ctx, self._pw):
            try:
                if closer:
                    closer.close() if closer is not self._pw else closer.stop()
            except Exception:
                pass
        self._ctx = self._pw = self._page = None

    # --- 登录 -------------------------------------------------------------
    def is_logged_in(self, goto: bool = True) -> bool:
        page = self._page
        if page is None:
            raise TwitterError("浏览器尚未启动")
        if goto:
            try:
                page.goto(HOME_URL, wait_until="domcontentloaded")
            except Exception:
                return False
        if "/login" in (page.url or "") or "i/flow/login" in (page.url or ""):
            return False
        try:
            page.wait_for_selector(LOGGED_IN_MARKERS, timeout=12000)
        except Exception:
            return False
        return True

    def import_chrome_cookies(self) -> int:
        """把本机 Chrome 的 x.com cookie 写入当前持久化上下文。"""
        if self._ctx is None:
            raise TwitterError("浏览器尚未启动")
        cookies = chrome_cookies()
        if not cookies:
            raise TwitterError("Chrome 中没有有效的 x.com cookie：请先在 Chrome 登录 x.com")
        self._ctx.add_cookies(cookies)
        return len(cookies)

    def login(self, wait_seconds: int = 300, from_chrome: bool = True) -> dict:
        """默认从本机 Chrome 导入 cookie；--manual 时打开登录页等人工登录。"""
        if from_chrome:
            try:
                count = self.import_chrome_cookies()
            except TwitterError as exc:
                return {"ok": False, "message": str(exc), "count": 0}
            # 首次注入后 X 可能仍短暂停留在登录墙，重试一次再判定
            for attempt in range(2):
                if self.is_logged_in():
                    return {
                        "ok": True,
                        "message": "已从 Chrome 导入 {} 条 cookie 并验证登录".format(count),
                        "count": count,
                    }
                if attempt == 0:
                    self._page.wait_for_timeout(3000)
            return {
                "ok": False,
                "message": "已导入 {} 条 cookie，但 X 仍判定未登录：cookie 可能过期，请改用 --manual".format(count),
                "count": count,
            }
        page = self._page
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
        except Exception as exc:
            return {"ok": False, "message": "打开登录页失败：{}".format(exc)}
        deadline = time.time() + max(30, int(wait_seconds))
        while time.time() < deadline:
            page.wait_for_timeout(3000)
            try:
                if page.locator(LOGGED_IN_MARKERS).count() > 0 and "/login" not in page.url:
                    page.goto(HOME_URL, wait_until="domcontentloaded")
                    return {"ok": True, "message": "登录成功，登录态已写入持久化 profile"}
            except Exception:
                continue
        return {"ok": False, "message": "等待登录超时，请重试 mra.py twitter login"}

    # --- 发布 -------------------------------------------------------------
    def post(self, text: str, media=()) -> dict:
        """发布一条推文：返回 {ok, error, url}。"""
        page = self._page
        if page is None:
            raise TwitterError("浏览器尚未启动")
        body = str(text or "").strip()
        if not body:
            return {"ok": False, "error": "推文内容为空", "url": ""}
        try:
            page.goto(COMPOSE_URL, wait_until="domcontentloaded")
        except Exception as exc:
            return {"ok": False, "error": "打开写作页失败：{}".format(exc), "url": ""}
        try:
            page.wait_for_selector(TEXTAREA, timeout=self.timeout_ms)
        except Exception:
            return {
                "ok": False,
                "error": "未找到发推输入框，可能未登录或页面结构变化",
                "url": "",
            }
        # 桌面端发推框在 dialog 内；页面同时存在隐藏的 inline 副本，优先限定 dialog
        scope = "[role=\"dialog\"] " if page.locator(DIALOG_TEXTAREA).count() else ""
        textarea = scope + TEXTAREA
        submit = scope + '[data-testid="tweetButton"]'
        page.click(textarea)
        page.keyboard.insert_text(body)
        files = [str(Path(item).expanduser()) for item in media or []]
        if files:
            try:
                page.set_input_files(scope + FILE_INPUT, files)
                page.wait_for_timeout(1500)
            except Exception as exc:
                return {"ok": False, "error": "图片上传失败：{}".format(exc), "url": ""}
        page.wait_for_timeout(500)
        try:
            page.click(submit, timeout=10000)
        except Exception as exc:
            return {"ok": False, "error": "点击发布按钮失败：{}".format(exc), "url": ""}
        # 发布结果：出现 toast，或写作框关闭
        toast_text = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            try:
                if page.locator(TOAST).count() > 0:
                    toast_text = page.locator(TOAST).first.inner_text().strip()
                    break
                if page.locator(DIALOG_TEXTAREA).count() == 0:
                    toast_text = "composer closed"
                    break
            except Exception:
                continue
        lowered = toast_text.lower()
        failed = any(word in lowered for word in ("失败", "出错", "重试", "went wrong", "failed"))
        if failed:
            return {"ok": False, "error": "X 返回错误：{}".format(toast_text), "url": ""}
        return {"ok": True, "error": "", "url": "", "toast": toast_text}


def recover_stale(db, seconds: int = 900) -> int:
    """把长时间停留在 posting 的记录收敛为 failed，避免永久卡死。"""
    return db.recover_stale_twitter(seconds=seconds)


def run_due(db, poster, limit: int = 3, now: int | None = None) -> list[dict]:
    """执行到点推文。poster(text, media) -> {ok, error, url}，便于单测注入。"""
    results: list[dict] = []
    for _ in range(max(1, int(limit))):
        item = db.claim_due_twitter_post(now)
        if not item:
            break
        try:
            outcome = poster(item["text"], item.get("media") or [])
        except Exception as exc:  # 浏览器异常：收敛 failed，禁止自动重发
            outcome = {"ok": False, "error": str(exc), "url": ""}
        if outcome.get("ok"):
            db.finish_twitter_post(item["_id"], "done", tweet_url=outcome.get("url") or "")
        else:
            db.finish_twitter_post(item["_id"], "failed", error=str(outcome.get("error") or "未知错误"))
        results.append(
            {
                "id": item["_id"],
                "scheduled_at": item["scheduled_at"],
                "ok": bool(outcome.get("ok")),
                "error": outcome.get("error") or "",
            }
        )
    return results
