#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_prompt_ab.py — 57 提示词 A/B 多轮回测（只读 prompt，不改运行时）

目的（SPEC-57 §8 P1 前置验证）：
  同一模型、同一用例，比较「现行 prompt」（A 臂）与「现行 prompt + 宪法 P0 段」（B 臂），
  判断宪法注入是带来可测收益，还是只增加成本。

两类任务（`--task`）：
  intent   结构化分类（意图识别 55 例，指标=准确率）；预期天花板效应
  analysis 开放分析（56 评测集 baseline 场景 8 题，指标=事实命中率 + 违例率）；宪法主战场

设计要点：
  1. A/B 唯一差异是 system prompt 尾部是否注入宪法段，其他全部相同。
  2. 意图用例复用 `1-ARCHITECTURE/intent-recognition-spec/test-cases.json`；
     分析用例复用 `56-L2架构能力聚合层/evals/scenarios.yaml` 中 `baseline: true` 的场景。
  3. 宪法段**从 PROMPT_CONSTITUTION.md 现场提取**，不复制正文（ADR-02 单一事实源）：
     full = §3 全部 C-01..C-12；lite = C-04/C-05/C-06/C-08/C-11/C-12。
  4. 护栏：json_ok 不下降、avg_tokens 涨幅 ≤ 40%。

用法：
  python3 57-Agent提示词工程/evals/run_prompt_ab.py --task intent --round 1 --arm full
  python3 57-Agent提示词工程/evals/run_prompt_ab.py --task analysis --round 1 --arm full
  python3 57-Agent提示词工程/evals/run_prompt_ab.py --task analysis --round 1 --arm full --suite golden
  python3 57-Agent提示词工程/evals/run_prompt_ab.py --summarize
退出码：0 完成；1 配置/网络失败；2 参数错误
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MODULE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = MODULE_DIR.parent
EVALS_DIR = Path(__file__).resolve().parent
OUT_DIR = EVALS_DIR / "out"

INTENT_SPEC = REPO_ROOT / "1-ARCHITECTURE" / "intent-recognition-spec"
INTENT_PROMPT = INTENT_SPEC / "system_prompt.md"
TEST_CASES = INTENT_SPEC / "test-cases.json"
SCENARIOS = REPO_ROOT / "56-L2架构能力聚合层" / "evals" / "scenarios.yaml"
GOLDEN = EVALS_DIR / "golden" / "l2_prompts.yaml"
CONSTITUTION = MODULE_DIR / "PROMPT_CONSTITUTION.md"
ENV_PATH = REPO_ROOT / "1-ARCHITECTURE" / "dreamos" / ".env"

# 与 56 evals/run_baseline.py 的 SYSTEM_PROMPT 保持一致（分析基线，不含任何工具）
ANALYSIS_SYSTEM = (
    "你是一个金融分析助手。仅基于你的既有知识作答，不使用任何外部工具或实时数据。"
    "若某项数据你无法确知，请明确说明无法获取，禁止编造具体数值。"
    "回答简洁、结构化。"
)

TEMPERATURE = 0.1
MAX_TOKENS = 900
RETRIES = 2
CONCURRENCY = 6

# P4：实验编号（48 D2 口径：D2B-/D3B-/XA-），写入每轮结果供晋升留痕
EXPERIMENT_ID = ""

LITE_CLAUSES = {"C-04", "C-05", "C-06", "C-08", "C-11", "C-12"}

CLAUSE_RE = re.compile(r"^\|\s*\*\*(C-\d{2})\*\*\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*`([^`]+)`\s*\|")
VIOLATION_PATTERNS = {
    "E_CLAIM_EXECUTION": re.compile(r"已买入|已卖出|已下单|已触发|已平仓"),
    "E_PROPHECY": re.compile(r"将会|预计|必然|一定"),
    "E_SELF_ACCEPT": re.compile(r"已修复|已通过|已验证|已上线"),
}
EVIDENCE_RE = re.compile(
    r"(证据|evidence)[^\n。；]{0,12}?(none|partial|full|无|部分|充分|不足)", re.I
)
INSUFFICIENT_RE = re.compile(r"无法获取|未知|数据不足|暂无数据|不可用")


# ── 配置与加载 ────────────────────────────────────────────────────────


def load_env() -> Dict[str, str]:
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


