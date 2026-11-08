#!/usr/bin/env python3
"""check_mcp_tool_drift — 注册表 ↔ 壳代码 tools/list 漂移门禁（P0）

做法：对注册表中 status ∈ {available, degraded} 且非 http 的每个壳，以
stdio 真实拉起 shell_path，发送 initialize + tools/list，把返回的工具名与
注解跟 mcp_capabilities.yaml 逐项比对。

判据（与 SPEC-L0-MCP-PACKAGING §3.7 对齐）：
  - 代码多出工具（extra）      → 未登记即上线，ERR
  - 注册表多出工具（missing）  → 注册表凭空发明，ERR
  - readOnlyHint 不一致        → 读写语义漂移，ERR
  - 壳无法拉起                 → 默认 WARN；--strict 升 ERR

退出码：0 = 无漂移；1 = 有漂移/严格模式下拉起失败；2 = 环境错误。

用法：
  python "47-MCP管理系统/registry/scripts/check_mcp_tool_drift.py"
  python .../check_mcp_tool_drift.py --quiet --json
  python .../check_mcp_tool_drift.py --shell l0.data.mcp --strict
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("ERR: pyyaml 未安装 — pip install pyyaml")
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_DEFAULT = Path(
    os.environ.get(
        "DREAMBUDDY_MCP_REGISTRY",
        str(REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"),
    )
)


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK，统一切到 UTF-8 避免箭头/中文输出崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


PROBEABLE_STATUS = ("available", "degraded")
PROTOCOL_VERSION = "2024-11-05"


def load_registry(registry_path: Path) -> Dict[str, Any]:
    with open(registry_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def probeable_shells(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for shell in doc.get("shells") or []:
        if not isinstance(shell, dict):
            continue
        if shell.get("status") not in PROBEABLE_STATUS:
            continue
        if shell.get("transport") == "http" or not shell.get("shell_path"):
            continue
        out.append(shell)
    return out


def probe_shell(
    shell: Dict[str, Any],
    repo_root: Path = REPO_ROOT,
    timeout: float = 30.0,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """stdio 拉起壳 → initialize + tools/list。返回 (ok, tools, error)。"""
    path = repo_root / str(shell.get("shell_path") or "")
    if not path.exists():
        return False, [], f"shell_path 不存在: {path}"

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("ANONYMIZED_TELEMETRY", "False")

    payload = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-drift-check", "version": "0.1"},
                },
            }
        )
        + "\n"
    )
    payload += json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"

    proc = subprocess.Popen(
        [sys.executable, str(path)],
        cwd=str(repo_root),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, [], f"探测超时（{timeout:.0f}s）"

    responses: Dict[Any, Dict[str, Any]] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") in (1, 2):
            responses[msg["id"]] = msg

    if 1 not in responses:
        tail = "\n".join(err.strip().splitlines()[-5:])
        return False, [], f"initialize 无响应（rc={proc.returncode}）: {tail}"

    tools = (responses.get(2, {}).get("result") or {}).get("tools") or []
    tools = [t for t in tools if isinstance(t, dict) and t.get("name")]
    return True, tools, ""


def diff_tools(
    shell: Dict[str, Any], actual_tools: List[Dict[str, Any]]
) -> Tuple[List[str], List[str], List[Tuple[str, bool, bool]]]:
    """返回 (extra, missing, annotation_mismatch)。"""
    reg = {
        t["name"]: t for t in (shell.get("tools") or []) if isinstance(t, dict) and t.get("name")
    }
    act = {t["name"]: t for t in actual_tools if t.get("name")}
    extra = sorted(set(act) - set(reg))
    missing = sorted(set(reg) - set(act))

    ann_mismatch: List[Tuple[str, bool, bool]] = []
    for name in sorted(set(reg) & set(act)):
        reg_ann = (reg[name].get("annotations") or {}).get("readOnlyHint")
        act_ann = (act[name].get("annotations") or {}).get("readOnlyHint")
        if reg_ann is not None and act_ann is not None and bool(reg_ann) != bool(act_ann):
            ann_mismatch.append((name, bool(reg_ann), bool(act_ann)))
    return extra, missing, ann_mismatch


def _drift_detail(item: Dict[str, Any]) -> str:
    bits: List[str] = []
    if item["extra"]:
        bits.append(f"未登记={item['extra']}")
    if item["missing"]:
        bits.append(f"注册表多出={item['missing']}")
    for name, reg_v, act_v in item["annotation_mismatch"]:
        bits.append(f"{name}.readOnlyHint 注册表={reg_v} 代码={act_v}")
    return "；".join(bits)


def run(
    registry_path: Path = REGISTRY_DEFAULT,
    *,
    quiet: bool = False,
    json_output: bool = False,
    strict: bool = False,
    only_shells: Optional[List[str]] = None,
    timeout: float = 30.0,
) -> int:
    try:
        doc = load_registry(registry_path)
    except Exception as exc:
        print(f"ERR: 读取注册表失败 {registry_path}: {exc}")
        return 2

    shells = probeable_shells(doc)
    if only_shells:
        wanted = set(only_shells)
        shells = [s for s in shells if s.get("shell_id") in wanted]

    results: List[Dict[str, Any]] = []
    drifted = 0
    launch_failed = 0
    started = time.time()

    for shell in shells:
        sid = shell.get("shell_id", "<missing>")
        ok, tools, error = probe_shell(shell, timeout=timeout)
        item: Dict[str, Any] = {
            "shell_id": sid,
            "ok": ok,
            "actual_tools": [t["name"] for t in tools],
            "registry_tools": [t.get("name") for t in (shell.get("tools") or [])],
            "extra": [],
            "missing": [],
            "annotation_mismatch": [],
            "error": error,
        }
        if ok:
            extra, missing, ann = diff_tools(shell, tools)
            item.update(extra=extra, missing=missing, annotation_mismatch=ann)
            if extra or missing or ann:
                drifted += 1
        else:
            launch_failed += 1
        results.append(item)

    elapsed = time.time() - started

    if json_output:
        print(
            json.dumps(
                {
                    "registry": str(registry_path),
                    "checked": len(results),
                    "drifted": drifted,
                    "launch_failed": launch_failed,
                    "elapsed_s": round(elapsed, 3),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif quiet:
        # CI 模式：只输出失败项，保证红灯日志可定位
        for item in results:
            if not item["ok"]:
                print(f"[WARN] {item['shell_id']}: {item['error']}", file=sys.stderr)
            elif item["extra"] or item["missing"] or item["annotation_mismatch"]:
                print(f"[ERR ] {item['shell_id']}: {_drift_detail(item)}", file=sys.stderr)
    else:
        print(f"MCP tools/list ↔ 注册表漂移检查（{registry_path.name}）")
        for item in results:
            sid = item["shell_id"]
            if not item["ok"]:
                print(f"  [WARN] {sid:<24} 无法拉起: {item['error']}")
                continue
            if item["extra"] or item["missing"] or item["annotation_mismatch"]:
                print(f"  [ERR ] {sid:<24} {_drift_detail(item)}")
            else:
                print(f"  [ OK ] {sid:<24} {len(item['actual_tools'])} 工具")
        print(
            f"结果: {drifted} 漂移 / {launch_failed} 无法拉起 / "
            f"{len(results)} 检查 · {elapsed:.2f}s"
        )

    if drifted:
        return 1
    if strict and launch_failed:
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdio()
    ap = argparse.ArgumentParser(description="MCP 注册表 ↔ 壳代码工具面漂移门禁")
    ap.add_argument("--registry", default=str(REGISTRY_DEFAULT))
    ap.add_argument("--quiet", action="store_true", help="只输出失败摘要")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--strict", action="store_true", help="壳无法拉起也视为失败")
    ap.add_argument("--shell", action="append", help="只检查指定 shell_id（可重复）")
    ap.add_argument("--timeout", type=float, default=30.0, help="单壳探测超时秒数")
    args = ap.parse_args(argv)
    return run(
        Path(args.registry),
        quiet=args.quiet,
        json_output=args.json,
        strict=args.strict,
        only_shells=args.shell,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
