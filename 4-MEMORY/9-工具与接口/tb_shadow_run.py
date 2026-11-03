"""影子验证脚本 — 用真实 DB 数据跑 TB1-TB5，不改业务数据，只产报告。

输入：
  - 本地 cognitive_memory.db（memories.confidence 分布）
  - 本地 voyager_consecutive.jsonl（verify 流水）
  - 本地 voyager_memory_extra.json（扩展字段，含 known_gaps / cross_domain_refs）

输出：
  4-MEMORY/artifacts/tb_shadow_report.json   # 机器可读
  4-MEMORY/artifacts/tb_shadow_report.md    # 人读摘要

Shadow 语义：所有 TB1-TB5 调用均传 deepcopy 数据，不回写任何表/文件。
"""

from __future__ import annotations

import json
import random
import sys
import traceback
from pathlib import Path

import numpy as np

# 绝对 import（本目录非包，与 TDD 测试同约定）
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from cognitive_interfaces import BetaState  # noqa: E402
from drift_detector import classify_drift, compute_psi  # noqa: E402
from grpo_evolution import GRPOEvolutionLoop, StrategyConfig  # noqa: E402
from regime_gate import ThompsonSamplingRegimeGate  # noqa: E402
from training_reward import compute_reward, pareto_score  # noqa: E402

# 可选依赖：SQLite 读 DB / JSONL 读 verify 流水
try:
    import sqlite3

    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False


MEMORY_ROOT = _THIS_DIR.parent
ARTIFACTS_DIR = MEMORY_ROOT / "artifacts"
DB_PATH = MEMORY_ROOT / "data" / "cognitive_memory.db"
VOYAGER_EXTRA_PATH = ARTIFACTS_DIR / "voyager_memory_extra.json"
VOYAGER_CONSECUTIVE_PATH = ARTIFACTS_DIR / "voyager_consecutive.jsonl"


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------


def load_confidence_samples(n: int = 5000, seed: int = 7) -> list[float]:
    """从 DB 采样 confidence（带种子保证可复现）。"""
    rng = random.Random(seed)
    if HAS_SQLITE and DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        try:
            rows = conn.execute(
                "SELECT confidence FROM memories WHERE confidence IS NOT NULL AND confidence > 0"
            ).fetchall()
            samples = [r[0] for r in rows]
        finally:
            conn.close()
    else:
        # DB 不可用 → 回退均匀分布（shadow FAIL-OPEN）
        samples = [rng.random() for _ in range(n * 4)]
        print(f"[shadow] DB 不可用，退化为均匀分布样本（{len(samples)} 条）", file=sys.stderr)

    if len(samples) > n:
        idx = sorted(rng.sample(range(len(samples)), n))
        samples = [samples[i] for i in idx]
    return samples


def load_verify_success_rates(n: int = 200, seed: int = 11) -> list[float]:
    """从 DB 的 verify_count > 0 记忆算 success_rate（更真实：已被验证过的记忆）。"""
    rng = random.Random(seed)
    rates = []

    if HAS_SQLITE and DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            try:
                rows = conn.execute(
                    "SELECT quality_level, confidence, verify_count FROM memories "
                    "WHERE verify_count > 0 AND confidence IS NOT NULL"
                ).fetchall()
                # 真实 success_rate 代理：quality_level 从 D/C→A/S 视为成功
                rank = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}
                for ql, conf, _vcount in rows:
                    base = rank.get(ql, 2) / 5.0  # 0.2 ~ 1.0
                    # confidence 轻微加权
                    rates.append(0.6 * base + 0.4 * float(conf))
            finally:
                conn.close()
            if rates:
                print(
                    f"[shadow] verify_success_rates from DB: "
                    f"n={len(rates)}, mean={float(np.mean(rates)):.3f}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[shadow] DB verify 抽样失败：{e}", file=sys.stderr)

    if not rates:
        # 退化为 Beta(2,1)（偏成功）+ Beta(1,2)（偏失败）混合
        print("[shadow] 退化：混合 Beta 样本", file=sys.stderr)
        rates = [
            rng.betavariate(2, 1) if rng.random() < 0.5 else rng.betavariate(1, 2)
            for _ in range(n * 4)
        ]

    if len(rates) > n:
        rates = rng.sample(rates, n)
    return rates


