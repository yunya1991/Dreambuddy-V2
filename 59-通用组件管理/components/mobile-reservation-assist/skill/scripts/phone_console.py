"""确定性手机控制台：把 uiautomator2 驱动能力包装成 CLI 动作。

三个入口共用同一套动作实现：
- `mra phone <action>`：单次确定性操作
- `mra console`：交互式控制台（不依赖大模型）
- `mra chat` / `mra ask`：自然语言 → 白名单计划 → 同一套动作
"""

from __future__ import annotations

import shlex
import time

# 常用应用别名 → 包名；未知名称按包名原样透传
APP_ALIASES = {
    "xhs": "com.xingin.xhs",
    "xiaohongshu": "com.xingin.xhs",
    "小红书": "com.xingin.xhs",
    "jianying": "com.lemon.lv",
    "capcut": "com.lemon.lv",
    "剪映": "com.lemon.lv",
    "douyin": "com.ss.android.ugc.aweme",
    "抖音": "com.ss.android.ugc.aweme",
    "qianwen": "com.aliyun.tongyi",
    "千问": "com.aliyun.tongyi",
    "notes": "com.miui.notes",
    "memo": "com.miui.notes",
    "笔记": "com.miui.notes",
    "autojs": "org.autojs.autojs6",
    "settings": "com.android.settings",
    "设置": "com.android.settings",
}

# 可由 CLI / 大模型计划调用的确定性动作（全部不触碰支付与发布终态）
PHONE_ACTIONS = (
    "open_app",
    "tap",
    "type",
    "swipe",
    "key",
    "screen",
    "shot",
    "wait",
    "pkg",
    "apps",
    "adapters",
)

# 交互式命令的正名（用户输入短名即可）
ALIASES = {
    "open": "open_app",
    "app": "open_app",
    "screen": "screen",
    "text": "screen",
    "tap": "tap",
    "click": "tap",
    "type": "type",
    "input": "type",
    "swipe": "swipe",
    "key": "key",
    "shot": "shot",
    "screenshot": "shot",
    "wait": "wait",
    "pkg": "pkg",
    "apps": "apps",
    "adapters": "adapters",
}

# 位置参数顺序：`tap 开始创作`、`x=100 y=200` 两种写法都支持
POSITIONAL = {
    "open_app": ("app",),
    "tap": ("text",),
    "type": ("text",),
    "swipe": ("direction",),
    "key": ("key",),
    "wait": ("text",),
}

INT_KEYS = {"x", "y", "x1", "y1", "x2", "y2", "limit"}


def resolve_app(name: str) -> str:
    key = (name or "").strip()
    if not key:
        raise ValueError("缺少应用名或包名")
    return APP_ALIASES.get(key.lower(), APP_ALIASES.get(key, key))


