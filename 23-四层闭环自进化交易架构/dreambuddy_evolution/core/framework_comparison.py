"""FrameworkComparison — 5 框架配对 walk-forward 对比验证.

设计依据：融合方案 §5.1.5a + 评审报告 §12.2
5 个框架:
  F1: v0.7 交叉验证（Granger 过去因 + Attention 现在力 + CrossValidationGate）
  F2: 纯 Attention + Bayesian 后验权重
  F3: 互信息 + 动态权重
  F4: Shapley 值归因
  F5: 单 Granger 因果链

指标: 样本外夏普 / DSR（Deflated Sharpe）/ PBO（Probability of Backtest Overfitting）
统计: Holm-Bonferroni 配对校正
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy import stats

from dreambuddy_evolution.core.cross_validation_gate import CrossValidationGate

FRAMEWORK_NAMES = [
    "F1_cross_validation",
    "F2_attention_bayesian",
    "F3_mutual_information",
    "F4_shapley_attribution",
    "F5_granger_only",
]


def holm_bonferroni(p_values: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni 多重比较校正.

    按 p 值升序排列，第 i 个（1-indexed）校正后 p = min(1, p * (m - i + 1)).
    """
    m = len(p_values)
    sorted_items = sorted(p_values.items(), key=lambda x: x[1])
    adjusted: dict[str, float] = {}
    prev_adj = 0.0
    for i, (key, p) in enumerate(sorted_items, 1):
        adj = min(1.0, p * (m - i + 1))
        adj = max(adj, prev_adj)  # 单调性约束
        adjusted[key] = adj
        prev_adj = adj
    return adjusted


