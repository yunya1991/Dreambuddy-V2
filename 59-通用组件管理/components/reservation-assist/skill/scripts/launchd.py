"""launchd 渲染与安装：plist 模板只用占位符，禁止写死本机路径。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.reservation-assist.watch"
INBOX_LABEL = "com.reservation-assist.inbox"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
TEMPLATES = {
    LABEL: TEMPLATE_DIR / "com.reservation-assist.watch.plist.tpl",
    INBOX_LABEL: TEMPLATE_DIR / "com.reservation-assist.inbox.plist.tpl",
}
TEMPLATE = TEMPLATES[LABEL]
COMPONENT_ROOT = Path(__file__).resolve().parents[2]


def render(
    home: str | Path | None = None,
    python: str | None = None,
    component_root: str | Path | None = None,
    template_text: str | None = None,
    template: Path | None = None,
) -> str:
    path = template or TEMPLATE
    text = template_text if template_text is not None else path.read_text(encoding="utf-8")
    values = {
        "__HOME__": str(home if home is not None else Path.home()),
        "__PYTHON__": str(python or sys.executable),
        "__COMPONENT__": str(component_root or COMPONENT_ROOT),
    }
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def validate(text: str, label: str = LABEL) -> list[str]:
    problems = []
    if label not in text:
        problems.append("缺少 Label {}".format(label))
    if "<key>KeepAlive</key>" not in text and "<key>StartInterval</key>" not in text:
        problems.append("缺少 KeepAlive 或 StartInterval")
    if "<string>0</string>" not in text or "RA_ALLOW_SUBMIT" not in text:
        problems.append("未显式置 RA_ALLOW_SUBMIT=0（无人值守禁止提交）")
    if "__" in text:
        problems.append("仍有未替换的占位符")
    return problems


def default_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _launchctl(argv: list[str]) -> subprocess.CompletedProcess | None:
    """launchctl 不可用时返回 None，不让安装/卸载因系统限制崩溃。"""
    try:
        return subprocess.run(["launchctl", *argv], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None


def install(agents_dir: str | Path | None = None, load: bool = True) -> list[Path]:
    target_dir = Path(agents_dir) if agents_dir else default_agents_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for label, template in TEMPLATES.items():
        text = render(template=template)
        problems = validate(text, label)
        if problems:
            raise ValueError("{}：{}".format(label, "；".join(problems)))
        target = target_dir / "{}.plist".format(label)
        target.write_text(text, encoding="utf-8")
        target.chmod(0o644)
        if load and sys.platform == "darwin":
            _launchctl(["bootstrap", "gui/{}".format(os.getuid()), str(target)])
        installed.append(target)
    return installed


def uninstall(agents_dir: str | Path | None = None) -> bool:
    target_dir = Path(agents_dir) if agents_dir else default_agents_dir()
    removed = False
    for label in TEMPLATES:
        target = target_dir / "{}.plist".format(label)
        if sys.platform == "darwin":
            _launchctl(["bootout", "gui/{}/{}".format(os.getuid(), label)])
        if target.is_file():
            target.unlink()
            removed = True
    return removed


def bootout_all(agents_dir: str | Path | None = None) -> None:
    """停止全部 agent（关闭预约），保留 plist 便于下次启动。"""
    if sys.platform != "darwin":
        return
    for label in TEMPLATES:
        _launchctl(["bootout", "gui/{}/{}".format(os.getuid(), label)])


def bootstrap_all(agents_dir: str | Path | None = None) -> None:
    """启动已安装的 agent（开启预约）；未安装则重新渲染。"""
    if sys.platform != "darwin":
        return
    target_dir = Path(agents_dir) if agents_dir else default_agents_dir()
    for label, template in TEMPLATES.items():
        target = target_dir / "{}.plist".format(label)
        if not target.is_file():
            text = render(template=template)
            target.write_text(text, encoding="utf-8")
            target.chmod(0o644)
        _launchctl(["bootstrap", "gui/{}".format(os.getuid()), str(target)])


def status() -> str:
    if sys.platform != "darwin":
        return "非 macOS，无 launchd"
    lines = []
    for label in TEMPLATES:
        result = _launchctl(["print", "gui/{}/{}".format(os.getuid(), label)])
        if result is None:
            lines.append("{}：launchctl 不可用".format(label))
        else:
            lines.append("{}：{}".format(label, "已加载" if result.returncode == 0 else "未加载"))
    return "\n".join(lines)