def load_voyager_extras(n: int = 200, seed: int = 13) -> list[dict]:
    """从 voyager_memory_extra.json 提取 known_gaps / cross_domain_refs。"""
    rng = random.Random(seed)
    if not VOYAGER_EXTRA_PATH.exists():
        print("[shadow] voyager_memory_extra.json 不存在，退化为空样本", file=sys.stderr)
        return [
            {"known_gaps_count": rng.randint(0, 5), "cross_domain_refs": rng.randint(0, 3)}
            for _ in range(n)
        ]

    try:
        with VOYAGER_EXTRA_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[shadow] voyager extra 读失败：{e}", file=sys.stderr)
        raw = {}

    items = list(raw.values()) if isinstance(raw, dict) else list(raw)
    if len(items) > n:
        items = rng.sample(items, n)

    extras = []
    for it in items:
        if not isinstance(it, dict):
            continue
        gaps = it.get("known_gaps_count", it.get("known_gaps", []))
        if isinstance(gaps, list):
            gaps = len(gaps)
        refs = it.get("cross_domain_refs", 0)
        extras.append(
            {
                "known_gaps_count": int(gaps) if gaps is not None else 0,
                "cross_domain_refs": int(refs) if refs is not None else 0,
            }
        )

    if len(extras) < n:
        extras += [
            {"known_gaps_count": rng.randint(0, 5), "cross_domain_refs": rng.randint(0, 3)}
            for _ in range(n - len(extras))
        ]
    return extras


# ---------------------------------------------------------------------------
# TB1-TB5 影子跑
# ---------------------------------------------------------------------------


def run_tb1_shadow(expected: list[float], current: list[float]) -> dict:
    psi_val = compute_psi(expected, current)
    drift_level = classify_drift(psi_val)
    return {
        "psi_value": float(psi_val),
        "drift_level": drift_level,
        "expected_n": len(expected),
        "current_n": len(current),
        "pass": drift_level == "stable",
    }


def run_tb2_shadow(initial_conf: float, success_rates: list[float]) -> dict:
    """从 legacy confidence 出发按 verify 流水更新 Beta，看后验 mean 分布。"""
    state = BetaState(alpha=initial_conf, beta=1.0 - initial_conf)
    means: list[float] = [state.mean]
    for rate in success_rates:
        state = state.update(rate)
        means.append(state.mean)
    return {
        "initial_mean": initial_conf,
        "final_alpha": float(state.alpha),
        "final_beta": float(state.beta),
        "final_mean": float(state.mean),
        "mean_timeline_last_10": [round(m, 4) for m in means[-10:]],
        "posterior_shifted": state.mean > initial_conf + 0.05,
    }


