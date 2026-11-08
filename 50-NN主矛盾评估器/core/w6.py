# R2-04: W6 维度权重学习器（50 SPEC §5.1，独立实现，独立存储）。
#
# 样本 schema：decision_id, evidence_id, dimension, intent, provenance,
#              predicted_direction, confidence, realized_return, label_ts。
# 冷启动：前 500 样本等权默认值，w6_state=cold_start，不得用于 A/B 结论。
# 权重截断 [0.3, 1.5]；触发：>=500 条带标签样本 / 24h。
# 存储：runtime/w6/ 独立（samples.jsonl + weights.json + state.json）；禁止写 23 的 contradiction_samples.json。
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# 冷启动阈值（SPEC §5.1：前 500 样本等权）
COLD_START_SAMPLES = 500
# 权重截断区间（SPEC §5.1）
WEIGHT_MIN = 0.3
WEIGHT_MAX = 1.5
# 学习触发：>=500 带标签样本 / 24h
TRIGGER_WINDOW_SEC = 24 * 3600

SAMPLE_FIELDS = (
    "decision_id",
    "evidence_id",
    "dimension",
    "intent",
    "provenance",
    "predicted_direction",
    "confidence",
    "realized_return",
    "label_ts",
)


def _clamp(value: float) -> float:
    return max(WEIGHT_MIN, min(WEIGHT_MAX, value))


def validate_sample(sample: dict[str, Any]) -> bool:
    # 样本合法性：九字段齐全 + realized_return 已标注（非 None）。
    if not isinstance(sample, dict):
        return False
    for f in SAMPLE_FIELDS:
        if sample.get(f) is None:
            return False
    return True


def default_weights() -> dict[str, float]:
    # 冷启动等权默认值。
    return {"D1": 1.0, "D2": 1.0, "D3": 1.0, "D4": 1.0, "C6": 1.0, "C7": 1.0, "C8": 1.0, "NEWS": 1.0}


class W6Store:
    # W6 独立存储：samples.jsonl（追加）+ weights.json + state.json（崩溃恢复）。
    # 显式目录注入，不硬编码绝对路径；禁止写 23 的任何文件。

    def __init__(self, store_dir: str | Path):
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._samples_path = self._dir / "samples.jsonl"
        self._weights_path = self._dir / "weights.json"
        self._state_path = self._dir / "state.json"

    # ---- 样本 ----
    def append_sample(self, sample: dict[str, Any]) -> bool:
        if not validate_sample(sample):
            return False
        with open(self._samples_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(sample, ensure_ascii=False))
            f.write(chr(10))
        return True

    def load_samples(self) -> list[dict[str, Any]]:
        if not self._samples_path.exists():
            return []
        samples = []
        for line in self._samples_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except ValueError:
                continue
        return samples

    # ---- 权重 ----
    def load_weights(self) -> dict[str, float]:
        if not self._weights_path.exists():
            return default_weights()
        try:
            data = json.loads(self._weights_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("weights"), dict):
                return {k: _clamp(float(v)) for k, v in data["weights"].items()}
        except (OSError, ValueError, TypeError):
            pass
        return default_weights()

    def save_weights(self, weights: dict[str, float], state: str, n_samples: int) -> None:
        payload = {
            "weights": {k: round(_clamp(float(v)), 6) for k, v in weights.items()},
            "w6_state": state,
            "n_samples": n_samples,
            "updated_ts": time.time(),
        }
        self._weights_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- 状态（崩溃恢复）----
    def load_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {}
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict[str, Any]) -> None:
        self._state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def learn_weights(samples: list[dict[str, Any]]) -> tuple[dict[str, float], str]:
    # 从带标签样本学习维度权重：方向正确性按维度聚合。
    # 返回 (weights, w6_state)；样本 < 500 -> 等权 + cold_start。
    labeled = [s for s in samples if validate_sample(s)]
    if len(labeled) < COLD_START_SAMPLES:
        return default_weights(), "cold_start"
    stats: dict[str, list[float]] = {}
    for s in labeled:
        dim = str(s.get("dimension"))
        correct = (str(s.get("predicted_direction")) == "long" and float(s.get("realized_return") or 0.0) > 0) or (
            str(s.get("predicted_direction")) == "short" and float(s.get("realized_return") or 0.0) < 0
        )
        stats.setdefault(dim, []).append(1.0 if correct else 0.0)
    weights = default_weights()
    for dim, outcomes in stats.items():
        acc = sum(outcomes) / len(outcomes)
        # 方向正确率 0.5 -> 权重 1.0（中性）；线性映射 [0,1] -> [0.3,1.5]
        weights[dim] = _clamp(0.5 + acc)
    return weights, "learning"


def refresh(store: W6Store) -> dict[str, Any]:
    # 刷新入口：读样本 -> 学习 -> 落盘权重 -> 返回 (weights, w6_state)。
    samples = store.load_samples()
    weights, state = learn_weights(samples)
    store.save_weights(weights, state, len(samples))
    return {"weights": weights, "w6_state": state, "n_samples": len(samples)}
