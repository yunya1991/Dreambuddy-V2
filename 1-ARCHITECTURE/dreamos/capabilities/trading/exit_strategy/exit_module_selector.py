#!/usr/bin/env python3
"""
离场模块选择器 (Exit Module Selector)
====================================

基于场景 + 回测表现，为每个持仓选择最佳离场模块。

架构:
    1. ExitPerformanceMemory — 持久化场景×模块的回测得分
    2. ExitModuleSelector — 三级降级选择（精确场景 → 趋势×波动率 → 默认）
    3. 与 OrchestrationMemory 同构，但选择的是离场模块而非编排链路

选择逻辑:
    L0: 精确匹配 36 场景 → 选 score 最高的模块
    L1: 降维 趋势×波动率（12 场景）
    L2: 降维 仅趋势（3 场景）
    L3: 默认 classic（如果可用）或 simple

回测驱动:
    回测器对每个场景 × 每个可用离场模块运行回测，
    计算 Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
    写入 exit_performance_memory.json，selector 启动时加载
"""

from __future__ import annotations

import json
import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExitModuleScore:
    """单个离场模块在某个场景下的回测得分"""
    module_name: str = ""
    score: float = 0.0
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    avg_pnl: float = 0.0
    exit_reasons: Dict[str, int] = field(default_factory=dict)
    last_updated: str = ""


@dataclass
class ExitModuleChoice:
    """选择结果"""
    module_name: str = "simple"
    score: float = 0.0
    confidence: float = 0.0
    fallback_level: int = 0    # 0=精确, 1=趋势×波动率, 2=趋势, 3=默认
    source_scenario: str = ""


