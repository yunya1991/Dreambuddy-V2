#!/usr/bin/env python3
"""能力注册表（Capability Registry）：dreambuddy 可调度能力的唯一清单。

派生来源（不新增手工清单，component.yaml 仍是唯一源）：
  1. components/*/component.yaml 的 actions   → <component>.<action>   kind=run
     其中 aliases 展开为跨域短别名            → mobile.<command>       kind=mobile
  2. 19-DAL 只读数据桥                          → data.<tool>            kind=data
  3. 6-TRADING 只读状态桥（l1_trading MCP）      → trading.<tool>         kind=trading
  4. 云端只读控制面（HTTP MCP 缓存）             → cloud.<tool>           kind=cloud
  5. workflows/*.yaml                           → workflow.<name>        kind=workflow
  6. 定时任务只读                               → schedule.list          kind=schedule

用法:
    python3 tools/capabilities.py list [--json] [--kind run] [--safety write]
    python3 tools/capabilities.py show <id>
    python3 tools/capabilities.py check [--json]
    python3 tools/capabilities.py prompt [--json]
    python3 tools/capabilities.py export --out capabilities.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

ROOT = TOOLS_DIR.parent
REPO_ROOT = ROOT.parent
COMPONENTS = ROOT / "components"
WORKFLOWS = ROOT / "workflows"
MOBILE_COMPONENT = "mobile-reservation-assist"

KINDS = ("run", "mobile", "data", "trading", "cloud", "workflow", "schedule")
SAFETIES = ("read", "write", "ui")
SAFETY_ORDER = {"read": 0, "write": 1, "ui": 2, "irreversible": 3}

SCHEMA = "dreambuddy.capabilities.v2"
REGISTRY_ENV = "DREAMBUDDY_REGISTRY"
DEFAULT_REGISTRY = Path.home() / ".local/share/dreambuddy/registry/capabilities.json"

_CACHE: Dict[str, Any] = {"sig": None, "caps": [], "issues": []}


def _signature() -> tuple:
    paths = sorted(COMPONENTS.glob("*/component.yaml")) + sorted(WORKFLOWS.glob("*.yaml"))
    items = [(str(path), path.stat().st_mtime) for path in paths]
    for extra in (
        TOOLS_DIR / "data_bridge.py",
        TOOLS_DIR / "trading_bridge.py",
        TOOLS_DIR / "cloud_client.py",
        REPO_ROOT / "mcp_shells" / "l0_data" / "server.py",
        REPO_ROOT / "mcp_shells" / "l1_trading" / "server.py",
        COMPONENTS / MOBILE_COMPONENT / "skill" / "scripts" / "mra.py",
    ):
        items.append((str(extra), extra.stat().st_mtime if extra.exists() else 0))
    return tuple(items)


def _load(manifest: Path) -> dict:
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_caps() -> List[Dict[str, Any]]:
    caps: List[Dict[str, Any]] = []
    for manifest in sorted(COMPONENTS.glob("*/component.yaml")):
        data = _load(manifest)
        comp = data.get("name") or manifest.parent.name
        skill_dir = data.get("skill_dir") or "skill"
        for action in data.get("actions") or []:
            name = action.get("name")
            if not name:
                continue
            rel = action.get("script")
            script = manifest.parent / skill_dir / rel if rel else None
            ready = bool(script and script.exists())
            caps.append(
                {
                    "id": "{}.{}".format(comp, name),
                    "kind": "run",
                    "domain": str(data.get("family") or comp),
                    "component": comp,
                    "action": name,
                    "description": action.get("description", ""),
                    "when_to_use": action.get("when_to_use", ""),
                    "not_for": action.get("not_for", ""),
                    "safety": action.get("safety", "read"),
                    "args": [str(item) for item in action.get("args") or []],
                    "escalate": action.get("escalate") or {},
                    "aliases": [str(item) for item in action.get("aliases") or []],
                    "output": action.get("output", ""),
                    "params": action.get("params") or [],
                    "mcp": action.get("mcp") or {},
                    "script": str(script.relative_to(ROOT)) if script else "",
                    "source": str(manifest.relative_to(ROOT)),
                    "status": "ready" if ready else "missing_script",
                }
            )
    return caps


def _data_caps(issues: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    try:
        import data_bridge
    except Exception as exc:  # 数据桥不可用时注册表仍可用
        issues.append({"id": "data.*", "problem": "data_bridge 不可用：{}".format(exc)})
        return []
    caps = []
    try:
        tools = data_bridge.tools()
    except Exception as exc:
        issues.append({"id": "data.*", "problem": "读取数据工具失败：{}".format(exc)})
        return []
    for item in tools:
        caps.append(
            {
                "id": "data.{}".format(item["name"]),
                "kind": "data",
                "domain": "19-DAL",
                "tool": item["name"],
                "description": item.get("description", ""),
                "when_to_use": "只读查本地库指标 / 触发一次采集",
                "not_for": "禁止写库（写入口唯一在云端）",
                "safety": "read",
                "schema": item.get("inputSchema") or {},
                "params": [],
                "script": "tools/data_bridge.py",
                "source": "mcp_shells/l0_data/server.py",
                "status": "ready",
            }
        )
    return caps


def _trading_caps(issues: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """6-TRADING 只读状态：由 l1_trading MCP 投影，写动作 forward_signal 不注册。"""
    try:
        import trading_bridge
    except Exception as exc:  # 交易桥不可用时注册表仍可用
        issues.append({"id": "trading.*", "problem": "trading_bridge 不可用：{}".format(exc)})
        return []
    try:
        tools = trading_bridge.tools()
    except Exception as exc:
        issues.append({"id": "trading.*", "problem": "读取交易工具失败：{}".format(exc)})
        return []
    caps = []
    for item in tools:
        caps.append(
            {
                "id": "trading.{}".format(item["name"]),
                "kind": "trading",
                "domain": "6-TRADING",
                "tool": item["name"],
                "description": item.get("description", ""),
                "when_to_use": "只读查交易决策 / 信号总线 / 周期与约束 / 持仓余额",
                "not_for": "禁止在此下单或转发信号（执行走 l0.trade-exec 与人工审批）",
                "safety": "read",
                "schema": item.get("inputSchema") or {},
                "params": [],
                "script": "tools/trading_bridge.py",
                "source": "mcp_shells/l1_trading/server.py",
                "status": "ready",
            }
        )
    return caps


def _cloud_caps(issues: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """P5-2 云端只读控制面：只读缓存投影，构建期不联网。"""
    try:
        import cloud_client
    except Exception as exc:
        issues.append({"id": "cloud.*", "problem": "cloud_client 不可用：{}".format(exc)})
        return []
    conf = cloud_client.config()
    cached = cloud_client.tools(cache_only=True)
    if not cached and conf["complete"]:
        issues.append(
            {"id": "cloud.*", "problem": "已配置但无工具缓存（先 cloud tools --refresh）"}
        )
    caps = []
    for tool in cached:
        if tool.get("write"):
            continue
        caps.append(
            {
                "id": "cloud.{}".format(tool["name"]),
                "kind": "cloud",
                "domain": "cloud",
                "tool": tool["name"],
                "description": tool.get("description", ""),
                "when_to_use": "需要云端运行时事实（交易状态 / 云侧组件结果）且本地无等价能力",
                "not_for": "禁止经云端执行写动作；写仍走本地 plan/approve",
                "safety": "read",
                "schema": tool.get("inputSchema") or {},
                "params": [],
                "script": "tools/cloud_client.py",
                "source": conf["base"],
                "status": "ready",
            }
        )
    return caps


def _mobile_caps(run_caps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """跨域短别名（mobile.<command>）：由 component.yaml 的 aliases 展开，不再维护第二份清单。"""
    caps: List[Dict[str, Any]] = []
    for cap in run_caps:
        if cap["component"] != MOBILE_COMPONENT:
            continue
        for alias in cap.get("aliases") or []:
            command = alias.split(".", 1)[1]
            caps.append(
                {
                    "id": alias,
                    "kind": "mobile",
                    "domain": "手机AGENT",
                    "command": command,
                    "description": cap.get("description", ""),
                    "when_to_use": cap.get("when_to_use", ""),
                    "not_for": cap.get("not_for", ""),
                    "safety": cap.get("safety", "read"),
                    "escalate": cap.get("escalate") or {},
                    "params": cap.get("params") or [],
                    "mcp": {},
                    "alias_of": cap["id"],
                    "script": cap.get("script", ""),
                    "source": cap.get("source", ""),
                    "status": cap.get("status", "ready"),
                }
            )
    return caps


def _workflow_caps() -> List[Dict[str, Any]]:
    caps = []
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        data = _load(path)
        caps.append(
            {
                "id": "workflow.{}".format(path.stem),
                "kind": "workflow",
                "domain": "workflow",
                "workflow": path.stem,
                "description": data.get("name") or "工作流：{}（dry-run 预演）".format(path.stem),
                "when_to_use": "把多步动作按既有工作流预演",
                "not_for": "会话内只做 dry-run，不落盘",
                "safety": "read",
                "params": [],
                "script": str(path.relative_to(ROOT)),
                "source": str(path.relative_to(ROOT)),
                "status": "ready",
            }
        )
    return caps


def _schedule_caps() -> List[Dict[str, Any]]:
    return [
        {
            "id": "schedule.list",
            "kind": "schedule",
            "domain": "schedule",
            "command": "list",
            "description": "查看定时任务清单",
            "when_to_use": "确认已有定时任务",
            "not_for": "增删定时任务需显式命令（工具管理不可交给模型）",
            "safety": "read",
            "params": [],
            "script": "tools/jobs.py",
            "source": "tools/jobs.py",
            "status": "ready",
        }
    ]


def build(refresh: bool = False) -> List[Dict[str, Any]]:
    """构建（带 mtime 缓存）能力注册表。"""
    sig = _signature()
    if not refresh and _CACHE["sig"] == sig:
        return list(_CACHE["caps"])
    issues: List[Dict[str, str]] = []
    run_caps = _run_caps()
    caps = (
        run_caps
        + _data_caps(issues)
        + _trading_caps(issues)
        + _cloud_caps(issues)
        + _mobile_caps(run_caps)
        + _workflow_caps()
        + _schedule_caps()
    )
    _CACHE.update({"sig": sig, "caps": caps, "issues": issues})
    return list(caps)


def get(capability_id: str) -> Optional[Dict[str, Any]]:
    for cap in build():
        if cap["id"] == capability_id:
            return cap
    for cap in build():
        if cap.get("alias_of") == capability_id:
            return cap
    return None


def effective_safety(cap: Dict[str, Any], args: Any = None) -> str:
    """实际安全级 = 基础 safety 与 argv 命中 escalate 的较高者（调用方无法降级）。"""
    level = str(cap.get("safety") or "read")
    tokens = [str(item) for item in (args or [])]
    for flag, raised in (cap.get("escalate") or {}).items():
        if flag in tokens and SAFETY_ORDER.get(raised, 0) > SAFETY_ORDER.get(level, 0):
            level = str(raised)
    return level


def plan_for(capability_id: str, args: Any = None) -> Dict[str, Any]:
    """把能力 id 翻译成 execute_plan 认识的计划。"""
    cap = get(capability_id)
    if cap is None:
        raise ValueError("E_CAP：未注册的能力 {}".format(capability_id))
    reason = cap.get("description", "")
    if cap["kind"] == "run":
        return {
            "kind": "run",
            "component": cap["component"],
            "action": cap["action"],
            "args": [str(item) for item in (args or [])],
            "capability": cap["id"],
            "reason": reason,
        }
    if cap["kind"] == "data":
        return {
            "kind": "data",
            "tool": cap["tool"],
            "args": args if isinstance(args, dict) else {},
            "capability": cap["id"],
            "reason": reason,
        }
    if cap["kind"] == "cloud":
        return {
            "kind": "cloud",
            "tool": cap["tool"],
            "args": args if isinstance(args, dict) else {},
            "capability": cap["id"],
            "reason": reason,
        }
    if cap["kind"] == "trading":
        return {
            "kind": "trading",
            "tool": cap["tool"],
            "args": args if isinstance(args, dict) else {},
            "capability": cap["id"],
            "reason": reason,
        }
    if cap["kind"] == "mobile":
        return {
            "kind": "mobile",
            "command": cap["command"],
            "args": [str(item) for item in (args or [])],
            "capability": cap["id"],
            "reason": reason,
        }
    if cap["kind"] == "workflow":
        return {
            "kind": "workflow",
            "workflow": cap["workflow"],
            "capability": cap["id"],
            "reason": reason,
        }
    if cap["kind"] == "schedule":
        return {"kind": "schedule", "command": "list", "capability": cap["id"], "reason": reason}
    raise ValueError("E_CAP：未知能力类型 {}".format(cap["kind"]))


def mobile_read_commands() -> tuple:
    return tuple(cap["command"] for cap in build() if cap["kind"] == "mobile")


def legacy_catalog() -> Dict[str, Any]:
    """兼容旧路由提示词的结构（测试与既有调用方依赖这个形状）。"""
    caps = build()
    return {
        "component_actions": [
            {
                "component": cap["component"],
                "action": cap["action"],
                "description": cap["description"],
                "safety": cap["safety"],
            }
            for cap in caps
            if cap["kind"] == "run"
        ],
        "data_read": [
            {"name": cap["tool"], "schema": cap.get("schema") or {}, "safety": "read"}
            for cap in caps
            if cap["kind"] == "data"
        ],
        "trading_read": [
            {"name": cap["tool"], "schema": cap.get("schema") or {}, "safety": "read"}
            for cap in caps
            if cap["kind"] == "trading"
        ],
        "cloud_read": [
            {"name": cap["tool"], "schema": cap.get("schema") or {}, "safety": "read"}
            for cap in caps
            if cap["kind"] == "cloud"
        ],
        "mobile_read": [cap["command"] for cap in caps if cap["kind"] == "mobile"],
        "workflows": [cap["workflow"] for cap in caps if cap["kind"] == "workflow"],
        "schedule_read": [cap["command"] for cap in caps if cap["kind"] == "schedule"],
    }


def prompt_catalog() -> Dict[str, Any]:
    """给大模型看的最小目录：id + 类型 + 安全级 + 一句说明。"""
    items: List[Dict[str, Any]] = []
    for cap in build():
        item: Dict[str, Any] = {
            "id": cap["id"],
            "kind": cap["kind"],
            "safety": cap["safety"],
            "desc": cap.get("description", ""),
        }
        flags = [
            param.get("flag") or param.get("name")
            for param in cap.get("params") or []
            if param.get("flag") or param.get("name")
        ]
        if flags:
            item["params"] = flags
        if cap.get("alias_of"):
            item["alias_of"] = cap["alias_of"]
        items.append(item)
    return {"capabilities": items}


def summary() -> Dict[str, Any]:
    caps = build()
    by_kind: Dict[str, int] = {}
    by_safety: Dict[str, int] = {}
    for cap in caps:
        by_kind[cap["kind"]] = by_kind.get(cap["kind"], 0) + 1
        by_safety[cap["safety"]] = by_safety.get(cap["safety"], 0) + 1
    return {"total": len(caps), "by_kind": by_kind, "by_safety": by_safety}


def check() -> Dict[str, Any]:
    caps = build(refresh=True)
    issues: List[Dict[str, str]] = list(_CACHE.get("issues") or [])
    seen = set()
    for cap in caps:
        cid = cap.get("id") or ""
        if not cid:
            issues.append({"id": "<空>", "problem": "缺少 id"})
            continue
        if cid in seen:
            issues.append({"id": cid, "problem": "id 重复"})
        seen.add(cid)
        if cap.get("kind") not in KINDS:
            issues.append({"id": cid, "problem": "未知 kind：{}".format(cap.get("kind"))})
        if cap.get("safety") not in SAFETIES:
            issues.append({"id": cid, "problem": "未知 safety：{}".format(cap.get("safety"))})
        if cap.get("status") != "ready":
            issues.append({"id": cid, "problem": str(cap.get("status"))})
        if not cap.get("description"):
            issues.append({"id": cid, "problem": "缺少 description"})
        if cap.get("kind") == "run":
            for flag, level in (cap.get("escalate") or {}).items():
                if not str(flag).startswith("--"):
                    issues.append(
                        {"id": cid, "problem": "escalate 键必须是 --flag：{}".format(flag)}
                    )
                if level not in SAFETIES:
                    issues.append(
                        {"id": cid, "problem": "escalate 目标安全级非法：{}".format(level)}
                    )
        if cap.get("kind") == "mobile":
            target = cap.get("alias_of") or ""
            if not target:
                issues.append({"id": cid, "problem": "别名缺少 alias_of"})
            elif target not in seen:
                issues.append({"id": cid, "problem": "别名指向未注册动作：{}".format(target)})
    by_kind: Dict[str, int] = {}
    for cap in caps:
        by_kind[cap["kind"]] = by_kind.get(cap["kind"], 0) + 1
    return {"ok": not issues, "total": len(caps), "by_kind": by_kind, "issues": issues}


def registry_path() -> Path:
    raw = (os.environ.get(REGISTRY_ENV) or "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_REGISTRY


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def sources() -> List[Dict[str, str]]:
    """参与合并的来源清单（相对路径 + 内容指纹），供消费端判断索引是否陈旧。"""
    items: List[Dict[str, str]] = []
    for manifest in sorted(COMPONENTS.glob("*/component.yaml")):
        items.append(
            {
                "id": manifest.parent.name,
                "path": str(manifest.relative_to(ROOT)),
                "sha256": _sha256(manifest),
            }
        )
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        items.append(
            {
                "id": "workflow.{}".format(path.stem),
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256(path),
            }
        )
    for bridge in ("data_bridge.py", "trading_bridge.py", "cloud_client.py"):
        path = TOOLS_DIR / bridge
        if path.exists():
            items.append(
                {
                    "id": bridge.removesuffix(".py"),
                    "path": str(path.relative_to(ROOT)),
                    "sha256": _sha256(path),
                }
            )
    return items


def payload(refresh: bool = False) -> Dict[str, Any]:
    now = __import__("datetime").datetime.now().astimezone()
    caps = build(refresh=refresh)
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": summary(),
        "sources": sources(),
        "capabilities": caps,
    }


def export(path: Path) -> Dict[str, Any]:
    data = payload(refresh=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def sync(path: Optional[Path] = None) -> Dict[str, Any]:
    return export(path or registry_path())


def verify(path: Optional[Path] = None) -> Dict[str, Any]:
    """发布索引 vs 实时派生结果：缺失跳过，内容不一致即漂移。"""
    target = path or registry_path()
    if not target.is_file():
        return {"ok": True, "skipped": True, "path": str(target), "reason": "索引未发布"}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "path": str(target), "reason": "索引不可读：{}".format(exc)}
    if data.get("schema") != SCHEMA:
        return {
            "ok": False,
            "path": str(target),
            "reason": "索引 schema 不匹配（{} != {}）".format(data.get("schema"), SCHEMA),
        }
    fresh = build(refresh=True)
    if data.get("capabilities") != fresh:
        old_ids = {cap.get("id") for cap in data.get("capabilities") or []}
        new_ids = {cap.get("id") for cap in fresh}
        return {
            "ok": False,
            "path": str(target),
            "reason": "能力清单漂移（新增 {} / 移除 {}）".format(
                sorted(new_ids - old_ids)[:3], sorted(old_ids - new_ids)[:3]
            ),
        }
    if data.get("sources") != sources():
        return {"ok": False, "path": str(target), "reason": "来源文件指纹漂移"}
    return {
        "ok": True,
        "skipped": False,
        "path": str(target),
        "generated_at": data.get("generated_at"),
        "total": len(fresh),
    }


def _print_list(caps: List[Dict[str, Any]]) -> None:
    print("能力注册表（{} 项）".format(len(caps)))
    for cap in caps:
        alias = "  → {}".format(cap["alias_of"]) if cap.get("alias_of") else ""
        print(
            "  {:<44} [{}/{}] {}{}".format(
                cap["id"], cap["kind"], cap.get("safety", "?"), cap.get("description", ""), alias
            )
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="dreambuddy 能力注册表")
    sub = parser.add_subparsers(dest="cmd")
    p_list = sub.add_parser("list", help="列出已注册能力")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--kind", choices=KINDS)
    p_list.add_argument("--safety", choices=SAFETIES)
    p_show = sub.add_parser("show", help="查看单个能力")
    p_show.add_argument("capability_id")
    p_show.add_argument("--json", action="store_true")
    p_check = sub.add_parser("check", help="校验注册表（重复 id / 缺脚本 / 缺说明）")
    p_check.add_argument("--json", action="store_true")
    p_prompt = sub.add_parser("prompt", help="输出给大模型的路由目录")
    p_prompt.add_argument("--json", action="store_true")
    p_export = sub.add_parser("export", help="导出注册表快照")
    p_export.add_argument("--out", default="")
    p_sync = sub.add_parser(
        "sync", help="生成并发布合并索引（默认 ~/.local/share/dreambuddy/registry）"
    )
    p_sync.add_argument("--out", default="")
    p_verify = sub.add_parser("verify", help="校验已发布索引与实时派生结果是否一致")
    p_verify.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "show":
        cap = get(args.capability_id)
        if cap is None:
            print("E_CAP：未注册的能力 {}".format(args.capability_id))
            return 1
        print(json.dumps(cap, ensure_ascii=False, indent=2) if args.json else _format_cap(cap))
        return 0
    if args.cmd == "check":
        result = check()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(
                "能力注册表校验：{}（{} 项）".format(
                    "通过" if result["ok"] else "有问题", result["total"]
                )
            )
            for key, count in sorted(result["by_kind"].items()):
                print("  {}: {}".format(key, count))
            for issue in result["issues"]:
                print("  ✗ {} {}".format(issue["id"], issue["problem"]))
        return 0 if result["ok"] else 2
    if args.cmd == "prompt":
        catalog = prompt_catalog()
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "sync":
        out = Path(args.out).expanduser() if args.out else registry_path()
        data = sync(out)
        print(
            "已发布 {} 项能力 → {}（schema {}）".format(
                data["summary"]["total"], out, data["schema"]
            )
        )
        return 0
    if args.cmd == "verify":
        result = verify()
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result.get("skipped"):
            print("SKIP：{}（{}）".format(result["reason"], result["path"]))
        elif result["ok"]:
            print(
                "OK：索引与实时注册表一致（{} 项 · {}）".format(
                    result["total"], result["generated_at"]
                )
            )
        else:
            print("FAIL：{}（{}）".format(result["reason"], result["path"]))
        return 0 if result["ok"] else 1
    if args.cmd == "export":
        out = Path(args.out).expanduser() if args.out else ROOT / "capabilities.json"
        payload = export(out)
        print("已导出 {} 项能力 → {}".format(payload["summary"]["total"], out))
        return 0

    caps = build()
    if getattr(args, "kind", None):
        caps = [cap for cap in caps if cap["kind"] == args.kind]
    if getattr(args, "safety", None):
        caps = [cap for cap in caps if cap.get("safety") == args.safety]
    if getattr(args, "json", False):
        print(json.dumps(caps, ensure_ascii=False, indent=2))
    else:
        _print_list(caps)
    return 0


def _format_cap(cap: Dict[str, Any]) -> str:
    lines = ["{}  [{} · {}]".format(cap["id"], cap["kind"], cap.get("safety", "?"))]
    if cap.get("description"):
        lines.append("  {}".format(cap["description"]))
    for key in ("when_to_use", "not_for", "script", "source", "status", "alias_of"):
        if cap.get(key):
            lines.append("  {}: {}".format(key, cap[key]))
    flags = [p.get("flag") for p in cap.get("params") or [] if p.get("flag")]
    if flags:
        lines.append("  params: {}".format(" ".join(flags)))
    if cap.get("mcp"):
        lines.append("  mcp: {}".format(json.dumps(cap["mcp"], ensure_ascii=False)))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
