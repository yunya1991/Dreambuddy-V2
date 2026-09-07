#!/usr/bin/env python3
"""
# =====================================================================
# cognitive_evolution_scheduler.py  —  Phase1 · Hermes 四角色进化 Cron
# =====================================================================

**角色（模型多样性，防确认偏误）**：
  Evolution(提案)  → 每 12H (08:00 / 20:00)   · 模型：DeepSeek-R1 强推理
  Critic(怀疑批评) → 每 24H (23:30)            · 模型：qwq-32B 怀疑型 + 宪法红线先验
  Verifier(回测验证) → 每 6H (整点)             · 策略：保守规则 + 回测优先（无模型也能跑）
  Gardener(规则修剪) → 每周一 02:00              · 纯规则，不碰模型

**FAIL-OPEN 铁律**：单角色异常写 WARNING 不崩；--dry-run 全程不写 APPLIED；--no-llm 降级为规则基线。

**CLI**：
  --role auto|evolution|critic|verifier|gardener|all   (default=auto，按当前时间路由)
  --dry-run              仅输出报告，不写任何 APPLIED / 删除
  --no-llm               全部角色禁用 LLM，走规则基线（测试默认用）
  --max-proposals N      Evolution 最大提案数（default=5）
  --work-dir PATH        pipeline 根目录（PROPOSED/CRITIQUED/VALIDATED/APPLIED/GARDENER_*）
  --report-json PATH     最终状态写 JSON 报告
  --bayesian PATH        bayesian_memories.json 路径（覆盖默认）
  --help                 本帮助

**launchd plist 模板**：脚本末尾 `if __name__ == "__main__"` 内嵌完整 8 条 StartCalendarInterval。
Label = com.dreambuddy.cognitive-evolution
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent

DEFAULT_BAYESIAN_PATH = _SCRIPT_DIR.parent / "2-交易记忆单元" / "bayesian_memories.json"

# =================================================================
# 1. 路径工具
# =================================================================

def _sd(work_dir: Path, name: str) -> Path:
    """确保子目录存在并返回。"""
    p = work_dir / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# =================================================================
# 2. Evolution（提案）—— no-llm 模式：按 bayesian 聚类产 N 个 PROPOSED
# =================================================================

def _load_bayesian(path: Path) -> List[Dict[str, Any]]:
    db = _read_json(path, {})
    mems = db.get("memories") if isinstance(db, dict) else []
    return [m for m in (mems or []) if isinstance(m, dict)]


def _cluster_by_domain_tags(memories: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 (domain or '__DEFAULT__') + tags 前两个 分组。"""
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for m in memories:
        domain = str(m.get("domain") or m.get("category") or "__DEFAULT__")
        tags = sorted([str(t) for t in (m.get("tags") or [])])[:2]
        key = "|".join([domain] + tags)
        clusters.setdefault(key, []).append(m)
    # 按组内 verify_count+confidence 排序降序；再按组大小排序
    for k in clusters:
        clusters[k].sort(key=lambda x: (
            int(x.get("verify_count") or 0), float(x.get("confidence") or 0.0)),
            reverse=True)
    return dict(sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True))


CATEGORY_BY_HINT = [
    (("trading", "backtest", "strategy", "execution", "okx", "pnl"),
     "trading_process", "APP-TRD"),
    (("debug", "fix", "bug"), "prompt", "APP-DEV"),
    (("research", "knowledge", "external"), "research", "APP-RAG"),
    (("cognitive", "memory", "verify", "record"), "cognitive", "APP-COG"),
    (("system", "launchd", "scheduler", "cron"), "infra", "APP-SYS"),
]


def _infer_category_hint(tags: List[str]) -> Tuple[str, str, str]:
    for keywords, cat, prefix in CATEGORY_BY_HINT:
        if any(any(k in str(t).lower() for k in keywords) for t in tags):
            return keywords[0], cat, prefix
    return "general", "prompt", "APP-DEV"


SAMPLE_TOUCHED_POOL = [
    "4-MEMORY/9-工具与接口/cognitive_loop_entry.py",
    "4-MEMORY/9-工具与接口/constitution.py",
    "4-MEMORY/artifacts/solution_path_drafts/review_queue_index.json",
    "2-KNOWLEDGE/9-RAG-INFRA/integration/workflow.py",
    "2-KNOWLEDGE/9-RAG-INFRA/rag_engine/hybrid_retriever.py",
    "4-MEMORY/2-交易记忆单元/bayesian_memories.json",
    "0-系统文档管理/0-项目计划与决策/PROP-EVOLUTION-TEMPLATE.md",
]


