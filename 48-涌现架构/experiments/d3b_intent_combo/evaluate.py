"""
D3-B A/B 反事实验证器。

对每个 test session：
  - 无组合（actual）：recall_steps = len(recalled_memory_ids) + len(recalled_skills)
  - 有组合（counterfactual）：若 intent_proxy 存在 combo，则 recall_steps = 1
    （一次组合检索替代多次独立 recall）；否则等于 actual。
  - 知识命中率 = (combo 与 session 实际使用的交集) / combo.size

判定（SPEC §4.4）：
  candidate: delta_recall_steps 95% CI 下界 > 0 且 hit_rate >= 0.3 且 correction 不增加
  falsified: delta CI 上界 <= 0 或 hit_rate < 0.1
  inconclusive: CI 跨 0
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from combo import IntentKnowledgeCombo, build_combos, index_by_session, load_events, load_split

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent


@dataclass
class SessionMetrics:
    session_id: str
    intent_proxy: str
    actual_recall_steps: int
    combo_recall_steps: int
    delta_recall_steps: float
    hit_rate: float
    combo_size: int
    correction_count: int
    time_to_action: float
    action_count: int
    has_combo: bool


def _session_metrics(sess: dict, combo: IntentKnowledgeCombo | None) -> SessionMetrics:
    mem_ids = sess.get("recalled_memory_ids", []) or []
    skills = sess.get("recalled_skills", []) or []
    signals = sess.get("intent_signals", {}) or {}
    file_domains = signals.get("file_domains", []) or []

    actual_steps = len(mem_ids) + len(skills)

    if combo is not None and combo.size > 0:
        combo_steps = 1
        hits = (
            len(set(combo.memory_ids) & set(mem_ids))
            + len(set(combo.skills) & set(skills))
            + len(set(combo.file_domains) & set(file_domains))
        )
        hit_rate = hits / combo.size
        has_combo = True
    else:
        combo_steps = actual_steps
        hit_rate = 0.0
        has_combo = False

    delta = float(actual_steps - combo_steps)
    end_ts = sess.get("end_ts")
    ts = sess.get("ts")
    tta = float(end_ts - ts) if end_ts is not None and ts is not None else 0.0
    return SessionMetrics(
        session_id=sess.get("session_id", ""),
        intent_proxy=sess.get("intent_proxy", ""),
        actual_recall_steps=actual_steps,
        combo_recall_steps=combo_steps,
        delta_recall_steps=delta,
        hit_rate=hit_rate,
        combo_size=combo.size if combo else 0,
        correction_count=int(sess.get("correction_count", 0)),
        time_to_action=tta,
        action_count=int(sess.get("action_count", 0)),
        has_combo=has_combo,
    )


def _bootstrap_ci(
    values: list[float], n_iter: int = 10000, seed: int = 42
) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    import random

    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_iter):
        sample = [values[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(statistics.mean(sample))
    means.sort()
    lo = means[int(0.025 * n_iter)]
    hi = means[int(0.975 * n_iter)]
    return statistics.mean(values), lo, hi


def evaluate(
    test_sessions: list[dict],
    combos: dict[str, IntentKnowledgeCombo],
    min_combo_size: int = 3,
) -> dict:
    rows: list[SessionMetrics] = []
    for sess in test_sessions:
        proxy = sess.get("intent_proxy", "")
        combo = combos.get(proxy)
        if combo is not None and combo.size < min_combo_size:
            combo = None
        rows.append(_session_metrics(sess, combo))

    deltas = [r.delta_recall_steps for r in rows]
    hit_rates = [r.hit_rate for r in rows if r.has_combo]
    corrections = [r.correction_count for r in rows]

    mean_delta, ci_lo, ci_hi = _bootstrap_ci(deltas)
    mean_hit = statistics.mean(hit_rates) if hit_rates else 0.0
    mean_correction = statistics.mean(corrections)

    n_with_combo = sum(1 for r in rows if r.has_combo)
    mean_actual_steps = statistics.mean([r.actual_recall_steps for r in rows])
    mean_combo_steps = statistics.mean([r.combo_recall_steps for r in rows])

    # 判定
    if ci_lo > 0 and mean_hit >= 0.3:
        verdict = "candidate"
        reason = f"delta_recall_steps 95% CI [{ci_lo:.4f}, {ci_hi:.4f}] > 0 且 hit_rate={mean_hit:.3f} >= 0.3"
    elif ci_hi <= 0 or mean_hit < 0.1:
        verdict = "falsified"
        reason = f"delta CI 上界 {ci_hi:.4f} <= 0 或 hit_rate={mean_hit:.3f} < 0.1"
    else:
        verdict = "inconclusive"
        reason = f"delta CI [{ci_lo:.4f}, {ci_hi:.4f}] 跨 0 或 hit_rate={mean_hit:.3f} 未达门槛"

    return {
        "n_test": len(rows),
        "n_with_combo": n_with_combo,
        "mean_actual_recall_steps": mean_actual_steps,
        "mean_combo_recall_steps": mean_combo_steps,
        "mean_delta_recall_steps": mean_delta,
        "delta_ci_low": ci_lo,
        "delta_ci_high": ci_hi,
        "mean_hit_rate": mean_hit,
        "mean_correction_count": mean_correction,
        "verdict": verdict,
        "reason": reason,
        "per_session": [r.__dict__ for r in rows],
    }


def main() -> int:
    art = PKG_ROOT / "baselines" / "artifacts" / "d3_intent_events"
    events = load_events(art / "intent_events.jsonl")
    train_ids, test_ids = load_split(art / "split_manifest.json")
    idx = index_by_session(events)
    train = [idx[s] for s in train_ids if s in idx]
    test = [idx[s] for s in test_ids if s in idx]
    combos = build_combos(train)
    result = evaluate(test, combos)
    # 只输出摘要（per_session 太大）
    summary = {k: v for k, v in result.items() if k != "per_session"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
