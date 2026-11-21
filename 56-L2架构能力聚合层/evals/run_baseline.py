# -*- coding: utf-8 -*-
"""run_baseline.py — DeepSeek 单模型基线（8 题 × 六维，分列不合成总分）

依据 SPEC §6。
输入:
  - evals/scenarios.yaml（baseline=true, must_have_facts[].match）
  - evals/out/evidence.jsonl（P1 系统答案 / P1b、P2 工具命中）
输出:
  - evals/out/baseline_comparison.json
  - evals/out/baseline_comparison.md
用法:
  python3 evals/run_baseline.py [--max-calls 40]
退出码: 0 = 完成；1 = 配置缺失
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probes import EVALS_DIR, OUT_DIR  # noqa: E402

ENV_PATH = EVALS_DIR.parents[1] / "1-ARCHITECTURE" / "dreamos" / ".env"
EVIDENCE_PATH = OUT_DIR / "evidence.jsonl"
SYSTEM_PROMPT = (
    "你是一个金融分析助手。仅基于你的既有知识作答，不使用任何外部工具或实时数据。"
    "若某项数据你无法确知，请明确说明无法获取，禁止编造具体数值。"
    "回答简洁、结构化。"
)
MAX_TOKENS = 900


def _load_env() -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def _load_scenarios() -> List[Dict[str, Any]]:
    import yaml

    with open(EVALS_DIR / "scenarios.yaml", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("scenarios") or []


def _load_evidence() -> List[Dict[str, Any]]:
    if not EVIDENCE_PATH.exists():
        return []
    return [
        json.loads(x) for x in EVIDENCE_PATH.read_text(encoding="utf-8").splitlines() if x.strip()
    ]


def _deepseek_chat(cfg: Dict[str, str], question: str) -> Dict[str, Any]:
    url = f"{cfg['DEEPSEEK_BASE_URL'].rstrip('/')}/chat/completions"
    payload = {
        "model": cfg["DEEPSEEK_MODEL"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['DEEPSEEK_API_KEY']}",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
        latency = (time.perf_counter() - t0) * 1000.0
        choice = (body.get("choices") or [{}])[0]
        return {
            "ok": True,
            "answer": (choice.get("message") or {}).get("content") or "",
            "usage": body.get("usage") or {},
            "latency_ms": round(latency, 3),
        }
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "answer": "",
            "usage": {},
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _fact_rate(facts: List[Dict[str, Any]], answer: str) -> Optional[float]:
    if not facts:
        return None
    if not answer:
        return 0.0
    hit = 0
    for f in facts:
        tokens = f.get("match") or []
        if not tokens:
            continue
        if any(str(tok) in answer for tok in tokens):
            hit += 1
    return round(hit / len(facts), 3)


def _latency_score(ms: Optional[float]) -> Optional[float]:
    if ms is None:
        return None
    if ms < 5_000:
        return 5.0
    if ms < 15_000:
        return 4.0
    if ms < 30_000:
        return 3.0
    if ms < 60_000:
        return 2.0
    if ms < 120_000:
        return 1.0
    return 0.0


def _token_score(tokens: Optional[int]) -> Optional[float]:
    if tokens is None:
        return None
    if tokens < 1_000:
        return 5.0
    if tokens < 3_000:
        return 4.0
    if tokens < 6_000:
        return 3.0
    if tokens < 12_000:
        return 2.0
    return 1.0


def _system_tool_hits(ev: List[Dict[str, Any]], sid: str) -> List[str]:
    pairs = set()
    for r in ev:
        if r.get("scenario_id") != sid:
            continue
        if r.get("kind") == "scenario":
            for c in r.get("tool_calls") or []:
                if c.get("shell_id") and c.get("shell_id") != "?":
                    pairs.add(f"{c['shell_id']}:{c['tool']}")
        elif r.get("kind") in ("tool_call", "tool_sweep"):
            if r.get("shell_id") and r.get("shell_id") != "?":
                pairs.add(f"{r['shell_id']}:{r['tool']}")
    return sorted(pairs)


def _system_answer(ev: List[Dict[str, Any]], sid: str) -> Optional[Dict[str, Any]]:
    rows = [
        r
        for r in ev
        if r.get("scenario_id") == sid and r.get("entry") == "P1" and r.get("kind") == "scenario"
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("ts", ""))
    return rows[-1]


def build_comparison(max_calls: int = 40) -> Dict[str, Any]:
    cfg = _load_env()
    missing = [
        k for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL") if not cfg.get(k)
    ]
    if missing:
        return {"ok": False, "error": f"missing env: {missing}"}

    scenarios = [s for s in _load_scenarios() if s.get("baseline")]
    ev = _load_evidence()
    calls = 0
    rows: List[Dict[str, Any]] = []

    for sc in scenarios:
        sid = sc["id"]
        q = str(sc.get("input") or "")
        facts = sc.get("must_have_facts") or []
        expected = sc.get("expected_tools") or []

        sys_rec = _system_answer(ev, sid)
        sys_answer = (sys_rec or {}).get("answer") or ""
        sys_latency = (sys_rec or {}).get("latency_ms")
        hits = _system_tool_hits(ev, sid)

        # DeepSeek 基线（每题 1 次；失败不重试以控预算）
        base: Dict[str, Any] = {"ok": False, "answer": "", "usage": {}, "latency_ms": None}
        if calls < max_calls:
            base = _deepseek_chat(cfg, q)
            calls += 1

        sys_fact = _fact_rate(facts, sys_answer)
        base_fact = _fact_rate(facts, base.get("answer") or "")
        base_tokens = (base.get("usage") or {}).get("total_tokens")

        sys_d1 = float(min(5, len(hits))) if hits else 0.0
        base_d1 = 0.0
        sys_d3 = (
            5.0
            if any(r.get("stages") for r in ev if r.get("scenario_id") == sid)
            else (3.0 if hits else 1.0)
        )
        base_d3 = 0.0
        sys_d4 = (
            5.0
            if (sys_rec and sys_rec.get("trace_id") and sys_answer)
            else (3.0 if (sys_rec and sys_rec.get("trace_id")) else 0.0)
        )
        base_d4 = 0.0

        rows.append(
            {
                "scenario_id": sid,
                "question": q,
                "system": {
                    "answer": sys_answer[:2000],
                    "answer_available": bool(sys_answer),
                    "tools_hit": hits,
                    "expected_tools": expected,
                    "latency_ms": sys_latency,
                    "d1_capability_coverage": sys_d1,
                    "d2_correctness": None if sys_fact is None else round(5 * sys_fact, 2),
                    "d3_scheduling": sys_d3,
                    "d4_evidence": sys_d4,
                    "d5_latency": _latency_score(sys_latency),
                    "d6_token_cost": None,
                },
                "baseline": {
                    "answer": (base.get("answer") or "")[:2000],
                    "answer_available": bool(base.get("answer")),
                    "usage": base.get("usage"),
                    "latency_ms": base.get("latency_ms"),
                    "d1_capability_coverage": base_d1,
                    "d2_correctness": None if base_fact is None else round(5 * base_fact, 2),
                    "d3_scheduling": base_d3,
                    "d4_evidence": base_d4,
                    "d5_latency": _latency_score(base.get("latency_ms")),
                    "d6_token_cost": _token_score(base_tokens),
                },
            }
        )

    summary = {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "deepseek_calls": calls,
        "call_budget": max_calls,
        "questions": len(rows),
        "latency_note": "系统侧时延为 P1 单次实测（n=1），非推断统计；DeepSeek 侧同为 n=1",
        "d2_method": "关键词命中率（must_have_facts[].match）× 5，非 LLM 评审",
        "d6_note": "系统侧 token 用量未在产品链 SSE 中暴露，记 null",
        "rows": rows,
    }
    return summary


def _render_md(data: Dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"# DeepSeek 基线\n\n失败: {data.get('error')}\n"
    lines = [
        "# DeepSeek 单模型基线对比（8 题 × 六维，分列）",
        "",
        f"- DeepSeek 调用次数: {data['deepseek_calls']} / 上限 {data['call_budget']}",
        f"- 时延口径: {data['latency_note']}",
        f"- D2 口径: {data['d2_method']}",
        f"- D6 口径: {data['d6_note']}",
        "",
        "| 题 | D1 能力覆盖<br>sys/base | D2 正确性<br>sys/base | D3 调度<br>sys/base | D4 证据<br>sys/base | D5 时延分<br>sys/base | D6 token<br>sys/base |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in data["rows"]:
        s, b = r["system"], r["baseline"]

        def _fmt(v: Any) -> str:
            return "n/a" if v is None else f"{v:g}" if isinstance(v, float) else str(v)

        lines.append(
            f"| {r['scenario_id']} | {_fmt(s['d1_capability_coverage'])}/{_fmt(b['d1_capability_coverage'])} "
            f"| {_fmt(s['d2_correctness'])}/{_fmt(b['d2_correctness'])} "
            f"| {_fmt(s['d3_scheduling'])}/{_fmt(b['d3_scheduling'])} "
            f"| {_fmt(s['d4_evidence'])}/{_fmt(b['d4_evidence'])} "
            f"| {_fmt(s['d5_latency'])}/{_fmt(b['d5_latency'])} "
            f"| {_fmt(s['d6_token_cost'])}/{_fmt(b['d6_token_cost'])} |"
        )
    lines += [
        "",
        "## 原始时延/token",
        "",
        "| 题 | sys 时延(ms) | base 时延(ms) | base tokens | 系统工具命中 |",
        "|---|---|---|---|---|",
    ]
    for r in data["rows"]:
        s, b = r["system"], r["baseline"]
        lines.append(
            f"| {r['scenario_id']} | {s['latency_ms']} | {b['latency_ms']} "
            f"| {(b.get('usage') or {}).get('total_tokens')} | {', '.join(s['tools_hit']) or '-'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=40)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = build_comparison(max_calls=args.max_calls)
    (OUT_DIR / "baseline_comparison.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "baseline_comparison.md").write_text(_render_md(data), encoding="utf-8")
    if not data.get("ok"):
        print(data.get("error"))
        return 1
    print(f"完成 {data['questions']} 题，DeepSeek 调用 {data['deepseek_calls']} 次")
    print(f"写入: {OUT_DIR/'baseline_comparison.json'} / .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
