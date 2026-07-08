#!/usr/bin/env python3
"""
策略多样性机制 — 借鉴 LEAN 多策略组合框架

核心问题：当 B1（主路径"观望等待"）占比 > 80% 时，
系统陷入单一策略模式，与 LEAN 的多策略组合原则相悖。

LEAN 核心思想：
  - 多策略同时运行，相关性越低越好
  - 任何单策略占比不超过 40%（避免过拟合）
  - 根据 Regime 自动切换策略权重
  - 策略回撤超阈值时降权，不停用

本模块实现：
  1. B1 占比监控（从 sim-trade 历史读取）
  2. B1 > 80% 时触发多样性扩展：
     B4: 均值回归策略（资金费率极端时）
     B5: 突破追势策略（量价配合时）
     B6: 跨期套利策略（期现价差机会）
     B7: 被忽视情景策略（做梦部第四象限）
  3. 策略权重按近期表现动态调整（LEAN Portfolio 思路）
  4. 最大化策略组合夏普比率

依赖：
  - sim-trade 历史数据（data/polling_trader/）
  - MarketPreprocessor（归一化行情数据）
  - SelfEvolutionEngine（停滞检测）
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import json, math, time

BASE_DIR  = Path(__file__).parent.parent.parent.parent
DATA_DIR  = BASE_DIR / "data" / "polling_trader"

# B1 占比阈值（超过此值触发多样性扩展）
B1_DOMINANCE_THRESHOLD = 0.80   # 借鉴 LEAN: 单策略不超过 40%，我们放宽到 80%
# 策略回撤超过此值降权
DRAWDOWN_PENALTY_THRESHOLD = 0.15
# 策略组合最大仓位各占比
MAX_SINGLE_STRATEGY_WEIGHT = 0.60


@dataclass
class StrategyStats:
    """单策略历史绩效统计。"""
    strategy_id:  str
    name:         str
    win_rate:     float = 0.5
    sharpe:       float = 0.0
    max_drawdown: float = 0.0
    call_count:   int   = 0
    win_count:    int   = 0
    pnl_sum:      float = 0.0
    weight:       float = 1.0          # 动态权重（LEAN Portfolio）
    last_updated: str   = ""


@dataclass
class DiversityReport:
    """多样性检测报告。"""
    b1_dominance:      float          # B1 在历史中的占比
    triggered:         bool           # 是否触发多样性扩展
    reason:            str
    recommended_mix:   List[str]      # 推荐的策略组合
    strategy_weights:  Dict[str, float]  # 每个策略的权重
    new_branches:      List[Dict]     # 新增策略分支


class StrategyDiversityManager:
    """
    策略多样性管理器。

    用法:
        sdm = StrategyDiversityManager()
        report = sdm.check_and_expand(market_snapshot, current_branches)
        # 如果 report.triggered，将 report.new_branches 追加到策略列表
    """

    def __init__(self):
        self._stats: Dict[str, StrategyStats] = self._init_stats()
        self._history_file = BASE_DIR / "data" / "strategy_diversity" / "stats.json"
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()

    def _init_stats(self) -> Dict[str, StrategyStats]:
        return {
            "B1": StrategyStats("B1", "顺势跟踪（主路径）"),
            "B2": StrategyStats("B2", "质变对冲"),
            "B3": StrategyStats("B3", "螺旋否定"),
            "B4": StrategyStats("B4", "均值回归"),
            "B5": StrategyStats("B5", "突破追势"),
            "B6": StrategyStats("B6", "资金套利"),
            "B7": StrategyStats("B7", "被忽视情景"),
        }

    # ── 主入口：检测并扩展策略 ────────────────────────────────────────────────

    def check_and_expand(self,
                          market_snapshot: Dict[str, Any],
                          current_branches: List[Any]) -> DiversityReport:
        """
        检测 B1 占比，必要时扩展策略多样性。

        Args:
            market_snapshot: 当前市场数据
            current_branches: 当前 BCRMEngine 生成的策略分支

        Returns:
            DiversityReport，包含是否触发 + 新增分支
        """
        # 1. 计算当前策略分布
        b1_dominance = self._compute_b1_dominance()

        # 2. 判断是否触发
        if b1_dominance < B1_DOMINANCE_THRESHOLD:
            return DiversityReport(
                b1_dominance=b1_dominance,
                triggered=False,
                reason=f"B1 占比 {b1_dominance:.1%} 正常（< {B1_DOMINANCE_THRESHOLD:.0%}）",
                recommended_mix=["B1"],
                strategy_weights={"B1": 1.0},
                new_branches=[],
            )

        # 3. B1 过于主导 → 触发多样性扩展
        reason = f"B1 占比 {b1_dominance:.1%} > {B1_DOMINANCE_THRESHOLD:.0%}，触发策略多样性扩展"

        # 4. 根据市场状态选择互补策略
        new_strategies = self._select_complementary_strategies(market_snapshot)

        # 5. 计算策略权重（LEAN Portfolio 动态权重）
        weights = self._compute_portfolio_weights(new_strategies)

        # 6. 生成新策略分支
        new_branches = self._build_new_branches(market_snapshot, new_strategies, weights)

        # 7. 更新权重（基于历史绩效调整）
        self._update_weights_from_performance()

        return DiversityReport(
            b1_dominance=b1_dominance,
            triggered=True,
            reason=reason,
            recommended_mix=["B1"] + new_strategies,
            strategy_weights=weights,
            new_branches=new_branches,
        )

    # ── 核心：选择互补策略 ────────────────────────────────────────────────────

    def _select_complementary_strategies(self,
                                          snapshot: Dict[str, Any]) -> List[str]:
        """
        根据市场状态选择与 B1 相关性最低的互补策略。
        LEAN 原则：策略相关性越低，组合夏普越高。
        """
        selected = []

        pct      = float(snapshot.get("price_change_pct",
                         snapshot.get("supply_demand_score", 0.5) * 20 - 10) or 0)
        rsi      = float(snapshot.get("rsi", snapshot.get("technical_score", 0.5) * 100) or 50)
        funding  = float(snapshot.get("funding_rate",
                         snapshot.get("capital_flow_score", 0.5) * 0.002 - 0.001) or 0)
        vol_r    = float(snapshot.get("volume_ratio", 1.0) or 1.0)
        fgi      = float(snapshot.get("fgi",
                         snapshot.get("sentiment_score", 0.5) * 100) or 50)

        # B4 均值回归：RSI 极端 + 资金费率极端（与 B1 趋势策略负相关）
        if rsi < 30 or rsi > 70 or abs(funding) > 0.0002:
            selected.append("B4")

        # B5 突破追势：成交量放大 + 价格变动（与 B1 同向但更激进）
        # 与 B1 正相关，但突破形态不同
        if vol_r > 1.5 and abs(pct) > 3:
            selected.append("B5")

        # B6 资金套利：资金费率持续偏向某一方（可稳定套取费率）
        if abs(funding) > 0.0003:
            selected.append("B6")

        # B7 被忽视情景：FGI 极端（恐惧底部 or 贪婪顶部反转机会）
        if fgi < 20 or fgi > 85:
            selected.append("B7")

        # 至少选1个（保证多样性，选历史表现最好的）
        if not selected:
            best = max(
                [s for s in ["B4", "B5", "B6", "B7"]],
                key=lambda sid: self._stats[sid].sharpe
            )
            selected.append(best)

        # LEAN 原则：最多3个额外策略，避免过度分散
        return selected[:3]

    # ── 策略权重计算（LEAN Portfolio）────────────────────────────────────────

    def _compute_portfolio_weights(self,
                                    strategies: List[str]) -> Dict[str, float]:
        """
        基于历史夏普比率计算策略权重。
        LEAN 使用 Equal Risk Contribution (ERC) 方法。
        这里简化为夏普加权，并限制单策略最大占比。
        """
        all_strats = ["B1"] + strategies
        weights: Dict[str, float] = {}

        # 基础权重：基于历史夏普（避免夏普为0/负的策略占比过高）
        sharpes = {s: max(self._stats[s].sharpe, 0.1) for s in all_strats}
        total_sharpe = sum(sharpes.values())

        for s in all_strats:
            w = sharpes[s] / total_sharpe
            weights[s] = min(w, MAX_SINGLE_STRATEGY_WEIGHT)

        # 归一化（确保总权重=1）
        total = sum(weights.values())
        weights = {s: round(w / total, 3) for s, w in weights.items()}

        return weights

    # ── 生成新策略分支（StrategyBranch 格式）────────────────────────────────

    def _build_new_branches(self,
                             snapshot: Dict[str, Any],
                             strategies: List[str],
                             weights: Dict[str, float]) -> List[Dict]:
        """构建新策略分支的字典格式（供 BCRMEngine 追加）。"""
        branches = []
        price   = float(snapshot.get("price", 0) or 0)
        vol     = float(snapshot.get("volatility",
                        snapshot.get("volume_ratio", 1.0) * 0.02) or 0.02)

        templates = {
            "B4": {
                "branch_id":        "B4",
                "condition":        "RSI极端或资金费率极端（均值回归信号）",
                "action":           "均值回归：逆向小仓位，等待回归",
                "position_modifier": 0.3,
                "stop_condition":   "RSI穿越50线或资金费率回归中性",
                "rationale":        "借鉴LEAN: 与趋势策略负相关，降低组合波动",
                "stop_loss_px":     price * (1 - vol * 1.5) if price else 0,
                "take_profit_px":   price * (1 + vol * 2.5) if price else 0,
                "reduce_ratio":     0.0,
            },
            "B5": {
                "branch_id":        "B5",
                "condition":        "成交量放大≥1.5x且价格变动>3%（突破信号）",
                "action":           "突破追势：顺势追入，仓位较B1更激进",
                "position_modifier": 1.2,
                "stop_condition":   "量能萎缩或价格跌破突破点",
                "rationale":        "借鉴vnpy: 量价突破形态，高确定性入场",
                "stop_loss_px":     price * (1 - vol * 1.2) if price else 0,
                "take_profit_px":   price * (1 + vol * 4.0) if price else 0,
                "reduce_ratio":     0.0,
            },
            "B6": {
                "branch_id":        "B6",
                "condition":        "资金费率持续偏向多空某方（>0.03%）",
                "action":           "资金套利：持仓反向收取资金费率",
                "position_modifier": 0.5,
                "stop_condition":   "资金费率回归 ±0.01% 区间",
                "rationale":        "借鉴Binance套利策略: 资金费率年化>10%时稳定收益",
                "stop_loss_px":     price * (1 - vol * 0.8) if price else 0,
                "take_profit_px":   0,  # 靠套利收益，无硬止盈
                "reduce_ratio":     0.0,
            },
            "B7": {
                "branch_id":        "B7",
                "condition":        "FGI<20（极度恐惧）或FGI>85（极度贪婪）",
                "action":           "被忽视情景：做梦部第四象限，反向试探",
                "position_modifier": 0.2,
                "stop_condition":   "FGI回归40-60中性区间",
                "rationale":        "做梦部: 市场极端情绪通常是最大机会被忽视时",
                "stop_loss_px":     price * (1 - vol * 2.0) if price else 0,
                "take_profit_px":   price * (1 + vol * 5.0) if price else 0,
                "reduce_ratio":     0.0,
            },
        }

        for sid in strategies:
            if sid in templates:
                b = dict(templates[sid])
                b["_weight"] = weights.get(sid, 0.2)
                branches.append(b)

        return branches

    # ── 统计：B1 占比计算 ─────────────────────────────────────────────────────

    def _compute_b1_dominance(self) -> float:
        """从 sim-trade 历史数据计算 B1 占比。"""
        try:
            sim_dir = BASE_DIR / "data" / "polling_trader"
            files   = sorted(sim_dir.glob("*.json")) if sim_dir.exists() else []

            b1_count = 0
            total    = 0
            for f in files[-50:]:  # 最近50条
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    branch = d.get("strategy_branch", d.get("branch_id", ""))
                    total += 1
                    if not branch or branch == "B1" or \
                       "观望" in str(d.get("action", "")):
                        b1_count += 1
                except Exception:
                    pass

            if total == 0:
                return 1.0   # 无历史 = 假设全 B1
            return b1_count / total
        except Exception:
            return 1.0

    # ── 动态权重更新（基于绩效，LEAN 自适应）────────────────────────────────

    def _update_weights_from_performance(self):
        """根据近期绩效更新各策略权重（LEAN 动态权重思路）。"""
        for sid, stat in self._stats.items():
            if stat.call_count < 3:
                continue
            wr = stat.win_count / stat.call_count
            avg_pnl = stat.pnl_sum / stat.call_count
            # 夏普估算（简化）
            stat.sharpe = wr * 2 - 1 + avg_pnl * 10
            # 回撤惩罚
            if stat.max_drawdown > DRAWDOWN_PENALTY_THRESHOLD:
                stat.weight = max(0.1, stat.weight * 0.8)
            else:
                stat.weight = min(1.5, stat.weight * 1.05)
        self._save_history()

    def record_outcome(self, branch_id: str, won: bool, pnl: float):
        """记录某策略分支的交易结果（供外部调用更新统计）。"""
        if branch_id not in self._stats:
            self._stats[branch_id] = StrategyStats(branch_id, f"策略{branch_id}")
        stat = self._stats[branch_id]
        stat.call_count += 1
        if won:
            stat.win_count += 1
        stat.pnl_sum += pnl
        if pnl < 0:
            stat.max_drawdown = max(stat.max_drawdown, abs(pnl))
        stat.last_updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save_history()

    def _load_history(self):
        if self._history_file.exists():
            try:
                data = json.loads(self._history_file.read_text(encoding="utf-8"))
                for sid, s in data.items():
                    if sid in self._stats:
                        for k, v in s.items():
                            if hasattr(self._stats[sid], k):
                                setattr(self._stats[sid], k, v)
            except Exception:
                pass

    def _save_history(self):
        data = {sid: {
            "win_rate":     s.win_rate,
            "sharpe":       s.sharpe,
            "max_drawdown": s.max_drawdown,
            "call_count":   s.call_count,
            "win_count":    s.win_count,
            "pnl_sum":      s.pnl_sum,
            "weight":       s.weight,
            "last_updated": s.last_updated,
        } for sid, s in self._stats.items()}
        self._history_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    def get_stats(self) -> Dict:
        return {sid: {
            "call_count": s.call_count,
            "win_rate":   round(s.win_count / max(s.call_count, 1), 3),
            "sharpe":     round(s.sharpe, 3),
            "weight":     round(s.weight, 3),
        } for sid, s in self._stats.items()}
