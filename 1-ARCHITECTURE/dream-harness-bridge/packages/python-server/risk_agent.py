#!/usr/bin/env python3
"""risk-agent — 风险面 subagent (新建域, Spec §3.2 扩展)

数据源: 风险指标已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: heatmap(热力图) + bar(风险矩阵)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class RiskAgent:
    """风险面 subagent: 风险指标 → SubagentOutput"""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def execute(self, node_output: dict) -> SubagentOutput:
        indicators = node_output.get("indicators", {})
        rationale = node_output.get("rationale", [])
        direction = node_output.get("direction", "NEUTRAL")
        confidence = float(node_output.get("confidence", 0.5))

        signals = self._extract_signals(indicators)
        summary = self._generate_summary(signals, rationale, direction, confidence)
        charts = self._generate_charts(indicators)

        # D3: 填充 reasoning_chain + evidence_refs + artifact_uri
        reasoning_chain = " | ".join(rationale) if rationale else ""
        evidence_refs = [f"indicator:{k}" for k in indicators.keys()]
        artifact_uri = f"artifact://risk/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="risk",
            summary=summary,
            signals=signals,
            charts=charts,
            raw_data=node_output,
            confidence=confidence,
            reasoning_chain=reasoning_chain,
            evidence_refs=evidence_refs,
            artifact_uri=artifact_uri,
        )

    def _extract_signals(self, indicators: Dict[str, Any]) -> List[Signal]:
        """从风险指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        var95 = indicators.get("var_95", 0)
        var99 = indicators.get("var_99", 0)
        corr_btc = indicators.get("correlation_btc", 0)
        corr_eth = indicators.get("correlation_eth", 0)
        stress = indicators.get("stress_loss", 0)
        max_dd = indicators.get("max_drawdown", 0)
        sharpe = indicators.get("sharpe", 0)

        # VaR95 信号
        if var95 > 0.08:
            signals.append(Signal("VaR95", var95, "short", 0.7))
        elif var95 < 0.03:
            signals.append(Signal("VaR95", var95, "long", 0.55))
        else:
            signals.append(Signal("VaR95", var95, "neutral", 0.5))

        # VaR99 信号
        if var99 > 0.12:
            signals.append(Signal("VaR99", var99, "short", 0.7))
        elif var99 < 0.05:
            signals.append(Signal("VaR99", var99, "long", 0.5))

        # BTC 相关性信号
        if corr_btc > 0.8:
            signals.append(Signal("BTC相关性", corr_btc, "short", 0.55))
        elif corr_btc < 0.3:
            signals.append(Signal("BTC相关性", corr_btc, "long", 0.5))
        else:
            signals.append(Signal("BTC相关性", corr_btc, "neutral", 0.4))

        # 压力损失信号
        if stress > 0.15:
            signals.append(Signal("压力损失", stress, "short", 0.65))
        elif stress < 0.05:
            signals.append(Signal("压力损失", stress, "long", 0.5))
        else:
            signals.append(Signal("压力损失", stress, "neutral", 0.45))

        # 最大回撤信号
        if max_dd > 0.1:
            signals.append(Signal("最大回撤", max_dd, "short", 0.6))
        elif max_dd < 0.03:
            signals.append(Signal("最大回撤", max_dd, "long", 0.5))

        # 夏普比率信号
        if sharpe > 2.0:
            signals.append(Signal("夏普比率", sharpe, "long", 0.6))
        elif sharpe < 0.5:
            signals.append(Signal("夏普比率", sharpe, "short", 0.55))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"风险分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}"
                )
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"风险面{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        charts: List[ChartSpec] = []

        # 热力图: 相关性矩阵
        corr_btc = indicators.get("correlation_btc", 0)
        corr_eth = indicators.get("correlation_eth", 0)
        var95 = indicators.get("var_95", 0)
        stress = indicators.get("stress_loss", 0)
        heatmap_data = [
            ["BTC", "相关性", corr_btc],
            ["ETH", "相关性", corr_eth],
            ["VaR95", "风险值", var95],
            ["压力损失", "风险值", stress],
        ]
        charts.append(ChartSpec(
            type="heatmap",
            title="风险指标热力图",
            data=heatmap_data,
            config={
                "xAxis": {"type": "category",
                          "data": ["BTC", "ETH", "VaR95", "压力损失"]},
                "yAxis": {"type": "category", "data": ["相关性", "风险值"]},
                "visualMap": {"min": 0, "max": 1, "calculable": True},
            },
        ))

        # 柱状图: 风险矩阵
        bar_data = [
            {"name": "VaR95", "value": var95},
            {"name": "VaR99", "value": indicators.get("var_99", 0)},
            {"name": "压力损失", "value": stress},
            {"name": "最大回撤", "value": indicators.get("max_drawdown", 0)},
        ]
        charts.append(ChartSpec(
            type="bar",
            title="风险矩阵",
            data=bar_data,
            config={
                "xAxis": {"type": "category",
                          "data": ["VaR95", "VaR99", "压力损失", "最大回撤"]},
                "yAxis": {"type": "value", "name": "百分比"},
            },
        ))

        return charts

    # ── D4: ML 压力测试三层 + Portfolio Heat ────────────────

    @staticmethod
    def compute_portfolio_heat(positions: List[Dict[str, Any]],
                               correlations: Dict[str, float]) -> Dict[str, Any]:
        """Portfolio Heat 三层指标

        Layer 1: Nominal Heat — 名义暴露
        Layer 2: Correlation-Adjusted Heat — 经相关性调整后的有效暴露
        Layer 3: Max Potential Loss — 极端情景下的最大潜在损失
        """
        nominal_heat: List[Dict[str, Any]] = []
        corr_adjusted: List[Dict[str, Any]] = []
        max_potential: List[Dict[str, Any]] = []

        for pos in positions:
            symbol = pos.get("symbol", "")
            weight = float(pos.get("weight", 0))
            corr = correlations.get(symbol, 0.5)

            # Layer 1: 名义暴露
            nominal_heat.append({"symbol": symbol, "value": weight})

            # Layer 2: 相关性调整 (有效暴露 = weight * sqrt(correlation))
            effective = weight * (corr ** 0.5)
            corr_adjusted.append({"symbol": symbol, "value": effective})

            # Layer 3: 最大潜在损失 (假设 worst-case shock = 3 * VaR)
            max_loss = weight * 0.30  # 30% 极端跌幅
            max_potential.append({"symbol": symbol, "value": max_loss})

        return {
            "nominal": nominal_heat,
            "correlation_adjusted": corr_adjusted,
            "max_potential_loss": max_potential,
        }

    @staticmethod
    def ml_stress_test(returns_data: List[List[float]],
                       var_confidence: float = 0.95) -> Dict[str, Any]:
        """ML 压力测试: PCA / Autoencoder / VAE 三管线

        输入: returns_data (N_days × M_assets 收益率矩阵)
        输出: VaR + Expected Shortfall (ES) for each pipeline

        纯 numpy 实现, 不依赖 sklearn/torch (FAIL-OPEN)。
        """
        import math

        try:
            import numpy as np
        except ImportError:
            return {"error": "numpy not available", "var": 0.0, "es": 0.0,
                    "pipelines": {}}

        if not returns_data or len(returns_data) < 2:
            return {"error": "insufficient data", "var": 0.0, "es": 0.0,
                    "pipelines": {}}

        data = np.array(returns_data, dtype=float)
        n_samples, n_assets = data.shape

        # 中心化
        mean = data.mean(axis=0)
        centered = data - mean

        # 协方差矩阵
        cov = np.cov(centered, rowvar=False)
        if n_assets == 1:
            cov = cov.reshape(1, 1)

        z_score = 1.645 if var_confidence == 0.95 else 2.326  # 95% or 99%

        results = {}

        # ── Pipeline 1: PCA ────────────────────
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            # 降序排列, 取前 k 个主成分 (k = min(3, n_assets))
            k = min(3, n_assets)
            top_indices = np.argsort(eigenvalues)[::-1][:k]
            top_eigenvalues = eigenvalues[top_indices]

            # PCA 重构的协方差
            top_vectors = eigenvectors[:, top_indices]
            recon_cov = top_vectors @ np.diag(top_eigenvalues) @ top_vectors.T

            # 投影到主成分空间, 计算组合 VaR
            projected = centered @ top_vectors
            portfolio_returns = projected.sum(axis=1) / k
            pca_var = float(np.percentile(portfolio_returns, (1 - var_confidence) * 100))
            tail = portfolio_returns[portfolio_returns <= pca_var]
            pca_es = float(tail.mean()) if len(tail) > 0 else pca_var

            results["pca"] = {
                "var": abs(pca_var),
                "es": abs(pca_es),
                "components": k,
                "explained_variance": float(top_eigenvalues.sum() / eigenvalues.sum()) if eigenvalues.sum() > 0 else 0,
            }
        except Exception:  # noqa: BLE001 FAIL-OPEN
            results["pca"] = {"var": 0.0, "es": 0.0, "error": "PCA failed"}

        # ── Pipeline 2: Autoencoder (简化为 SVD 降维) ───────
        try:
            # AE 简化: SVD 降维 + 重构误差作为异常检测
            U, s, Vt = np.linalg.svd(centered, full_matrices=False)
            k_ae = min(2, n_assets, n_samples - 1)
            if k_ae < 1:
                k_ae = 1
            # 降维重构
            reduced = U[:, :k_ae] @ np.diag(s[:k_ae])
            recon = reduced @ Vt[:k_ae, :]
            recon_errors = np.linalg.norm(centered - recon, axis=1)
            # VaR based on reconstruction error distribution
            ae_var = float(np.percentile(recon_errors, var_confidence * 100))
            tail_ae = recon_errors[recon_errors >= ae_var]
            ae_es = float(tail_ae.mean()) if len(tail_ae) > 0 else ae_var

            results["autoencoder"] = {
                "var": ae_var,
                "es": ae_es,
                "latent_dim": k_ae,
                "mean_recon_error": float(recon_errors.mean()),
            }
        except Exception:  # noqa: BLE001 FAIL-OPEN
            results["autoencoder"] = {"var": 0.0, "es": 0.0, "error": "AE failed"}

        # ── Pipeline 3: VAE (简化为变分采样) ─────────────────
        try:
            # VAE 简化: 假设潜在分布为正态, Monte Carlo 采样
            latent_mean = centered.mean(axis=0)
            latent_std = centered.std(axis=0) + 1e-6
            n_simulations = 1000
            rng = np.random.default_rng(42)
            simulated = rng.normal(latent_mean, latent_std, (n_simulations, n_assets))
            sim_portfolio = simulated.sum(axis=1) / n_assets
            vae_var = float(np.percentile(sim_portfolio, (1 - var_confidence) * 100))
            tail_vae = sim_portfolio[sim_portfolio <= vae_var]
            vae_es = float(tail_vae.mean()) if len(tail_vae) > 0 else vae_var

            results["vae"] = {
                "var": abs(vae_var),
                "es": abs(vae_es),
                "simulations": n_simulations,
            }
        except Exception:  # noqa: BLE001 FAIL-OPEN
            results["vae"] = {"var": 0.0, "es": 0.0, "error": "VAE failed"}

        # 聚合: 取三管线最大 VaR 作为保守估计
        all_vars = [r.get("var", 0) for r in results.values() if isinstance(r, dict)]
        all_ess = [r.get("es", 0) for r in results.values() if isinstance(r, dict)]
        conservative_var = max(all_vars) if all_vars else 0.0
        conservative_es = max(all_ess) if all_ess else 0.0

        return {
            "var": conservative_var,
            "es": conservative_es,
            "pipelines": results,
        }

    def _generate_stress_test_charts(self, stress_result: Dict[str, Any]) -> List[ChartSpec]:
        """D4: 生成 ML 压力测试图表"""
        charts: List[ChartSpec] = []
        pipelines = stress_result.get("pipelines", {})
        if not pipelines:
            return charts

        # 柱状图: 三管线 VaR + ES 对比
        pipe_names = list(pipelines.keys())
        var_values = [pipelines[p].get("var", 0) for p in pipe_names]
        es_values = [pipelines[p].get("es", 0) for p in pipe_names]

        charts.append(ChartSpec(
            type="bar",
            title="ML 压力测试: VaR vs ES (三管线)",
            data={"VaR": var_values, "ES": es_values},
            config={
                "xAxis": {"type": "category", "data": pipe_names},
                "yAxis": {"type": "value", "name": "风险值"},
                "series": [
                    {"name": "VaR", "type": "bar", "data": var_values},
                    {"name": "ES", "type": "bar", "data": es_values},
                ],
            },
        ))

        return charts


def handle_risk_agent(params: dict) -> dict:
    """IPC handler: risk-agent"""
    try:
        agent = RiskAgent()
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