class FrameworkComparison:
    """5 框架 walk-forward 对比验证器."""

    def __init__(self, prices: np.ndarray, window: int = 60) -> None:
        """
        Args:
            prices: 1D 价格序列
            window: 因子计算滚动窗口
        """
        self.prices = np.asarray(prices, dtype=float)
        self.window = window
        self.returns = np.diff(self.prices) / self.prices[:-1]
        self._factors: Optional[np.ndarray] = None

    # ── 因子构建（价格衍生）────────────────────────────────────────

    def build_factors(self) -> np.ndarray:
        """从价格衍生技术因子矩阵 (T, F)."""
        p = self.prices
        n = len(p)
        w = self.window

        # 收益率
        ret = np.zeros(n)
        ret[1:] = self.returns

        # 因子 1: 动量（过去 w 期收益率）
        momentum = np.zeros(n)
        momentum[w:] = (p[w:] - p[:-w]) / p[:-w]

        # 因子 2: 波动率（过去 w 期收益率标准差）
        vol = np.zeros(n)
        for i in range(w, n):
            vol[i] = np.std(ret[i - w + 1 : i + 1])

        # 因子 3: RSI 类（过去 w 期涨跌比）
        rsi = np.full(n, 50.0)
        for i in range(w, n):
            diffs = np.diff(p[i - w : i + 1])
            gains = np.mean(diffs[diffs > 0]) if np.any(diffs > 0) else 0.0
            losses = -np.mean(diffs[diffs < 0]) if np.any(diffs < 0) else 0.0
            rsi[i] = 100 * gains / (gains + losses + 1e-10)

        # 因子 4: 均线偏离（价格 / w 期均线 - 1）
        ma_dev = np.zeros(n)
        for i in range(w, n):
            ma_dev[i] = p[i] / np.mean(p[i - w + 1 : i + 1]) - 1.0

        # 因子 5: 偏度（过去 w 期收益率偏度）
        skew = np.zeros(n)
        for i in range(w, n):
            r = ret[i - w + 1 : i + 1]
            skew[i] = stats.skew(r) if np.std(r) > 1e-10 else 0.0

        self._factors = np.column_stack([momentum, vol, rsi, ma_dev, skew])
        return self._factors

    # ── 框架信号生成 ──────────────────────────────────────────────

    def generate_all_signals(self) -> dict[str, np.ndarray]:
        """生成 5 个框架的信号序列 (-1/0/1)."""
        if self._factors is None:
            self.build_factors()
        factors = self._factors
        returns = self.returns
        n = len(self.prices)

        signals = {
            "F1_cross_validation": self._signal_cross_validation(factors, returns, n),
            "F2_attention_bayesian": self._signal_attention_bayesian(factors, returns, n),
            "F3_mutual_information": self._signal_mutual_information(factors, returns, n),
            "F4_shapley_attribution": self._signal_shapley(factors, returns, n),
            "F5_granger_only": self._signal_granger_only(factors, returns, n),
        }
        return signals

    def _signal_cross_validation(self, factors, returns, n) -> np.ndarray:
        """F1: 交叉验证 — Granger 过去因 + Attention 现在力 + CrossValidationGate."""
        w = self.window
        sig = np.zeros(n)
        gate = CrossValidationGate(persistence_threshold=3, structural_break_threshold=0.4)
        # 简化：G_dim 用 Granger 检验（动量因子是否 Granger-cause 收益）
        # A_dim 用 Attention 权重（因子与当期收益的相关度加权）
        dims = ["technical", "fundamental", "macro"]
        # 模拟：前 2 个因子→technical, 中间2→fundamental, 最后1→macro
        factor_dim_map = ["technical", "technical", "fundamental", "fundamental", "macro"]

        for i in range(w * 2, n):
            # 过去因：滚动 Granger 检验（简化为相关性检验）
            past_rets = returns[i - 2 * w : i - w]
            past_factors = factors[i - 2 * w : i - w]
            # 用与收益相关性最强的因子维度作为 G_dim
            corrs = [np.corrcoef(past_factors[:, j], past_rets)[0, 1]
                     if np.std(past_factors[:, j]) > 1e-10 else 0.0
                     for j in range(factors.shape[1])]
            best_g = np.argmax(np.abs(corrs))
            g_dim = factor_dim_map[best_g]

            # 现在力：最近窗口因子与收益的相关度作为 attention 权重
            recent_factors = factors[i - w : i]
            recent_rets = returns[i - w : i]
            attn_weights = np.array([
                abs(np.corrcoef(recent_factors[:, j], recent_rets)[0, 1])
                if np.std(recent_factors[:, j]) > 1e-10 else 0.0
                for j in range(factors.shape[1])
            ])
            # 聚合到 3 维度
            dim_strength = {d: 0.0 for d in dims}
            for j, d in enumerate(factor_dim_map):
                dim_strength[d] += attn_weights[j]
            total = sum(dim_strength.values())
            if total > 0:
                dim_strength = {k: v / total for k, v in dim_strength.items()}
            a_dim = max(dim_strength, key=dim_strength.get)

            # 结构性断裂：波动率变化作为 vol_regime_shift
            vol_recent = np.std(recent_rets)
            vol_past = np.std(returns[i - 2 * w : i - w])
            vol_shift = vol_recent > vol_past * 1.3 if vol_past > 1e-10 else False

            result = gate.compare(
                G_dim=g_dim, G_conf=abs(corrs[best_g]),
                A_dim=a_dim, A_strength=dim_strength[a_dim],
                structural_break={"volatility_regime_shift": vol_shift},
            )
            # 信号方向：用 A_dim 对应因子的方向
            if result["confidence_mult"] > 1.0:
                sig[i] = 1.0 if momentum_direction(factors, i, best_g) > 0 else -1.0
            elif result["shift_signal"]:
                sig[i] = 1.0 if momentum_direction(factors, i, best_g) > 0 else -1.0
        return sig

    def _signal_attention_bayesian(self, factors, returns, n) -> np.ndarray:
        """F2: 纯 Attention + Bayesian 后验（无交叉验证）."""
        w = self.window
        sig = np.zeros(n)
        # Bayesian 后验权重：先验均匀，每窗口更新
        prior = np.ones(factors.shape[1]) / factors.shape[1]
        factor_dim_map = ["technical", "technical", "fundamental", "fundamental", "macro"]

        for i in range(w * 2, n):
            recent_factors = factors[i - w : i]
            recent_rets = returns[i - w : i]
            # 似然：因子方向与收益方向一致率
            likelihood = np.array([
                np.mean(np.sign(recent_factors[:, j]) == np.sign(recent_rets))
                if np.std(recent_factors[:, j]) > 1e-10 else 0.5
                for j in range(factors.shape[1])
            ])
            posterior = prior * likelihood
            posterior /= posterior.sum() + 1e-10
            prior = 0.7 * prior + 0.3 * posterior  # EMA 平滑

            # 按权重聚合方向
            direction = 0.0
            for j in range(factors.shape[1]):
                direction += posterior[j] * np.sign(factors[i, j])
            sig[i] = 1.0 if direction > 0.1 else (-1.0 if direction < -0.1 else 0.0)
        return sig

    def _signal_mutual_information(self, factors, returns, n) -> np.ndarray:
        """F3: 互信息 + 动态权重."""
        w = self.window
        sig = np.zeros(n)
        factor_dim_map = ["technical", "technical", "fundamental", "fundamental", "macro"]

        for i in range(w * 2, n):
            recent_factors = factors[i - w : i]
            recent_rets = returns[i - w : i]
            # 互信息（简化：用 |相关系数| 作为 MI 代理）
            mi = np.array([
                abs(np.corrcoef(recent_factors[:, j], recent_rets)[0, 1])
                if np.std(recent_factors[:, j]) > 1e-10 else 0.0
                for j in range(factors.shape[1])
            ])
            mi /= mi.sum() + 1e-10

            direction = 0.0
            for j in range(factors.shape[1]):
                direction += mi[j] * np.sign(factors[i, j])
            sig[i] = 1.0 if direction > 0.1 else (-1.0 if direction < -0.1 else 0.0)
        return sig

    def _signal_shapley(self, factors, returns, n) -> np.ndarray:
        """F4: Shapley 值归因（简化为因子收益的边际贡献）."""
        w = self.window
        sig = np.zeros(n)

        for i in range(w * 2, n):
            recent_factors = factors[i - w : i]
            recent_rets = returns[i - w : i]
            # Shapley 值：每个因子单独预测收益的能力（回归系数）
            shapley = np.zeros(factors.shape[1])
            for j in range(factors.shape[1]):
                if np.std(recent_factors[:, j]) > 1e-10:
                    beta = np.cov(recent_factors[:, j], recent_rets)[0, 1] / np.var(recent_factors[:, j])
                    shapley[j] = beta
            total_abs = np.abs(shapley).sum() + 1e-10
            weights = shapley / total_abs

            direction = np.dot(weights, np.sign(factors[i]))
            sig[i] = 1.0 if direction > 0.1 else (-1.0 if direction < -0.1 else 0.0)
        return sig

    def _signal_granger_only(self, factors, returns, n) -> np.ndarray:
        """F5: 单 Granger 因果链（只用过去因，无 Attention）."""
        w = self.window
        sig = np.zeros(n)
        factor_dim_map = ["technical", "technical", "fundamental", "fundamental", "macro"]

        for i in range(w * 2, n):
            past_rets = returns[i - 2 * w : i - w]
            past_factors = factors[i - 2 * w : i - w]
            # Granger 因果：因子滞后预测收益的能力
            corrs = [np.corrcoef(past_factors[:-1, j], past_rets[1:])[0, 1]
                     if np.std(past_factors[:-1, j]) > 1e-10 else 0.0
                     for j in range(factors.shape[1])]
            best_g = np.argmax(np.abs(corrs))
            direction = np.sign(corrs[best_g]) * np.sign(factors[i, best_g])
            sig[i] = 1.0 if direction > 0 else (-1.0 if direction < 0 else 0.0)
        return sig

    # ── 指标计算 ──────────────────────────────────────────────────

    @staticmethod
    def sharpe_ratio(pnl: np.ndarray, periods_per_year: int = 8760) -> float:
        """年化夏普比率.

        periods_per_year: 30m 周期 → 2*365*24 = 17520；这里用 8760（1h 等效）
        """
        pnl = np.asarray(pnl, dtype=float)
        pnl = pnl[np.isfinite(pnl)]
        if len(pnl) < 2 or np.std(pnl) < 1e-12:
            return 0.0
        mean = np.mean(pnl)
        std = np.std(pnl, ddof=1)
        sr = mean / std * np.sqrt(periods_per_year)
        return float(sr)

    @staticmethod
    def deflated_sharpe_ratio(pnl: np.ndarray, n_trials: int = 5,
                               periods_per_year: int = 17520) -> float:
        """DSR — 考虑多重比较后夏普的显著性（Bailey & Lopez de Prado 2014）.

        DSR = Φ((SR_hat - SR_0) / σ_hat)
        其中 SR_hat 为年化夏普，SR_0 = sqrt(2*ln(n_trials)) 为多重比较阈值。
        """
        pnl = np.asarray(pnl, dtype=float)
        pnl = pnl[np.isfinite(pnl)]
        T = len(pnl)
        if T < 10 or np.std(pnl) < 1e-12:
            return 0.0
        # 年化夏普
        sr_annual = np.mean(pnl) / np.std(pnl, ddof=1) * np.sqrt(periods_per_year)
        # 每期夏普（用于方差估计）
        sr_period = np.mean(pnl) / np.std(pnl, ddof=1)
        g3 = stats.skew(pnl)
        g4 = stats.kurtosis(pnl, fisher=False)
        sr_var = (1 - g3 * sr_period + (g4 - 1) / 4 * sr_period ** 2) / (T - 1)
        if sr_var <= 0:
            return 0.0
        sr_var_annual = sr_var * periods_per_year  # 年化方差
        sr0 = np.sqrt(2 * np.log(max(1, n_trials)))
        dsr = stats.norm.cdf((sr_annual - sr0) / np.sqrt(sr_var_annual))
        return float(dsr)

    def probability_of_backtest_overfitting(
        self, signals: dict[str, np.ndarray], returns: np.ndarray, n_splits: int = 5
    ) -> float:
        """PBO — 回测过拟合概率（Bailey et al. 2017 组合对称交叉验证 CSCV）.

        将回测期分为两半，计算各框架在两半的秩相关。
        PBO = P(logit < 0) = 框架在 IS 最优但 OOS 最差的概率。
        """
        n = len(returns)
        half = n // 2

        is_sharpes = {}
        oos_sharpes = {}
        for name, sig in signals.items():
            # sig[i] 对应 returns[i]，对齐到相同长度
            min_is = min(half, len(sig))
            is_pnl = sig[:min_is] * returns[:min_is] if min_is > 0 else np.array([])
            min_oos = min(n - half, len(sig) - half)
            oos_pnl = sig[half:half + min_oos] * returns[half:half + min_oos] if min_oos > 0 else np.array([])
            is_sharpes[name] = self.sharpe_ratio(is_pnl)
            oos_sharpes[name] = self.sharpe_ratio(oos_pnl)

        names = list(signals.keys())
        if len(names) < 2:
            return 0.0

        # 用 CSCV 近似：多次随机分割计算 logit
        logits = []
        rng = np.random.RandomState(42)
        for _ in range(max(1, n_splits)):
            perm = rng.permutation(n)
            is_idx = perm[:half]
            oos_idx = perm[half:]
            is_sr = {name: self.sharper(signals[name][is_idx], returns[is_idx]) for name in names}
            oos_sr = {name: self.sharper(signals[name][oos_idx], returns[oos_idx]) for name in names}
            # IS 最优框架在 OOS 的秩
            best_is = max(is_sr, key=is_sr.get)
            oos_rank = sorted(oos_sr, key=oos_sr.get, reverse=True).index(best_is)
            # logit = ln(rank / (N - rank))
            rank = oos_rank + 1
            n_fw = len(names)
            logit = math.log(rank / (n_fw - rank + 1e-10))
            logits.append(logit)

        pbo = float(np.mean(np.array(logits) < 0))
        return pbo

    def sharper(self, sig: np.ndarray, returns: np.ndarray) -> float:
        """辅助：信号 × 收益的夏普."""
        min_len = min(len(sig), len(returns))
        if min_len < 2:
            return 0.0
        pnl = sig[:min_len] * returns[:min_len]
        return self.sharpe_ratio(pnl)

    # ── Walk-Forward 主流程 ───────────────────────────────────────

    def walk_forward(self, n_folds: int = 5, train_ratio: float = 0.7) -> dict:
        """执行 n_folds 滚动 walk-forward 验证.

        Returns:
            {
              framework_name: {
                "oos_sharpe": float,
                "dsr": float,
                "mean_return": float,
                "win_rate": float,
              }
            }
        """
        n = len(self.prices)
        fold_size = n // (n_folds + 1)
        results: dict[str, dict] = {name: {"pnls": [], "oos_sharpes": []} for name in FRAMEWORK_NAMES}

        signals = self.generate_all_signals()

        for fold in range(n_folds):
            train_end = fold_size * (fold + 1)
            test_start = train_end
            test_end = min(train_end + fold_size, n)
            if test_end - test_start < 10:
                continue

            test_returns = self.returns[test_start - 1 : test_end - 1]
            for name, sig in signals.items():
                test_sig = sig[test_start:test_end]
                min_len = min(len(test_sig), len(test_returns))
                if min_len < 5:
                    continue
                pnl = test_sig[:min_len] * test_returns[:min_len]
                results[name]["pnls"].extend(pnl.tolist())
                results[name]["oos_sharpes"].append(self.sharpe_ratio(pnl))

        # 汇总
        summary = {}
        for name in FRAMEWORK_NAMES:
            pnls = np.array(results[name]["pnls"])
            pnls = pnls[np.isfinite(pnls)]
            if len(pnls) == 0:
                summary[name] = {
                    "oos_sharpe": 0.0, "dsr": 0.0, "mean_return": 0.0, "win_rate": 0.0,
                }
                continue
            summary[name] = {
                "oos_sharpe": float(np.mean(results[name]["oos_sharpes"])),
                "dsr": self.deflated_sharpe_ratio(pnls),
                "mean_return": float(np.mean(pnls)),
                "win_rate": float(np.mean(pnls > 0)),
            }

        # PBO
        summary["_meta"] = {
            "pbo": self.probability_of_backtest_overfitting(signals, self.returns, n_splits=n_folds),
        }
        return summary

    def pairwise_comparison(self, result: dict) -> dict[str, float]:
        """配对 t 检验 + Holm-Bonferroni 校正.

        Returns: {pair_name: adjusted_p_value}
        """
        pnls = self._collect_oos_pnls(result)
        names = [n for n in FRAMEWORK_NAMES if n in pnls]
        if len(names) < 2:
            return {}

        ref = "F1_cross_validation"
        p_values: dict[str, float] = {}
        for other in names:
            if other == ref:
                continue
            if len(pnls[ref]) < 2 or len(pnls[other]) < 2:
                continue
            # 配对需要等长，取最短
            min_len = min(len(pnls[ref]), len(pnls[other]))
            if min_len < 5:
                continue
            diff = np.array(pnls[ref][:min_len]) - np.array(pnls[other][:min_len])
            t_stat, p_val = stats.ttest_1samp(diff, 0.0)
            p_values[f"{ref}_vs_{other}"] = float(p_val)

        return holm_bonferroni(p_values)

    def _collect_oos_pnls(self, result: dict) -> dict[str, list]:
        """从 walk_forward 结果中收集各框架的 OOS pnl 序列（需重新运行信号）。"""
        signals = self.generate_all_signals()
        n = len(self.prices)
        n_folds = 5
        fold_size = n // (n_folds + 1)
        pnls = {name: [] for name in FRAMEWORK_NAMES}
        for fold in range(n_folds):
            train_end = fold_size * (fold + 1)
            test_start = train_end
            test_end = min(train_end + fold_size, n)
            if test_end - test_start < 10:
                continue
            test_returns = self.returns[test_start - 1 : test_end - 1]
            for name in FRAMEWORK_NAMES:
                sig = signals[name]
                min_len = min(len(sig[test_start:test_end]), len(test_returns))
                if min_len < 5:
                    continue
                pnl = sig[test_start:test_end][:min_len] * test_returns[:min_len]
                pnls[name].extend(pnl.tolist())
        return pnls


def momentum_direction(factors: np.ndarray, i: int, j: int) -> float:
    """辅助：因子 j 在 i 时刻的方向（符号）。"""
    return float(np.sign(factors[i, j]))
