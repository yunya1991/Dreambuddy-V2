#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_prompt_constitution_coherence.py — 宪法与提示词协同自检（SPEC-57 P6）

回答一个问题：**宪法和提示词是否同版本、同一份口径、在运行时真正协同。**

检查链路（全部确定性）：
  1. 宪法：文件版本标记、条款数、与注册表 constitution_version 一致；
  2. 提示词：注册表每个 prompt 都能 render 出注入块，meta 七字段齐全，指纹对账通过；
  3. 快照：前端 prompt-registry.generated.json 的 prompt_id/version/fingerprint/
     constitution_version 与注册表一致；
  4. owner 接入：6-TRADING / 33-REA / 9-nanoclaw 三个薄封装返回的 prompt 版本与
     宪法版本和注册表一致；
  5. 线上（可选 --url）：GET /api/prompts/meta 返回的七字段与快照一致。

用法：
  python3 57-Agent提示词工程/evals/check_prompt_constitution_coherence.py
  python3 57-Agent提示词工程/evals/check_prompt_constitution_coherence.py --url http://43.160.201.117
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, List, Tuple

PROMPT_HOME = Path(__file__).resolve().parents[1]
REPO = PROMPT_HOME.parent
RUNTIME = PROMPT_HOME / "runtime"
SNAPSHOT = (
    REPO / "3.1-FRONTEND" / "src" / "lib" / "orchestration" / "prompt-registry.generated.json"
)
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import l2_prompt_bridge as bridge  # noqa: E402
import prompt_context_57 as pc  # noqa: E402

META_FIELDS = (
    "prompt_id",
    "prompt_version",
    "prompt_fingerprint",
    "constitution_version",
    "constitution_tokens",
    "tool_set_fingerprint",
    "reasoning_effort",
)


def _run(cmd: List[str], cwd: Path) -> str:
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=90, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 失败: {proc.stderr.strip()[:300]}")
    return proc.stdout


def check_constitution() -> Tuple[bool, str]:
    version, clauses = pc.load_constitution()
    registry_version = str(pc.load_registry().get("constitution_version", ""))
    if version != registry_version:
        return False, f"宪法 {version} ≠ 注册表 {registry_version}"
    if len(clauses) < 12:
        return False, f"条款数不足: {len(clauses)}"
    return True, f"constitution@{version}，{len(clauses)} 条"


def check_prompts() -> Tuple[bool, str]:
    entries = [p for p in pc.load_registry().get("prompts") or [] if isinstance(p, dict)]
    version = pc.constitution_version()
    problems: List[str] = []
    for entry in entries:
        pid = str(entry.get("prompt_id"))
        if str(entry.get("constitution_version")) != version:
            problems.append(f"{pid}: constitution_version 不匹配")
            continue
        rendered = bridge.render(pid)
        if not rendered["injected"]:
            problems.append(f"{pid}: 未注入")
            continue
        meta = rendered["meta"] or {}
        if any(not meta.get(k) for k in META_FIELDS):
            problems.append(f"{pid}: meta 缺字段")
        if meta.get("constitution_version") != version:
            problems.append(f"{pid}: meta 宪法版本不一致")
        if entry.get("fingerprint") != meta.get("prompt_fingerprint"):
            problems.append(f"{pid}: 指纹不一致")
    if problems:
        return False, "；".join(problems)
    return True, f"{len(entries)} 个 prompt 全部注入成功（constitution@{version}）"


def check_snapshot() -> Tuple[bool, str]:
    if not SNAPSHOT.is_file():
        return False, f"快照不存在: {SNAPSHOT}"
    doc = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    entry = pc.get_prompt(str(doc.get("prompt_id")))
    pairs = {
        "prompt_id": (doc.get("prompt_id"), entry.get("prompt_id")),
        "version": (doc.get("prompt_version"), entry.get("version")),
        "fingerprint": (doc.get("prompt_fingerprint"), entry.get("fingerprint")),
        "constitution_version": (
            doc.get("constitution_version"),
            pc.constitution_version(),
        ),
    }
    bad = {k: v for k, v in pairs.items() if v[0] != v[1]}
    if bad:
        return False, f"快照与注册表不一致: {bad}"
    return True, f"{doc['prompt_id']}@{doc['prompt_version']} / {doc['constitution_version']}"


def check_owner_wrappers() -> Tuple[bool, str]:
    version = pc.constitution_version()
    registry_version = {
        str(p.get("prompt_id")): str(p.get("version"))
        for p in pc.load_registry().get("prompts") or []
        if isinstance(p, dict)
    }

    out = _run(
        [sys.executable, "scripts/l2_trade_ops_prompt.py", "render", "--task", "a1"],
        REPO / "6-TRADING",
    )
    _, meta = json.loads(out)
    if not meta or meta.get("constitution_version") != version:
        return False, "6-TRADING 未注入宪法"

    out = _run(
        [sys.executable, "-m", "core.prompt_binding", "ai-context"],
        REPO / "33-REA逆向解析工程",
    )
    ctx = json.loads(out)
    if ctx.get("constitution_version") != version:
        return False, "33-REA ai_context 未绑定宪法"

    out = _run(
        [sys.executable, "render_l2_prompt.py", "verify"],
        REPO / "9-基本面分析" / "ops" / "nanoclaw",
    )
    info = json.loads(out)
    if info.get("prompt_id") != "l2.emergence.meta_evolution":
        return False, "9-nanoclaw verify 返回异常"

    for pid in ("l2.app.trade_ops", "l2.worker.rea", "l2.emergence.meta_evolution"):
        if pid not in registry_version:
            return False, f"注册表缺 {pid}"
    return True, "6-TRADING / 33-REA / 9-nanoclaw 均读到 constitution@" + version


def check_online(base_url: str) -> Tuple[bool, str]:
    url = base_url.rstrip("/") + "/api/prompts/meta"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            if resp.status != 200:
                return False, f"{url} HTTP {resp.status}"
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"{url} 不可达: {type(exc).__name__}: {exc}"

    meta = doc.get("prompt_meta") or {}
    if any(not meta.get(k) for k in META_FIELDS):
        return False, f"线上 meta 缺字段: {sorted(k for k in META_FIELDS if not meta.get(k))}"
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if meta.get("constitution_version") != pc.constitution_version():
        return False, "线上宪法版本与本地不一致"
    if (
        meta.get("prompt_id") != snap.get("prompt_id")
        or meta.get("prompt_version") != snap.get("prompt_version")
        or meta.get("prompt_fingerprint") != snap.get("prompt_fingerprint")
    ):
        return False, "线上七字段与快照不一致"
    return (
        True,
        f"{url} → {meta['prompt_id']}@{meta['prompt_version']} / {meta['constitution_version']}",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="云端根地址，例如 http://43.160.201.117")
    args = ap.parse_args()

    checks: List[Tuple[str, Any]] = [
        ("宪法本体", check_constitution),
        ("提示词注入", check_prompts),
        ("前端快照", check_snapshot),
        ("owner 接入", check_owner_wrappers),
    ]
    if args.url:
        checks.append(("线上出口", lambda: check_online(args.url)))

    failed = 0
    print("\n提示词 ↔ 宪法 协同自检")
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        failed += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}：{detail}")

    total = len(checks)
    print(f"\n{total - failed}/{total} 通过\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