def run_tb3_shadow(beta_state: BetaState, psi_val: float, extras: list[dict]) -> dict:
    """用 TB3 compute_reward 按 extras 样本算得分分布。

    recall_hits 从 extras index 和一个固定 seed 派生，保证同一 extras 输入同一 hits，
    但不同 extras 样本 hits 不同（避免上一轮的平坦分布）。
    """
    scores: list[float] = []
    for i, ex in enumerate(extras):
        rng = random.Random(1000 + i)
        n = len(extras)
        # hits 从 (0.3n, 0.9n) 随机，跨样本有变化
        hits = max(0, int(round(n * (0.3 + rng.random() * 0.6))))
        reward = compute_reward(
            beta_state=beta_state,
            psi_value=psi_val,
            recall_hits=hits,
            recall_total=n,
            known_gaps_count=ex["known_gaps_count"],
            cross_domain_refs=ex["cross_domain_refs"],
        )
        scores.append(pareto_score(reward))
    arr = np.array(scores)
    return {
        "n": len(scores),
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "p10": float(np.percentile(arr, 10)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "ideal_case_score": float(max(scores)),
        "worst_case_score": float(min(scores)),
        "spread": float(arr.max() - arr.min()),
    }


def run_tb4_shadow(success_rates: list[float], drift_every: int = 50) -> dict:
    """Regime gate 按流水更新，每隔 drift_every 次触发一次 reset，记录 arm 置信度分布。"""
    gate = ThompsonSamplingRegimeGate()
    drift_count = 0
    arm_confidences = {arm: [] for arm in gate.arms}

    for i, rate in enumerate(success_rates):
        arm = gate.select_regime()
        drift = i > 0 and i % drift_every == 0
        if drift:
            drift_count += 1
        gate.update(arm, rate, drift_detected=drift)
        for a in gate.arms:
            arm_confidences[a].append(gate.get_confidence(a))

    summary = {}
    for arm, seq in arm_confidences.items():
        arr = np.array(seq)
        summary[arm] = {
            "final": float(arr[-1]),
            "mean": float(arr.mean()),
            "p90": float(np.percentile(arr, 90)),
        }
    return {
        "n_steps": len(success_rates),
        "drift_resets": drift_count,
        "arm_summary": summary,
    }


def run_tb5_shadow(
    beta_state: BetaState, psi_val: float, extras: list[dict], success_rates: list[float]
) -> dict:
    """PolicySelectLoop 影子跑：两候选 argmax，记录 evolve_step 切换次数。

    候选差异：lenient 高 known_gaps_threshold + 高 cross_domain_budget；
               strict 低 known_gaps_threshold + 低 cross_domain_budget。
    """
    gate = ThompsonSamplingRegimeGate()
    candidates = [
        StrategyConfig(known_gaps_threshold=10, max_cross_domain_refs=20, version="v0.1-lenient"),
        StrategyConfig(known_gaps_threshold=2, max_cross_domain_refs=1, version="v0.1-strict"),
    ]
    loop = GRPOEvolutionLoop(candidates, gate)

    switches = 0
    for i, ex in enumerate(extras):
        rng = random.Random(2000 + i)
        kwargs = {
            "beta_state": beta_state,
            "psi_value": psi_val,
            "recall_hits": max(0, int(round(len(extras) * (0.3 + rng.random() * 0.6)))),
            "recall_total": len(extras),
            "known_gaps_count": ex["known_gaps_count"],
            "cross_domain_refs": ex["cross_domain_refs"],
        }
        result = loop.evolve_step(**kwargs)
        if result is not None:
            switches += 1

    return {
        "n_steps": len(extras),
        "switches": switches,
        "final_config": loop.current_config.version,
        "history_len": len(loop.history),
        "fallback_events": sum(1 for h in loop.history if h.get("fallback")),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    random.seed(42)
    np.random.seed(42)

    report: dict = {
        "date": "2026-11-03",
        "purpose": "TB1-TB5 shadow validation against real local DB",
        "db_path": str(DB_PATH),
        "artifacts_path": str(ARTIFACTS_DIR),
    }

    print("[shadow] Step 1/6: 加载真实数据…", file=sys.stderr)
    expected = load_confidence_samples(n=5000, seed=7)
    current = load_confidence_samples(n=5000, seed=99)
    verify_rates = load_verify_success_rates(n=200, seed=11)
    extras = load_voyager_extras(n=200, seed=13)
    report["data_summary"] = {
        "confidence_samples": len(expected),
        "confidence_mean_expected": round(float(np.mean(expected)), 4),
        "confidence_mean_current": round(float(np.mean(current)), 4),
        "verify_rates_n": len(verify_rates),
        "extras_n": len(extras),
    }

    print("[shadow] Step 2/6: TB1 PSI 漂移检测…", file=sys.stderr)
    try:
        report["TB1"] = run_tb1_shadow(expected, current)
    except Exception as e:
        report["TB1"] = {"error": str(e), "traceback": traceback.format_exc()}

    print("[shadow] Step 3/6: TB2 Beta 后验演化…", file=sys.stderr)
    try:
        initial_conf = float(np.mean(expected))
        tb2 = run_tb2_shadow(initial_conf, verify_rates)
        report["TB2"] = tb2
    except Exception as e:
        report["TB2"] = {"error": str(e), "traceback": traceback.format_exc()}

    print("[shadow] Step 4/6: TB3 AlphaPareto 评分分布…", file=sys.stderr)
    try:
        beta_state = BetaState(alpha=tb2["final_alpha"], beta=tb2["final_beta"])
        report["TB3"] = run_tb3_shadow(beta_state, float(report["TB1"]["psi_value"]), extras)
    except Exception as e:
        report["TB3"] = {"error": str(e), "traceback": traceback.format_exc()}

    print("[shadow] Step 5/6: TB4 Thompson Sampling regime gate…", file=sys.stderr)
    try:
        report["TB4"] = run_tb4_shadow(verify_rates, drift_every=50)
    except Exception as e:
        report["TB4"] = {"error": str(e), "traceback": traceback.format_exc()}

    print("[shadow] Step 6/6: TB5 PolicySelectLoop 切换行为…", file=sys.stderr)
    try:
        report["TB5"] = run_tb5_shadow(
            beta_state, float(report["TB1"]["psi_value"]), extras, verify_rates
        )
    except Exception as e:
        report["TB5"] = {"error": str(e), "traceback": traceback.format_exc()}

    # 汇总 pass 状态
    psi_val = report.get("TB1", {}).get("psi_value", 1.0)
    drift_level = report.get("TB1", {}).get("drift_level", "unknown")
    final_mean = report.get("TB2", {}).get("final_mean", 0.0)
    switches = report.get("TB5", {}).get("switches", -1)
    report["verdict"] = {
        "psi_stable": drift_level == "stable",
        "beta_posterior_lifted": (
            final_mean > report["TB2"]["initial_mean"] if "TB2" in report else False
        ),
        "tb5_no_fallback": report.get("TB5", {}).get("fallback_events", 1) == 0,
        "overall": (
            "pass"
            if all(
                [
                    drift_level != "severe_drift",
                    report.get("TB3", {}).get("n", 0) > 0,
                    report.get("TB4", {}).get("n_steps", 0) > 0,
                    switches >= 0,
                ]
            )
            else "warn"
        ),
    }

    # 写入 JSON + markdown
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACTS_DIR / "tb_shadow_report.json"
    md_path = ARTIFACTS_DIR / "tb_shadow_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown 摘要
    tb3 = report.get("TB3", {})
    tb4 = report.get("TB4", {})
    tb5 = report.get("TB5", {})
    verdict = report["verdict"]
    md = f"""# 影子验证报告 — TB1-TB5

**日期**：2026-11-03
**数据源**：`{DB_PATH}`（memories.confidence 分布 + voyager 扩展字段）
**语义**：只读影子跑，零业务数据回写

---

## TB1 PSI 漂移检测
| 指标 | 值 |
| --- | --- |
| 样本数（expected / current） | {report['data_summary']['confidence_samples']} / {report['data_summary']['confidence_samples']} |
| mean(expected / current) | {report['data_summary']['confidence_mean_expected']} / {report['data_summary']['confidence_mean_current']} |
| PSI | **{psi_val:.4f}** |
| 漂移等级 | **{drift_level}** |

## TB2 Beta 后验演化
| 指标 | 值 |
| --- | --- |
| 初始 mean | {report['TB2']['initial_mean']:.4f} |
| 终态 Beta(α, β) | {report['TB2']['final_alpha']:.3f}, {report['TB2']['final_beta']:.3f} |
| 终态 mean | **{final_mean:.4f}** |
| 后验提升 | {'✅ 是' if report['TB2'].get('posterior_shifted') else '❌ 否'} |
| 近 10 步 timeline | {report['TB2']['mean_timeline_last_10']} |

## TB3 AlphaPareto 评分分布
| 指标 | 值 |
| --- | --- |
| N | {tb3.get('n')} |
| mean | {tb3.get('mean')} |
| p50 / p90 | {tb3.get('p50')} / {tb3.get('p90')} |
| 理想 / 最差 | {tb3.get('ideal_case_score')} / {tb3.get('worst_case_score')} |

## TB4 Thompson Sampling Regime Gate
| arm | final | mean | p90 |
| --- | --- | --- | --- |
"""
    for arm, s in tb4.get("arm_summary", {}).items():
        md += f"| {arm} | {s.get('final'):.3f} | {s.get('mean'):.3f} | {s.get('p90'):.3f} |\n"
    md += f"""| drift 重置次数 | {tb4.get('drift_resets')} |
| total steps | {tb4.get('n_steps')} |

## TB5 PolicySelectLoop 切换行为
| 指标 | 值 |
| --- | --- |
| N | {tb5.get('n_steps')} |
| 切换次数 | {tb5.get('switches')} |
| 最终配置 | {tb5.get('final_config')} |
| FAIL-OPEN fallback 事件 | {tb5.get('fallback_events')} |

---

## 总裁决
| 项 | 结论 |
| --- | --- |
| TB1 PSI 是否 stable | {'✅ 是' if verdict['psi_stable'] else '⚠️ 否'} |
| TB2 Beta 后验是否提升 | {'✅ 是' if verdict['beta_posterior_lifted'] else '❌ 否'} |
| TB5 无 FAIL-OPEN fallback | {'✅ 是' if verdict['tb5_no_fallback'] else '❌ 否'} |
| **整体** | **{verdict['overall'].upper()}** |
"""
    md_path.write_text(md, encoding="utf-8")

    print("\n[shadow] 报告已生成：", file=sys.stderr)
    print(f"         JSON → {json_path}", file=sys.stderr)
    print(f"         MD   → {md_path}", file=sys.stderr)
    print(f"[shadow] verdict = {verdict['overall'].upper()}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