class ExitPerformanceMemory:
    """离场模块性能记忆表（持久化）"""

    DEFAULT_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "core", "memory", "exit_performance_memory.json"
    )

    def __init__(self, path: Optional[str] = None):
        self.path = path or self.DEFAULT_PATH
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载"""
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(f"离场性能记忆表已加载: {len(self._data)} 场景")
            except Exception as e:
                logger.warning(f"离场性能记忆表加载失败: {e}")
                self._data = {}
        else:
            logger.info("离场性能记忆表不存在, 将使用默认选择")
            self._data = {}

    def _save(self):
        """保存到 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"离场性能记忆表保存失败: {e}")

    def get_scores(self, scenario_id: str) -> Dict[str, ExitModuleScore]:
        """获取某场景下所有模块的得分"""
        scenario_data = self._data.get(scenario_id, {})
        result = {}
        for mod_name, mod_data in scenario_data.items():
            result[mod_name] = ExitModuleScore(
                module_name=mod_name,
                score=float(mod_data.get("score", 0)),
                sharpe=float(mod_data.get("sharpe", 0)),
                total_return=float(mod_data.get("total_return", 0)),
                max_drawdown=float(mod_data.get("max_drawdown", 0)),
                win_rate=float(mod_data.get("win_rate", 0)),
                total_trades=int(mod_data.get("total_trades", 0)),
                avg_pnl=float(mod_data.get("avg_pnl", 0)),
                exit_reasons=mod_data.get("exit_reasons", {}),
                last_updated=mod_data.get("last_updated", ""),
            )
        return result

    def get_best_module(self, scenario_id: str) -> Optional[ExitModuleScore]:
        """获取某场景下得分最高的模块"""
        scores = self.get_scores(scenario_id)
        if not scores:
            return None
        return max(scores.values(), key=lambda s: s.score)

    def update_from_backtest(
        self,
        scenario_id: str,
        module_name: str,
        metrics: Dict[str, Any],
    ):
        """从回测结果更新某场景某模块的得分

        Args:
            scenario_id: 场景 ID（如 BULL_LOW_ACCELERATING）
            module_name: 模块名（classic / simple / yijing / fundamental）
            metrics: 回测指标（sharpe, total_return, max_drawdown, win_rate, total_trades, avg_pnl, exit_reasons）
        """
        if scenario_id not in self._data:
            self._data[scenario_id] = {}
        # 评分公式: Score = Sharpe×0.4 + Return×0.3 + (1-MaxDD)×0.2 + WinRate×0.1
        sharpe = float(metrics.get("sharpe", 0))
        ret = float(metrics.get("total_return", 0))
        max_dd = float(metrics.get("max_drawdown", 0))
        win_rate = float(metrics.get("win_rate", 0))
        score = sharpe * 0.4 + ret * 0.3 + (1.0 - max_dd) * 0.2 + win_rate * 0.1

        self._data[scenario_id][module_name] = {
            "score": round(score, 4),
            "sharpe": round(sharpe, 4),
            "total_return": round(ret, 4),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "total_trades": int(metrics.get("total_trades", 0)),
            "avg_pnl": round(float(metrics.get("avg_pnl", 0)), 4),
            "exit_reasons": metrics.get("exit_reasons", {}),
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()
        logger.info(
            f"离场性能更新: {scenario_id} × {module_name} | "
            f"score={score:.4f} sharpe={sharpe:.2f} ret={ret:.2%} maxDD={max_dd:.2%} win={win_rate:.1%}"
        )


class ExitModuleSelector:
    """离场模块选择器 — 基于场景+回测表现选最优

    三级降级选择（与 OrchestrationMemory 同构）:
        L0: 精确匹配 36 场景
        L1: 降维 趋势×波动率（12 场景）
        L2: 降维 仅趋势（3 场景）
        L3: 默认 classic（可用时）或 simple

    使用示例:
        selector = ExitModuleSelector()
        choice = selector.select("BEAR_LOW_ACCELERATING")
        adapter = selector.get_adapter(choice.module_name)
        decision = adapter.evaluate(symbol="BTC", ...)
    """

    # 场景 → 趋势/波动率 降维映射
    TREND_MAP = {
        "BULL": "BULL", "BEAR": "BEAR", "RANGE": "RANGE", "EXTREME": "EXTREME",
    }
    VOL_MAP = {
        "LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH", "EXTREME": "EXTREME",
    }

    # 默认模块优先级（无回测数据时）
    DEFAULT_PRIORITY = ["classic", "simple", "yijing", "fundamental"]

    def __init__(self, memory_path: Optional[str] = None):
        self.memory = ExitPerformanceMemory(memory_path)
        self._adapters: Dict[str, Any] = {}
        self._init_adapters()

    def _init_adapters(self):
        """初始化所有适配器"""
        from dreamos.capabilities.trading.exit_strategy.exit_module_adapter import (
            get_all_adapters,
        )
        self._adapters = get_all_adapters()

    # v2.5 场景级强制路由（避免震荡市选到回测差的模块）
    # - LOW 波动率: 内置 ATR (builtin) > simple > yijing > classic（震荡市越简单越好）
    # - MEDIUM/HIGH: 按回测 score 自由选优（classic/yijing 优于 simple）
    # - RANGE/CHOP: 同 LOW 波动率（震荡市）
    # 返回 None 表示"无强制，按 L0/L1/L2/L3 正常选优"
    def _scenario_override(self, scenario_id: str) -> Optional[ExitModuleChoice]:
        if not scenario_id:
            return None
        # 震荡/低波动 → 强制走 builtin（_try_selector_exit 看到 builtin 会返回 None 让 check_exit 回退内置 ATR）
        is_low_vol = any(tok in scenario_id for tok in ("LOW", "CHOP", "RANGE"))
        if is_low_vol:
            return ExitModuleChoice(
                module_name="builtin",  # 特殊标识：告诉 _try_selector_exit 回退内置 ATR
                score=0.0,
                confidence=0.35,
                fallback_level=4,  # 特殊：场景强制路由
                source_scenario=f"override_low_vol({scenario_id})",
            )
        return None

    def select(self, scenario_id: str = "") -> ExitModuleChoice:
        """选择最佳离场模块

        选择链路（v2.5 新增强制路由）：
            override(LOW/RANGE/CHOP→builtin) → L0 精确匹配 → L1 趋势×波动率 → L2 仅趋势 → L3 默认

        Args:
            scenario_id: 场景 ID（如 BEAR_LOW_ACCELERATING）

        Returns:
            ExitModuleChoice
        """
        if not scenario_id:
            return self._default_choice("无场景ID")

        # 0. 场景级强制路由（震荡/低波动→builtin，优先级最高，无需回测数据）
        override = self._scenario_override(scenario_id)
        if override is not None:
            return override

        # L0: 精确匹配
        best = self.memory.get_best_module(scenario_id)
        if best and best.score > 0:
            return ExitModuleChoice(
                module_name=best.module_name,
                score=best.score,
                confidence=0.9,
                fallback_level=0,
                source_scenario=scenario_id,
            )

        # L1: 降维 趋势×波动率
        trend, vol = self._extract_trend_vol(scenario_id)
        if trend and vol:
            l1_key = f"{trend}_{vol}"
            best_l1 = self.memory.get_best_module(l1_key)
            if best_l1 and best_l1.score > 0:
                return ExitModuleChoice(
                    module_name=best_l1.module_name,
                    score=best_l1.score,
                    confidence=0.7,
                    fallback_level=1,
                    source_scenario=l1_key,
                )

        # L2: 降维 仅趋势
        if trend:
            best_l2 = self.memory.get_best_module(trend)
            if best_l2 and best_l2.score > 0:
                return ExitModuleChoice(
                    module_name=best_l2.module_name,
                    score=best_l2.score,
                    confidence=0.5,
                    fallback_level=2,
                    source_scenario=trend,
                )

        # L3: 默认
        return self._default_choice(scenario_id)

    def _default_choice(self, scenario_id: str = "") -> ExitModuleChoice:
        """默认选择：按优先级选第一个可用的模块"""
        for mod_name in self.DEFAULT_PRIORITY:
            adapter = self._adapters.get(mod_name)
            if adapter and adapter.is_available:
                return ExitModuleChoice(
                    module_name=mod_name,
                    score=0.0,
                    confidence=0.3,
                    fallback_level=3,
                    source_scenario=f"default({scenario_id})",
                )
        # 兜底: simple 一定可用
        return ExitModuleChoice(
            module_name="simple",
            score=0.0,
            confidence=0.1,
            fallback_level=3,
            source_scenario="fallback",
        )

    def _extract_trend_vol(self, scenario_id: str) -> Tuple[str, str]:
        """从场景 ID 提取趋势和波动率

        例: BEAR_LOW_ACCELERATING → (BEAR, LOW)
            BULL_HIGH_BREAKDOWN → (BULL, HIGH)
            RANGE_MEDIUM_CHOP → (RANGE, MEDIUM)
        """
        parts = scenario_id.split("_")
        trend = ""
        vol = ""
        for part in parts:
            if part in self.TREND_MAP:
                trend = self.TREND_MAP[part]
            elif part in self.VOL_MAP:
                vol = self.VOL_MAP[part]
        return trend, vol

    def get_adapter(self, module_name: str):
        """获取指定模块的适配器"""
        adapter = self._adapters.get(module_name)
        if adapter is None:
            logger.warning(f"离场模块 {module_name} 不存在, 回退到 simple")
            adapter = self._adapters.get("simple")
        return adapter

    def evaluate(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,
        market_data: Dict[str, Any],
        scenario_id: str = "",
        position_age_sec: float = 0.0,
        unrealized_pnl_pct: float = 0.0,
        leverage: float = 1.0,
        atr_pct: float = 0.02,
        mfe_pnl_pct: float = 0.0,
        max_dd_pct: float = 0.0,
    ):
        """选择最佳模块并评估离场

        Returns:
            (UnifiedExitDecision, ExitModuleChoice)
        """
        choice = self.select(scenario_id)
        adapter = self.get_adapter(choice.module_name)
        decision = adapter.evaluate(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            market_data=market_data,
            position_age_sec=position_age_sec,
            unrealized_pnl_pct=unrealized_pnl_pct,
            leverage=leverage,
            atr_pct=atr_pct,
            mfe_pnl_pct=mfe_pnl_pct,
            max_dd_pct=max_dd_pct,
            scenario_id=scenario_id,
        )
        return decision, choice

    @property
    def available_modules(self) -> List[str]:
        """当前可用的离场模块列表"""
        return [name for name, adapter in self._adapters.items() if adapter.is_available]