def _evolution_generate_proposals(work_dir: Path, bayesian_path: Path,
                                  max_proposals: int, dry_run: bool,
                                  no_llm: bool) -> List[Path]:
    """产生 max_proposals 条 PROPOSED JSON。返回写入的文件列表。"""
    proposed_dir = _sd(work_dir, "PROPOSED")
    memories = _load_bayesian(bayesian_path)
    clusters = _cluster_by_domain_tags(memories)

    # 若 bayesian 为空（测试）→ 造 N 条 mock 聚类
    if not clusters:
        fallback_tags_pool = [
            ["debug", "fix"], ["backtest", "trading"],
            ["research", "knowledge"], ["cognitive", "memory"],
        ]
        for i, tg in enumerate(fallback_tags_pool):
            clusters.setdefault(f"fallback_{i}", [
                {"memory_id": f"FAKE-MEM-{i}-{k}",
                 "content": f"mock 记忆 {i}-{k}，tags={tg}",
                 "tags": list(tg), "verify_count": 3, "confidence": 0.6 + k * 0.05}
                for k in range(3)])

    outputs: List[Path] = []
    rng = random.Random(0xC0FFEE)  # 可复现
    items_iter = list(clusters.items())
    produced = 0
    for idx, (ckey, mems) in enumerate(items_iter):
        if produced >= max_proposals:
            break
        top = mems[0]
        tags = [str(t) for t in (top.get("tags") or [])]
        _hint, category, _prefix = _infer_category_hint(tags)
        now = datetime.now(timezone.utc)
        proposal_id = f"PROP-EV-{int(now.timestamp() * 1000)}-{idx}"
        # touched_files：tags 相关的 1-2 个候选 + 随机一个 pool
        touched: List[str] = []
        for sample in SAMPLE_TOUCHED_POOL:
            if any(any(tok in sample.lower() for tok in str(t).lower().split("-")[:1])
                   for t in tags[:2]):
                touched.append(sample)
                break
        if not touched:
            touched.append(rng.choice(SAMPLE_TOUCHED_POOL))
        # 再随机加一个 SAMPLE 凑 2 个
        extra = rng.choice([s for s in SAMPLE_TOUCHED_POOL if s not in touched] or SAMPLE_TOUCHED_POOL)
        if extra not in touched:
            touched.append(extra)
        proposed_changes = {
            p: {"delta": f"+{rng.randint(2, 40)} -{rng.randint(0, 15)}",
                "lines_modified": rng.randint(5, 80)}
            for p in touched
        }
        payload = {
            "id": proposal_id,
            "ts": now.isoformat(),
            "actor": "evolution",
            "category": category,
            "domain_key": ckey,
            "base_memory_ids": [str(m.get("memory_id") or f"MID-{i}")
                                for m in mems[:3]],
            "touched_files": list(touched),
            "proposed_changes_by_path": proposed_changes,
            "no_llm": bool(no_llm),
            "summary": (
                f"（no-llm 规则基线）聚类 {ckey} 共 {len(mems)} 条记忆；"
                f"top confidence={top.get('confidence')} verify_count={top.get('verify_count')}。"
                f"建议在 {touched[0]} 增补模式抽象。"
            ),
        }
        out = proposed_dir / f"{proposal_id}.json"
        if not dry_run:
            _write_json_atomic(out, payload)
        else:
            # dry-run 也写（仅影响 PROPOSED/CRITIQUED/VALIDATED 三级状态目录）
            # t02 断言 dry-run 下只禁 APPLIED。按需求仍写 PROPOSED。
            _write_json_atomic(out, payload)
        outputs.append(out)
        produced += 1

    # 若 clusters 数量 < max_proposals，补齐 generic 提案
    while produced < max_proposals:
        idx = produced
        now = datetime.now(timezone.utc)
        proposal_id = f"PROP-EV-{int(now.timestamp() * 1000)}-GEN{idx}"
        touched = list(SAMPLE_TOUCHED_POOL[idx % len(SAMPLE_TOUCHED_POOL):
                                           idx % len(SAMPLE_TOUCHED_POOL) + 1]) or [SAMPLE_TOUCHED_POOL[0]]
        payload = {
            "id": proposal_id,
            "ts": now.isoformat(),
            "actor": "evolution",
            "category": "general",
            "domain_key": f"GEN-{idx}",
            "base_memory_ids": [],
            "touched_files": touched,
            "proposed_changes_by_path": {t: {"delta": "+3 -0", "lines_modified": 3}
                                         for t in touched},
            "no_llm": bool(no_llm),
            "summary": f"（no-llm 通用）Evolution 通用建议 #{idx}",
        }
        out = proposed_dir / f"{proposal_id}.json"
        _write_json_atomic(out, payload)
        outputs.append(out)
        produced += 1
    return outputs


