"""real_market_features.py — 真实市场特征批次 (BTC regime / 波动 / 资金流) → NeuralSDE 输入.

动机: Phase B/C 的 DomainCouplingHead 训练与推理一直用 `torch.randn` 合成输入,
hidden_state 与真实市场无因果关系. 本模块把 ckpt **训练时同源** 的真实特征喂进
frozen NeuralSDE drift_net, 使 hidden 随真实市场状态变化, 才可能得到状态依赖 coupling.

数据源 (与 neural_sde_v1_dim64.training_report.json 严格对齐):
  - closes: 23-四层闭环自进化交易架构/data/btc_closes_1h.json
    (6072 根 1h, mean=78752.3 / std=1634.0 与 ckpt price_mean/std 完全一致)
  - factors: 23-四层闭环自进化交易架构/data/exogenous_factors_36.json
    (6072 × 36, C1-C8+news 全量因子, 与 closes 逐行对齐)
  - regime: BTCRegimeDetector(n_regimes=3, window=720) HMM drawdown 观测
  - log_sig: SignatureEngine(depth=3) 对最近 n_step 根 close 求 log-signature,
    再用 ckpt 的 log_sig_mean/std 做 z-score (与 prepare_data 同一路径)

状态标签 (仅用于分组统计, 不进模型输入):
  - regime: 0=bull / 1=chop / 2=bear (窗口末点)
  - vol: 窗口内 log-return 已实现波动率, 样本三分位分档
  - flow: C1 资金流因子 (etf_total_flow / funding_rate / exchange_inflow_24h) z 均值, 三分位分档

FAIL-OPEN: 数据/ckpt 缺失 / 维度不符 / 计算异常 → 返回 None, 调用方回退合成输入.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CLOSES = REPO / "23-四层闭环自进化交易架构" / "data" / "btc_closes_1h.json"
DEFAULT_FACTORS = REPO / "23-四层闭环自进化交易架构" / "data" / "exogenous_factors_36.json"
DEFAULT_CKPT = REPO / "23-四层闭环自进化交易架构" / "data" / "neural_sde_v1_dim64.pt"

# CROSS_ATTENTION_FACTOR_METRICS 中 C1 资金流列 (exogenous_data_bridge.py L516-523)
FLOW_FACTOR_INDICES = (0, 1, 4)
FLOW_FACTOR_NAMES = ("etf_total_flow", "funding_rate", "exchange_inflow_24h")


@dataclass
class RealMarketBatch:
    """一批真实市场窗口 (窗口结束点对齐)."""

    window_ends: np.ndarray  # (N,) int, close 索引
    y: np.ndarray  # (N, 1) z-score 收盘价
    log_sig: np.ndarray  # (N, log_sig_input_dim) z-score log-signature
    regime: np.ndarray  # (N, n_regimes) one-hot
    factors: np.ndarray  # (N, n_factors) z-score 外生因子
    regime_label: np.ndarray  # (N,) int
    vol: np.ndarray  # (N,) 已实现波动率
    flow: np.ndarray  # (N,) 资金流代理 (flow 列 z 均值)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        return int(self.y.shape[0])

    def state_buckets(self) -> dict[str, np.ndarray]:
        """regime / vol / flow 三分位分档 (返回每样本的 bucket 索引)."""
        return {
            "regime": np.asarray(self.regime_label, dtype=int),
            "vol": _tercile(self.vol),
            "flow": _tercile(self.flow),
        }


def _tercile(values: np.ndarray) -> np.ndarray:
    """按 33%/67% 分位切成 3 档 (常量列 → 全 0)."""
    arr = np.asarray(values, dtype=np.float64).ravel()
    if arr.size == 0 or not np.all(np.isfinite(arr)):
        return np.zeros(arr.size, dtype=int)
    q1, q2 = np.quantile(arr, [1 / 3, 2 / 3])
    if q2 <= q1:
        return np.zeros(arr.size, dtype=int)
    return np.searchsorted([q1, q2], arr, side="right").astype(int)


def _select_window_ends(
    regime_labels: np.ndarray, seq_len: int, n_windows: int, seed: int = 42
) -> np.ndarray:
    """按 regime 分层抽取窗口结束点, 保证三种 regime 都有样本."""
    valid = np.arange(seq_len - 1, regime_labels.size)
    if valid.size == 0:
        return valid
    if n_windows >= valid.size:
        return valid
    rng = np.random.default_rng(seed)
    chosen: list[int] = []
    regimes = np.unique(regime_labels[valid])
    per = max(1, n_windows // max(1, regimes.size))
    for r in regimes:
        idx = valid[regime_labels[valid] == r]
        take = min(per, idx.size)
        chosen.extend(rng.choice(idx, take, replace=False).tolist())
    remaining = n_windows - len(chosen)
    if remaining > 0:
        rest = np.setdiff1d(valid, np.asarray(chosen, dtype=int))
        chosen.extend(rng.choice(rest, min(remaining, rest.size), replace=False).tolist())
    return np.sort(np.asarray(chosen, dtype=int))


def _zscore_factors(raw: np.ndarray, n: int) -> np.ndarray:
    """与 train_neural_sde.py L212-222 完全一致的因子预处理."""
    arr = np.asarray(raw, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.shape[0] > n:
        arr = arr[:n]
    elif arr.shape[0] < n:
        pad = np.zeros((n - arr.shape[0], arr.shape[1]), dtype=np.float64)
        arr = np.concatenate([pad, arr], axis=0)
    mean = arr.mean(axis=0)
    std = arr.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return (arr - mean) / std


def _load_ckpt_stats(ckpt_meta: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """取 price/log_sig 归一化统计 + log_sig 输入维度 (q_proj 宽度)."""
    meta = ckpt_meta
    if meta is None:
        if not DEFAULT_CKPT.exists():
            return None
        import torch

        meta = torch.load(str(DEFAULT_CKPT), map_location="cpu", weights_only=False)
    try:
        stats = {
            "price_mean": float(meta["price_mean"]),
            "price_std": float(meta["price_std"]),
            "log_sig_mean": np.asarray(meta["log_sig_mean"], dtype=np.float64),
            "log_sig_std": np.asarray(meta["log_sig_std"], dtype=np.float64),
            "sig_dim": int(meta.get("sig_dim", 15)),
            "n_regimes": int(meta.get("n_regimes", 3)),
            "n_step": int(meta.get("n_step", 32)),
            "sig_depth": int(meta.get("sig_depth", 3)),
            "seq_len": int(meta.get("seq_len", 64)),
        }
        # drift_net 实际接受 log_sig 的宽度 = experts.*.q_proj 输入维度
        q_proj = (meta.get("drift_net_state_dict") or {}).get("experts.0.q_proj.weight")
        stats["log_sig_input_dim"] = (
            int(q_proj.shape[1]) if q_proj is not None else stats["sig_dim"]
        )
        return stats
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FO-REAL] ckpt 统计提取失败: %s", exc)
        return None


def build_real_market_batch(
    ckpt_meta: Optional[dict[str, Any]] = None,
    closes_path: Path = DEFAULT_CLOSES,
    factors_path: Path = DEFAULT_FACTORS,
    n_windows: int = 96,
    n_regimes: Optional[int] = None,
    regime_labels: Optional[np.ndarray] = None,
    seed: int = 42,
) -> Optional[RealMarketBatch]:
    """构建真实市场特征批次; 任何前置条件缺失 → None (调用方回退合成输入)."""
    stats = _load_ckpt_stats(ckpt_meta)
    if stats is None:
        return None
    if not closes_path.exists():
        logger.warning("[FO-REAL] closes 缺失: %s", closes_path)
        return None

    try:
        closes = np.asarray(json.loads(closes_path.read_text()), dtype=np.float64).ravel()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FO-REAL] closes 读取失败: %s", exc)
        return None
    seq_len = stats["seq_len"]
    n_step = stats["n_step"]
    if closes.size < seq_len + 1:
        logger.warning("[FO-REAL] closes 样本不足: %d", closes.size)
        return None

    # 1) regime 标签 (优先复用调用方传入, 避免重复 HMM 拟合)
    n_reg = int(n_regimes or stats["n_regimes"])
    if regime_labels is None:
        try:
            from dreambuddy_evolution.core.btc_regime_detector import BTCRegimeDetector

            regime_labels = BTCRegimeDetector(n_regimes=n_reg).detect(closes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[FO-REAL] regime 检测失败, 回退全 0: %s", exc)
            regime_labels = np.zeros(closes.size, dtype=int)
    labels = np.asarray(regime_labels, dtype=int).ravel()
    if labels.size < closes.size:
        labels = np.concatenate([labels, np.zeros(closes.size - labels.size, dtype=int)])
    labels = labels[: closes.size]

    # 2) 外生因子 z-score
    factors: Optional[np.ndarray] = None
    raw_factors: Optional[np.ndarray] = None
    if factors_path.exists():
        try:
            raw = json.loads(factors_path.read_text())
            raw_factors = np.asarray(raw, dtype=np.float64)
            if raw_factors.shape[0] > closes.size:
                raw_factors = raw_factors[: closes.size]
            elif raw_factors.shape[0] < closes.size:
                pad = np.zeros((closes.size - raw_factors.shape[0], raw_factors.shape[1]))
                raw_factors = np.concatenate([pad, raw_factors], axis=0)
            factors = _zscore_factors(raw, closes.size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[FO-REAL] factors 读取失败, 用零向量: %s", exc)
    if factors is None:
        factors = np.zeros((closes.size, 1), dtype=np.float64)

    # 3) 窗口选择 (按 regime 分层)
    ends = _select_window_ends(labels, seq_len, n_windows, seed=seed)
    if ends.size == 0:
        return None

    price_norm = (closes - stats["price_mean"]) / max(stats["price_std"], 1e-8)

    # 4) log_sig (与 prepare_data 同一路径: SignatureEngine(depth) + ckpt z-score)
    from dreambuddy_evolution.core.signature_engine import SignatureEngine

    engine = SignatureEngine(depth=stats["sig_depth"])
    try:
        from dreambuddy_evolution.core import signature_engine as _se

        engine_name = (
            "signatory"
            if engine._signatory_available
            else ("esig" if _se._ESIG_AVAILABLE else "numpy")
        )
    except Exception:  # noqa: BLE001
        engine_name = "unknown"
    raw_log_sigs: list[np.ndarray] = []
    for e in ends:
        window = closes[int(e) - n_step + 1 : int(e) + 1]
        try:
            ls = np.asarray(engine.log_signature(window), dtype=np.float64).ravel()
        except Exception:  # noqa: BLE001
            ls = np.zeros(stats["sig_dim"], dtype=np.float64)
        if ls.size < stats["sig_dim"]:
            ls = np.concatenate([ls, np.zeros(stats["sig_dim"] - ls.size)])
        ls = ls[: stats["sig_dim"]]
        if not np.all(np.isfinite(ls)):
            ls = np.zeros(stats["sig_dim"], dtype=np.float64)
        raw_log_sigs.append(ls)
    raw_log_sig = np.asarray(raw_log_sigs, dtype=np.float64)  # (N, sig_dim)

    log_sig = (raw_log_sig - stats["log_sig_mean"]) / np.maximum(stats["log_sig_std"], 1e-8)
    # pad 到 drift_net 实际输入宽度 (cross-attn q_proj 宽度可能 > sig_dim)
    out_dim = stats["log_sig_input_dim"]
    if log_sig.shape[1] < out_dim:
        log_sig = np.concatenate(
            [log_sig, np.zeros((log_sig.shape[0], out_dim - log_sig.shape[1]))], axis=1
        )
    else:
        log_sig = log_sig[:, :out_dim]

    # 5) 状态特征: regime one-hot / 已实现波动 / 资金流
    reg_label = labels[ends].astype(int)
    reg_label = np.clip(reg_label, 0, n_reg - 1)
    onehot = np.zeros((ends.size, n_reg), dtype=np.float64)
    onehot[np.arange(ends.size), reg_label] = 1.0

    vol = np.zeros(ends.size, dtype=np.float64)
    for k, e in enumerate(ends):
        window = closes[int(e) - seq_len + 1 : int(e) + 1]
        rets = np.diff(np.log(np.maximum(window, 1e-9)))
        vol[k] = float(np.std(rets)) if rets.size else 0.0

    flow_idx = [i for i in FLOW_FACTOR_INDICES if i < factors.shape[1]]
    flow = factors[ends][:, flow_idx].mean(axis=1) if flow_idx else np.zeros(ends.size)
    flow_coverage = {
        FLOW_FACTOR_NAMES[j]: (
            float(np.mean(np.abs(raw_factors[:, i]) > 0)) if raw_factors is not None else 0.0
        )
        for j, i in enumerate(flow_idx)
    }

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO))
        except ValueError:
            return str(p)

    meta = {
        "input_source": "real_btc_1h_36factors",
        "closes_path": _rel(closes_path),
        "factors_path": _rel(factors_path) if factors_path.exists() else "",
        "n_windows": int(ends.size),
        "n_candidates": int(closes.size - seq_len + 1),
        "seq_len": int(seq_len),
        "n_step": int(n_step),
        "n_factors": int(factors.shape[1]),
        "log_sig_real_dim": int(stats["sig_dim"]),
        "log_sig_input_dim": int(out_dim),
        # ckpt 的 log_sig 统计由 esig/signatory 尺度拟合; numpy 降级尺度不同 → z 会发散
        "log_sig_engine": engine_name,
        "regime_counts": {
            str(k): int(v) for k, v in zip(*np.unique(reg_label, return_counts=True), strict=True)
        },
        "price_z_range": [
            round(float(price_norm[ends].min()), 3),
            round(float(price_norm[ends].max()), 3),
        ],
        "log_sig_z_abs_max": round(float(np.abs(log_sig[:, : stats["sig_dim"]]).max()), 3),
        "flow_factor_names": [FLOW_FACTOR_NAMES[j] for j in range(len(flow_idx))],
        "flow_factor_coverage": {k: round(v, 4) for k, v in flow_coverage.items()},
        "regime_index_basis": "window_end",
        "seed": int(seed),
    }
    return RealMarketBatch(
        window_ends=ends,
        y=price_norm[ends].reshape(-1, 1),
        log_sig=log_sig,
        regime=onehot,
        factors=factors[ends],
        regime_label=reg_label,
        vol=vol,
        flow=np.asarray(flow, dtype=np.float64),
        meta=meta,
    )
