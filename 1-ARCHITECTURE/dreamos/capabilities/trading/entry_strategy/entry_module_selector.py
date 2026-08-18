#!/usr/bin/env python3
"""
入场模块选择器 (Entry Module Selector)
======================================

基于场景 + 回测表现，为每个待入场窗口选择最佳入场模块。
架构完全对齐 ExitModuleSelector（三级降级 + 场景强降级）。

三级降级选择（按置信度从高到低）：
    L0 精确匹配 36 场景（如 BEAR_HIGH_BREAKDOWN）       score 置信度 0.9
    L1 趋势×波动率（趋势 3 类 × 波动率 3 类 = 9 场景）  score 置信度 0.7
    L2 仅趋势（BULL/BEAR/NEUTRAL 3 类）                score 置信度 0.5
    L3 默认优先级（无回测数据）                          置信度 0.3

场景强降级（fallback_level=5，无需回测数据，优先级最高）：
    LOW 波动率 / CHOP / RANGE 震荡市 → 选 scenario_ema（基线最稳，避免高智能假信号）
    NORMAL / HIGH 波动率 → 按回测 score 正常选优

选择的模块将被 EntryModuleBacktester 回测评估后写入 EntryPerformanceMemory：
    {scenario_id: {module_name: {sharpe, total_return, win_rate, max_dd, score, trades}}}

打分公式（与离场完全对齐）：
    Score = Sharpe × 0.4 + Return × 0.3 + (1 - MaxDD) × 0.2 + WinRate × 0.1
    （每个指标先在模块内部做 Min-Max 归一化到 [0,1]）
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("entry_module_selector")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class EntryModuleChoice:
    """入场模块选择结果"""
    module_name: str                 # 被选中的模块名
    score: float = 0.0               # 综合得分 [0, 1]
    confidence: float = 0.0          # 选择置信度（L0~L3 层级决定）
    fallback_level: int = 3          # 0=L0 精确, 1=L1, 2=L2, 3=L3默认, 5=场景强降级
    source_scenario: str = ""        # 命中的场景（精确/趋势×波动率/趋势）
    top_modules: List[Tuple[str, float]] = None  # 前3模块，调试用

    def __post_init__(self):
        if self.top_modules is None:
            self.top_modules = []


# 默认优先级（无回测数据时 L3 fallback）
DEFAULT_MODULE_PRIORITY: List[str] = [
    "scenario_ema",   # 0. 基线最稳
    "s3_trend",       # 1. 三屏趋势（多周期共振稳）
    "a2_fusion",      # 2. A2 综合（跨链融合）
    "c2_momentum",    # 3. C2 动量
    "yj_infer",       # 4. 易经推理
    "martin_v15",     # 5. 马丁 V15（仅震荡+特定触发，排最后）
]


# ============================================================
# 选择器
# ============================================================

class EntryModuleSelector:
    """入场模块择优选择器

    用法:
        selector = EntryModuleSelector(memory_path="dreamos/core/memory/entry_performance_memory.json")
        choice = selector.select("NEUTRAL_NORMAL_ACCELERATING")
        adapter = selector.get_adapter(choice.module_name)
        decision = adapter.evaluate(symbol, scenario_id, window_klines, market_data)
    """

    def __init__(
        self,
        memory_path: str = "",
        min_trades_l0: int = 30,
        min_trades_l1: int = 50,
        min_trades_l2: int = 100,
    ):
        if not memory_path:
            memory_path = os.environ.get(
                "DREAMOS_ENTRY_PERF_MEMORY",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "core/memory/entry_performance_memory.json")
            )
        self.memory_path = memory_path
        self.min_trades_l0 = min_trades_l0
        self.min_trades_l1 = min_trades_l1
        self.min_trades_l2 = min_trades_l2
        self._memory: Dict[str, Any] = {}
        self._load_memory()

    # ------------------------------------------------------------------
    # 内存加载与适配器
    # ------------------------------------------------------------------

    def _load_memory(self):
        try:
            if os.path.exists(self.memory_path):
                with open(self.memory_path, "r", encoding="utf-8") as f:
                    self._memory = json.load(f)
        except Exception as e:
            logger.warning(f"加载 entry_performance_memory 失败: {e}")
            self._memory = {}

    def get_adapter(self, module_name: str):
        """获取入场模块适配器实例（None 则走 fallback 基线）"""
        try:
            from dreamos.capabilities.trading.entry_strategy.entry_module_adapter import create_entry_adapter
            return create_entry_adapter(module_name)
        except Exception as e:
            logger.debug(f"获取入场适配器 {module_name} 失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 工具：场景降维、归一化打分
    # ------------------------------------------------------------------

    @staticmethod
    def decompose_scenario(scenario_id: str) -> Dict[str, str]:
        """分解场景 → {trend, vol, accel}

        场景命名约定: <TREND>_<VOL>_<ACCEL>，如 BEAR_HIGH_BREAKDOWN / NEUTRAL_LOW_ACCELERATING
        """
        parts = scenario_id.split("_")
        trend = parts[0] if parts else "NEUTRAL"
        vol = parts[1] if len(parts) > 1 else "NORMAL"
        accel = "_".join(parts[2:]) if len(parts) > 2 else "ACCELERATING"
        return {"trend": trend, "vol": vol, "accel": accel}

    def _metrics_from_record(self, rec: Dict[str, Any]) -> Dict[str, float]:
        """从回测记录提取 4 个打分指标"""
        return {
            "sharpe": float(rec.get("sharpe") or rec.get("sharpe_ratio") or 0),
            "return": float(rec.get("total_return") or rec.get("avg_pnl") or 0),
            "max_dd": float(rec.get("max_dd") or rec.get("max_drawdown") or 0),
            "win_rate": float(rec.get("win_rate") or rec.get("winrate") or 0),
        }

    # ------------------------------------------------------------------
    # 场景强降级
    # ------------------------------------------------------------------

    def _scenario_override(self, scenario_id: str) -> Optional[EntryModuleChoice]:
        if not scenario_id:
            return None
        # LOW / CHOP / RANGE → 震荡市 → 强制 scenario_ema 基线最稳
        is_ranging = any(tok in scenario_id for tok in ("LOW", "CHOP", "RANGE"))
        if is_ranging:
            return EntryModuleChoice(
                module_name="scenario_ema",
                score=0.0, confidence=0.45, fallback_level=5,
                source_scenario=f"override_low_vol_ranging({scenario_id})",
            )
        return None

    # ------------------------------------------------------------------
    # 主选择入口
    # ------------------------------------------------------------------

    def select(self, scenario_id: str) -> EntryModuleChoice:
        """选择最佳入场模块。链路：override → L0 → L1 → L2 → L3"""
        if not scenario_id:
            return self._default_choice("无场景ID")

        override = self._scenario_override(scenario_id)
        if override is not None:
            return override

        dec = self.decompose_scenario(scenario_id)
        trend, vol = dec["trend"], dec["vol"]

        # L0: 精确场景
        if scenario_id in self._memory:
            top = self._top_modules_from_records(self._memory[scenario_id], self.min_trades_l0)
            if top:
                name, score = top[0]
                return EntryModuleChoice(
                    module_name=name, score=score, confidence=0.9, fallback_level=0,
                    source_scenario=f"L0精确({scenario_id})", top_modules=top,
                )

        # L1: 趋势 × 波动率
        l1_key = f"{trend}_{vol}"
        l1_candidates = {}
        for sid, recs in self._memory.items():
            d = self.decompose_scenario(sid)
            if d["trend"] == trend and d["vol"] == vol:
                for mod, rec in recs.items():
                    if mod not in l1_candidates:
                        l1_candidates[mod] = {"trades": 0, "records": []}
                    l1_candidates[mod]["trades"] += int(rec.get("trades") or 0)
                    l1_candidates[mod]["records"].append(rec)
        if l1_candidates:
            merged = {}
            for mod, info in l1_candidates.items():
                if info["trades"] < 1:
                    continue
                merged[mod] = self._merge_records(info["records"])
            top = self._top_modules_from_records(merged, self.min_trades_l1)
            if top:
                name, score = top[0]
                return EntryModuleChoice(
                    module_name=name, score=score, confidence=0.7, fallback_level=1,
                    source_scenario=f"L1趋势×波动率({l1_key})", top_modules=top,
                )

        # L2: 仅趋势
        l2_candidates = {}
        for sid, recs in self._memory.items():
            d = self.decompose_scenario(sid)
            if d["trend"] == trend:
                for mod, rec in recs.items():
                    if mod not in l2_candidates:
                        l2_candidates[mod] = {"trades": 0, "records": []}
                    l2_candidates[mod]["trades"] += int(rec.get("trades") or 0)
                    l2_candidates[mod]["records"].append(rec)
        if l2_candidates:
            merged = {}
            for mod, info in l2_candidates.items():
                if info["trades"] < 1:
                    continue
                merged[mod] = self._merge_records(info["records"])
            top = self._top_modules_from_records(merged, self.min_trades_l2)
            if top:
                name, score = top[0]
                return EntryModuleChoice(
                    module_name=name, score=score, confidence=0.5, fallback_level=2,
                    source_scenario=f"L2仅趋势({trend})", top_modules=top,
                )

        # L3: 默认优先级（无回测数据）
        return self._default_choice(f"无可用回测数据({scenario_id})")

    def _default_choice(self, reason: str) -> EntryModuleChoice:
        for name in DEFAULT_MODULE_PRIORITY:
            adapter = self.get_adapter(name)
            if adapter is not None and getattr(adapter, 'is_available', True):
                return EntryModuleChoice(
                    module_name=name, score=0.0, confidence=0.3, fallback_level=3,
                    source_scenario=f"L3默认({reason})",
                )
        return EntryModuleChoice(
            module_name="scenario_ema", score=0.0, confidence=0.0, fallback_level=3,
            source_scenario=f"L3保底({reason})",
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _merge_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """多条记录按 trades 加权合并"""
        w_sum, s_sum, r_sum, dd_sum, wr_sum = 0.0, 0.0, 0.0, 0.0, 0.0
        t_sum = 0
        for r in records:
            m = self._metrics_from_record(r)
            t = int(r.get("trades") or 0) or 1
            w_sum += t; t_sum += t
            s_sum += m["sharpe"] * t
            r_sum += m["return"] * t
            dd_sum += m["max_dd"] * t
            wr_sum += m["win_rate"] * t
        if w_sum <= 0:
            return {"trades": 0, "sharpe": 0, "total_return": 0, "max_dd": 0, "win_rate": 0}
        return {
            "trades": t_sum,
            "sharpe": s_sum / w_sum,
            "total_return": r_sum / w_sum,
            "max_dd": dd_sum / w_sum,
            "win_rate": wr_sum / w_sum,
        }

    def _top_modules_from_records(
        self,
        records: Dict[str, Any],
        min_trades: int,
    ) -> List[Tuple[str, float]]:
        """按 trades 过滤 + 归一化打分，返回 [(module, score)] Top3"""
        valid = {m: r for m, r in records.items() if int(r.get("trades") or 0) >= min_trades}
        if not valid:
            return []
        # 归一化每项
        metrics = {m: self._metrics_from_record(r) for m, r in valid.items()}
        all_sharpes = [m["sharpe"] for m in metrics.values()]
        all_returns = [m["return"] for m in metrics.values()]
        all_maxdds = [m["max_dd"] for m in metrics.values()]
        all_wrs = [m["win_rate"] for m in metrics.values()]

        def _norm(vals: List[float], higher_better: bool) -> Dict[float, float]:
            mn, mx = min(vals), max(vals)
            if abs(mx - mn) < 1e-9:
                return {v: 0.5 for v in vals}
            if higher_better:
                return {v: (v - mn) / (mx - mn) for v in vals}
            return {v: (mx - v) / (mx - mn) for v in vals}

        s_norm = _norm(all_sharpes, True)
        r_norm = _norm(all_returns, True)
        d_norm = _norm(all_maxdds, False)
        w_norm = _norm(all_wrs, True)

        scored = []
        for m, met in metrics.items():
            score = (
                s_norm[met["sharpe"]] * 0.4
                + r_norm[met["return"]] * 0.3
                + d_norm[met["max_dd"]] * 0.2
                + w_norm[met["win_rate"]] * 0.1
            )
            scored.append((m, round(score, 4)))
        scored.sort(key=lambda x: -x[1])
        return scored[:3]
