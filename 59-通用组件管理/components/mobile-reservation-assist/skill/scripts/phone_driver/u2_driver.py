"""uiautomator2 驱动：按 UI 文本/坐标操作，不依赖无障碍服务。

MIUI/HyperOS 会反复撤销第三方无障碍（Auto.js），剪映/抖音这类流程改由本驱动
经 adb 直接执行；失败时立刻抛出带页面文本与截图的 U2Error，由上层问千问，
不做本地反复盲试。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

# 坐标基准：既有真机流程按 1080x2400 校准，其他分辨率按比例缩放
BASE_WIDTH, BASE_HEIGHT = 1080, 2400

# 通用弹窗关闭词：会员广告、权限、引导提示
POPUP_LABELS = (
    "始终允许", "仅在使用中允许", "本次使用允许", "允许访问全部",
    "同意并继续", "同意", "我知道了", "暂不加入", "以后再说", "跳过", "关闭", "取消",
)

MEDIA_DIRS = ("/sdcard/DCIM/Camera", "/sdcard/Movies/剪映", "/sdcard/DCIM/剪映", "/sdcard/Pictures/剪映")


class U2Error(RuntimeError):
    """单步失败：携带当时页面证据，交给上层问千问。"""

    def __init__(self, step: str, message: str = "", page_text: str = "", screenshot: str = ""):
        super().__init__("{}：{}".format(step, message or "未找到目标控件"))
        self.step = step
        self.message = message
        self.page_text = page_text
        self.screenshot = screenshot

    def as_dict(self) -> dict:
        return {
            "step": self.step,
            "error": self.message,
            "page_text": self.page_text,
            "screenshot": self.screenshot,
        }


def available() -> bool:
    """uiautomator2 是否可导入（不探测设备）。"""
    try:
        import uiautomator2  # noqa: F401
    except Exception:
        return False
    return True


def _shot_dir() -> Path:
    root = Path(os.environ.get("MRA_STATE_DIR") or (Path.home() / ".mobile-reservation-assist"))
    path = root / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


class U2Driver:
    """薄封装：只提供流程需要的动作，保持可替换（测试用 FakeDriver 同接口）。"""

    def __init__(self, serial: str = "", poll: float = 0.5, shot_dir: Path | None = None):
        self.serial = serial or os.environ.get("MRA_DEVICE_SERIAL") or os.environ.get("ANDROID_SERIAL") or ""
        self.poll = poll
        self._shot_dir = shot_dir
        self._device = None
        self._size: tuple[int, int] | None = None
        self._orig_ime = ""

    # ── 连接 ────────────────────────────────────────────────────────────
    @property
    def d(self):
        if self._device is None:
            import uiautomator2 as u2

            self._device = u2.connect(self.serial or None)
        return self._device

    def window_size(self) -> tuple[int, int]:
        if self._size is None:
            try:
                width, height = self.d.window_size()
            except Exception:
                width, height = BASE_WIDTH, BASE_HEIGHT
            self._size = (int(width), int(height))
        return self._size

    def app_start(self, package: str) -> None:
        self._capture_ime()
        self.d.app_start(package, wait=True)
        time.sleep(2)

    def _capture_ime(self) -> None:
        """u2 输入时会切到 AdbKeyboard，先记住用户原输入法。"""
        if self._orig_ime:
            return
        output = self.shell("settings get secure default_input_method").strip()
        current = output.splitlines()[0].strip() if output else ""
        if "." in current and "uiautomator" not in current:
            self._orig_ime = current

    def restore_ime(self) -> bool:
        """把默认输入法切回用户原来的（默认讯飞），避免自动化结束后键盘异常。"""
        target = self._orig_ime or os.environ.get("MRA_DEFAULT_IME") or ""
        if not target:
            return False
        self.shell("ime set {}".format(target))
        time.sleep(0.5)
        return True

    def app_restart(self, package: str) -> None:
        """冷启动：强制停掉再从首页进入，避免停在上次的中间页面。"""
        self.shell("am force-stop {}".format(package))
        time.sleep(1)
        self.app_start(package)

    def current_package(self) -> str:
        """MIUI 上 u2 的 app_current 会返回旧包名，优先解析 topResumedActivity。"""
        output = self.shell("dumpsys activity activities | grep topResumedActivity")
        if "topResumedActivity=" in output:
            segment = output.split("topResumedActivity=", 1)[1]
            token = segment.split("/", 1)[0].strip().split()[-1]
            if "." in token:
                return token
        try:
            return str(self.d.app_current().get("package") or "")
        except Exception:
            return ""

    # ── 查找与点击 ──────────────────────────────────────────────────────
    def find(self, label: str):
        """按 text → textContains → description → descriptionContains 依次找。"""
        if not label:
            return None
        for kwargs in (
            {"text": label},
            {"textContains": label},
            {"description": label},
            {"descriptionContains": label},
        ):
            element = self.d(**kwargs)
            try:
                if element.exists:
                    return element
            except Exception:
                continue
        return None

    def wait(self, label: str, timeout: float = 8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            element = self.find(label)
            if element is not None:
                return element
            time.sleep(self.poll)
        return None

    def tap(self, label: str, timeout: float = 8.0) -> bool:
        element = self.wait(label, timeout)
        if element is None:
            return False
        try:
            element.click()
        except Exception:
            return False
        time.sleep(1)
        return True

    def tap_any(self, labels, timeout: float = 6.0) -> str:
        """逐个尝试，命中返回该词；全不命中返回空串。"""
        deadline = time.time() + timeout
        while True:
            for label in labels:
                element = self.find(label)
                if element is not None:
                    try:
                        element.click()
                    except Exception:
                        continue
                    time.sleep(1)
                    return label
            if time.time() >= deadline:
                return ""
            time.sleep(self.poll)

    def tap_xy(self, x: int, y: int) -> bool:
        """基准坐标（1080x2400）→ 当前分辨率。"""
        width, height = self.window_size()
        try:
            self.d.click(int(x * width / BASE_WIDTH), int(y * height / BASE_HEIGHT))
        except Exception:
            return False
        time.sleep(1)
        return True

    def tap_input(self, hint: str = ""):
        """找输入框：先按提示词，再退化为第一个 EditText。"""
        if hint:
            element = self.find(hint)
            if element is not None:
                return element
        for kwargs in ({"className": "android.widget.EditText"}, {"focused": True}):
            element = self.d(**kwargs)
            try:
                if element.exists:
                    return element
            except Exception:
                continue
        return None

    def _dismiss_ime_picker(self) -> bool:
        """MIUI 在切换 AdbKeyboard 时会弹输入法选择器，挡住页面按钮。"""
        page = self.page_text(600)
        if "AdbKeyboard" not in page:
            return False
        if self.tap_any(("AdbKeyboard",), timeout=2):
            time.sleep(1)
            return True
        self.press("back")
        time.sleep(1)
        return True

    def fill_fields(self, pairs: list[tuple[tuple[str, ...], str]]) -> list[bool]:
        """按提示词填多个输入框（抖音发布页：标题 20 字 + 描述），逐个回读。"""
        results: list[bool] = []
        for hints, value in pairs:
            if not value.strip():
                results.append(True)
                continue
            self._dismiss_ime_picker()
            element = None
            for hint in hints:
                element = self.find(hint)
                if element is not None:
                    break
            if element is None:
                element = self.tap_input()
            ok = False
            if element is not None:
                try:
                    element.click()
                    time.sleep(0.6)
                    element.set_text(value)
                    time.sleep(1)
                    ok = True
                except Exception:
                    ok = False
            self._dismiss_ime_picker()              # 选择器可能延迟弹出
            head = value.strip().splitlines()[0][:10]
            results.append(ok and head in self.page_text(6000))
        return results

    def fill(self, value: str, hint: str = "") -> bool:
        """点输入框并写入文本；用整页文本回读（MIUI 下 UiObject 回读常失效）。"""
        element = self.tap_input(hint)
        if element is None:
            return False
        try:
            element.click()
            time.sleep(0.6)
            element.set_text(value)
            time.sleep(1.2)
        except Exception:
            return False
        head = value.strip().splitlines()[0][:12] if value.strip() else ""
        return not head or head in self.page_text(4000)

    def fill_all(self, values: list[str]) -> list[bool]:
        """按顺序填 EditText（抖音发布页：标题 / 描述），同样用整页文本校验。"""
        edits = self.d(className="android.widget.EditText")
        try:
            count = edits.count
        except Exception:
            count = 0
        for index, value in enumerate(values):
            if index >= count:
                continue
            try:
                edits[index].click()
                time.sleep(0.5)
                edits[index].set_text(value)
                time.sleep(0.6)
            except Exception:
                continue
        page = self.page_text(4000)
        return [
            bool(value.strip()) and value.strip().splitlines()[0][:12] in page
            for value in values
        ]

    # ── 页面信息 ────────────────────────────────────────────────────────
    def page_text(self, limit: int = 1200) -> str:
        try:
            xml = self.d.dump_hierarchy()
        except Exception:
            return ""
        values: list[str] = []
        for match in re.finditer(r'(?:text|content-desc)="([^"]+)"', xml or ""):
            value = match.group(1).strip()
            if value and value not in values:
                values.append(value)
        return "\n".join(values)[:limit]

    def has_text(self, needle: str) -> bool:
        return bool(needle) and needle in self.page_text(4000)

    def screenshot(self, tag: str = "u2") -> str:
        directory = self._shot_dir or _shot_dir()
        path = directory / "{}_{}.png".format(tag, time.strftime("%Y%m%d_%H%M%S"))
        try:
            self.d.screenshot(str(path))
        except Exception:
            return ""
        return str(path)

    # ── 系统动作 ────────────────────────────────────────────────────────
    def swipe_up(self, scale: float = 0.72) -> bool:
        width, height = self.window_size()
        try:
            self.d.swipe(width // 2, int(height * scale), width // 2, int(height * 0.3), 0.4)
        except Exception:
            return False
        time.sleep(1)
        return True

    def press(self, key: str) -> bool:
        try:
            self.d.press(key)
        except Exception:
            return False
        time.sleep(0.8)
        return True

    def hide_keyboard(self) -> bool:
        try:
            self.d.hide_keyboard()
        except Exception:
            return False
        time.sleep(0.6)
        return True

    def dismiss(self, labels=POPUP_LABELS, rounds: int = 3) -> list[str]:
        """关弹窗；不允许付费（遇到会员页只关不买）。"""
        closed: list[str] = []
        for _ in range(rounds):
            hit = ""
            for label in labels:
                element = self.find(label)
                if element is not None and label not in closed:
                    try:
                        element.click()
                    except Exception:
                        continue
                    closed.append(label)
                    hit = label
                    time.sleep(1)
                    break
            if not hit:
                break
        return closed

    def shell(self, command: str) -> str:
        try:
            result = self.d.shell(command)
        except Exception:
            return ""
        return str(getattr(result, "output", None) or result or "")

    def latest_media(self, suffix: str = ".mp4") -> str:
        """相册/剪映目录里最新的媒体文件（供上游记录，失败不算流程失败）。"""
        for directory in MEDIA_DIRS:
            output = self.shell("ls -t {} 2>/dev/null | head -20".format(directory))
            for line in output.splitlines():
                name = line.strip()
                if name.lower().endswith(suffix.lower()):
                    return "{}/{}".format(directory.rstrip("/"), name)
        return ""
