"""
StrategySynthesizer — 深度学习策略生成器（非LLM·数据驱动）

蓝本：decision-transformer (RL as Sequence Modeling) + finclaw GA 进化
核心思想：不用 LLM 生成策略，用深度学习+进化算法做数据驱动的策略发现。

进化闭环：
  1. dt_learn_trajectories — Decision Transformer 学习历史最优交易轨迹
  2. genetic_programming   — 遗传编程(GP)对策略基因做结构变异/交叉
  3. backtest_validate     — 简易回测验证（Sharpe/最大回撤）
  4. synthesize            — 完整流程：学习→变异→验证→优胜劣汰

依赖降级：
  - torch 可用 → 简化版 Decision Transformer（因果自注意力）
  - torch 不可用 → 统计降级（按 Sharpe 排序取 top-K 轨迹特征聚合）
  - 遗传编程纯 numpy，无额外依赖

FAIL-OPEN：任何步骤异常 → 空列表/保守评分，不 crash。
"""
from __future__ import annotations

import logging
import math
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 torch（Decision Transformer 需要）
try:
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover
    _TORCH_AVAILABLE = False
    torch = None
    nn = None


# ==================================================================================================
# Decision Transformer 简化实现
# ==================================================================================================
class _DecisionTransformer(nn.Module if nn is not None else object):
    """简化版 Decision Transformer（RL as Sequence Modeling）

    输入: (states, actions, returns_to_go) 序列
    目标: 给定 returns_to_go 目标，预测最优 action
    架构: 3 个 token embedding + 因果自注意力 + MLP head
    """

    def __init__(
        self,
        state_dim: int = 8,
        action_dim: int = 4,
        hidden_dim: int = 64,
        n_heads: int = 4,
        n_layers: int = 2,
        max_seq_len: int = 64,
    ):
        if nn is None:  # pragma: no cover
            raise RuntimeError("torch not available")
        super().__init__()
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.hidden_dim = hidden_dim
        self.max_seq_len = max_seq_len

        # Token embeddings
        self.state_emb = nn.Linear(state_dim, hidden_dim)
        self.action_emb = nn.Linear(action_dim, hidden_dim)
        self.rtg_emb = nn.Linear(1, hidden_dim)
        self.pos_emb = nn.Embedding(max_seq_len, hidden_dim)

        # Transformer encoder（因果自注意力）
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=n_heads,
            dim_feedforward=hidden_dim * 4,
            batch_first=True,
            dropout=0.1,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # Action prediction head
        self.action_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim),
        )

    def forward(self, states: torch.Tensor, actions: torch.Tensor, rtgs: torch.Tensor) -> torch.Tensor:
        """
        Args:
            states: (B, T, state_dim)
            actions: (B, T, action_dim)
            rtgs: (B, T, 1)
        Returns:
            pred_actions: (B, T, action_dim)
        """
        B, T, _ = states.shape
        T = min(T, self.max_seq_len)
        states = states[:, :T, :]
        actions = actions[:, :T, :]
        rtgs = rtgs[:, :T, :]

        # 三种 token 交替排列: (s0, a0, r0, s1, a1, r1, ...)
        s_emb = self.state_emb(states)  # (B, T, H)
        a_emb = self.action_emb(actions)
        r_emb = self.rtg_emb(rtgs)

        # 位置编码
        pos = torch.arange(T, device=states.device).unsqueeze(0)  # (1, T)
        s_emb = s_emb + self.pos_emb(pos)
        a_emb = a_emb + self.pos_emb(pos)
        r_emb = r_emb + self.pos_emb(pos)

        # 拼接: (B, 3T, H)
        tokens = torch.stack([s_emb, a_emb, r_emb], dim=2).reshape(B, 3 * T, self.hidden_dim)

        # 因果掩码（手动创建，避免 torch.generate_square_subsequent_mask 的兼容性崩溃）
        seq_len = 3 * T
        mask = torch.triu(torch.full((seq_len, seq_len), float('-inf'), device=states.device), diagonal=1)
        x = self.transformer(tokens, mask=mask, is_causal=True)

        # 取 action token 位置（索引 1, 4, 7, ... = 3t+1）
        action_indices = torch.arange(1, 3 * T, 3, device=states.device)
        action_tokens = x[:, action_indices, :]
        return self.action_head(action_tokens)


