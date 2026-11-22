"""59 域能力索引的只读消费端（dreambuddy.capabilities.v2）。

- 索引由 59 域 `dreambuddy caps sync` 发布到 `~/.local/share/dreambuddy/registry/capabilities.json`；
- 本模块只读该文件，不 import 59 域代码；
- 跨域执行一律子进程（`dreambuddy run ...`），安全级由执行侧重新判定。

解析顺序（CLI 路径）：环境变量 DREAMBUDDY_CLI → ~/.config/dreambuddy/dreambuddy.path → 默认 59 域路径。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_PREFIX = "dreambuddy.capabilities."
LOCAL_COMPONENT = "mobile-reservation-assist"
SAFETY_ORDER = {"read": 0, "write": 1, "ui": 2, "irreversible": 3}

# data.* 能力到 19-DAL CLI 的路由与参数映射（schema 是松散的 object，需按 DAL 语义扁平化）
DATA_ROUTES: Dict[str, Dict[str, Any]] = {
    "data_store_read": {
        "argv": ["read"],
        "flatten": {
            "filters": {
                "sub_category": "--sub-category",
                "metric_name": "--metric-name",
                "start_ts": "--start-ts",
                "end_ts": "--end-ts",
            }
        },
    },
    "data_fetch": {"argv": ["fetch"], "json": {"params"}, "required": ["scope"]},
    "data_collect_once": {"argv": ["scopes"], "drop": {"source"}},
}


class RegistryError(RuntimeError):
    """索引缺失 / 不可读 / 版本不兼容。"""


def registry_path() -> Path:
    raw = (os.environ.get("DREAMBUDDY_REGISTRY") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local/share/dreambuddy/registry/capabilities.json"


def cli_path() -> Path:
    env = (os.environ.get("DREAMBUDDY_CLI") or "").strip()
    if env:
        return Path(env).expanduser()
    config = Path.home() / ".config/dreambuddy/dreambuddy.path"
    try:
        if config.is_file():
            raw = config.read_text(encoding="utf-8").strip()
            if raw:
                return Path(raw).expanduser()
    except OSError:
        pass
    return Path.home() / "WorkBuddy/dreambuddy-v2/59-通用组件管理/tools/dreambuddy.py"


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path).expanduser() if path else registry_path()
    if not target.is_file():
        raise RegistryError(
            "能力索引未发布：{}（在 59 域执行 dreambuddy caps sync）".format(target)
        )
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError("能力索引不可读：{}".format(exc)) from exc
    schema = str(data.get("schema") or "")
    if not schema.startswith(SCHEMA_PREFIX):
        raise RegistryError("能力索引 schema 不支持：{}".format(schema or "<空>"))
    return data


def capabilities(index: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    data = index if index is not None else load()
    return list(data.get("capabilities") or [])


def find(capability_id: str, index: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    for cap in capabilities(index):
        if cap.get("id") == capability_id:
            return cap
    return None


def is_local(cap: Dict[str, Any]) -> bool:
    return cap.get("component") == LOCAL_COMPONENT


def effective_safety(cap: Dict[str, Any], args: Any = None) -> str:
    level = str(cap.get("safety") or "read")
    tokens = [str(item) for item in (args or [])]
    for flag, raised in (cap.get("escalate") or {}).items():
        if flag in tokens and SAFETY_ORDER.get(raised, 0) > SAFETY_ORDER.get(level, 0):
            level = str(raised)
    return level


def _flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def _emit(values: Dict[str, Any], schema: Dict[str, Any], spec: Dict[str, Any], out: List[str]) -> None:
    props = (schema or {}).get("properties") or {}
    for key, value in values.items():
        if key in (spec.get("drop") or set()):
            continue
        if key in (spec.get("flatten") or {}):
            if not isinstance(value, dict):
                raise ValueError("{} 必须是对象".format(key))
            mapping = spec["flatten"][key]
            for sub, sub_value in value.items():
                flag = mapping.get(sub) or _flag(sub)
                if isinstance(sub_value, bool):
                    if sub_value:
                        out.append(flag)
                elif isinstance(sub_value, (dict, list)):
                    out.extend([flag, json.dumps(sub_value, ensure_ascii=False)])
                else:
                    out.extend([flag, str(sub_value)])
            continue
        flag = _flag(key)
        prop = props.get(key) or {}
        if key in (spec.get("json") or set()) or isinstance(value, (dict, list)):
            out.extend([flag, json.dumps(value, ensure_ascii=False)])
        elif prop.get("type") == "boolean" or isinstance(value, bool):
            if value:
                out.append(flag)
        else:
            out.extend([flag, str(value)])


def data_argv(cli: Path, cap: Dict[str, Any], args: Any = None) -> Optional[List[str]]:
    """按 schema/路由把 data.* 能力翻译成 `dreambuddy dal <cmd>`。

    支持三种入参形态：
      1. `--json '{"filters": {"sub_category": "macro"}}'`（推荐，按 schema 扁平化）
      2. `key=value ...`（值可为 JSON）
      3. 原生 flag 透传（如 `--sub-category macro --metric-name DGS10`）
    """
    tool = str(cap.get("tool") or "")
    spec = DATA_ROUTES.get(tool)
    if spec is None:
        return None
    base = [sys.executable, str(cli), "dal"] + list(spec["argv"])
    rest = [str(item) for item in (args or [])]
    if not rest:
        values: Dict[str, Any] = {}
    elif rest[0] in ("--json", "-j"):
        if len(rest) < 2:
            raise ValueError("--json 需要 JSON 对象")
        try:
            values = json.loads(rest[1])
        except json.JSONDecodeError as exc:
            raise ValueError("--json 不是合法 JSON（{}）".format(exc.msg))
    elif all(not item.startswith("-") and "=" in item for item in rest):
        values = {}
        for item in rest:
            key, _, raw = item.partition("=")
            values[key] = _maybe_json(raw)
    else:
        return base + rest
    if not isinstance(values, dict):
        raise ValueError("参数必须是 JSON 对象")
    for key in spec.get("required") or []:
        if key not in values:
            raise ValueError("缺少必填参数 {}".format(key))
    out: List[str] = []
    _emit(values, cap.get("schema") or {}, spec, out)
    return base + out


def _maybe_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return raw
    return raw


def plan_argv(
    cli: Path, cap: Dict[str, Any], args: Any = None, allow_write: bool = False
) -> Optional[List[str]]:
    """把能力翻译成 59 域统一入口的子进程命令；不支持的类型返回 None。

    - run     → dreambuddy run <component> <action>
    - data    → dreambuddy dal <tool>
    - workflow→ dreambuddy workflow run <name> --dry-run（跨域只跑只读预演）
    - schedule→ dreambuddy schedule list
    allow_write=True 时给 run 类补上执行侧门禁所需的 --allow-write（是否真能执行仍由 59 域复核）。
    """
    kind = cap.get("kind")
    rest = [str(item) for item in (args or [])]
    if kind == "run":
        component = str(cap.get("component") or "")
        action = str(cap.get("action") or "")
        if not component or not action:
            return None
        argv = [sys.executable, str(cli), "run", component, action] + rest
        if allow_write:
            argv.append("--allow-write")
        return argv
    if kind == "data":
        return data_argv(cli, cap, rest)
    if kind == "workflow":
        return [sys.executable, str(cli), "workflow", "run", str(cap.get("workflow") or ""), "--dry-run"]
    if kind == "schedule":
        return [sys.executable, str(cli), "schedule", "list"]
    return None