def parse_line(line: str) -> tuple[str, dict]:
    """把一行控制台输入解析成 (动作, 参数字典)。"""
    parts = shlex.split(line.strip())
    if not parts:
        raise ValueError("空命令")
    action = ALIASES.get(parts[0].lower(), parts[0])
    if action not in PHONE_ACTIONS:
        raise ValueError("未知命令：{}（输入 help 查看）".format(parts[0]))
    params: dict = {}
    positional = list(POSITIONAL.get(action, ()))
    for token in parts[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            params[key] = int(value) if key in INT_KEYS and value.lstrip("-").isdigit() else value
        elif positional:
            params[positional.pop(0)] = int(token) if token.lstrip("-").isdigit() and action == "swipe" else token
        else:
            raise ValueError("多余参数：{}".format(token))
    return action, params


class PhoneConsole:
    """动作执行器；driver 可注入，便于测试。"""

    def __init__(self, driver=None):
        self._driver = driver

    @property
    def driver(self):
        if self._driver is None:
            from phone_driver.u2_driver import U2Driver

            self._driver = U2Driver()
        return self._driver

    def execute(self, action: str, **params) -> dict:
        handler = getattr(self, "_do_{}".format(action), None)
        if handler is None:
            raise ValueError("不支持的手机动作：{}".format(action))
        return handler(**params)

    # ── 动作实现 ────────────────────────────────────────────────────────
    def _do_open_app(self, app: str, restart: bool = False) -> dict:
        package = resolve_app(app)
        if restart:
            self.driver.app_restart(package)
        else:
            self.driver.app_start(package)
        return {"ok": True, "app": package, "package": self.driver.current_package()}

    def _do_tap(self, text: str = "", x: int | None = None, y: int | None = None, timeout: float = 8.0) -> dict:
        if x is not None and y is not None:
            ok = self.driver.tap_xy(int(x), int(y))
            return {"ok": bool(ok), "x": int(x), "y": int(y)}
        if not text:
            raise ValueError("tap 需要文本或 x/y 坐标")
        ok = self.driver.tap(text, timeout=float(timeout))
        return {"ok": bool(ok), "text": text}

    def _do_type(self, text: str, hint: str = "", clear: bool = False) -> dict:
        if not text:
            raise ValueError("type 需要文本")
        ok = self.driver.type_text(text, hint=hint, clear=bool(clear))
        return {"ok": bool(ok), "text": text}

    def _do_swipe(self, direction: str = "up", x1: int | None = None, y1: int | None = None,
                  x2: int | None = None, y2: int | None = None, duration: float = 0.3) -> dict:
        if None not in (x1, y1, x2, y2):
            ok = self.driver.swipe_xy(int(x1), int(y1), int(x2), int(y2), duration=float(duration))
            return {"ok": bool(ok), "from": [x1, y1], "to": [x2, y2]}
        width, height = self.driver.window_size()
        cx, cy = width // 2, height // 2
        routes = {
            "up": (cx, int(height * 0.75), cx, int(height * 0.25)),
            "down": (cx, int(height * 0.25), cx, int(height * 0.75)),
            "left": (int(width * 0.85), cy, int(width * 0.15), cy),
            "right": (int(width * 0.15), cy, int(width * 0.85), cy),
        }
        if direction not in routes:
            raise ValueError("swipe 方向只支持 up/down/left/right")
        ok = self.driver.swipe_xy(*routes[direction], duration=float(duration))
        return {"ok": bool(ok), "direction": direction}

    def _do_key(self, key: str = "back") -> dict:
        ok = self.driver.press(key)
        return {"ok": bool(ok), "key": key}

    def _do_screen(self, limit: int = 1200) -> dict:
        return {
            "ok": True,
            "package": self.driver.current_package(),
            "text": self.driver.page_text(int(limit)),
        }

    def _do_shot(self, tag: str = "console") -> dict:
        path = self.driver.screenshot(tag)
        return {"ok": bool(path), "path": path}

    def _do_wait(self, text: str, timeout: float = 10.0) -> dict:
        if not text:
            raise ValueError("wait 需要文本")
        element = self.driver.wait(text, timeout=float(timeout))
        return {"ok": element is not None, "found": element is not None, "text": text}

    def _do_pkg(self) -> dict:
        return {"ok": True, "package": self.driver.current_package()}

    def _do_apps(self) -> dict:
        return {"ok": True, "aliases": APP_ALIASES}

    def _do_adapters(self) -> dict:
        from pathlib import Path

        directory = Path(__file__).resolve().parent / "phone_adapters"
        names = sorted(
            path.stem for path in directory.glob("*.py")
            if not path.stem.startswith("_")
        )
        return {"ok": True, "adapters": names}

    # ── 交互式控制台 ────────────────────────────────────────────────────
    HELP = """可用命令：
  open <app|包名>            打开应用（xhs/jianying/douyin/qianwen/notes...）
  screen                    读取当前页面文本与包名
  tap <文本>                 按文本点击
  tap x=500 y=1200           按坐标点击
  type <文本>                写入当前输入框（--clear 语义用 clear=1）
  swipe up|down|left|right   滑动
  key back|home|recent       系统按键
  wait <文本> timeout=10     等待元素出现
  shot                      截图
  pkg                       当前包名
  apps                      查看应用别名
  adapters                  查看平台适配器
  help / exit               帮助 / 退出
"""

    def repl(self) -> None:
        print("═══ 手机控制台 ═══ 输入 help 查看命令，exit 退出")
        while True:
            try:
                line = input("phone> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("exit", "quit", "/exit", "/quit"):
                break
            if line in ("help", "/help", "?"):
                print(self.HELP)
                continue
            try:
                action, params = parse_line(line)
                result = self.execute(action, **params)
            except Exception as exc:  # noqa: BLE001 - 控制台不因单条命令退出
                print("  ✗ {}".format(exc))
                continue
            ok = result.get("ok", True)
            print("  {} {}".format("✓" if ok else "✗", _render(result)))
            time.sleep(0.2)
        print("控制台结束。")


def _render(result: dict) -> str:
    if "text" in result and result.get("package"):
        return "[{}]\n{}".format(result["package"], result["text"])
    return " ".join("{}={}".format(key, value) for key, value in result.items() if key != "ok")
