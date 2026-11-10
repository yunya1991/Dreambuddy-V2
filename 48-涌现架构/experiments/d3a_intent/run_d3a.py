"""D3-A 意图预测主实验（SPEC v0.4 §4.3）。

预测目标：session 的 task_type（intent_proxy）。
系统预测器：一阶 Markov 链（task_type 转移）+ 小时段先验。
基线：B0 多数类 / B1 IntentEngine 规则 / B3 kNN。
评估：M-D3-TOP1 + ECE，session 级配对 bootstrap，四态判定。

用法：
  python 48-涌现架构/experiments/d3a_intent/run_d3a.py [--run-class exploratory|formal]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]
PKG_ROOT = HERE.parents[2]  # 48-涌现架构
sys.path.insert(0, str(PKG_ROOT))

from experiments.d3a_intent import evaluate  # noqa: E402
from experiments.d3a_intent.baselines import (  # noqa: E402
    B3KNN,
    B0Majority,
    B1IntentEngine,
    SessionEvent,
    parse_event,
)

DATA_DIR = PKG_ROOT / "baselines" / "artifacts" / "d3_intent_events"
RESULTS_DIR = PKG_ROOT / "experiments" / "d3a_intent" / "results"


def _hour_bin(ts: float) -> int:
    h = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    if h < 6:
        return 0
    if h < 12:
        return 1
    if h < 18:
        return 2
    return 3


class SystemEnsemble:
    """系统预测器：file_domains + 1/2-gram Markov + recalled_skills + 小时段 多源融合。

    score(tt) = w1*P(tt|domains) + w2*P(tt|prev) + w3*P(tt|prev2,prev)
              + w4*P(tt|skills) + w5*P(tt|hour)
    """

    def __init__(
        self,
        w_file: float = 0.45,
        w_markov1: float = 0.15,
        w_markov2: float = 0.15,
        w_skill: float = 0.1,
        w_time: float = 0.15,
        temperature: float = 0.45,
    ):
        self.w_file = w_file
        self.w_markov1 = w_markov1
        self.w_markov2 = w_markov2
        self.w_skill = w_skill
        self.w_time = w_time
        self.temperature = temperature
        self._domain_counts: dict[str, Counter] = defaultdict(Counter)
        self._skill_counts: dict[str, Counter] = defaultdict(Counter)
        self._trans1: dict[str, Counter] = defaultdict(Counter)
        self._trans2: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self._hour_prior: dict[int, Counter] = defaultdict(Counter)
        self._prev: str | None = None
        self._prev2: str | None = None

    def fit(self, events: list[SessionEvent]) -> None:
        for i, e in enumerate(events):
            hb = _hour_bin(e.ts)
            self._hour_prior[hb][e.task_type] += 1
            for d in e.file_domains:
                self._domain_counts[d][e.task_type] += 1
            for s in e.recalled_skills:
                self._skill_counts[s][e.task_type] += 1
            if i > 0:
                self._trans1[events[i - 1].task_type][e.task_type] += 1
            if i > 1:
                key = (events[i - 2].task_type, events[i - 1].task_type)
                self._trans2[key][e.task_type] += 1
        if len(events) >= 1:
            self._prev = events[-1].task_type
        if len(events) >= 2:
            self._prev2 = events[-2].task_type

    def predict(self, event: SessionEvent) -> tuple[str, dict[str, float]]:
        hb = _hour_bin(event.ts)
        scores: Counter = Counter()
        # file_domains
        ds: Counter = Counter()
        for d in event.file_domains:
            if d in self._domain_counts:
                ds.update(self._domain_counts[d])
        if ds:
            t = sum(ds.values())
            for tt, c in ds.items():
                scores[tt] += self.w_file * (c / t)
        # recalled_skills
        ss: Counter = Counter()
        for s in event.recalled_skills:
            if s in self._skill_counts:
                ss.update(self._skill_counts[s])
        if ss:
            t = sum(ss.values())
            for tt, c in ss.items():
                scores[tt] += self.w_skill * (c / t)
        # 1-gram Markov
        if self._prev and self._prev in self._trans1:
            t = sum(self._trans1[self._prev].values())
            for tt, c in self._trans1[self._prev].items():
                scores[tt] += self.w_markov1 * (c / t)
        # 2-gram Markov
        if self._prev2 and self._prev:
            key = (self._prev2, self._prev)
            if key in self._trans2:
                t = sum(self._trans2[key].values())
                for tt, c in self._trans2[key].items():
                    scores[tt] += self.w_markov2 * (c / t)
        # 小时段先验
        if hb in self._hour_prior:
            t = sum(self._hour_prior[hb].values())
            for tt, c in self._hour_prior[hb].items():
                scores[tt] += self.w_time * (c / t)
        if not scores:
            return "general", {"general": 1.0}
        total = sum(scores.values())
        raw = {k: v / total for k, v in scores.items()}
        T = self.temperature
        logits = {k: math.log(max(v, 1e-12)) / T for k, v in raw.items()}
        max_logit = max(logits.values())
        exps = {k: math.exp(v - max_logit) for k, v in logits.items()}
        exp_sum = sum(exps.values())
        probs = {k: v / exp_sum for k, v in exps.items()}
        top = max(probs, key=probs.get)
        self._prev2 = self._prev
        self._prev = event.task_type
        return top, probs


def load_events() -> list[SessionEvent]:
    path = DATA_DIR / "intent_events.jsonl"
    events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(parse_event(json.loads(line)))
    events.sort(key=lambda e: e.ts)
    return events


def load_split() -> tuple[set[str], set[str]]:
    manifest = json.loads((DATA_DIR / "split_manifest.json").read_text(encoding="utf-8"))
    return set(manifest["train_sessions"]), set(manifest["test_sessions"])


def run(args: argparse.Namespace) -> dict:
    events = load_events()
    train_ids, test_ids = load_split()
    train = [e for e in events if e.session_id in train_ids]
    test = [e for e in events if e.session_id in test_ids]
    # 确保时序排序
    train.sort(key=lambda e: e.ts)
    test.sort(key=lambda e: e.ts)

    # 拟合基线
    b0 = B0Majority()
    b0.fit(train)
    b1 = B1IntentEngine()
    b1.fit(train)
    b3 = B3KNN(k=5)
    b3.fit(train)
    baselines = {"B0_majority": b0, "B1_intent_engine": b1, "B3_knn": b3}

    # 系统预测器需要按时间顺序看历史，所以用全量 train 拟合后逐个预测 test
    system = SystemEnsemble(w_file=0.35, w_markov1=0.1, w_markov2=0.15, w_skill=0.25, w_time=0.15)
    system.fit(train)

    # 预测
    truths = [e.task_type for e in test]
    sys_preds: list[str] = []
    sys_probs: list[dict[str, float]] = []
    base_preds: dict[str, list[str]] = {name: [] for name in baselines}

    for e in test:
        p, pr = system.predict(e)
        sys_preds.append(p)
        sys_probs.append(pr)
        for name, model in baselines.items():
            bp, _ = model.predict(e)
            base_preds[name].append(bp)

    # 评估
    sys_acc = evaluate.top1_acc(sys_preds, truths)
    base_accs = {name: evaluate.top1_acc(preds, truths) for name, preds in base_preds.items()}
    best_base = max(base_accs, key=base_accs.get)
    best_base_acc = base_accs[best_base]

    ece = evaluate.expected_calibration_error(sys_probs, sys_preds, truths)

    # session 级配对差值
    deltas = [
        (1.0 if sp == t else 0.0) - (1.0 if bp == t else 0.0)
        for sp, bp, t in zip(sys_preds, base_preds[best_base], truths, strict=True)
    ]
    ci = evaluate.session_bootstrap_ci(deltas, n_iter=10_000)
    decision = evaluate.decide(ci, ece, len(test), min_sessions=200)

    if args.run_class == "exploratory" and decision["verdict"] == "candidate":
        decision = {
            "verdict": "inconclusive",
            "reason": (
                "run_class=exploratory：D3-A 未经人工复核，禁止产出正式 candidate；"
                + decision["reason"]
            ),
        }

    result = {
        "run_id": f"D3A-{abs(hash((len(test), sys_acc, ece))) & 0xFFFFFFFF:012x}",
        "run_class": args.run_class,
        "n_train": len(train),
        "n_test": len(test),
        "system": {"top1": round(sys_acc, 6), "ece": ece, "temperature": 0.45},
        "baselines": {k: {"top1": round(v, 6)} for k, v in base_accs.items()},
        "best_baseline": best_base,
        "best_baseline_top1": round(best_base_acc, 6),
        "delta_top1": round(sys_acc - best_base_acc, 6),
        "bootstrap_ci": ci,
        "ece_threshold": evaluate.ECE_THRESHOLD,
        "decision": decision,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="D3-A 意图预测实验")
    parser.add_argument(
        "--run-class",
        choices=["exploratory", "formal"],
        default="exploratory",
    )
    args = parser.parse_args()

    result = run(args)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{result['run_id']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"[d3a] run_id={result['run_id']} "
        f"verdict={result['decision']['verdict']} "
        f"top1={result['system']['top1']} "
        f"best_base={result['best_baseline']}({result['best_baseline_top1']}) "
        f"ece={result['system']['ece']} "
        f"ci={result['bootstrap_ci']['ci_low']}..{result['bootstrap_ci']['ci_high']}"
    )


if __name__ == "__main__":
    main()