def load_base_prompt() -> str:
    """与 intent_classifier.load_system_prompt 同口径：取第一个 ``` 代码块。"""
    lines = INTENT_PROMPT.read_text(encoding="utf-8").split("\n")
    inside = False
    buf: List[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            if not inside:
                inside = True
                continue
            break
        if inside:
            buf.append(line)
    return "\n".join(buf).strip()


def load_constitution_clauses() -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for line in CONSTITUTION.read_text(encoding="utf-8").splitlines():
        m = CLAUSE_RE.match(line)
        if m:
            cid, requirement, criterion, code = m.groups()
            out[cid] = {"requirement": requirement, "criterion": criterion, "code": code}
    return out


def build_constitution_block(arm: str) -> str:
    if arm == "none":
        return ""
    clauses = load_constitution_clauses()
    if not clauses:
        raise RuntimeError(f"未能从 {CONSTITUTION} 提取任何条款，宪法表格式可能已变更")
    chosen = {k: v for k, v in clauses.items() if arm == "full" or k in LITE_CLAUSES}
    m = re.search(r"constitution@(\d+\.\d+\.\d+)", CONSTITUTION.read_text(encoding="utf-8"))
    ver = m.group(1) if m else "unknown"
    lines = [
        f"【源文件宪法 constitution@{ver}｜P0 段｜优先级高于本文其余内容，违规由确定性校验器判定】",
    ]
    for cid in sorted(chosen):
        item = chosen[cid]
        lines.append(
            f"- {cid} {item['requirement']}（判据：{item['criterion']}；违例码 {item['code']}）"
        )
    if arm == "full":
        lines.append(
            "- C-04 要求在输出中给出证据等级 evidence ∈ {none, partial, full}，缺省视为 none。"
        )
    lines.append("其余格式要求不变：只输出一个 JSON 对象，不含 markdown 围栏与解释文字。")
    return "\n".join(lines)


def load_intent_cases(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    raw = TEST_CASES.read_text(encoding="utf-8")
    clean = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("//"))
    cases = json.loads(clean)["test_cases"]
    return cases[:limit] if limit else cases


def load_analysis_cases(
    limit: Optional[int] = None, suite: str = "baseline"
) -> List[Dict[str, Any]]:
    import yaml

    if suite == "golden":
        doc = yaml.safe_load(GOLDEN.read_text(encoding="utf-8")) or {}
        cases: List[Dict[str, Any]] = []
        for item in doc.get("suites") or []:
            if item.get("prompt_id") == "l2.debate.core":
                cases = list(item.get("cases") or [])
                break
        if not cases:
            raise RuntimeError(f"{GOLDEN} 未找到 l2.debate.core 的 golden cases")
        return cases[:limit] if limit else cases

    doc = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8")) or {}
    cases = [s for s in doc.get("scenarios") or [] if s.get("baseline")]
    return cases[:limit] if limit else cases


# ── 模型调用 ──────────────────────────────────────────────────────────


def chat(cfg: Dict[str, str], system: str, user: str) -> Dict[str, Any]:
    body = {
        "model": cfg["DEEPSEEK_MODEL"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    url = f"{cfg['DEEPSEEK_BASE_URL'].rstrip('/')}/chat/completions"
    last_err = ""
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg['DEEPSEEK_API_KEY']}",
            },
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode())
            choice = (payload.get("choices") or [{}])[0]
            return {
                "ok": True,
                "content": (choice.get("message") or {}).get("content") or "",
                "usage": payload.get("usage") or {},
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < RETRIES:
                time.sleep(1.5 * (attempt + 1))
    return {"ok": False, "content": "", "usage": {}, "latency_ms": None, "error": last_err}


# ── 解析与判定 ────────────────────────────────────────────────────────


def parse_json(text: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    text = (text or "").strip()
    for candidate in (text, re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()):
        try:
            doc = json.loads(candidate)
            if isinstance(doc, dict):
                return doc, True
        except json.JSONDecodeError:
            pass
    if "{" in text and "}" in text:
        try:
            doc = json.loads(text[text.index("{") : text.rindex("}") + 1])
            if isinstance(doc, dict):
                return doc, True
        except json.JSONDecodeError:
            pass
    return None, False


def _violations(content: str) -> List[str]:
    return [code for code, pat in VIOLATION_PATTERNS.items() if pat.search(content)]


def score_intent(case: Dict[str, Any], resp: Dict[str, Any]) -> Dict[str, Any]:
    expected = case["expected"]
    doc, json_ok = parse_json(resp.get("content") or "")
    doc = doc or {}
    primary_ok = doc.get("intent_primary") == expected.get("intent_primary")
    secondary_ok = doc.get("intent_secondary") == expected.get("intent_secondary")
    exp_slots = expected.get("slots") or {}
    got_slots = doc.get("slots") or {}
    content = resp.get("content") or ""
    return {
        "case_id": case["id"],
        "difficulty": case.get("difficulty"),
        "expected": {
            "primary": expected.get("intent_primary"),
            "secondary": expected.get("intent_secondary"),
        },
        "actual": {
            "primary": doc.get("intent_primary"),
            "secondary": doc.get("intent_secondary"),
            "evidence": doc.get("evidence"),
        },
        "primary_ok": primary_ok,
        "secondary_ok": secondary_ok,
        "joint_ok": bool(primary_ok and secondary_ok),
        "slot_total": len(exp_slots),
        "slot_ok": sum(1 for k, v in exp_slots.items() if str(got_slots.get(k)) == str(v)),
        "json_ok": json_ok,
        "evidence_ok": "evidence" in doc
        and str(doc.get("evidence")).lower() in ("none", "partial", "full"),
        "violations": _violations(content),
        "tokens": (resp.get("usage") or {}).get("total_tokens"),
        "latency_ms": resp.get("latency_ms"),
        "api_ok": bool(resp.get("ok")),
        "raw_head": content[:400],
    }


def score_analysis(case: Dict[str, Any], resp: Dict[str, Any]) -> Dict[str, Any]:
    content = resp.get("content") or ""
    facts = case.get("must_have_facts") or []
    hits = [
        any(str(tok) in content for tok in (f.get("match") or [])) for f in facts if f.get("match")
    ]
    return {
        "case_id": case["id"],
        "title": case.get("title"),
        "fact_total": len(hits),
        "fact_hit": sum(1 for h in hits if h),
        "fact_rate": round(sum(1 for h in hits if h) / len(hits), 3) if hits else None,
        "evidence_declared": bool(EVIDENCE_RE.search(content)),
        "insufficient_declared": bool(INSUFFICIENT_RE.search(content)),
        "violations": _violations(content),
        "answer_chars": len(content),
        "tokens": (resp.get("usage") or {}).get("total_tokens"),
        "latency_ms": resp.get("latency_ms"),
        "api_ok": bool(resp.get("ok")),
        "raw_head": content[:600],
    }


def aggregate(rows: List[Dict[str, Any]], task: str) -> Dict[str, Any]:
    n = len(rows) or 1
    base = {
        "cases": len(rows),
        "api_failures": sum(0 if r["api_ok"] else 1 for r in rows),
        "violation_cases": sum(1 for r in rows if r["violations"]),
        "violations_by_code": {
            code: sum(1 for r in rows if code in r["violations"]) for code in VIOLATION_PATTERNS
        },
        "avg_tokens": round(sum(r["tokens"] or 0 for r in rows) / n, 1),
        "avg_latency_ms": round(sum(r["latency_ms"] or 0 for r in rows) / n, 1),
    }
    if task == "intent":
        slot_total = sum(r["slot_total"] for r in rows)
        base.update(
            {
                "primary_acc": round(sum(r["primary_ok"] for r in rows) / n * 100, 2),
                "secondary_acc": round(sum(r["secondary_ok"] for r in rows) / n * 100, 2),
                "joint_acc": round(sum(r["joint_ok"] for r in rows) / n * 100, 2),
                "slot_acc": (
                    round(sum(r["slot_ok"] for r in rows) / slot_total * 100, 2)
                    if slot_total
                    else None
                ),
                "json_ok_rate": round(sum(r["json_ok"] for r in rows) / n * 100, 2),
                "evidence_rate": round(sum(r["evidence_ok"] for r in rows) / n * 100, 2),
            }
        )
    else:
        rated = [r for r in rows if r["fact_rate"] is not None]
        base.update(
            {
                "fact_rate_mean": (
                    round(sum(r["fact_rate"] for r in rated) / len(rated) * 100, 2)
                    if rated
                    else None
                ),
                "evidence_declared_rate": round(
                    sum(r["evidence_declared"] for r in rows) / n * 100, 2
                ),
                "insufficient_declared_rate": round(
                    sum(r["insufficient_declared"] for r in rows) / n * 100, 2
                ),
            }
        )
    return base


def mcnemar_exact(b_only: int, a_only: int) -> float:
    n = b_only + a_only
    if n == 0:
        return 1.0
    k = min(b_only, a_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return round(min(1.0, 2 * tail), 4)


# ── 单轮执行 ──────────────────────────────────────────────────────────


def run_arm(
    cfg: Dict[str, str],
    system: str,
    cases: List[Dict[str, Any]],
    tag: str,
    task: str,
) -> List[Dict[str, Any]]:
    scorer = score_intent if task == "intent" else score_analysis

    def one(case: Dict[str, Any]) -> Dict[str, Any]:
        row = scorer(case, chat(cfg, system, case["input"]))
        row["arm"] = tag
        return row

    rows: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(one, c) for c in cases]
        for i, fut in enumerate(as_completed(futures), 1):
            rows.append(fut.result())
            if i % 10 == 0:
                print(f"  {tag}: {i}/{len(cases)}", flush=True)
    order = {c["id"]: idx for idx, c in enumerate(cases)}
    rows.sort(key=lambda r: order.get(r["case_id"], 0))
    return rows


def _paired(
    task: str, a_rows: List[Dict[str, Any]], b_rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    key = "joint_ok" if task == "intent" else None
    if key:
        a = {r["case_id"]: r for r in a_rows}
        b = {r["case_id"]: r for r in b_rows}
        b_only = [cid for cid in a if b[cid][key] and not a[cid][key]]
        a_only = [cid for cid in a if a[cid][key] and not b[cid][key]]
        return {
            "b_only": b_only,
            "a_only": a_only,
            "delta_pp": round(
                sum(r[key] for r in b_rows) / len(b_rows) * 100
                - sum(r[key] for r in a_rows) / len(a_rows) * 100,
                2,
            ),
            "mcnemar_p": mcnemar_exact(len(b_only), len(a_only)),
        }
    # analysis：按事实命中率配对，用逐题差值均值衡量
    a = {r["case_id"]: r for r in a_rows}
    b = {r["case_id"]: r for r in b_rows}
    deltas = []
    improved, regressed = [], []
    for cid, row in a.items():
        if row["fact_rate"] is None or b[cid]["fact_rate"] is None:
            continue
        d = b[cid]["fact_rate"] - row["fact_rate"]
        deltas.append(d)
        if d > 0:
            improved.append(cid)
        elif d < 0:
            regressed.append(cid)
    mean_delta = round(sum(deltas) / len(deltas) * 100, 2) if deltas else 0.0
    return {
        "improved": improved,
        "regressed": regressed,
        "delta_pp": mean_delta,
        "mcnemar_p": mcnemar_exact(len(improved), len(regressed)),
    }


def run_round(
    round_no: int, arm: str, limit: Optional[int], task: str, suite: str = "baseline"
) -> int:
    cfg = load_env()
    missing = [
        k for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL") if not cfg.get(k)
    ]
    if missing:
        print(f"缺少环境变量: {missing}（来源 {ENV_PATH}）")
        return 1

    if task == "intent":
        base, cases = load_base_prompt(), load_intent_cases(limit)
    else:
        base, cases = ANALYSIS_SYSTEM, load_analysis_cases(limit, suite)
    block = build_constitution_block(arm)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"[{task} round {round_no}] arm={arm} cases={len(cases)} "
        f"prompt_chars={len(base)} block_chars={len(block)}"
    )
    arms = {"none": base}
    if arm != "none":
        arms[arm] = base + "\n\n" + block

    result: Dict[str, Any] = {
        "task": task,
        "round": round_no,
        "arm": arm,
        "experiment_id": EXPERIMENT_ID,
        "model": cfg["DEEPSEEK_MODEL"],
        "temperature": TEMPERATURE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_prompt_chars": len(base),
        "constitution_block_chars": len(block),
        "arms": {},
    }
    for name, system in arms.items():
        rows = run_arm(cfg, system, cases, name, task)
        result["arms"][name] = {"metrics": aggregate(rows, task), "rows": rows}

    if arm != "none":
        result["paired"] = _paired(
            task, result["arms"]["none"]["rows"], result["arms"][arm]["rows"]
        )

    path = OUT_DIR / f"{task}_round{round_no}_{arm}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写入 {path}")
    for name, payload in result["arms"].items():
        m = payload["metrics"]
        core = (
            f"joint={m['joint_acc']}% json={m['json_ok_rate']}% evidence={m['evidence_rate']}%"
            if task == "intent"
            else f"fact={m['fact_rate_mean']}% evidence_decl={m['evidence_declared_rate']}%"
        )
        print(f"  {name}: {core} viol={m['violation_cases']} tok={m['avg_tokens']}")
    if "paired" in result:
        print(f"  paired: delta={result['paired']['delta_pp']}pp p={result['paired']['mcnemar_p']}")
    return 0


# ── 汇总 ──────────────────────────────────────────────────────────────


def summarize() -> int:
    files = sorted(OUT_DIR.glob("*_round*.json"))
    if not files:
        print("没有找到任何轮次结果")
        return 1

    intent_rows: List[str] = []
    analysis_rows: List[str] = []
    payload_rows: List[Dict[str, Any]] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        arm = data["arm"]
        if arm == "none":
            continue
        task = data.get("task", "intent")
        a = data["arms"]["none"]["metrics"]
        b = data["arms"][arm]["metrics"]
        paired = data.get("paired") or {}
        delta = paired.get("delta_pp", paired.get("delta_joint_pp"))
        if task == "intent":
            intent_rows.append(
                f"| {data['round']} | {arm} | {a['joint_acc']} | {b['joint_acc']} | "
                f"{delta} | {a['json_ok_rate']} | {b['json_ok_rate']} | "
                f"{a['evidence_rate']} | {b['evidence_rate']} | {a['violation_cases']} | "
                f"{b['violation_cases']} | {a['avg_tokens']} | {b['avg_tokens']} | {paired.get('mcnemar_p')} |"
            )
        else:
            analysis_rows.append(
                f"| {data['round']} | {arm} | {a['fact_rate_mean']} | {b['fact_rate_mean']} | "
                f"{delta} | {a['evidence_declared_rate']} | {b['evidence_declared_rate']} | "
                f"{a['violation_cases']} | {b['violation_cases']} | {a['avg_tokens']} | "
                f"{b['avg_tokens']} | {paired.get('mcnemar_p')} |"
            )
        payload_rows.append(
            {
                "file": f.name,
                "task": task,
                "round": data["round"],
                "arm": arm,
                "a": a,
                "b": b,
                "paired": paired,
            }
        )

    lines = [
        "# 57 提示词 A/B 多轮回测汇总",
        "",
        "口径：同一 DeepSeek 模型、同一用例、温度 0.1；A 臂 = 现行 prompt，B 臂 = 现行 + 宪法 P0 段。",
        "A/B 唯一差异是 system prompt 尾部是否注入宪法；宪法段由 PROMPT_CONSTITUTION.md 现场提取。",
        "",
        "## 任务类 1：意图识别（55 例，主指标 joint = 一级+二级同时正确）",
        "",
        "| 轮次 | B 臂 | A joint% | B joint% | Δ(pp) | A json% | B json% | A evidence% | B evidence% | A 违例 | B 违例 | A tok | B tok | McNemar p |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *intent_rows,
        "",
        "## 任务类 2：开放分析（56 评测 baseline 8 题，主指标事实命中率）",
        "",
        "| 轮次 | B 臂 | A fact% | B fact% | Δ(pp) | A 声明证据% | B 声明证据% | A 违例 | B 违例 | A tok | B tok | McNemar p |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        *analysis_rows,
        "",
        "## 判定规则（预注册，避免事后择优）",
        "",
        "1. 提升成立：`Δ ≥ +3pp` 且 `McNemar p < 0.20`，且护栏不破（json 不降；avg_tokens 涨幅 ≤ 40%）。",
        "2. 违例数下降但准确率/命中率下滑 = 退化，不判提升。",
        "3. 同类任务至少两轮方向一致，才认定为稳定结论。",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rounds": payload_rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n".join(lines))
    print(f"\n写入 {OUT_DIR/'summary.md'} / summary.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="57 提示词 A/B 多轮回测")
    ap.add_argument("--task", choices=["intent", "analysis"], default="intent")
    ap.add_argument("--round", type=int, default=0, help="轮次编号（>=1）")
    ap.add_argument(
        "--arm", choices=["none", "full", "lite"], default="full", help="B 臂宪法段版本"
    )
    ap.add_argument("--limit", type=int, default=0, help="限制用例数（冒烟用）")
    ap.add_argument(
        "--suite",
        choices=["baseline", "golden"],
        default="baseline",
        help="analysis 用例来源：baseline=56 评测 8 题；golden=57 golden set 20 题",
    )
    ap.add_argument(
        "--experiment-id",
        default="",
        help="48 D2 实验编号（D2B-/D3B-/XA-），写入轮次结果供 P4 晋升留痕",
    )
    ap.add_argument("--summarize", action="store_true", help="汇总已有轮次")
    args = ap.parse_args()

    if args.summarize:
        return summarize()
    if args.round < 1:
        ap.print_help()
        return 2
    global EXPERIMENT_ID
    EXPERIMENT_ID = args.experiment_id
    return run_round(args.round, args.arm, args.limit or None, args.task, args.suite)


if __name__ == "__main__":
    raise SystemExit(main())