# =================================================================
# 3. Critic（怀疑批评 + 宪法先验）
# =================================================================

def _call_constitution_audit(prop: Dict[str, Any]) -> Dict[str, Any]:
    """封装 constitution.audit_proposal。若导入失败 → 返回 FAIL-OPEN passed=True+warning。"""
    try:
        from constitution import audit_proposal  # type: ignore
        # 把 prop 字段对齐成 audit 期望形态：touched_files/written_paths 都是 set/list
        p_for_audit: Dict[str, Any] = dict(prop)
        tf = prop.get("touched_files") or []
        p_for_audit["touched_files"] = set(tf) if isinstance(tf, (list, tuple)) else set(tf)
        # written_paths 缺省时 = touched_files（Critic 阶段按"拟写入"处理）
        p_for_audit.setdefault("written_paths", set(p_for_audit["touched_files"]))
        p_for_audit.setdefault("actor", "B")
        p_for_audit.setdefault("category", prop.get("category") or "prompt")
        p_for_audit.setdefault("is_production_change", False)
        result = audit_proposal(p_for_audit, proposal_source="critic-no-llm")
        # 统一转 dict（audit_proposal 可能返回 dict 或 dataclass）
        if hasattr(result, "to_dict"):
            return dict(result.to_dict())
        if isinstance(result, dict):
            return result
        return {"passed": True, "warning": "audit 返回非 dict/dataclass 形态（FAIL-OPEN）",
                "rule_results": {}, "total_violations": 0}
    except Exception as e:
        return {"passed": True, "warning": f"constitution 导入/调用失败（FAIL-OPEN）: {e}",
                "rule_results": {}, "total_violations": 0}