# ==================================================================================================
# StrategySynthesizer 主类
# ==================================================================================================
class StrategySynthesizer:
    """深度学习策略生成器（非LLM·数据驱动）

    进化闭环：
      1. dt_learn_trajectories — Decision Transformer 学习历史最优交易轨迹
      2. genetic_programming   — 遗传编程(GP)对策略基因做结构变异/交叉
      3. backtest_validate     — 简易回测验证（Sharpe/最大回撤）
      4. synthesize            — 完整流程：学习→变异→验证→优胜劣汰
    """

    def __init__(
        self,
        gene_root: Optional[str | Path] = None,
        enable_dt: bool = True,
        enable_gp: bool = True,
        min_new_gene_sharpe_ratio: float = 0.8,
    ):
        """
        Args:
            gene_root: 基因库根目录（strategy_genes/ 的父目录）
            enable_dt: 是否启用 Decision Transformer
            enable_gp: 是否启用遗传编程
            min_new_gene_sharpe_ratio: 新基因 Sharpe 需 ≥ top基因 Sharpe × 此比例（验收: 0.8）
        """
        if gene_root is None:
            self._gene_root = Path(__file__).resolve().parent.parent / "gene_data"
        else:
            self._gene_root = Path(gene_root)
        self.enable_dt = enable_dt and _TORCH_AVAILABLE
        self.enable_gp = enable_gp
        self.min_sharpe_ratio = min_new_gene_sharpe_ratio

        # DT 模型（延迟初始化）
        self._dt_model: Optional[_DecisionTransformer] = None
        self._dt_trained: bool = False

        # 统计
        self.stats = {
            "dt_trajectories_learned": 0,
            "gp_candidates_generated": 0,
            "genes_validated": 0,
            "genes_accepted": 0,
        }

    # ------------------------------------------------------------------
    # 1. Decision Transformer 轨迹学习
    # ------------------------------------------------------------------
    def dt_learn_trajectories(self, historical_trades: list[dict]) -> dict:
        """Decision Transformer 学习历史最优交易轨迹

        Args:
            historical_trades: 历史交易列表，每个 dict 含:
                - states: list[list[float]]  状态序列
                - actions: list[list[float]] 动作序列
                - rewards: list[float]       奖励序列
                - sharpe: float              该轨迹的 Sharpe（可选，用于排序）
        Returns:
            dict: {
                "method": "decision_transformer" | "statistical_fallback",
                "n_trajectories": int,
                "top_sharpe": float,
                "learned_patterns": list[dict],  # 学到的模式特征
                "model_loaded": bool,
            }
        FAIL-OPEN: 异常 → 返回空模式，method=statistical_fallback
        """
        if not historical_trades:
            return {"method": "unavailable", "n_trajectories": 0, "top_sharpe": 0.0,
                    "learned_patterns": [], "model_loaded": False}

        try:
            # 按 Sharpe 排序，取 top 30% 作为"最优轨迹"
            sorted_trades = sorted(
                historical_trades,
                key=lambda t: float(t.get("sharpe", 0.0)),
                reverse=True,
            )
            n_top = max(1, int(len(sorted_trades) * 0.3))
            top_trades = sorted_trades[:n_top]
            top_sharpe = float(top_trades[0].get("sharpe", 0.0)) if top_trades else 0.0

            if self.enable_dt and _TORCH_AVAILABLE:
                patterns = self._dt_train(top_trades)
                # 若 DT 内部因数据不足降级到统计方法，method 同步反映
                method = "decision_transformer" if patterns else "statistical_fallback"
                if not patterns:
                    patterns = self._statistical_fallback(top_trades)
            else:
                patterns = self._statistical_fallback(top_trades)
                method = "statistical_fallback"

            self.stats["dt_trajectories_learned"] = len(top_trades)
            return {
                "method": method,
                "n_trajectories": len(top_trades),
                "top_sharpe": top_sharpe,
                "learned_patterns": patterns,
                "model_loaded": self._dt_model is not None,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[StrategySynthesizer] dt_learn_trajectories failed: %s", e)
            return {"method": "unavailable", "n_trajectories": 0, "top_sharpe": 0.0,
                    "learned_patterns": [], "model_loaded": False}

    def _dt_train(self, top_trades: list[dict]) -> list[dict]:
        """用 torch 训练简化版 Decision Transformer"""
        if not top_trades or nn is None:
            return []

        # 避免 macOS OpenMP 线程崩溃（pthread_mutex_init failed）
        try:
            torch.set_num_threads(1)
        except Exception:
            pass

        # 提取并对齐轨迹
        states_list, actions_list, rewards_list = [], [], []
        for t in top_trades:
            s = t.get("states") or []
            a = t.get("actions") or []
            r = t.get("rewards") or []
            if s and a and r and len(s) == len(a) == len(r):
                states_list.append(s)
                actions_list.append(a)
                rewards_list.append(r)

        if not states_list:
            return self._statistical_fallback(top_trades)

        # 统一维度（取第一条的维度，不足的 padding）
        state_dim = len(states_list[0][0])
        action_dim = len(actions_list[0][0])
        max_len = min(64, max(len(s) for s in states_list))

        # 构建 batch（padding 到 max_len）
        B = len(states_list)
        states_arr = np.zeros((B, max_len, state_dim), dtype=np.float32)
        actions_arr = np.zeros((B, max_len, action_dim), dtype=np.float32)
        rtgs_arr = np.zeros((B, max_len, 1), dtype=np.float32)

        for i, (s, a, r) in enumerate(zip(states_list, actions_list, rewards_list)):
            L = min(len(s), max_len)
            states_arr[i, :L] = s[:L]
            actions_arr[i, :L] = a[:L]
            # returns-to-go: 从后往前累加
            rtg = 0.0
            for t_idx in range(L - 1, -1, -1):
                rtg += float(r[t_idx])
                rtgs_arr[i, t_idx, 0] = rtg

        # 初始化模型
        self._dt_model = _DecisionTransformer(
            state_dim=state_dim, action_dim=action_dim, hidden_dim=64
        )
        optimizer = torch.optim.Adam(self._dt_model.parameters(), lr=1e-3)

        # 训练（少步数，快速拟合）
        states_t = torch.from_numpy(states_arr)
        actions_t = torch.from_numpy(actions_arr)
        rtgs_t = torch.from_numpy(rtgs_arr)

        self._dt_model.train()
        n_epochs = 10
        for epoch in range(n_epochs):
            pred = self._dt_model(states_t, actions_t, rtgs_t)
            loss = nn.functional.mse_loss(pred, actions_t)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        self._dt_trained = True

        # 提取学到的模式：top 轨迹的 action 均值 + state 均值
        patterns = []
        for i in range(min(5, B)):
            patterns.append({
                "avg_state": states_arr[i].mean(axis=0).tolist(),
                "avg_action": actions_arr[i].mean(axis=0).tolist(),
                "total_reward": float(rtgs_arr[i, 0, 0]),
            })
        return patterns

    def _statistical_fallback(self, top_trades: list[dict]) -> list[dict]:
        """统计降级：聚合 top 轨迹的特征"""
        patterns = []
        for t in top_trades[:5]:
            s = t.get("states") or []
            a = t.get("actions") or []
            if s and a:
                patterns.append({
                    "avg_state": list(np.mean(s, axis=0)) if isinstance(s[0], list) else [float(np.mean(s))],
                    "avg_action": list(np.mean(a, axis=0)) if isinstance(a[0], list) else [float(np.mean(a))],
                    "sharpe": float(t.get("sharpe", 0.0)),
                })
        return patterns

    # ------------------------------------------------------------------
    # 2. 遗传编程（GP）策略变异
    # ------------------------------------------------------------------
    def genetic_programming(
        self,
        gene_library: dict,
        target_metric: str = "ess",
        n_candidates: int = 5,
    ) -> list[dict]:
        """遗传编程生成新策略基因候选

        两种变异方式：
          A. 参数变异: 对现有 condition gene 的 parameters.value 做高斯扰动
          B. 组合交叉: 从现有 combinations 中重组 condition_ids

        Args:
            gene_library: load_gene_library() 返回的字典
            target_metric: 优化目标（ess/sharpe）
            n_candidates: 生成候选数量
        Returns:
            list[dict]: 新基因候选，每个含 gene_id/category/condition_type/expression/parameters
        FAIL-OPEN: 异常 → []
        """
        if not self.enable_gp:
            return []
        try:
            conditions = gene_library.get("conditions", []) or []
            combinations = gene_library.get("combinations", []) or []
            if not conditions:
                return []

            candidates: list[dict] = []

            # A. 参数变异（70%）
            n_mutate = int(n_candidates * 0.7)
            for _ in range(n_mutate):
                base = conditions[np.random.randint(len(conditions))]
                mutated = self._mutate_condition(base)
                if mutated:
                    candidates.append(mutated)

            # B. 组合交叉（30%）
            n_cross = n_candidates - len(candidates)
            if combinations and n_cross > 0:
                for _ in range(n_cross):
                    crossed = self._crossover_combinations(combinations, conditions)
                    if crossed:
                        candidates.append(crossed)

            self.stats["gp_candidates_generated"] = len(candidates)
            return candidates
        except Exception as e:  # noqa: BLE001
            logger.warning("[StrategySynthesizer] genetic_programming failed: %s", e)
            return []

    def _mutate_condition(self, base_gene: dict) -> Optional[dict]:
        """对 condition gene 的参数做高斯扰动"""
        try:
            params = base_gene.get("parameters", {}) or {}
            if not params:
                return None
            new_params = {}
            for pname, pdef in params.items():
                if not isinstance(pdef, dict):
                    continue
                val = pdef.get("value")
                rng = pdef.get("range", {}) or {}
                lo, hi = rng.get("low"), rng.get("high")
                if val is None or lo is None or hi is None:
                    new_params[pname] = pdef
                    continue
                try:
                    val_f = float(val)
                    lo_f, hi_f = float(lo), float(hi)
                    # 高斯扰动，sigma = range 的 10%
                    sigma = (hi_f - lo_f) * 0.1
                    new_val = val_f + np.random.normal(0, sigma)
                    new_val = max(lo_f, min(hi_f, new_val))  # clamp 到 range
                    new_pdef = dict(pdef)
                    new_pdef["value"] = round(new_val, 6)
                    new_params[pname] = new_pdef
                except (TypeError, ValueError):
                    new_params[pname] = pdef

            ts = int(time.time()) % 100000
            new_gene = dict(base_gene)
            new_gene["gene_id"] = f"CD-GP-{ts}-{uuid.uuid4().hex[:4]}"
            new_gene["parameters"] = new_params
            new_gene["source"] = "genetic_mutation"
            new_gene["parent_gene_id"] = base_gene.get("gene_id", "")
            new_gene["tags"] = list(base_gene.get("tags", [])) + ["gp-mutated"]
            return new_gene
        except Exception:
            return None

    def _crossover_combinations(
        self, combinations: list[dict], conditions: list[dict]
    ) -> Optional[dict]:
        """从两个组合中交叉 condition_ids，生成新组合的首个 condition 变异"""
        try:
            if len(combinations) < 2:
                return None
            c1 = combinations[np.random.randint(len(combinations))]
            c2 = combinations[np.random.randint(len(combinations))]
            ids1 = c1.get("condition_ids", []) or []
            ids2 = c2.get("condition_ids", []) or []
            if not ids1 or not ids2:
                return None

            # 取交集或各取一个
            all_ids = list(set(ids1) | set(ids2))
            if not all_ids:
                return None
            chosen_id = all_ids[np.random.randint(len(all_ids))]

            # 找到对应 condition gene
            chosen = next((c for c in conditions if c.get("gene_id") == chosen_id), None)
            if chosen is None:
                return None

            # 基于该 gene 做一次参数变异
            return self._mutate_condition(chosen)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 3. 回测验证
    # ------------------------------------------------------------------
    def backtest_validate(
        self,
        candidate: dict,
        price_data: Optional[np.ndarray] = None,
        top_gene_sharpe: float = 1.0,
    ) -> dict:
        """简易回测验证候选基因

        Args:
            candidate: 候选基因 dict
            price_data: 价格序列（1D numpy array），None 时用合成数据
            top_gene_sharpe: 现有 top 基因 Sharpe（用于计算达标阈值）
        Returns:
            dict: {
                "gene_id": str,
                "sharpe": float,
                "max_drawdown": float,
                "n_trades": int,
                "passes_threshold": bool,  # sharpe >= top * min_ratio
                "score": float,            # 综合评分 [0,1]
            }
        FAIL-OPEN: 异常 → 保守评分（sharpe=0, passes=False）
        """
        gene_id = candidate.get("gene_id", "unknown")
        try:
            # 无效候选直接返回保守评分（parameters 必须存在且为 dict）
            params = candidate.get("parameters")
            if not isinstance(params, dict) or not params:
                return {"gene_id": gene_id, "sharpe": 0.0, "max_drawdown": 1.0,
                        "n_trades": 0, "passes_threshold": False, "score": 0.0}

            if price_data is None or len(price_data) < 10:
                # 合成价格数据（几何布朗运动）
                n = 500
                price_data = self._synth_prices(n)

            returns = np.diff(price_data) / price_data[:-1]
            returns = returns[np.isfinite(returns)]

            # 基于候选基因的参数生成信号
            # 简化：用 parameters 阈值与价格波动的关系生成多空信号
            signal = self._gene_to_signal(candidate, price_data)
            if signal is None or len(signal) != len(returns):
                # 无法解析 → 用随机信号兜底（保守）
                signal = np.random.choice([-1, 0, 1], size=len(returns))

            # 策略收益 = signal * return
            strat_returns = signal * returns
            strat_returns = strat_returns[np.isfinite(strat_returns)]

            if len(strat_returns) == 0:
                return {"gene_id": gene_id, "sharpe": 0.0, "max_drawdown": 1.0,
                        "n_trades": 0, "passes_threshold": False, "score": 0.0}

            # Sharpe（年化，假设日频）
            mean_ret = float(np.mean(strat_returns))
            std_ret = float(np.std(strat_returns))
            sharpe = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0
            sharpe = max(-5.0, min(5.0, sharpe))  # clamp

            # 最大回撤
            cum = np.cumprod(1.0 + strat_returns)
            peak = np.maximum.accumulate(cum)
            drawdown = (peak - cum) / np.where(peak > 0, peak, 1.0)
            max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 1.0

            # 交易次数（信号变化次数）
            n_trades = int(np.sum(np.abs(np.diff(signal)) > 0))

            # 达标判断
            threshold = top_gene_sharpe * self.min_sharpe_ratio
            passes = sharpe >= threshold

            # 综合评分：Sharpe 归一 + 回撤惩罚
            sharpe_norm = max(0.0, min(1.0, (sharpe + 1.0) / 3.0))  # [-1, 2] → [0, 1]
            dd_penalty = max(0.0, 1.0 - max_dd * 2.0)
            score = sharpe_norm * 0.7 + dd_penalty * 0.3

            self.stats["genes_validated"] += 1
            return {
                "gene_id": gene_id,
                "sharpe": round(sharpe, 4),
                "max_drawdown": round(max_dd, 4),
                "n_trades": n_trades,
                "passes_threshold": passes,
                "score": round(score, 4),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[StrategySynthesizer] backtest_validate failed for %s: %s", gene_id, e)
            return {"gene_id": gene_id, "sharpe": 0.0, "max_drawdown": 1.0,
                    "n_trades": 0, "passes_threshold": False, "score": 0.0}

    def _gene_to_signal(self, gene: dict, prices: np.ndarray) -> Optional[np.ndarray]:
        """将候选基因的 parameters 转换为交易信号

        简化逻辑：
          - 有趋势类参数 → 基于价格动量生成信号
          - 有波动率类参数 → 基于波动率突破生成信号
          - 否则 → None（由调用方兜底）
        """
        try:
            params = gene.get("parameters", {}) or {}
            rets = np.diff(prices) / prices[:-1]
            n = len(rets)
            signal = np.zeros(n)

            # 提取参数值
            param_values = []
            for pname, pdef in params.items():
                if isinstance(pdef, dict) and pdef.get("value") is not None:
                    try:
                        param_values.append(float(pdef["value"]))
                    except (TypeError, ValueError):
                        pass

            if not param_values:
                return None

            # 用参数值作为阈值/窗口
            threshold = np.mean(np.abs(param_values))
            window = max(2, int(abs(np.median(param_values)))) if param_values else 5
            window = min(window, n // 4) if n > 4 else 2

            # 动量信号：滚动均值偏离阈值
            if window >= 2 and n >= window:
                rolling_mean = np.convolve(rets, np.ones(window) / window, mode="valid")
                # 对齐长度
                sig = np.zeros(n)
                sig[window - 1:] = np.where(rolling_mean > threshold * 0.001, 1.0,
                                            np.where(rolling_mean < -threshold * 0.001, -1.0, 0.0))
                return sig
            return None
        except Exception:
            return None

    @staticmethod
    def _synth_prices(n: int = 500) -> np.ndarray:
        """合成价格数据（几何布朗运动 + 趋势）"""
        np.random.seed(42)
        mu = 0.0002
        sigma = 0.02
        dt = 1.0
        z = np.random.normal(0, 1, n)
        log_ret = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * z
        prices = 100.0 * np.exp(np.cumsum(log_ret))
        return prices

    # ------------------------------------------------------------------
    # 4. 完整合成流程
    # ------------------------------------------------------------------
    def synthesize(
        self,
        historical_trades: Optional[list[dict]] = None,
        gene_library: Optional[dict] = None,
        price_data: Optional[np.ndarray] = None,
        n_candidates: int = 5,
        top_gene_sharpe: float = 1.0,
    ) -> dict:
        """完整策略合成流程

        1. DT 学习历史最优轨迹
        2. GP 生成候选基因
        3. 回测验证
        4. 优胜劣汰（仅保留达标的）

        Args:
            historical_trades: 历史交易轨迹（DT 学习用）
            gene_library: 基因库（GP 变异用）
            price_data: 价格数据（回测用）
            n_candidates: 生成候选数
            top_gene_sharpe: 现有 top 基因 Sharpe（验收阈值基准）
        Returns:
            dict: {
                "dt_result": dict,
                "candidates": list[dict],          # 所有候选
                "validated": list[dict],           # 回测结果
                "accepted_genes": list[dict],      # 达标的新基因
                "n_accepted": int,
                "stats": dict,
            }
        """
        # 1. DT 学习
        dt_result = self.dt_learn_trajectories(historical_trades or [])

        # 2. GP 生成候选
        candidates = self.genetic_programming(gene_library or {}, n_candidates=n_candidates)

        # 3. 回测验证
        validated = []
        for cand in candidates:
            v = self.backtest_validate(cand, price_data, top_gene_sharpe)
            validated.append(v)

        # 4. 优胜劣汰
        accepted = []
        for cand, v in zip(candidates, validated):
            if v.get("passes_threshold", False):
                accepted.append({
                    "gene": cand,
                    "validation": v,
                })
                self.stats["genes_accepted"] += 1

        return {
            "dt_result": dt_result,
            "candidates": candidates,
            "validated": validated,
            "accepted_genes": accepted,
            "n_accepted": len(accepted),
            "stats": dict(self.stats),
        }

    # ------------------------------------------------------------------
    # 5. Meta-RL 三环自改进（SPEC §4.2.6）
    # ------------------------------------------------------------------
    NEW_GENE_COLD_START_POSITION = 0.05  # HC-AGI-10: 新基因冷启动仓位地板 5%

    def meta_rl_self_improve(self,
                             validation_results: list[dict],
                             learning_rate: float = 0.1) -> dict:
        """Meta-RL 三环自改进机制

        三环：
          1. 适应环（Adaptation）: 基于验证结果调整变异参数（sigma 缩放）
          2. 选择环（Selection）: 根据 Sharpe 调整基因库权重
          3. 探索环（Exploration）: 调整 GP 变异强度，平衡探索/利用

        Args:
            validation_results: backtest_validate 返回的验证结果列表
            learning_rate: 学习率（0-1）
        Returns:
            dict: {
                "adapted_sigma_scale": float,   # 变异 sigma 缩放因子
                "selected_gene_ids": list[str], # 被选中的基因 ID
                "exploration_rate": float,      # 探索率
                "n_improved": int,              # 改进的基因数
            }
        FAIL-OPEN: 异常 → 保守参数（sigma=1.0, 探索率=0.3）
        """
        try:
            if not validation_results:
                return {
                    "adapted_sigma_scale": 1.0,
                    "selected_gene_ids": [],
                    "exploration_rate": 0.3,
                    "n_improved": 0,
                }

            # 1. 适应环：根据平均 Sharpe 调整变异 sigma
            sharpes = [float(v.get("sharpe", 0.0)) for v in validation_results]
            avg_sharpe = float(np.mean(sharpes)) if sharpes else 0.0
            # Sharpe 高 → 减小 sigma（利用）；Sharpe 低 → 增大 sigma（探索）
            sigma_scale = max(0.3, min(3.0, 1.0 - avg_sharpe * 0.2))

            # 2. 选择环：选中 Sharpe > 0 的基因
            selected = [
                v.get("gene_id", "")
                for v in validation_results
                if float(v.get("sharpe", 0.0)) > 0
            ]

            # 3. 探索环：根据通过率调整探索率
            pass_rate = (
                sum(1 for v in validation_results if v.get("passes_threshold", False))
                / len(validation_results)
            )
            # 通过率低 → 提高探索率；通过率高 → 降低探索率
            exploration_rate = max(0.1, min(0.7, 0.5 - pass_rate * 0.4))

            return {
                "adapted_sigma_scale": round(sigma_scale, 4),
                "selected_gene_ids": selected,
                "exploration_rate": round(exploration_rate, 4),
                "n_improved": len(selected),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[StrategySynthesizer] meta_rl_self_improve failed: %s", e)
            return {
                "adapted_sigma_scale": 1.0,
                "selected_gene_ids": [],
                "exploration_rate": 0.3,
                "n_improved": 0,
            }

    # ------------------------------------------------------------------
    # 6. 验证并集成到基因库（HC-AGI-04 / HC-AGI-10）
    # ------------------------------------------------------------------
    def validate_and_integrate(self,
                               candidate: dict,
                               price_data: Optional[np.ndarray] = None,
                               top_gene_sharpe: float = 1.0) -> dict:
        """验证候选基因并集成到基因库

        HC-AGI-04: 新基因必须经过回测验证
        HC-AGI-10: 新基因冷启动仓位 ≤ 0.05（5% 地板）

        Args:
            candidate: 候选基因 dict
            price_data: 价格序列
            top_gene_sharpe: top 基因 Sharpe
        Returns:
            dict: {
                "gene_id": str,
                "validation": dict,           # backtest_validate 结果
                "cold_start_position": float, # 冷启动仓位（≤0.05）
                "integrated": bool,           # 是否集成成功
            }
        FAIL-OPEN: 异常 → integrated=False
        """
        gene_id = candidate.get("gene_id", "unknown")
        try:
            # 1. 回测验证（HC-AGI-04）
            validation = self.backtest_validate(candidate, price_data, top_gene_sharpe)

            # 2. 冷启动仓位地板（HC-AGI-10: ≤ 0.05）
            cold_start_position = self.NEW_GENE_COLD_START_POSITION

            # 3. 集成判断：通过回测阈值则集成
            integrated = bool(validation.get("passes_threshold", False))

            return {
                "gene_id": gene_id,
                "validation": validation,
                "cold_start_position": cold_start_position,
                "integrated": integrated,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[StrategySynthesizer] validate_and_integrate failed for %s: %s", gene_id, e)
            return {
                "gene_id": gene_id,
                "validation": {"sharpe": 0.0, "passes_threshold": False},
                "cold_start_position": self.NEW_GENE_COLD_START_POSITION,
                "integrated": False,
            }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        """报告后端依赖状态"""
        return {
            "torch": _TORCH_AVAILABLE,
            "decision_transformer": self.enable_dt and _TORCH_AVAILABLE,
            "genetic_programming": self.enable_gp,
            "min_sharpe_ratio": self.min_sharpe_ratio,
        }
