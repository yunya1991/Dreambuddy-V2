#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_l2_prompt.py — 9 基本面 nanoclaw 的 l2.emergence.meta_evolution 接入（SPEC-57 §8 P6）

nanoclaw 由外部 CLI 运行时按 `prompts/<swarm>_prompt.md` 约定消费提示词，
仓库无法直接改外部运行时，因此这里提供**可执行的前置渲染**：

  1. render：把注册资产 + 宪法/人格注入块写成本地渲染产物（含 meta 旁车）；
  2. gate  ：对体检报告 JSON 做 C-01..C-12 出口校验；
  3. verify：指纹/评测集/契约自查。

jobs.local.json 的 meta_evolution_monitor_hourly 已把本脚本列为第 0 步。

用法：
  python3 ops/nanoclaw/render_l2_prompt.py render
  python3 ops/nanoclaw/render_l2_prompt.py gate --report <path.json>
  python3 ops/nanoclaw/render_l2_prompt.py verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RUNTIME = REPO / "57-Agent提示词工程" / "runtime"
PROMPT_ID = "l2.emergence.meta_evolution"
# 渲染产物必须落在注册资产（prompts/，tree 指纹范围）之外，否则会触发 E_CONSTITUTION_DRIFT
DEFAULT_OUT = HERE / "cache" / "l2_prompt" / "meta_evolution_prompt.rendered.md"
DEFAULT_META = HERE / "cache" / "l2_prompt" / "meta_evolution_prompt.rendered.meta.json"

if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

_IMPORT_ERROR = ""


def _bridge():
    try:
        import l2_prompt_bridge

        return l2_prompt_bridge
    except Exception as exc:  # noqa: BLE001 — 57 不可用不得阻断 nanoclaw
        global _IMPORT_ERROR
        _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def render(out: Path = DEFAULT_OUT, meta_out: Path = DEFAULT_META) -> int:
    bridge = _bridge()
    if bridge is None:
        print(json.dumps({"error": _IMPORT_ERROR}, ensure_ascii=False))
        return 1
    rendered = bridge.render(PROMPT_ID, include_asset=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered["system_prompt"] + "\n", encoding="utf-8")
    meta_out.write_text(
        json.dumps(
            {
                "prompt_id": rendered["prompt_id"],
                "prompt_version": rendered["version"],
                "injected": rendered["injected"],
                "meta": rendered["meta"],
                "source": DEFAULT_OUT.name,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(out),
                "meta_out": str(meta_out),
                "chars": len(rendered["system_prompt"]),
                "injected": rendered["injected"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if rendered["injected"] else 1


def gate(report: Path) -> int:
    bridge = _bridge()
    if bridge is None:
        print(json.dumps({"error": _IMPORT_ERROR}, ensure_ascii=False))
        return 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    result = bridge.gate(PROMPT_ID, payload, evidence=str(payload.get("evidence") or "partial"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") != "deny" else 1


def verify() -> int:
    bridge = _bridge()
    if bridge is None:
        print(json.dumps({"error": _IMPORT_ERROR}, ensure_ascii=False))
        return 1
    print(json.dumps(bridge.verify(PROMPT_ID), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["render", "gate", "verify"])
    ap.add_argument("--report", default="")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    if args.cmd == "render":
        return render(Path(args.out))
    if args.cmd == "gate":
        if not args.report:
            print("gate 需要 --report", file=sys.stderr)
            return 2
        return gate(Path(args.report))
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