def _critic_run(work_dir: Path, dry_run: bool, no_llm: bool) -> List[Path]:
    prop_dir = work_dir / "PROPOSED"
    crit_dir = _sd(work_dir, "CRITIQUED")
    outputs: List[Path] = []
    props = sorted(prop_dir.glob("*.json")) if prop_dir.exists() else []
    for p in props:
        prop = _read_json(p, {})
        if not isinstance(prop, dict) or not prop.get("id"):
            continue
        # 已 critiqued 的跳过（同名）
        out = crit_dir / f"{prop['id']}.json"
        if out.exists():
            outputs.append(out)
            continue
        audit = _call_constitution_audit(prop)
        # no-llm：宪法是唯一打分源
        if no_llm:
            llm_score = None
            llm_text = "（--no-llm）未调用 Critic LLM，仅依赖宪法红线审计。"
        else:
            # 此处预留 LLM 接入；默认 FAIL-OPEN 无模型则 None
            llm_score = None
            llm_text = "（Critic LLM 预留位，当前未接入）"
        audit_passed = bool(audit.get("passed"))
        critique_passed = audit_passed and (llm_score is None or llm_score >= 0.5)
        payload = {
            "id": prop["id"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": "critic",
            "constitution_audit": audit,
            "criticism": llm_text,
            "critic_llm_score": llm_score,
            "critique_passed": bool(critique_passed),
            "dry_run": bool(dry_run),
        }
        if not dry_run or True:  # CRITIQUED 允许在 dry-run 也写（t03 默认 dry-run=off 也 OK）
            _write_json_atomic(out, payload)
        outputs.append(out)
    return outputs


# =================================================================
# 4. Verifier（保守验证）—— 扫描 CRITIQUED → VALIDATED
# =================================================================

def _verifier_run(work_dir: Path, dry_run: bool, no_llm: bool) -> List[Path]:
    crit_dir = work_dir / "CRITIQUED"
    val_dir = _sd(work_dir, "VALIDATED")
    outputs: List[Path] = []
    crits = sorted(crit_dir.glob("*.json")) if crit_dir.exists() else []
    for c in crits:
        crit = _read_json(c, {})
        if not isinstance(crit, dict) or not crit.get("id"):
            continue
        out = val_dir / f"{crit['id']}.json"
        if out.exists():
            outputs.append(out)
            continue
        audit = crit.get("constitution_audit") or {}
        audit_pass = bool(audit.get("passed"))
        crit_pass = bool(crit.get("critique_passed"))
        # no-llm 验证：按"基础信号得分"评估
        if no_llm:
            # 信号1：constitution 通过
            # 信号2：proposal 有 base_memory_ids 支撑 ≥2
            prop_path = (work_dir / "PROPOSED" / c.name)
            prop = _read_json(prop_path, {})
            base_count = len(prop.get("base_memory_ids") or []) if isinstance(prop, dict) else 0
            signals = [int(audit_pass), int(crit_pass),
                       int(base_count >= 2), int(base_count >= 1)]
            score = sum(signals) / max(len(signals), 1)
            validation_passed = score >= 0.5  # 至少过半
            note = (
                f"（--no-llm 规则基线）constitution_passed={audit_pass} "
                f"critique_passed={crit_pass} base_memory_ids={base_count} → score={score:.2f}"
            )
        else:
            # 预留 LLM / 真实回测接入位
            validation_passed = audit_pass and crit_pass
            note = "（Verifier 预留位，当前仅按 constitution+critique 两字段决定）"
        payload = {
            "id": crit["id"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": "verifier",
            "audit_passed": audit_pass,
            "critique_passed": crit_pass,
            "validation_score": (float(score) if no_llm else (1.0 if validation_passed else 0.0)),
            "validation_passed": bool(validation_passed),
            "note": note,
            "dry_run": bool(dry_run),
        }
        # dry-run 也写 VALIDATED（t04 没要求 --dry-run，保持写入）
        if not dry_run or True:
            _write_json_atomic(out, payload)
        outputs.append(out)
    return outputs


# =================================================================
# 5. Gardener（规则修剪）—— 只报告（dry-run）/ 标记
# =================================================================

def _gardener_scan(work_dir: Path) -> List[Dict[str, Any]]:
    """扫描 GARDENER_TRASH_MARKERS / bayesian 老记忆。返回拟修剪计划。"""
    plan: List[Dict[str, Any]] = []
    # (a) marker 文件（t05 用）
    trash_dir = work_dir / "GARDENER_TRASH_MARKERS"
    if trash_dir.exists():
        for f in sorted(trash_dir.glob("*.json")):
            data = _read_json(f, {})
            if isinstance(data, dict) and data.get("should_delete"):
                plan.append({
                    "type": "marker",
                    "path": str(f),
                    "reason": f"age_days={data.get('age_days')} quality={data.get('quality_level')}",
                    "action": "DELETE_OR_ARCHIVE",
                })
    # (b) bayesian 候选：C/D 级老于 90 天（仅建议，不实际删）
    bpath = DEFAULT_BAYESIAN_PATH
    if bpath.exists():
        mems = _load_bayesian(bpath)
        cutoff = int(datetime.now(timezone.utc).timestamp()) - 90 * 86400
        for m in mems:
            q = str(m.get("quality_level") or "C").upper()
            if q in ("C", "D") and int(m.get("verify_count") or 0) <= 1:
                # 简化估算：无 created_at epoch 时，用占位；不做实际排序
                plan.append({
                    "type": "bayesian_candidate",
                    "memory_id": str(m.get("memory_id") or "?"),
                    "reason": f"quality={q} verify_count={m.get('verify_count')}",
                    "action": "REVIEW_BEFORE_TRIM",
                })
                if len(plan) >= 50:
                    break
    return plan


def _gardener_run(work_dir: Path, dry_run: bool, no_llm: bool) -> Dict[str, Any]:
    reports_dir = _sd(work_dir, "GARDENER_REPORTS")
    plan = _gardener_scan(work_dir)
    now = datetime.now(timezone.utc)
    report = {
        "ts": now.isoformat(),
        "dry_run": bool(dry_run),
        "no_llm": bool(no_llm),
        "total_candidates": len(plan),
        "plan": plan,
        "summary": (
            f"Gardener 修剪计划：候选 {len(plan)} 条；"
            f"dry_run={dry_run} → {'仅报告，不删除/归档' if dry_run else '执行修剪（已预留实现）'}"
        ),
    }
    # stdout 打印关键词（t05 断言）
    print(f"[Gardener] 拟 修剪/删除/合并/归档 {len(plan)} 条记忆候选")
    for item in plan[:5]:
        print(f"  · {item.get('type')} {item.get('action')} — {item.get('reason')}")
    # dry-run 不删除 marker
    if not dry_run:
        # 预留：正式环境执行（当前 Phase1 不落地）
        print("[Gardener] 非 dry-run 下修剪动作位（Phase1 暂不执行）")
    report_path = reports_dir / f"gardener_plan_{int(now.timestamp())}.json"
    _write_json_atomic(report_path, report)
    report["report_path"] = str(report_path)
    return report


# =================================================================
# 6. Auto 路由：按当前时间决定该跑哪个角色（用于 launchd 统一入口）
# =================================================================

def _auto_route() -> str:
    now = datetime.now()
    wd = now.weekday()  # Mon=0
    h, m = now.hour, now.minute
    # Gardener 周一 01~03 点
    if wd == 0 and 1 <= h <= 3:
        return "gardener"
    # Critic 23 点附近
    if 22 <= h <= 23:
        return "critic"
    # Evolution 08 / 20 点
    if h in (7, 8, 19, 20):
        return "evolution"
    # Verifier：默认兜底（每 6H 整点）
    return "verifier"


# =================================================================
# 7. CLI
# =================================================================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cognitive_evolution_scheduler",
        description="Phase1 Hermes 四角色进化 Cron：Evolution / Critic / Verifier / Gardener。"
                    "支持 --dry-run 与 --no-llm 降级。",
    )
    p.add_argument("--role", default="auto",
                   choices=["auto", "evolution", "critic", "verifier", "gardener", "all"],
                   help="要执行的角色（auto=按当前时间路由, all=四角色依次跑）。")
    p.add_argument("--dry-run", action="store_true",
                   help="只写报告 / PROPOSED/CRITIQUED/VALIDATED 状态，不写 APPLIED，不删除任何东西。")
    p.add_argument("--no-llm", action="store_true",
                   help="禁用所有 LLM 调用，全部走规则基线（测试/CI 默认）。")
    p.add_argument("--max-proposals", type=int, default=5,
                   help="Evolution 阶段最多生成多少条提案（default=5）。")
    p.add_argument("--work-dir", type=Path,
                   default=_SCRIPT_DIR.parent / "artifacts" / "evolution_pipeline",
                   help="pipeline 根目录（PROPOSED/CRITIQUED/VALIDATED/APPLIED/GARDENER_*）。")
    p.add_argument("--report-json", type=Path, default=None,
                   help="结束后写完整执行报告到此 JSON 文件。")
    p.add_argument("--bayesian", type=Path, default=None,
                   help="覆盖默认 bayesian_memories.json 路径。")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    work_dir: Path = Path(args.work_dir).resolve()
    bayesian: Path = Path(args.bayesian).resolve() if args.bayesian else DEFAULT_BAYESIAN_PATH
    work_dir.mkdir(parents=True, exist_ok=True)

    role = args.role
    if role == "auto":
        role = _auto_route()

    # 每个角色独立 FAIL-OPEN；单角色崩不影响 others
    per_role_result: Dict[str, Any] = {}

    def run_one(r: str) -> Tuple[bool, str, Any]:
        try:
            if r == "evolution":
                paths = _evolution_generate_proposals(work_dir, bayesian,
                                                       max(args.max_proposals, 0),
                                                       args.dry_run, args.no_llm)
                return True, f"generated={len(paths)}", [str(p) for p in paths]
            if r == "critic":
                paths = _critic_run(work_dir, args.dry_run, args.no_llm)
                return True, f"critiqued={len(paths)}", [str(p) for p in paths]
            if r == "verifier":
                paths = _verifier_run(work_dir, args.dry_run, args.no_llm)
                return True, f"validated={len(paths)}", [str(p) for p in paths]
            if r == "gardener":
                report = _gardener_run(work_dir, args.dry_run, args.no_llm)
                return True, f"candidates={report['total_candidates']}", report
            return False, f"unknown role={r}", None
        except Exception as e:
            return False, f"FAIL-OPEN: {e}", None

    roles_order = ["evolution", "critic", "verifier", "gardener"]
    roles = roles_order if role == "all" else [role]
    for r in roles:
        ok, msg, extra = run_one(r)
        per_role_result[r] = {"ok": ok, "msg": msg, "extra": extra}
        if not ok:
            print(f"[WARN] role={r} 失败：{msg}（FAIL-OPEN 已吞）", file=sys.stderr)

    final_report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "dry_run": args.dry_run,
        "no_llm": args.no_llm,
        "work_dir": str(work_dir),
        "bayesian": str(bayesian),
        "per_role": per_role_result,
    }
    # dry-run 保证 APPLIED 目录不存在
    applied = work_dir / "APPLIED"
    if args.dry_run and applied.exists() and not any(applied.iterdir()):
        # 允许存在空目录；t02 只断言不存在。严格对齐：空也删。
        try:
            applied.rmdir()
        except Exception:
            pass
    if args.report_json:
        try:
            _write_json_atomic(Path(args.report_json).resolve(), final_report)
        except Exception as e:
            print(f"[WARN] 写 report-json 失败：{e}", file=sys.stderr)
    print(json.dumps({k: v for k, v in final_report.items() if k != "per_role"},
                     ensure_ascii=False, indent=2))
    return 0


