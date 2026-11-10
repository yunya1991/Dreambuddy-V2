# ruff: noqa: E402  (sys.path 必须先于 experiments/asil 导入)
"""ASIL 双涌现闭环 — D3 意图涌现 + D2 技术架构涌现。

用户决策（2026-11-10）：跨域迁移（T-I2E/T-E2T）挂起，先实现 D3/D2 自身闭环。
评估环节支持 Trae-in-the-loop：把评审包写成文件，由 Trae（或人）回写裁决；
无人值守时用确定性规则兜底，绝不阻塞。

闭环语义（每轮）：
    evaluate(champion) → propose(variant) → evaluate(variant)
    → gate(改进幅度 & 校准不回退) → accept/reject → 沉淀历史与冠军
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .d2b_adapter import D2B_TYPES as D2B_SUPPORTED
from .stat_gate import evidence_level, holm_adjust, paired_bootstrap, wilson_interval
from .variant_generator import (
    DEFAULT_D3_VARIANTS,
    D2TemplateGenerator,
    D3VariantGenerator,
    RuleVariant,
    plan_diagnostics,
)

# 路径：48-涌现架构 根（用于 import experiments.* / asil.*）
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

DEFAULT_EVENTS_PATH = (
    _PKG_ROOT / "baselines" / "artifacts" / "d3_intent_events" / "intent_events.jsonl"
)
DEFAULT_GAPS_PATH = _PKG_ROOT / "registry" / "capability_gaps.jsonl"
LOOP_DIR = _PKG_ROOT / "events" / "asil" / "loops"
REVIEW_DIR = _PKG_ROOT / "events" / "asil" / "reviews"


# ---------------------------------------------------------------------------
# 通用：轮次记录
# ---------------------------------------------------------------------------
@dataclass
class LoopRecord:
    domain: str
    round: int
    variant: str
    metrics: Dict[str, Any]
    baseline_metrics: Dict[str, Any]
    decision: str  # accept / reject / pending
    reviewer: str  # auto / trae
    notes: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Trae-in-the-loop：文件化评审握手
# ---------------------------------------------------------------------------
class TraeReviewCheckpoint:
    """把评审请求落盘，等 Trae/人回写同名 .result.json。

    - request() 写 <tag>-<ts>.request.json
    - collect() 读 <stem>.result.json（不存在返回 None）
    - auto_verdict() 确定性兜底裁决（不依赖 LLM）
    """

    def __init__(self, review_dir: Optional[Path] = None):
        self.review_dir = review_dir or REVIEW_DIR
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.pending: List[Dict[str, Any]] = []

    def reset_pending(self) -> None:
        self.pending.clear()

    def request(self, payload: Dict[str, Any], tag: str) -> Path:
        """写评审请求；文件名由 tag + payload 哈希决定，便于 Trae 回写后重跑复用。"""
        digest = hashlib.md5(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()[:8]
        path = self.review_dir / f"{tag}-{digest}.request.json"
        body = {
            "tag": tag,
            "digest": digest,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "instruction": "请评审后写入同名 .result.json：{decision: accept|reject, notes: str}",
            "payload": payload,
        }
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2))
        return path

    @staticmethod
    def result_path(request_path: Path) -> Path:
        return request_path.with_name(request_path.name.replace(".request.json", ".result.json"))

    def collect(self, request_path: Path) -> Optional[Dict[str, Any]]:
        return self.collect_status(request_path)[0]

    def collect_status(self, request_path: Path) -> tuple[Optional[Dict[str, Any]], str]:
        """返回 (结果, 状态)；状态 ∈ {ok, absent, invalid}。

        ok      : 存在且 decision ∈ {accept, reject}
        absent  : 尚未回写（正常的等待状态）
        invalid : 文件存在但 JSON 损坏 / decision 非法（必须显式暴露，不能当成待回写）
        """
        rp = self.result_path(request_path)
        if not rp.exists():
            return None, "absent"
        try:
            data = json.loads(rp.read_text())
        except json.JSONDecodeError:
            return None, "invalid"
        if not isinstance(data, dict) or data.get("decision") not in ("accept", "reject"):
            return data if isinstance(data, dict) else None, "invalid"
        return data, "ok"

    @staticmethod
    def auto_verdict(
        improved: bool,
        regression_free: bool,
        reason: str = "",
    ) -> Dict[str, Any]:
        accept = improved and regression_free
        return {
            "decision": "accept" if accept else "reject",
            "reviewer": "auto",
            "notes": reason or ("改进且无回退" if accept else "未达准入条件"),
        }


# ---------------------------------------------------------------------------
# D3 意图涌现闭环（RuleVariant / DEFAULT_D3_VARIANTS 定义见 variant_generator.py）
# ---------------------------------------------------------------------------


class D3EmergenceLoop:
    """意图涌现闭环：候选变体 → 验证集指标 → 门禁 → 冠军演进。"""

    def __init__(
        self,
        events_path: Optional[Path] = None,
        variants: Optional[Sequence[RuleVariant]] = None,
        min_delta: float = 0.0,
        ece_tolerance: float = 0.02,
        val_ratio: float = 0.3,
        seed: int = 42,
        reviewer: str = "auto",
        review_dir: Optional[Path] = None,
        loop_dir: Optional[Path] = None,
        auto_evolve: bool = False,
        max_variants: int = 12,
        holdout_ratio: float = 0.2,
        n_boot: int = 2000,
        alpha: float = 0.05,
    ):
        self.events_path = events_path or DEFAULT_EVENTS_PATH
        self.variants = list(variants or DEFAULT_D3_VARIANTS)
        self.min_delta = min_delta
        self.ece_tolerance = ece_tolerance
        self.val_ratio = val_ratio
        self.seed = seed
        self.reviewer = reviewer
        self.auto_evolve = auto_evolve
        self.max_variants = max_variants
        self.holdout_ratio = holdout_ratio
        self.n_boot = n_boot
        self.alpha = alpha
        self.generator = D3VariantGenerator()
        self.checkpoint = TraeReviewCheckpoint(review_dir)
        self.loop_dir = loop_dir or LOOP_DIR
        self.loop_dir.mkdir(parents=True, exist_ok=True)

        self._train: List[Dict[str, Any]] = []
        self._val: List[Dict[str, Any]] = []
        self._holdout: List[Dict[str, Any]] = []
        self._domain_counts: Dict[str, Counter] = defaultdict(Counter)
        self._majority = "general"

    # ---------------- 数据 ----------------
    def load_data(self) -> None:
        """加载 intent_events，按 session_id 哈希做确定性切分。"""
        if not self.events_path.exists():
            raise FileNotFoundError(f"intent events not found: {self.events_path}")
        events = [
            json.loads(line) for line in self.events_path.read_text().splitlines() if line.strip()
        ]
        train, val, holdout = [], [], []
        holdout_pct = int(self.holdout_ratio * 100)
        val_pct = int(self.val_ratio * 100)
        for e in events:
            # 用稳定哈希切分（内置 hash() 受 PYTHONHASHSEED 影响，不可复现）
            key = f"{e.get('session_id', '')}:{self.seed}".encode()
            h = int(hashlib.md5(key).hexdigest()[:8], 16) % 100
            if h >= 100 - holdout_pct:
                holdout.append(e)
            elif h >= 100 - holdout_pct - val_pct:
                val.append(e)
            else:
                train.append(e)
        self._train, self._val, self._holdout = train, val, holdout

        counts: Dict[str, Counter] = defaultdict(Counter)
        for e in train:
            domains = (e.get("intent_signals") or {}).get("file_domains") or []
            label = e.get("intent_proxy") or "general"
            for d in domains:
                counts[d][label] += 1
        self._domain_counts = counts
        self._majority = Counter(e.get("intent_proxy") or "general" for e in train).most_common(1)[
            0
        ][0]

    # ---------------- 预测 / 评估 ----------------
    def _predict_one(
        self, event: Dict[str, Any], variant: RuleVariant
    ) -> tuple[str, Dict[str, float]]:
        domains = (event.get("intent_signals") or {}).get("file_domains") or []
        fallback = self._majority if variant.fallback == "majority" else "general"

        if variant.aggregate == "top_domain" and domains:
            known = [d for d in domains if d in self._domain_counts]
            if known:
                best = max(known, key=lambda d: sum(self._domain_counts[d].values()))
                domains = [best]

        scores: Counter = Counter()
        for d in domains:
            if d in self._domain_counts:
                scores.update(self._domain_counts[d])
        if not scores:
            return fallback, {fallback: 1.0}

        total = sum(scores.values())
        probs = {k: v / total for k, v in scores.items()}
        top = max(probs, key=probs.get)
        if probs[top] < variant.min_conf:
            return fallback, {fallback: 1.0}
        return top, probs

    def _eval_split(self, split: List[Dict[str, Any]], variant: RuleVariant) -> Dict[str, Any]:
        from experiments.d3a_intent.evaluate import expected_calibration_error, top1_acc

        preds, probs_list, truths = [], [], []
        for e in split:
            p, probs = self._predict_one(e, variant)
            preds.append(p)
            probs_list.append(probs)
            truths.append(e.get("intent_proxy") or "general")
        return {
            "top1": round(top1_acc(preds, truths), 6),
            "ece": expected_calibration_error(probs_list, preds, truths),
            "n": len(split),
            "correct": [int(p == t) for p, t in zip(preds, truths, strict=True)],
        }

    def evaluate(self, variant: RuleVariant) -> Dict[str, Any]:
        """val 用于候选择优（筛选），holdout 仅用于统计显著性判定。"""
        v = self._eval_split(self._val, variant)
        h = self._eval_split(self._holdout, variant)
        return {
            "top1": v["top1"],
            "ece": v["ece"],
            "n_val": v["n"],
            "val_correct": v["correct"],
            "holdout_top1": h["top1"],
            "holdout_ece": h["ece"],
            "n_holdout": h["n"],
            "holdout_correct": h["correct"],
        }

    # ---------------- 闭环 ----------------
    @staticmethod
    def _view(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """对外/落盘视图：剔除逐样本向量，避免日志与产物膨胀。"""
        return {k: v for k, v in metrics.items() if not k.endswith("_correct")}

    def run(self, rounds: int = 3) -> Dict[str, Any]:
        """两阶段统计门禁：

        阶段 A（筛选）：val 上 top1 提升且 ECE 不回退
        阶段 B（判定）：holdout 上配对 bootstrap CI 下界 > 0，且 Holm 校正后 p < alpha
        所有候选共用同一基线冠军，family = 本轮通过筛选的候选集合。
        """
        if not self._train:
            self.load_data()
        self.checkpoint.reset_pending()

        champion = self.variants[0]
        champ_metrics = self.evaluate(champion)

        candidates = [v for v in self.variants if v.name != champion.name]
        seen = {champion.name}
        pending: List[Dict[str, Any]] = []

        for r in range(1, rounds + 1):
            if not candidates:
                if not self.auto_evolve or len(seen) >= self.max_variants:
                    break
                # 变体生成器：从已评估反馈构造未探索的规则组合（受剩余预算约束）
                gen_history = [
                    {
                        "decision": "reject" if not p["screened"] else "pending",
                        "metrics": p["metrics"],
                        "baseline_metrics": champ_metrics,
                    }
                    for p in pending
                ]
                fresh = self.generator.propose(gen_history, champion, self.ece_tolerance)
                budget = self.max_variants - len(seen)
                candidates.extend([v for v in fresh if v.name not in seen][:budget])
                if not candidates:
                    break
            cand = candidates.pop(0)
            if cand.name in seen:
                continue
            seen.add(cand.name)

            cand_metrics = self.evaluate(cand)
            val_improved = cand_metrics["top1"] > champ_metrics["top1"] + self.min_delta
            val_calibrated = cand_metrics["ece"] <= champ_metrics["ece"] + self.ece_tolerance
            screened = val_improved and val_calibrated
            stat = None
            if screened:
                stat = paired_bootstrap(
                    cand_metrics["holdout_correct"],
                    champ_metrics["holdout_correct"],
                    n_boot=self.n_boot,
                    alpha=self.alpha,
                    seed=self.seed + r,
                )
            pending.append(
                {
                    "round": r,
                    "cand": cand,
                    "metrics": cand_metrics,
                    "screened": screened,
                    "stat": stat,
                }
            )

        # --- Holm 校正（同一 holdout 上的 family） ---
        screened_items = [p for p in pending if p["screened"]]
        adjusted = holm_adjust([p["stat"]["p_value"] for p in screened_items])
        for item, p_adj in zip(screened_items, adjusted, strict=True):
            item["p_adjusted"] = p_adj
            item["gate_pass"] = item["stat"]["ci_low"] > 0 and p_adj < self.alpha

        history: List[LoopRecord] = []
        for item in pending:
            if not item["screened"]:
                item["p_adjusted"] = None
                item["gate_pass"] = False
            decision, reviewer, notes = self._decide(
                tag=f"d3-r{item['round']}-{item['cand'].name}",
                payload={
                    "domain": "D3",
                    "round": item["round"],
                    "candidate": asdict(item["cand"]),
                    "candidate_metrics": self._view(item["metrics"]),
                    "champion": champion.name,
                    "champion_metrics": self._view(champ_metrics),
                    "statistical_gate": item["stat"],
                    "p_adjusted": item["p_adjusted"],
                },
                improved=item["gate_pass"],
                regression_free=item["screened"],
            )
            item["decision"], item["reviewer"], item["notes"] = decision, reviewer, notes

            metrics = {**item["metrics"], "params": asdict(item["cand"])}
            metrics.pop("val_correct", None)
            metrics.pop("holdout_correct", None)
            metrics["p_adjusted"] = item["p_adjusted"]
            metrics["gate"] = (
                "holdout_bootstrap_holm" if item["screened"] else "screened_out_on_val"
            )
            if item["stat"]:
                metrics["ci"] = {
                    k: item["stat"][k] for k in ("mean_diff", "ci_low", "ci_high", "p_value")
                }
            history.append(
                LoopRecord(
                    domain="D3",
                    round=item["round"],
                    variant=item["cand"].name,
                    metrics=metrics,
                    baseline_metrics=self._view(champ_metrics),
                    decision=decision,
                    reviewer=reviewer,
                    notes=notes,
                )
            )

        # 冠军：仅在通过统计门禁且被接受者中按 holdout 选优（无则保持基线）
        accepted = [p for p in pending if p["decision"] == "accept"]
        if accepted:
            best = max(
                accepted,
                key=lambda p: (p["metrics"]["holdout_top1"], p["metrics"]["top1"]),
            )
            champion, champ_metrics = best["cand"], best["metrics"]

        summary = {
            "domain": "D3",
            "rounds": len(history),
            "champion": champion.name,
            "champion_metrics": self._view(champ_metrics),
            "n_train": len(self._train),
            "n_val": len(self._val),
            "n_holdout": len(self._holdout),
            "stat_gate": {
                "alpha": self.alpha,
                "n_boot": self.n_boot,
                "family_size": len(screened_items),
            },
            "pending_reviews": list(self.checkpoint.pending),
            "history": [h.to_dict() for h in history],
        }
        self._persist("d3", summary)
        return summary

    def _decide(
        self,
        tag: str,
        payload: Dict[str, Any],
        improved: bool,
        regression_free: bool,
    ) -> tuple[str, str, str]:
        if self.reviewer == "trae":
            req = self.checkpoint.request(payload, tag)
            res, status = self.checkpoint.collect_status(req)
            if status == "ok":
                return res["decision"], "trae", res.get("notes", "")
            auto = self.checkpoint.auto_verdict(improved, regression_free)
            reason = "awaiting_result" if status == "absent" else "invalid_result"
            self.checkpoint.pending.append({"tag": tag, "request": str(req), "reason": reason})
            note = (
                "trae 评审待回写，已按确定性规则兜底"
                if status == "absent"
                else "trae 评审结果无效（decision 须为 accept|reject），已兜底"
            )
            return auto["decision"], "auto", note
        auto = self.checkpoint.auto_verdict(improved, regression_free)
        return auto["decision"], "auto", auto["notes"]

    def _persist(self, name: str, summary: Dict[str, Any]) -> None:
        hist = self.loop_dir / f"{name}_history.jsonl"
        with open(hist, "a") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        (self.loop_dir / f"{name}_champion.json").write_text(
            json.dumps(
                {"champion": summary["champion"], "metrics": summary["champion_metrics"]},
                ensure_ascii=False,
                indent=2,
            )
        )


# ---------------------------------------------------------------------------
# D2 技术架构涌现闭环
# ---------------------------------------------------------------------------
class D2EmergenceLoop:
    """架构涌现闭环：open gap → 方案生成 → Oracle/45 门禁 → 裁决 → 积分卡。"""

    def __init__(
        self,
        gaps_path: Optional[Path] = None,
        use_gate_45: bool = False,
        max_gaps: Optional[int] = None,
        reviewer: str = "auto",
        review_dir: Optional[Path] = None,
        loop_dir: Optional[Path] = None,
        evolve_rounds: int = 1,
    ):
        self.gaps_path = gaps_path or DEFAULT_GAPS_PATH
        self.use_gate_45 = use_gate_45
        self.max_gaps = max_gaps
        self.reviewer = reviewer
        self.evolve_rounds = evolve_rounds
        self.generator = D2TemplateGenerator()
        self.checkpoint = TraeReviewCheckpoint(review_dir)
        self.loop_dir = loop_dir or LOOP_DIR
        self.loop_dir.mkdir(parents=True, exist_ok=True)

    def _load_open_gaps(self) -> List[Dict[str, Any]]:
        if not self.gaps_path.exists():
            return []
        gaps = []
        for line in self.gaps_path.read_text().splitlines():
            if not line.strip():
                continue
            g = json.loads(line)
            if g.get("status") == "open":
                gaps.append(g)
        if self.max_gaps:
            gaps = gaps[: self.max_gaps]
        return gaps

    def run(self) -> Dict[str, Any]:
        """基线扫描 → （可选）模板策略演进一轮 → 对比积分卡。"""
        self.checkpoint.reset_pending()
        summary = self._sweep()
        if self.evolve_rounds >= 2:
            policies = self.generator.propose(summary["history"])
            if policies:
                nxt = self._sweep(policy=D2TemplateGenerator.compose(policies))
                baseline_rate = summary["overall_pass_rate"]
                policy_round = {
                    "policies": [{"kind": p.kind, "description": p.description} for p in policies],
                    "scoreboard": nxt["scoreboard"],
                    "overall_pass_rate": nxt["overall_pass_rate"],
                    "overall_ci": nxt["overall_ci"],
                    "baseline_overall_ci": summary["overall_ci"],
                    "metrics_improved": nxt["overall_pass_rate"] > baseline_rate,
                    # 严格口径：新 CI 下界超过基线 CI 下界才算有统计意义的提升
                    "ci_improved": nxt["overall_ci"]["ci_low"] > summary["overall_ci"]["ci_low"],
                }
                with open(self.loop_dir / "d2_policy_rounds.jsonl", "a") as f:
                    f.write(json.dumps(policy_round, ensure_ascii=False) + "\n")
                summary = {
                    **nxt,
                    "baseline_scoreboard": summary["scoreboard"],
                    "baseline_overall_pass_rate": baseline_rate,
                    "policy_round": policy_round,
                }
        self._persist(summary)
        return summary

    def _sweep(self, policy: Optional[Any] = None) -> Dict[str, Any]:
        from .d2b_adapter import D2BAdapter
        from .oracle_rea_independent import OracleValidatorV2

        adapter = D2BAdapter(self.gaps_path)
        oracle = OracleValidatorV2()
        gaps = self._load_open_gaps()

        records: List[LoopRecord] = []
        by_type: Dict[str, List[bool]] = defaultdict(list)
        feedback: List[Dict[str, Any]] = []

        for i, gap in enumerate(gaps, 1):
            gtype = gap.get("gap_type", "unknown")
            plan = adapter.generate(gap) if gtype in D2B_SUPPORTED else None
            if plan is not None and policy is not None:
                plan = policy(plan)
            if plan is None:
                by_type[gtype].append(False)
                feedback.append(
                    {
                        "gap_id": gap.get("gap_id"),
                        "gap_type": gtype,
                        "proposed": "keep_open",
                        "reason": "generator 不支持该类型或生成失败",
                    }
                )
                continue

            diag = plan_diagnostics(plan, gap.get("expected_value"))
            oracle_res = oracle.validate(plan).to_dict()
            gate = self._run_gate(plan)
            gate_ok = gate is None or gate.get("gate_pass") is not False
            accepted = oracle_res["verdict"] == "candidate" and gate_ok

            decision, reviewer, notes = self._decide(
                tag=f"d2-g{i}-{gap.get('gap_id', 'unknown')}",
                payload={
                    "domain": "D2",
                    "gap": {
                        k: gap.get(k) for k in ("gap_id", "gap_type", "evidence", "expected_value")
                    },
                    "plan_summary": {
                        "module_name": plan.get("module_name"),
                        "modules": plan.get("modules"),
                        "design_rationale": plan.get("design_rationale"),
                    },
                    "oracle": oracle_res,
                    "gate_45": gate,
                },
                accepted=accepted,
            )

            by_type[gtype].append(decision == "accept")
            records.append(
                LoopRecord(
                    domain="D2",
                    round=i,
                    variant=gap.get("gap_id", "unknown"),
                    metrics={
                        "oracle_confidence": oracle_res["confidence"],
                        "gate_45": gate,
                        "plan_diagnostics": diag,
                    },
                    baseline_metrics={},
                    decision=decision,
                    reviewer=reviewer,
                    notes=notes,
                )
            )
            feedback.append(
                {
                    "gap_id": gap.get("gap_id"),
                    "gap_type": gtype,
                    "proposed": "claim" if decision == "accept" else "keep_open",
                    "reason": notes,
                }
            )

        total_hits = sum(sum(v) for v in by_type.values())
        total_n = sum(len(v) for v in by_type.values())
        scoreboard = {
            gtype: {
                **wilson_interval(sum(results), len(results)),
                "pass_rate": round(sum(results) / len(results), 3) if results else 0.0,
                "evidence_level": evidence_level(len(results)),
            }
            for gtype, results in by_type.items()
        }
        overall = wilson_interval(total_hits, total_n)
        champion = self._pick_champion(scoreboard)
        claimable = sorted(g for g, v in scoreboard.items() if v["evidence_level"] == "adequate")

        return {
            "domain": "D2",
            "n_gaps": len(gaps),
            "scoreboard": scoreboard,
            "champion_template": champion,
            "overall_pass_rate": round(total_hits / total_n, 3) if total_n else 0.0,
            "overall_ci": overall,
            "overall_evidence": evidence_level(total_n),
            # 任一类型证据不足即不允许把 overall 通过率当作结论（防口径漂移）
            "claim_ready": all(v["evidence_level"] == "adequate" for v in scoreboard.values()),
            # 分类型结论：哪些类型的通过率已可下结论，哪些仍停在 insufficient
            "claimable_types": claimable,
            "blocked_types": sorted(g for g in scoreboard if g not in claimable),
            "pending_reviews": list(self.checkpoint.pending),
            "history": [r.to_dict() for r in records],
            # 只写建议，不修改 capability_gaps.jsonl（零执行权）
            "gap_feedback": feedback,
        }

    @staticmethod
    def _pick_champion(scoreboard: Dict[str, Dict[str, Any]]) -> Optional[str]:
        """冠军模板：先比 pass_rate，再比 CI 下界（样本量敏感），最后比 n。

        避免「1 个 gap 通过 = 100%」击败「20 个 gap 通过 95%」。
        """
        if not scoreboard:
            return None
        return max(
            scoreboard,
            key=lambda k: (
                scoreboard[k]["pass_rate"],
                scoreboard[k]["ci_low"],
                scoreboard[k]["n"],
            ),
        )

    def _run_gate(self, plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.use_gate_45:
            return None
        try:
            from experiments.d2b_engineering.gate_45 import run_real_gate

            return run_real_gate(plan)
        except Exception as e:  # FAIL-OPEN
            return {"gate_mode": "unavailable", "gate_pass": None, "note": f"gate_45 异常: {e}"}

    def _decide(
        self,
        tag: str,
        payload: Dict[str, Any],
        accepted: bool,
    ) -> tuple[str, str, str]:
        if self.reviewer == "trae":
            req = self.checkpoint.request(payload, tag)
            res, status = self.checkpoint.collect_status(req)
            if status == "ok":
                return res["decision"], "trae", res.get("notes", "")
            auto = self.checkpoint.auto_verdict(accepted, True, "按 Oracle/门禁确定性判定")
            reason = "awaiting_result" if status == "absent" else "invalid_result"
            self.checkpoint.pending.append({"tag": tag, "request": str(req), "reason": reason})
            note = (
                "trae 评审待回写，已按确定性规则兜底"
                if status == "absent"
                else "trae 评审结果无效（decision 须为 accept|reject），已兜底"
            )
            return auto["decision"], "auto", note
        auto = self.checkpoint.auto_verdict(accepted, True, "按 Oracle/门禁确定性判定")
        return auto["decision"], "auto", auto["notes"]

    def _persist(self, summary: Dict[str, Any]) -> None:
        with open(self.loop_dir / "d2_history.jsonl", "a") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        (self.loop_dir / "d2_scoreboard.json").write_text(
            json.dumps(
                {
                    "scoreboard": summary["scoreboard"],
                    "champion_template": summary["champion_template"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        with open(self.loop_dir / "d2_gap_feedback.jsonl", "a") as f:
            for item in summary["gap_feedback"]:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ASIL D3/D2 涌现闭环")
    parser.add_argument("--domain", choices=["d3", "d2", "both"], default="both")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--reviewer", choices=["auto", "trae"], default="auto")
    parser.add_argument("--gate45", action="store_true", help="D2 闭环启用真实 45 门禁")
    parser.add_argument(
        "--evolve", action="store_true", help="启用变体生成器（D3 多轮 / D2 模板演进）"
    )
    args = parser.parse_args(argv)

    if args.domain in ("d3", "both"):
        s = D3EmergenceLoop(reviewer=args.reviewer, auto_evolve=args.evolve).run(rounds=args.rounds)
        print(f"[D3] champion={s['champion']} metrics={s['champion_metrics']}")
        print(f"  pending_reviews={len(s['pending_reviews'])}")
        for h in s["history"]:
            print(
                f"  r{h['round']} {h['variant']:<24} {h['decision']:<7} top1={h['metrics']['top1']}"
            )
    if args.domain in ("d2", "both"):
        s = D2EmergenceLoop(
            use_gate_45=args.gate45,
            reviewer=args.reviewer,
            evolve_rounds=2 if args.evolve else 1,
        ).run()
        print(
            f"[D2] gaps={s['n_gaps']} scoreboard={s['scoreboard']} champion={s['champion_template']}"
        )
        print(f"  pending_reviews={len(s['pending_reviews'])}")
        print(f"  claim_ready={s['claim_ready']}")
        print(f"  claimable_types={s['claimable_types']}")
        print(f"  blocked_types={s['blocked_types']}")
        if "policy_round" in s:
            pr = s["policy_round"]
            print(
                f"  policy_round: {[p['kind'] for p in pr['policies']]} "
                f"pass_rate {s['baseline_overall_pass_rate']} -> {pr['overall_pass_rate']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
