"""collect_domain_discovery_data.py — Phase A 标注数据管线 MVP

SPEC-L0-L1-DOMAIN-DISCOVERY v0.1 §3.1 标注 JSONL schema + §3.2 采集管线。
职责：把 AgentMailShadow trajectory + TB1 drift_detector + TB2 BetaState
打包成 `domain_discovery_training.jsonl`，供 Phase B DomainCouplingHead 训练消费。

MVP 约束：
  - 纯静态：TB1 psi / TB2 mean 从静态先验合成（Phase A 起始数据，真实值
    等 COMM-SHADOW 影子观察满 1 天后再切换到实值）。
  - 不 import / 调用任何域 agent：只消费 shadow 轨迹 + 静态 JSONL
  - FAIL-OPEN：缺 shadow 轨迹 / TB1 输出 → 合成中性样本继续跑
  - 输出路径：默认 .workbuddy/l1_training/domain_discovery_training.jsonl
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from drift_detector import PSI_MINOR_DRIFT, classify_drift

SHADOW_STORE_DEFAULT = (
    Path(__file__).resolve().parents[2] / ".workbuddy" / "agent_mail" / "trajectories.jsonl"
)
OUTPUT_DEFAULT = (
    Path(__file__).resolve().parents[2]
    / ".workbuddy"
    / "l1_training"
    / "domain_discovery_training.jsonl"
)

DOMAINS = ["cognition", "rea", "search", "semantic", "data", "eval"]

# 静态先验：每个域的基准 psi + 置信度均值（Phase A 起始数据）
# 真实值等 COMM-SHADOW 影子观察满 1 天后从实轨迹 + TB1 产出替换
_BASELINE_PSI = {
    "cognition": 0.08,
    "rea": 0.15,
    "search": 0.10,
    "semantic": 0.22,
    "data": 0.14,
    "eval": 0.09,
}
_BASELINE_CONFIDENCE = {
    "cognition": 0.78,
    "rea": 0.65,
    "search": 0.82,
    "semantic": 0.51,
    "data": 0.70,
    "eval": 0.75,
}


def _load_shadow_trajectories(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _perturb(value: float, key: str, scale: float = 0.025) -> float:
    """静态先验加 ±scale 微扰，避免所有样本同构。

    用 (value, key) 做哈希伪随机，保证同 key 同结果，跨 key 不同。
    """
    h = hashlib.sha256(f"{value}|{key}".encode("utf-8")).digest()
    offset = (int.from_bytes(h[:4], "big") / 2**32 - 0.5) * 2 * scale
    return min(max(value + offset, 0.0), 1.0)


def build_domain_states(
    participating_domains: List[str],
    psi_map: Optional[Dict[str, float]] = None,
    confidence_map: Optional[Dict[str, float]] = None,
    seed_key: str = "default",
) -> Dict[str, Dict[str, Any]]:
    """为 6 域各生成 {drift, psi, confidence_mean} 三元组。

    participating_domains 内域用实值（或传入 map）；其他域用基准先验（加微扰）。
    seed_key 相同 → 微扰相同（用于确定性测试）。
    """
    psi_map = psi_map or {}
    confidence_map = confidence_map or {}
    states: Dict[str, Dict[str, Any]] = {}
    active = set(participating_domains)
    for d in DOMAINS:
        if d in active:
            psi = float(psi_map.get(d, _BASELINE_PSI[d]))
            conf = float(confidence_map.get(d, _BASELINE_CONFIDENCE[d]))
        elif d in psi_map:
            # 真实轨迹已给出该域的实测 psi（含未参与本条的域），优先使用
            psi = float(psi_map[d])
            conf = float(confidence_map.get(d, _BASELINE_CONFIDENCE[d]))
        else:
            psi = _perturb(_BASELINE_PSI[d], key=f"{seed_key}|psi|{d}", scale=0.03)
            conf = _perturb(_BASELINE_CONFIDENCE[d], key=f"{seed_key}|conf|{d}", scale=0.04)
        drift = classify_drift(psi)
        states[d] = {"drift": drift, "psi": round(psi, 4), "confidence_mean": round(conf, 4)}
    return states


def compute_real_psi_map(trajectories: List[Dict[str, Any]]) -> Dict[str, float]:
    """从真实 shadow 轨迹的 degraded 指标实测各域稳定态偏离度（psi 字段）。

    仅消费带 degraded 字段的真实轨迹；合成轨迹（无该字段）不参与。
    标定方式：PSI 对二值指标（成功/降级）在零基线参考下会退化为不可分箱，
    因此把「退化率」线性标定到既有 H8 PSI 刻度：
        psi = min(degraded_rate / PSI_MINOR_DRIFT, 1.0)
    即退化率 10% = stable/minor 边界，25% = severe 阈值，100% 饱和为 1.0。
    """
    series: Dict[str, List[float]] = {}
    for entry in trajectories:
        domain = entry.get("agent_domain", "")
        if domain not in DOMAINS or "degraded" not in entry:
            continue
        series.setdefault(domain, []).append(1.0 if entry.get("degraded") else 0.0)
    psi_map: Dict[str, float] = {}
    for domain, values in series.items():
        if not values:
            continue
        degraded_rate = sum(values) / len(values)
        psi_map[domain] = round(min(degraded_rate / PSI_MINOR_DRIFT, 1.0), 4)
    return psi_map


def compute_real_confidence_map(trajectories: List[Dict[str, Any]]) -> Dict[str, float]:
    """真实轨迹各域成功率（1 - 降级比例）作为 confidence_mean 实测桥接。"""
    series: Dict[str, List[float]] = {}
    for entry in trajectories:
        domain = entry.get("agent_domain", "")
        if domain not in DOMAINS or "degraded" not in entry:
            continue
        series.setdefault(domain, []).append(1.0 if entry.get("degraded") else 0.0)
    return {
        domain: round(1.0 - sum(values) / len(values), 4)
        for domain, values in series.items()
        if values
    }


def build_reward(
    beta_means: Dict[str, float],
    dreamer_v: Optional[float] = None,
) -> Dict[str, float]:
    """SPEC §3.1 reward 块 — verify_success_rate 取参与域均值。"""
    verify_rate = sum(beta_means.values()) / len(beta_means) if beta_means else 0.5
    v_value = float(dreamer_v) if dreamer_v is not None else round(verify_rate, 4)
    return {
        "V_value": round(v_value, 4),
        "verify_success_rate": round(verify_rate, 4),
        "dreamer_V": round(verify_rate, 4),  # MVP 静态占位
    }


def build_training_sample(
    trajectory_entry: Optional[Dict[str, Any]],
    psi_map: Optional[Dict[str, float]] = None,
    confidence_map: Optional[Dict[str, float]] = None,
    source: str = "phaseA_static_prior",
    seed_key: str = "default",
) -> Dict[str, Any]:
    """组装单条 SPEC §3.1 标注样本。

    trajectory_entry 可为 None（缺 shadow 轨迹 → FAIL-OPEN 合成中性样本）。
    seed_key 相同 → 微扰 / trace_id 哈希相同（用于确定性测试）。
    """
    participating: List[str] = []
    trace_id: str = f"phaseA-{hashlib.sha256(seed_key.encode()).hexdigest()[:12]}"
    if isinstance(trajectory_entry, dict):
        participating = (
            [trajectory_entry.get("agent_domain", "")]
            if trajectory_entry.get("agent_domain")
            else []
        )
        trace_id = trajectory_entry.get("trace_id", trace_id) or trace_id
    participating = [d for d in participating if d in DOMAINS]
    if not participating:
        participating = ["cognition"]  # 至少一个活跃域，避免空 drift 分布

    states = build_domain_states(participating, psi_map, confidence_map, seed_key=seed_key)
    # BetaState.mean 近似 confidence_mean（MVP 静态桥接）
    beta_means = {d: states[d]["confidence_mean"] for d in participating}

    return {
        "input": {"domain_states": states},
        "reward": build_reward(beta_means),
        "source": source,
        "trace_id": trace_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "bbox_count": None,
    }


def collect(
    shadow_store_path: Optional[str] = None,
    output_path: Optional[str] = None,
    num_samples: int = 5,
    seed: Optional[int] = None,
) -> Path:
    """Phase A 采集管线主入口：
      1. 读 AgentMailShadow trajectory（FAIL-OPEN 缺则空）
      2. 对每条合成 1 个标注样本；轨迹不足时用静态先验补齐
      3. 写 JSONL 到 output_path

    返回：落盘路径。
    """
    seed_str = str(seed) if seed is not None else "phaseA"
    store = Path(shadow_store_path) if shadow_store_path else SHADOW_STORE_DEFAULT
    out = Path(output_path) if output_path else OUTPUT_DEFAULT
    out.parent.mkdir(parents=True, exist_ok=True)

    trajectories = _load_shadow_trajectories(store)
    # 真实轨迹（带 degraded 字段）→ 实测 psi / 成功率；合成轨迹不参与
    psi_map = compute_real_psi_map(trajectories)
    confidence_map = compute_real_confidence_map(trajectories)
    samples: List[Dict[str, Any]] = []

    for entry in trajectories:
        samples.append(
            build_training_sample(
                entry,
                psi_map=psi_map,
                confidence_map=confidence_map,
                source="phaseA_shadow_traj",
                seed_key=f"{seed_str}-t-{len(samples)}",
            )
        )
        if len(samples) >= num_samples:
            break

    fill_idx = 0
    while len(samples) < num_samples:
        samples.append(
            build_training_sample(
                None,
                source="phaseA_static_fill",
                seed_key=f"{seed_str}-f-{fill_idx}",
            )
        )
        fill_idx += 1

    with out.open("a", encoding="utf-8") as fh:
        for sample in samples:
            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")

    return out


__all__ = [
    "collect",
    "build_training_sample",
    "build_domain_states",
    "build_reward",
    "compute_real_psi_map",
    "compute_real_confidence_map",
    "DOMAINS",
    "OUTPUT_DEFAULT",
    "SHADOW_STORE_DEFAULT",
]