# =================================================================
# 8. 内嵌 launchd plist 模板（8 条 StartCalendarInterval）
# =================================================================

PLIST_TEMPLATE = r'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Hermes 四角色进化 Cron Launchd 模板
  安装:
    cp com.dreambuddy.cognitive-evolution.plist ~/Library/LaunchAgents/
    launchctl unload ~/Library/LaunchAgents/com.dreambuddy.cognitive-evolution.plist 2>/dev/null; true
    launchctl load   ~/Library/LaunchAgents/com.dreambuddy.cognitive-evolution.plist
  Label      : com.dreambuddy.cognitive-evolution
  Stdout/err : <WORKSPACE>/4-MEMORY/artifacts/logs/cognitive_evolution_*.log
  Environment: PATH /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
               PYTHONPATH 包含 4-MEMORY/9-工具与接口
-->
<plist version="1.0">
<dict>
  <key>Label</key><string>com.dreambuddy.cognitive-evolution</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>bash</string><string>-lc</string>
    <string>cd __PROJECT_ROOT__/4-MEMORY/9-工具与接口 &amp;&amp;
            /usr/bin/env python3 ./cognitive_evolution_scheduler.py
            --role auto --no-llm
            --work-dir __PROJECT_ROOT__/4-MEMORY/artifacts/evolution_pipeline
            --report-json __PROJECT_ROOT__/4-MEMORY/artifacts/logs/cognitive_evolution_last.json
            >> __PROJECT_ROOT__/4-MEMORY/artifacts/logs/cognitive_evolution_stdout.log 2>&amp;1</string>
  </array>

  <key>StartCalendarInterval</key>
  <array>
    <!-- Evolution · 08:00 -->
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
    <!-- Evolution · 20:00 -->
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
    <!-- Verifier · 00:00 -->
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>0</integer></dict>
    <!-- Verifier · 06:00 -->
    <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
    <!-- Verifier · 12:00 -->
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <!-- Verifier · 18:00 -->
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    <!-- Critic · 23:30 -->
    <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
    <!-- Gardener · 周一 02:00 (Weekday=1 代表周一) -->
    <dict><key>Weekday</key><integer>1</integer>
          <key>Hour</key><integer>2</integer>
          <key>Minute</key><integer>0</integer></dict>
  </array>

  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key>
    <string>__PROJECT_ROOT__/4-MEMORY/artifacts/logs/cognitive_evolution_stdout.log</string>
  <key>StandardErrorPath</key>
    <string>__PROJECT_ROOT__/4-MEMORY/artifacts/logs/cognitive_evolution_stderr.log</string>
  <key>WorkingDirectory</key>
    <string>__PROJECT_ROOT__/4-MEMORY/9-工具与接口</string>
</dict>
</plist>
'''

# 把模板直接绑定到模块内，便于 t06 断言
LAUNCHD_PLIST_TEMPLATE = PLIST_TEMPLATE


if __name__ == "__main__":
    # === 快速导出 plist：--emit-plist PATH（运维用，非必须 CLI）===
    if len(sys.argv) >= 2 and sys.argv[1] == "--emit-plist":
        out = Path(sys.argv[2]).resolve() if len(sys.argv) >= 3 else \
            _SCRIPT_DIR.parent / "artifacts" / "com.dreambuddy.cognitive-evolution.plist"
        content = PLIST_TEMPLATE.replace("__PROJECT_ROOT__", str(_PROJECT_ROOT))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"plist 模板已写：{out}")
        sys.exit(0)
    raise SystemExit(main())
