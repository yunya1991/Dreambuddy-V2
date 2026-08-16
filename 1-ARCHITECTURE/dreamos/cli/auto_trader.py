"""
自动化交易流程编排模块

完整自动化链路:
    定时触发 → 市场扫描 → A1-A5分析 → G1风控检查 → A5执行决策 → 交易所下单 → A9离场监控

支持 dry_run 模式进行模拟交易测试
支持 Aster 和 OKX 双交易所
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 加载 Dream OS 独立 .env 文件
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

MIN_LEVERAGE = 1
MAX_LEVERAGE = 5
DEFAULT_LEVERAGE = 3
CONFIDENCE_THRESHOLD = float(os.environ.get("DREAMOS_CONFIDENCE_THRESHOLD", "0.4"))
# 离场模块选择器开关：v2.5 修复后默认启用择优。
# 分类路由（ExitModuleSelector._scenario_override）：
#   LOW/CHOP/RANGE 震荡市 → module_name="builtin"（_try_selector_exit 看到后返回 None → 回退内置 ATR 时间衰减）
#   NORMAL/HIGH 趋势/高波动 → 按回测 score 选 classic/yijing 最优（fallback_level 0/1/2）
# 环境变量 DREAMOS_EXIT_SELECTOR_ENABLED=0 可强制关闭，完全走内置 ATR。
EXIT_SELECTOR_ENABLED = os.environ.get("DREAMOS_EXIT_SELECTOR_ENABLED", "1") == "1"
# 入场模块选择器开关（v2.6 新增）：默认开启，有回测数据(fallback_level<3)时覆盖 analysis 的方向/置信度；
# 无数据(LOW/CHOP/RANGE)时走 scenario_ema 强降级或 L3 回退原链路（不影响原 TradingAgent/C1→C2→C3）
ENTRY_SELECTOR_ENABLED = os.environ.get("DREAMOS_ENTRY_SELECTOR_ENABLED", "1") == "1"


def calc_dynamic_leverage(
    confidence: float,
    min_lev: int = MIN_LEVERAGE,
    max_lev: int = MAX_LEVERAGE,
    threshold: float = CONFIDENCE_THRESHOLD,
    atr_pct: Optional[float] = None,
    vol_benchmark: float = 0.025,
) -> int:
    """基于置信度+波动率动态计算杠杆倍数（Kelly 风格）

    映射逻辑:
      - 置信度 = threshold (默认 0.4) → min_lev (1x)
      - 置信度 >= 0.75 → 基础系数打满
      - atr_pct > vol_benchmark (默认 2.5%) 时按比例降杠杆(高波动币降风险)
      - atr_pct < 1.0% 时最高可 +1x
    """
    if confidence <= threshold:
        return min_lev
    conf_ratio = min(1.0, (confidence - threshold) / max(1e-6, (0.75 - threshold)))
    # 波动率调节 (ATR% 作为日波代理)
    vol_factor = 1.0
    if atr_pct is not None and atr_pct > 0:
        vol_ratio = vol_benchmark / max(1e-6, atr_pct)  # 小波动=高杠杆
        vol_factor = max(0.5, min(1.5, vol_ratio))
    target = min_lev + conf_ratio * (max_lev - min_lev)
    target *= vol_factor
    return max(min_lev, min(max_lev, int(round(target))))


def calc_dynamic_position_and_leverage(
    confidence: float,
    atr_pct: float,
    account_equity: Optional[float] = None,
    direction: str = "LONG",
    min_lev: int = MIN_LEVERAGE,
    max_lev: int = MAX_LEVERAGE,
    threshold: float = CONFIDENCE_THRESHOLD,
    symbol: str = "BTC",
    default_equity: float = 60.0,
) -> Dict[str, float]:
    """统一的 Kelly 动态仓位 & 杠杆模型（与 A5 模块版本保持一致）

    Args:
        confidence: 决策置信度 [0,1]（来自 A2/A5/A7 校准后）
        atr_pct:   ATR/price 波动率（0.02 = 2% 日波）
        account_equity: 账户总权益(USDT)，None 时用 default 或 查询接口
        direction:  LONG/SHORT，仅用于日志/校验
        min_lev/max_lev/threshold: 杠杆参数
        symbol:    币种（用于 BTC 溢价基准）
        default_equity: 接口查询失败时的默认权益(60 USDT 为测试账户量级)

    Returns:
        dict with keys: position_size, leverage, confidence_score, vol_score, kelly_pct, max_single_pct, min_position_usdt
    """
    # 1) 置信度分数：threshold 以下=0，0.75 以上=1.0
    if confidence >= threshold:
        conf_score = min(1.0, (confidence - threshold) / max(1e-6, 0.75 - threshold))
    else:
        conf_score = 0.0
    conf_score = max(0.0, min(1.0, conf_score))

    # 2) 波动率分数：日波 2.5% 基准=1.0；>4% 时惩罚；<1.5% 时奖励
    atr = max(0.001, float(atr_pct) if atr_pct else 0.025)
    vol_score = 0.025 / atr
    vol_score = max(0.5, min(1.5, vol_score))

    # 3) Kelly 比例：半凯利，f* = (p*b - q) / b，近似用置信度当作胜率 p
    edge = max(0.0, conf_score - 0.35)
    kelly_full = (edge * 3.0 - (1.0 - conf_score)) / 2.0
    kelly_full = max(0.02, min(0.30, kelly_full))
    kelly_half = kelly_full * 0.5

    # 4) 账户余额
    if account_equity is None or account_equity <= 0:
        account_equity = default_equity
    eq = max(0.0, float(account_equity))

    # 5) 单币种硬上限 & 下限
    tier1 = {"BTC", "ETH"}
    tier2 = {"SOL", "BNB", "XRP"}
    tier_small_min = {"OP", "ARB", "DOGE", "SHIB", "PEPE", "DOT"}
    max_single_pct = 0.25 if symbol.upper() in tier1 else (0.18 if symbol.upper() in tier2 else 0.15)
    min_position_usdt = 5.0 if symbol.upper() in tier_small_min else 3.0

    # 6) 综合名义本金 = equity × kelly × conf × vol
    position = eq * kelly_half * conf_score * vol_score
    position = max(min_position_usdt, min(position, eq * max_single_pct))
    position = round(position, 2)

    # 7) 杠杆 = 动态（置信度+波动率）
    leverage = calc_dynamic_leverage(
        confidence=confidence,
        min_lev=min_lev,
        max_lev=max_lev,
        threshold=threshold,
        atr_pct=atr_pct,
    )

    return {
        "position_size": position,
        "leverage": float(leverage),
        "confidence_score": round(conf_score, 3),
        "vol_score": round(vol_score, 3),
        "kelly_pct": round(kelly_half, 4),
        "max_single_pct": max_single_pct,
        "min_position_usdt": min_position_usdt,
        "account_equity": round(eq, 2),
    }


class AutoTrader:
    """自动化交易器"""

    # P1-2: 降级路径告警阈值
    FALLBACK_SUSPEND_THRESHOLD = 3  # 连续3次降级暂停该 symbol

    # PROP-20260816 P2: 持仓快照目录 (conftest monkeypatch 到 tmp 隔离)
    SNAPSHOT_DIR = Path(__file__).parent / "scheduler_data"

    def __init__(self, agent_id: str = "dream_os", dry_run: bool = True, exchange: str = "aster"):
        self.agent_id = agent_id
        self.dry_run = dry_run
        self.exchange = exchange.lower()
        self._okx_client = None
        self._hl_client = None
        self._aster_module = None
        self._trading_agent = None
        self._enabled = True
        self._last_trade_time = {}
        self._min_trade_interval_minutes = 30
        self._scenario_classifier = None
        self._orchestration_memory = None
        self._feedback_collector = None
        self._exit_selector = None  # 离场模块选择器（延迟初始化）
        self._entry_selector = None  # 入场模块选择器（延迟初始化）
        # _last_trade_time 持久化路径（跨 scheduler 重启共享）
        self._trade_time_path = str(Path(__file__).parent / ".trade_time.json")
        self._last_trade_time = self._load_trade_time_state()
        # 当前分析上下文（场景+编排），供 execute_trade 回写反馈使用
        self._current_context = {"scenario_id": "UNKNOWN", "pattern": "c_chain", "expected_direction": "HOLD"}
        # P1-2: 降级路径计数器 — symbol → 连续降级次数
        self._fallback_counts: Dict[str, int] = {}
        # P1-2: 暂停的 symbol 集合
        self._suspended_symbols: set = set()
        # P0-3: 4h 周期去重 — symbol → 最后开仓的 4h 周期起始时间戳
        # 1h 调度但开仓基于 4h，避免同一 4h 周期内重复开仓
        # 持久化到文件，跨实例共享（scheduler 每次扫描创建新实例）
        self._dedup_path = str(Path(__file__).parent / ".4h_dedup.json")
        self._last_trade_4h_ts: Dict[str, int] = self._load_dedup_state()
        # PROP-20260816 P2: 交易所侧平仓对账 —— 持仓快照文件
        # (交易所 TP/SL 触发平仓时本程序收不到事件,靠快照 diff + fills 确认)
        # SNAPSHOT_DIR 为类属性,conftest 在测试中 monkeypatch 到 tmp 目录
        self._snapshot_path = self.SNAPSHOT_DIR / "position_snapshot.json"
        # per-symbol 持仓运行时状态（classic 离场适配器用）：
        #   {symbol: {leverage, trailing_armed, trailing_stop_price,
        #             peak_price, trough_price, mfe_pnl_pct, max_dd_pct, entry_price}}
        # 跨离场巡检持续累积，未命中的 symbol 下次巡检自动复用
        self._position_exit_state: Dict[str, Dict[str, Any]] = {}

    def get_scenario_classifier(self):
        """场景分类器（延迟初始化）"""
        if self._scenario_classifier is None:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            self._scenario_classifier = ScenarioClassifier()
        return self._scenario_classifier

    def get_orchestration_memory(self):
        """编排记忆表（延迟初始化）"""
        if self._orchestration_memory is None:
            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            self._orchestration_memory = OrchestrationMemory()
            self._orchestration_memory.load()
        return self._orchestration_memory

    def get_feedback_collector(self):
        """执行反馈收集器（延迟初始化）

        断点3修复：交易执行结果回写到反馈收集器，驱动进化引擎。
        """
        if self._feedback_collector is None:
            from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
            memory = self.get_orchestration_memory()
            self._feedback_collector = ExecutionFeedbackCollector(memory)
        return self._feedback_collector

    def get_exit_selector(self):
        """离场模块选择器（延迟初始化）

        基于场景 + 回测表现选择最佳离场模块（classic / yijing / fundamental / simple）。
        仅有回测数据时生效（fallback_level < 3），否则 check_exit 回退到内置逻辑。
        """
        if self._exit_selector is None:
            try:
                from dreamos.capabilities.trading.exit_strategy.exit_module_selector import ExitModuleSelector
                self._exit_selector = ExitModuleSelector()
            except Exception as e:
                logger.warning(f"离场模块选择器加载失败: {e}")
                self._exit_selector = None
        return self._exit_selector

    def get_entry_selector(self):
        """入场模块选择器（延迟初始化）

        6 个可选模块（a2_fusion/c2_momentum/s3_trend/yj_infer/martin_v15/scenario_ema）。
        回测驱动：EntryPerformanceMemory.json 有数据时按 score 择优；无数据时走 L3 默认。
        LOW/CHOP/RANGE 场景强降级 scenario_ema（震荡市越简单越好）。
        """
        if self._entry_selector is None:
            try:
                from dreamos.capabilities.trading.entry_strategy import EntryModuleSelector
                self._entry_selector = EntryModuleSelector()
            except Exception as e:
                logger.warning(f"入场模块选择器加载失败: {e}")
                self._entry_selector = None
        return self._entry_selector

    def _try_selector_entry(
        self,
        symbol: str,
        scenario_id: str,
        candles_1h_rows: Optional[List[tuple]],  # [(t,o,h,l,c,v), ...] 升序 48 根 1h
        market_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """入场模块选择器 overlay（v2.6 新增）。

        返回 dict: {direction, confidence, module_name, reason, source_scenario, entry_decision_raw}
            或 None → 不 override，回退原链路 (TradingAgent / C1→C2→C3)

        触发条件（全部满足）:
            1. ENTRY_SELECTOR_ENABLED=1（默认）
            2. EntryModuleSelector 返回 fallback_level ∈ {0,1,2,5} 且 不是 default fallback (L3)
            3. 被选中的 adapter.is_available 且 返回 direction != HOLD
        """
        if not ENTRY_SELECTOR_ENABLED:
            return None
        try:
            selector = self.get_entry_selector()
            if selector is None:
                return None
            choice = selector.select(scenario_id)
            # L3 默认：无回测数据，不做 override（尊重原链路）
            if choice.fallback_level == 3:
                return None
            adapter = selector.get_adapter(choice.module_name)
            if adapter is None or not getattr(adapter, 'is_available', True):
                return None
            # 构造 48 根 1h K 行（与回测一致）：优先用 candles_1h_rows，否则从 market_data candles_1h 转换
            window_48 = candles_1h_rows or []
            if not window_48 and market_data.get("candles_1h"):
                for c in market_data["candles_1h"]:
                    if isinstance(c, dict):
                        row = (int(c.get("t",0)), float(c.get("o",0)), float(c.get("h",0)),
                               float(c.get("l",0)), float(c.get("c",0)), float(c.get("v",0)))
                        if row[4] > 0: window_48.append(row)
                    elif isinstance(c, (list, tuple)) and len(c) >= 6:
                        window_48.append(tuple(c[:6]))
            # 不足 48 时从 closes 回补（非严格但保持一致性）
            if len(window_48) < 24 and market_data.get("price", 0) > 0:
                # 无法凑齐足够K线 → 放弃 override
                return None
            entry_decision = adapter.evaluate(
                symbol=symbol, scenario_id=scenario_id,
                window_klines=window_48, market_data=market_data, extra_state=None,
            )
            direction = (entry_decision.direction or "HOLD").upper()
            confidence = float(entry_decision.confidence or 0.0)
            if direction not in ("LONG", "SHORT"):
                return None
            return {
                "direction": direction,
                "confidence": confidence,
                "module_name": choice.module_name,
                "source_scenario": choice.source_scenario,
                "fallback_level": choice.fallback_level,
                "reason": getattr(entry_decision, 'entry_reason', ''),
                "entry_decision_raw": entry_decision,
            }
        except Exception as e:
            logger.debug(f"入场选择器 override 失败: {e}")
            return None

    def record_trade_feedback(self, trade_result: Dict[str, Any]) -> None:
        """记录交易执行反馈到收集器

        在交易执行后调用，将场景+编排+方向+收益回写，
        供 EvolutionEngine._check_orchestration_optimization() 评估。

        Args:
            trade_result: {"direction", "result"(收益率), "expected_direction", ...}
        """
        try:
            collector = self.get_feedback_collector()
            scenario_id = trade_result.get("scenario_id", self._current_context["scenario_id"])
            pattern = trade_result.get("pattern", self._current_context["pattern"])
            collector.record(
                scenario_id=scenario_id,
                pattern=pattern,
                trade_result={
                    "direction": trade_result.get("direction", "HOLD"),
                    "result": trade_result.get("result", 0.0),
                    "expected_direction": trade_result.get("expected_direction",
                                                           self._current_context["expected_direction"]),
                    "symbol": trade_result.get("symbol", ""),
                    "entry_price": trade_result.get("entry_price", 0),
                    "exit_price": trade_result.get("exit_price", 0),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            logger.info(f"反馈已记录: {scenario_id} | {pattern} | dir={trade_result.get('direction')} | ret={trade_result.get('result', 0):.4f}")
        except Exception as e:
            logger.warning(f"记录交易反馈失败: {e}")

    def update_exit_feedback(self, symbol: str, entry_price: float,
                             exit_price: float, result: float) -> None:
        """P0-1: 平仓后回填实际结果到反馈收集器

        闭合反馈环：开仓时 record(result=0)，平仓时 update_exit_result 回填。
        这让进化引擎能获得真实收益数据，而非永久冻结。

        Args:
            symbol: 交易对
            entry_price: 开仓价
            exit_price: 平仓价
            result: 实际收益率（已扣手续费）
        """
        try:
            collector = self.get_feedback_collector()
            scenario_id = self._current_context.get("scenario_id", "UNKNOWN")
            updated = collector.update_exit_result(
                scenario_id=scenario_id,
                symbol=symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                result=result,
            )
            if updated:
                logger.info(f"P0-1 平仓反馈已回填: {symbol} | result={result:.4f}")
            else:
                logger.warning(f"P0-1 平仓反馈未匹配开仓记录: {symbol} | entry={entry_price}")
        except Exception as e:
            logger.warning(f"P0-1 回填平仓反馈失败: {e}")

    def _feed_cognitive_loop(self, symbol: str, direction: str, entry_price: float,
                             exit_price: float, ret: float, position_amt: float,
                             exit_reason: str = "", px_source: str = "") -> None:
        """P1-3: 平仓后将真实盈亏回填到 DreamOS E层认知闭环

        名义价值 = |position_amt| × entry_price, pnl_usdt = ret × 名义价值
        (ret 已扣手续费)。调用 orchestrator_v2.record_real_exit():
        真实审查 → lessons 落盘 → W/L/累计PnL/连败计数更新。

        任何异常仅记日志 —— 认知回填失败绝不影响持仓管家主流程。
        """
        try:
            notional = abs(float(position_amt or 0)) * float(entry_price or 0)
            pnl_usdt = round(float(ret) * notional, 6)
            trade_result = {
                "symbol": symbol,
                "direction": direction,
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "position_size": abs(float(position_amt or 0)),
                "pnl_usdt": pnl_usdt,
                "pnl_pct": float(ret),
                "confidence": 0.5,  # 旧管线无置信度记录,用中性值
                "addon_count": 0,
                "hold_hours": 0.0,
                "exit_reason": f"{exit_reason}|{px_source}".strip("|"),
            }
            from dreamos.capabilities.trading.orchestrator_v2 import record_real_exit
            review = record_real_exit(trade_result)
            logger.info(
                f"P1-3 认知回填: {symbol} | pnl={pnl_usdt:.4f} USDT | "
                f"assessment={review.get('assessment', '?')} | "
                f"lessons={len(review.get('lessons', []))}"
            )
        except Exception as e:
            logger.warning(f"P1-3 认知闭环回填失败(不影响主流程): {e}")

    def _resolve_exit_price(self, exec_result: Dict, estimated_price: float) -> Tuple[float, str]:
        """P2: 确定平仓价格来源（持仓管家接真实成交回报）

        Returns:
            (exit_price, source):
              - real_fill: 交易所真实成交均价（实盘成功平仓,优先使用）
              - dry_run:   模拟平仓,使用决策估算价
              - estimated: 实盘但无成交回报（部分成交/回报缺失）,降级估算价
        """
        try:
            if not isinstance(exec_result, dict):
                return estimated_price, "estimated"
            if exec_result.get("dry_run") or exec_result.get("simulated"):
                return estimated_price, "dry_run"
            if exec_result.get("result") == "SUCCESS":
                real_px = float(exec_result.get("real_fill_price") or 0)
                if real_px > 0:
                    return real_px, "real_fill"
            return estimated_price, "estimated"
        except Exception:
            return estimated_price, "estimated"

    def _load_dedup_state(self) -> Dict[str, int]:
        """P0-3: 加载持久化的 4h 去重表

        scheduler 每次扫描创建新 AutoTrader 实例，
        若不持久化，去重表每次为空，同一 4h 周期内会重复开仓。
        """
        try:
            if os.path.exists(self._dedup_path):
                with open(self._dedup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 过滤掉过期的 4h 记录（只保留当前和上一个 4h 周期）
                    current_4h = (int(time.time() * 1000) // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
                    prev_4h = current_4h - (4 * 3600 * 1000)
                    return {k: v for k, v in data.items() if v >= prev_4h}
        except Exception:
            pass
        return {}

    def _save_dedup_state(self) -> None:
        """P0-3: 持久化 4h 去重表"""
        try:
            with open(self._dedup_path, "w", encoding="utf-8") as f:
                json.dump(self._last_trade_4h_ts, f)
        except Exception as e:
            logger.warning(f"P0-3 保存 4h 去重表失败: {e}")

    def _mark_4h_traded(self, coin: str) -> None:
        """P0-3: 标记 symbol 在当前 4h 周期已开仓，并持久化"""
        current_4h_ts = (int(time.time() * 1000) // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        self._last_trade_4h_ts[coin] = current_4h_ts
        self._save_dedup_state()

    def _load_trade_time_state(self) -> Dict[str, float]:
        """加载持久化的开仓时间表（跨 scheduler 重启共享）

        scheduler 每次扫描创建新 AutoTrader 实例，若不持久化，
        _last_trade_time 每次为空 → _estimate_bars_held 返回 0 →
        止损范围被放大、移动止盈失效。
        """
        try:
            if os.path.exists(self._trade_time_path):
                with open(self._trade_time_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 清理 7 天前的陈旧记录，避免无限增长
                cutoff = time.time() - 7 * 24 * 3600
                return {k: float(v) for k, v in data.items() if float(v) > cutoff}
        except Exception as e:
            logger.warning(f"加载开仓时间表失败: {e}")
        return {}

    def _save_trade_time_state(self) -> None:
        """持久化开仓时间表"""
        try:
            with open(self._trade_time_path, "w", encoding="utf-8") as f:
                json.dump(self._last_trade_time, f)
        except Exception as e:
            logger.warning(f"保存开仓时间表失败: {e}")

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def get_exchange_client(self):
        """获取当前交易所客户端"""
        if self.exchange == "okx":
            return self.get_okx_client()
        elif self.exchange == "hyperliquid":
            return self.get_hyperliquid_client()
        elif self.exchange == "aster":
            return self.get_aster_module()
        return None

    def get_aster_module(self):
        """加载 Aster 交易模块 (ml_trade_service)

        Aster 采用 v3 EVM 签名,凭证从 .env 的 ASTER_USER/SIGNER/PRIVATE_KEY 读取。
        返回 ml_trade_service 模块对象,调用方使用模块级函数:
            _aster_market_order / _aster_market_order_qty / _aster_fetch_positions 等
        """
        if self._aster_module is None:
            try:
                root_dir = Path(__file__).parent.parent.parent.parent
                ml_path = root_dir / "10-经典指标系统"
                sys.path.insert(0, str(ml_path))
                import ml_trade_service
                self._aster_module = ml_trade_service
                logger.info("Aster 模块加载成功 (v3 EVM 签名)")
            except Exception as e:
                logger.warning(f"无法加载 Aster 模块: {e}")
                self._aster_module = None
        return self._aster_module

    def get_hyperliquid_client(self):
        """获取 Hyperliquid 客户端"""
        if self._hl_client is None:
            try:
                dreamos_dir = Path(__file__).parent.parent
                arch_dir = dreamos_dir.parent
                root_dir = arch_dir.parent
                sys.path.insert(0, str(root_dir))
                import importlib.util
                hl_path = root_dir / "experiments" / "ab-trading" / "execution" / "aster_spot.py"
                spec = importlib.util.spec_from_file_location("aster_spot", str(hl_path))
                aster_spot = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(aster_spot)
                self._hl_client = aster_spot.HyperliquidClient(self.agent_id)
            except Exception as e:
                logger.warning(f"无法连接 Hyperliquid: {e}")
                self._hl_client = None
        return self._hl_client

    def get_okx_client(self):
        if self._okx_client is None:
            try:
                dreamos_dir = Path(__file__).parent.parent
                arch_dir = dreamos_dir.parent
                root_dir = arch_dir.parent
                sys.path.insert(0, str(root_dir))
                import importlib.util
                okx_path = root_dir / "experiments" / "ab-trading" / "execution" / "okx_spot.py"
                spec = importlib.util.spec_from_file_location("okx_spot", str(okx_path))
                okx_spot = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(okx_spot)
                self._okx_client = okx_spot.OKXSpotClient(self.agent_id)
            except Exception as e:
                logger.warning(f"无法连接OKX: {e}")
                self._okx_client = None
        return self._okx_client

    def get_trading_agent(self):
        if self._trading_agent is None:
            try:
                from dreamos.apps.trading_agent.agent import TradingAgent
                self._trading_agent = TradingAgent(budget_mode="lean")
            except Exception as e:
                logger.warning(f"无法创建TradingAgent: {e}")
                self._trading_agent = None
        return self._trading_agent

    def run_full_analysis(self, symbol: str) -> Dict[str, Any]:
        """运行完整分析链路 (S-A-C-G)

        主路径: TradingAgent.run() -> 完整 S-A-C-G 链路
        降级路径: 当主路径失败时，执行场景驱动的编排链 (无大模型依赖)

        场景识别 + 编排记忆表查询在两条路径之前完成，
        确保无论主路径还是降级路径都使用场景驱动的编排选择。
        """
        market_data = self._fetch_market_data(symbol)

        # P0-6: 注入真实账户余额，供 Kelly 仓位模型使用
        self._inject_account_equity(market_data)

        # 场景识别 + 编排选择（消除随机性，由记忆表驱动）
        classifier = self.get_scenario_classifier()
        memory = self.get_orchestration_memory()
        scenario = classifier.classify(market_data)
        choice = memory.select(scenario.scenario_id)
        logger.info(f"场景识别: {scenario.scenario_id} → 编排: {choice.pattern} ({choice.fallback_level})")

        # 保存当前上下文，供 execute_trade / 离场检查 回写反馈使用
        self._current_context = {
            "scenario_id": scenario.scenario_id,
            "pattern": choice.pattern,
            "expected_direction": "HOLD",  # 由下方 analysis 结果更新
            "market_data": market_data,  # 缓存,供 run_auto_trade 构造 trade_order 使用
            "symbol": symbol,
        }

        agent = self.get_trading_agent()
        if not agent:
            logger.warning(f"TradingAgent 不可用，降级到经典指标分析 | 场景={scenario.scenario_id} 编排={choice.pattern}")
            return self._fallback_classic_analysis(symbol, market_data, scenario, choice)

        try:
            result = agent.run(
                user_input=f"分析 {symbol} 的交易机会",
                market_data=market_data,
                context={
                    "symbol": symbol,
                    "scenario": scenario.to_dict(),
                    "recommended_orchestration": choice.to_dict(),
                },
            )
            # 标记为正常路径
            result["_path"] = "full_sacg"
            result["_scenario"] = scenario.scenario_id
            result["_orchestration"] = choice.pattern
            # 更新上下文的预期方向（用于反馈的方向准确率评估）
            # 优先从顶层 action 取(TradingAgent 最终决策),其次从 outputs.A5.trade_order 取
            a5_out = result.get("outputs", {}).get("A5", {})
            expected_dir = result.get("action") or a5_out.get("trade_order", {}).get("action", "HOLD")
            self._current_context["expected_direction"] = expected_dir
            return result
        except Exception as e:
            logger.error(f"TradingAgent 分析失败: {e}，降级到经典指标分析 | 场景={scenario.scenario_id}")
            return self._fallback_classic_analysis(symbol, market_data, scenario, choice)

    def _fallback_classic_analysis(self, symbol: str, market_data: dict = None,
                                    scenario=None, choice=None) -> Dict[str, Any]:
        """降级路径: 场景驱动编排执行 (完全不依赖大模型)

        使用编排记忆表选择的节点链替代硬编码C链。
        当记忆表无匹配时走L3默认 c_chain (C1→C2→C3)。
        """
        from dreamos.shared.state import State, new_state
        from dreamos.registry import get_default_registry
        from dreamos.core.compute.graph_executor import GraphExecutor
        from dreamos.core.arrange.execution_graph import SequentialGraph
        from dreamos.capabilities.trading.nodes import register_all

        start_time = time.time()
        registry = get_default_registry()
        register_all(registry)

        # 构建 State
        if market_data is None:
            market_data = self._fetch_market_data(symbol)
        cycle_id = f"classic_{symbol}_{int(time.time())}"
        state = new_state(cycle_id=cycle_id)
        state.market_data = market_data
        state.inputs = {"mkt": market_data, "symbol": symbol}

        # 用记忆表选的节点，替代硬编码 ["C1", "C2", "C3"]
        chain_nodes = choice.nodes if choice else ["C1", "C2", "C3"]
        pattern_name = choice.pattern if choice else "c_chain"
        graph = SequentialGraph()
        for node_id in chain_nodes:
            node = registry.get(node_id)
            if node:
                graph.add_node(node)

        # 直接执行 (C 层)
        executor = GraphExecutor()
        report = executor.execute(graph, state)

        # 收集结果
        c1_result = state.get_result("C1")
        c2_result = state.get_result("C2")
        c3_result = state.get_result("C3")

        # 综合决策 (模拟 A5 逻辑)
        direction = "HOLD"
        confidence = 0.5
        trade_order = {}

        if c1_result and c2_result:
            c1_dir = getattr(c1_result, "direction", "HOLD")
            c2_dir = getattr(c2_result, "direction", "HOLD")
            c2_conf = getattr(c2_result, "confidence", 0.5)

            # 方向一致性检查
            if c1_dir == c2_dir and c1_dir != "HOLD":
                direction = c1_dir
                confidence = c2_conf
            else:
                # 对称门槛：多空同等置信度要求
                threshold = 0.62 if c2_dir == "SHORT" else 0.62
                if c2_conf >= threshold:
                    direction = c2_dir
                    confidence = c2_conf

        price = market_data.get("price", 0)
        if price == 0:
            direction = "HOLD"
            confidence = 0.0

        if direction != "HOLD" and price > 0:
            atr_pct = 0.02
            # P0-6: Kelly 动态仓位 & 杠杆
            dyn = calc_dynamic_position_and_leverage(
                confidence=confidence,
                atr_pct=atr_pct,
                account_equity=None,
                direction=direction,
                min_lev=MIN_LEVERAGE,
                max_lev=MAX_LEVERAGE,
                threshold=CONFIDENCE_THRESHOLD,
                symbol=symbol,
            )
            position_size = dyn["position_size"]
            leverage = int(dyn["leverage"])
            if direction == "LONG":
                stop_loss = round(price * (1 - atr_pct * 1.5), 4)
                take_profit = round(price * (1 + atr_pct * 3.0), 4)
            else:
                stop_loss = round(price * (1 + atr_pct * 1.5), 4)
                take_profit = round(price * (1 - atr_pct * 3.0), 4)

            trade_order = {
                "action": direction,
                "coin": symbol,
                "entry_price": price,
                "position_size": position_size,
                "leverage": leverage,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risk_per_trade": position_size * atr_pct,
                "rr_ratio": round(abs(take_profit - price) / max(abs(price - stop_loss), 0.0001), 2),
                "_kelly": dyn,
            }

        # 构建与主路径兼容的输出格式
        latency_ms = (time.time() - start_time) * 1000

        rationale = ["[降级模式] 经典指标分析路径 (无大模型依赖)"]
        if c1_result and hasattr(c1_result, "outputs"):
            r = c1_result.outputs.get("rationale", [])
            rationale.extend(r if isinstance(r, list) else [r])
        if c2_result and hasattr(c2_result, "outputs"):
            r = c2_result.outputs.get("rationale", [])
            rationale.extend(r if isinstance(r, list) else [r])
        if c3_result and hasattr(c3_result, "outputs"):
            r = c3_result.outputs.get("rationale", [])
            rationale.extend(r if isinstance(r, list) else [r])

        return {
            "cycle_id": cycle_id,
            "intent": {"type": "CLASSIC_INDICATORS", "confidence": 1.0},
            "plan": {"chain": "C", "nodes": chain_nodes},
            "execution": {
                "nodes_executed": getattr(report, "executed_nodes", 0),
                "success_count": getattr(report, "success_nodes", 0),
                "total_tokens": 0,
            },
            "action": direction,
            "confidence": round(confidence, 3),
            "rationale": rationale,
            "tokens_used": 0,
            "latency_ms": round(latency_ms, 1),
            "outputs": {
                "A5": {
                    "trade_order": trade_order,
                    "confidence": confidence,
                    "gate_passed": confidence >= float(os.environ.get("DREAMOS_CONFIDENCE_THRESHOLD", "0.4")),
                },
                "C1": c1_result.outputs if c1_result else {},
                "C2": c2_result.outputs if c2_result else {},
                "C3": c3_result.outputs if c3_result else {},
            },
            "_path": "classic_fallback",
            "_fallback_reason": "TradingAgent 不可用或 S-A 层失败，降级到经典指标分析",
            "_scenario": scenario.scenario_id if scenario else "UNKNOWN",
            "_orchestration": pattern_name,
            "_fallback_level": choice.fallback_level if choice else "L3",
        }

    def _inject_account_equity(self, market_data: dict) -> None:
        """P0-6: 查询真实账户余额并注入 market_data，供 Kelly 仓位模型使用

        获取失败时不阻断流程，Kelly 模型会用 default_equity 兜底。
        缓存 5 分钟避免频繁调用 API。
        """
        # 5 分钟缓存，避免每个币种都调 API
        cache_key = "_account_equity_ts"
        cache_ts = getattr(self, "_account_equity_cache_ts", 0)
        if time.time() - cache_ts < 300 and hasattr(self, "_account_equity_cache"):
            market_data["account_equity"] = self._account_equity_cache
            return

        try:
            client = self.get_exchange_client()
            if client and self.exchange == "aster":
                summary = client._aster_fetch_account_summary()
                if isinstance(summary, dict) and summary.get("ok"):
                    s = summary.get("summary", {}) or {}
                    eq = float(s.get("totalWalletBalance", 0) or 0)
                    if eq > 0:
                        market_data["account_equity"] = eq
                        self._account_equity_cache = eq
                        self._account_equity_cache_ts = time.time()
                        logger.info(f"账户余额注入: {eq:.2f} USDT (Kelly 仓位模型)")
                        return
        except Exception as e:
            logger.warning(f"查询账户余额失败,Kelly 模型将用默认值兜底: {e}")
        # 获取失败时不写入，让 Kelly 模型用 default_equity=60 兜底

    def _fetch_market_data(self, symbol: str) -> Dict[str, Any]:
        """获取市场数据（包含场景分类器所需字段）"""
        client = self.get_exchange_client()
        if not client:
            return {"symbol": symbol, "price": 0}

        try:
            if self.exchange == "hyperliquid":
                try:
                    dreamos_dir = Path(__file__).parent.parent
                    arch_dir = dreamos_dir.parent
                    root_dir = arch_dir.parent
                    sys.path.insert(0, str(root_dir))
                    import importlib.util
                    hl_path = root_dir / "experiments" / "ab-trading" / "execution" / "aster_spot.py"
                    spec = importlib.util.spec_from_file_location("aster_spot", str(hl_path))
                    aster_spot = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(aster_spot)

                    mids = aster_spot.get_all_mids(getattr(client, 'proxies', None))
                    price = mids.get(symbol, 0)
                    if price <= 0:
                        return {"symbol": symbol, "price": 0}

                    candles_1h = aster_spot.get_candles(symbol, "1h", 48, getattr(client, 'proxies', None))
                    candles_4h = aster_spot.get_candles(symbol, "4h", 52, getattr(client, 'proxies', None))

                    closes_1h = [float(c["c"]) for c in candles_1h if "c" in c]
                    closes_4h = [float(c["c"]) for c in candles_4h if "c" in c]
                    vols_1h = [float(c["v"]) for c in candles_1h if "v" in c]

                    if len(closes_4h) < 24:
                        return {"symbol": symbol, "price": price}

                    def ema(prices, n):
                        if len(prices) < n:
                            return prices[-1] if prices else 0
                        k = 2 / (n + 1)
                        e = prices[-n]
                        for p in prices[-n + 1:]:
                            e = p * k + e * (1 - k)
                        return e

                    def rsi(prices, n=14):
                        if len(prices) < n + 1:
                            return 50.0
                        deltas = [prices[i] - prices[i - 1] for i in range(1, min(n + 1, len(prices)))]
                        gains = [max(d, 0) for d in deltas]
                        losses = [max(-d, 0) for d in deltas]
                        avg_g = sum(gains) / n
                        avg_l = sum(losses) / n
                        if avg_l == 0:
                            return 100.0
                        rs = avg_g / avg_l
                        return 100 - 100 / (1 + rs)

                    def atr(raw_candles, n=14):
                        if len(raw_candles) < 2:
                            return 0
                        trs = []
                        for i in range(1, min(n + 1, len(raw_candles))):
                            h = float(raw_candles[i].get("h", 0))
                            l = float(raw_candles[i].get("l", 0))
                            c_prev = float(raw_candles[i - 1].get("c", 0))
                            trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
                        return sum(trs) / len(trs) if trs else 0

                    closes_rev = closes_4h[::-1]
                    ema20 = ema(closes_rev, 20)
                    ema50 = ema(closes_rev, min(50, len(closes_rev)))
                    ema200 = ema(closes_rev, min(200, len(closes_rev)))
                    rsi14 = rsi(closes_rev)
                    atr14 = atr(candles_4h)

                    change_1h = ((closes_1h[0] - closes_1h[1]) / closes_1h[1] * 100) if len(closes_1h) > 1 else 0
                    change_24h = ((closes_4h[0] - closes_4h[6]) / closes_4h[6] * 100) if len(closes_4h) > 6 else 0
                    change_4h = ((closes_4h[0] - closes_4h[1]) / closes_4h[1] * 100) if len(closes_4h) > 1 else 0

                    # candles_1h 转 dict 格式供 classic 适配器消费
                    hl_candles = []
                    for c in candles_1h:
                        if isinstance(c, dict):
                            hl_candles.append(c)
                        elif isinstance(c, (list, tuple)) and len(c) >= 5:
                            hl_candles.append({
                                "t": c[0], "o": c[1], "h": c[2], "l": c[3],
                                "c": c[4], "v": c[5] if len(c) > 5 else 0,
                            })
                    return {
                        "symbol": symbol,
                        "price": price,
                        "change_24h": round(change_24h, 3) / 100,
                        "change_4h": round(change_4h, 3) / 100,
                        "change_1h": round(change_1h, 3) / 100,
                        "ema20": round(ema20, 2),
                        "ema50": round(ema50, 2),
                        "ema200": round(ema200, 2),
                        "rsi14": round(rsi14, 1),
                        "atr_pct": round(atr14 / price, 4),
                        "candles_1h": hl_candles,
                    }
                except Exception as e:
                    logger.warning(f"Hyperliquid 获取完整市场数据失败: {e}")
                    if hasattr(client, 'get_mid'):
                        price = client.get_mid(symbol)
                    return {"symbol": symbol, "price": price}

            if self.exchange == "aster":
                # Aster 行情: _aster_mid 取价格,_aster_klines_ohlcv_rows 取K线
                # 返回行格式: [timestamp, open, high, low, close, volume]
                price = client._aster_mid(symbol)
                if price <= 0:
                    return {"symbol": symbol, "price": 0}

                rows_1h = client._aster_klines_ohlcv_rows(symbol, "1h", 50)
                rows_4h = client._aster_klines_ohlcv_rows(symbol, "4h", 20)

                # rows 按时间升序,取最后 N 根
                if len(rows_1h) < 24:
                    logger.warning(f"Aster 行情不足: {symbol} 1h K线仅 {len(rows_1h)} 根")
                    return {"symbol": symbol, "price": price}

                closes_1h = [r[4] for r in rows_1h]  # 升序,最后一个是最新
                closes_4h = [r[4] for r in rows_4h]

                def _ema(prices, n):
                    if len(prices) < n:
                        return prices[-1] if prices else 0
                    k = 2 / (n + 1)
                    e = prices[-n]
                    for p in prices[-n + 1:]:
                        e = p * k + e * (1 - k)
                    return e

                def _rsi(prices, n=14):
                    if len(prices) < n + 1:
                        return 50.0
                    deltas = [prices[i] - prices[i - 1] for i in range(1, min(n + 1, len(prices)))]
                    gains = [max(d, 0) for d in deltas]
                    losses = [max(-d, 0) for d in deltas]
                    avg_g = sum(gains) / n
                    avg_l = sum(losses) / n
                    if avg_l == 0:
                        return 100.0
                    rs = avg_g / avg_l
                    return 100 - 100 / (1 + rs)

                def _atr(rows, n=14):
                    if len(rows) < 2:
                        return 0
                    trs = []
                    for i in range(1, min(n + 1, len(rows))):
                        h = rows[i][2]
                        l = rows[i][3]
                        c_prev = rows[i - 1][4]
                        trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
                    return sum(trs) / len(trs) if trs else 0

                ema20 = _ema(closes_1h, 20)
                ema50 = _ema(closes_1h, min(50, len(closes_1h)))
                ema200 = _ema(closes_4h, min(20, len(closes_4h)))
                rsi14 = _rsi(closes_1h)
                atr14 = _atr(rows_1h)

                # 变化率:closes_1h 升序,最新在末尾
                change_1h = ((closes_1h[-1] - closes_1h[-2]) / closes_1h[-2] * 100) if len(closes_1h) > 1 else 0
                change_24h = ((closes_1h[-1] - closes_1h[-24]) / closes_1h[-24] * 100) if len(closes_1h) > 23 else 0
                change_4h = ((closes_4h[-1] - closes_4h[-4]) / closes_4h[-4] * 100) if len(closes_4h) > 3 else 0

                # rows_1h 转 dict 格式供 classic 适配器消费
                ast_candles = []
                for r in rows_1h:
                    if isinstance(r, (list, tuple)) and len(r) >= 5:
                        ast_candles.append({
                            "t": r[0], "o": r[1], "h": r[2], "l": r[3],
                            "c": r[4], "v": r[5] if len(r) > 5 else 0,
                        })
                return {
                    "symbol": symbol,
                    "price": price,
                    "change_24h": round(change_24h, 3) / 100,
                    "change_4h": round(change_4h, 3) / 100,
                    "change_1h": round(change_1h, 3) / 100,
                    "ema20": round(ema20, 2),
                    "ema50": round(ema50, 2),
                    "ema200": round(ema200, 2),
                    "rsi14": round(rsi14, 1),
                    "atr_pct": round(atr14 / price, 4),
                    "candles_1h": ast_candles,
                }

            if self.exchange == "okx":
                ticker = client.get_ticker(f"{symbol}-USDT")
                if ticker.get("ok"):
                    return {
                        "symbol": symbol,
                        "price": ticker["last"],
                        "bid": ticker["bid"],
                        "ask": ticker["ask"],
                        "vol24h": ticker["vol24h"],
                        "change_24h": ticker.get("change_24h", 0) / 100,
                        "change_1h": 0,
                        "change_4h": 0,
                        "ema20": ticker["last"],
                        "ema50": ticker["last"],
                        "ema200": ticker["last"],
                        "rsi14": 50,
                        "atr_pct": 0.02,
                    }
        except Exception as e:
            logger.warning(f"获取市场数据失败: {e}")

        return {"symbol": symbol, "price": 0}

    def check_risk_control(self, symbol: str, trade_order: Dict) -> Dict[str, Any]:
        """风险控制检查"""
        client = self.get_exchange_client()
        if not client:
            return {"passed": False, "reason": "无法连接交易所"}

        try:
            total_eq = 0.0
            if self.exchange == "hyperliquid":
                try:
                    acct = client.get_account()
                    total_eq = float(acct.get("equity", 0))
                except Exception:
                    total_eq = 0.0
            elif self.exchange == "okx":
                balance = client.get_balance()
                if not balance.get("ok"):
                    return {"passed": False, "reason": "无法获取账户余额"}
                total_eq = balance["total_eq"]
            elif self.exchange == "aster":
                # Aster 通过 ml_trade_service._aster_fetch_account_summary 获取账户余额
                try:
                    summary = client._aster_fetch_account_summary()
                    if summary.get("ok"):
                        s = summary.get("summary", {}) or {}
                        total_eq = float(s.get("totalWalletBalance", 0) or 0)
                        if total_eq == 0:
                            usdt = summary.get("assets", {}).get("USDT", {}) or {}
                            total_eq = float(usdt.get("walletBalance", 0) or 0)
                except Exception as e:
                    logger.warning(f"Aster 获取账户余额失败: {e}")
                    total_eq = 0.0

            position_size = trade_order.get("position_size", 10)
            # risk_per_trade 已经是单笔风险金额(USDT),不应再乘 position_size
            risk_amount = trade_order.get("risk_per_trade", position_size * 0.02)
            risk_pct = (risk_amount / total_eq) * 100 if total_eq > 0 else 100

            checks = []

            if risk_pct > 5:
                checks.append(f"单笔风险过高({risk_pct:.1f}% > 5%)")

            # P0-6: 仓位集中度检查 — 用 Kelly 模型的 max_single_pct，无 Kelly 信息时 30% 安全网
            kelly_info = trade_order.get("_kelly") or {}
            max_single_pct = kelly_info.get("max_single_pct", 0.30)
            if total_eq > 0 and position_size > total_eq * max_single_pct:
                checks.append(f"仓位过大({position_size:.1f} > 账户{max_single_pct:.0%})")

            if self._check_trade_interval(symbol):
                checks.append("交易间隔不足")

            return {
                "passed": len(checks) == 0,
                "reason": "; ".join(checks) if checks else "通过",
                "risk_pct": round(risk_pct, 2),
                "total_eq": round(total_eq, 2),
                "position_size": position_size,
            }
        except Exception as e:
            return {"passed": False, "reason": str(e)}

    def _check_trade_interval(self, symbol: str) -> bool:
        """检查交易间隔"""
        last_time = self._last_trade_time.get(symbol, 0)
        elapsed = (time.time() - last_time) / 60
        return elapsed < self._min_trade_interval_minutes

    def execute_trade(self, trade_order: Dict) -> Dict[str, Any]:
        """执行交易

        P0 黑天鹅防护:
          - 开仓(LONG/SHORT)成功后, 自动下交易所 TP/SL 条件单
          - 平仓(EXIT)前, 先取消所有 TP/SL 挂单
        即使程序崩溃/断网, 交易所条件单仍能触发, 防止黑天鹅事件.
        """
        if self.dry_run:
            sl = trade_order.get("stop_loss")
            tp = trade_order.get("take_profit")
            action = trade_order.get("action")
            has_tpsl = sl is not None and tp is not None and action in ("LONG", "SHORT")
            tpsl_set = bool(has_tpsl)
            tpsl_cancelled = (action == "EXIT")
            return {
                "result": "SKIP",
                "reason": "dry_run",
                "dry_run": True,
                "action": action,
                "symbol": trade_order.get("coin"),
                "entry_price": trade_order.get("entry_price"),
                "position_size": trade_order.get("position_size"),
                "leverage": trade_order.get("leverage"),
                "stop_loss": sl,
                "take_profit": tp,
                "exchange": self.exchange,
                "tpsl_set": tpsl_set,
                "tpsl_cancelled": tpsl_cancelled,
                "simulated": True,
            }

        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        action = trade_order.get("action", "HOLD")
        coin = trade_order.get("coin", "BTC")
        position_size = trade_order.get("position_size", 10)
        leverage = int(trade_order.get("leverage", DEFAULT_LEVERAGE))
        leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, leverage))
        stop_loss = trade_order.get("stop_loss")
        take_profit = trade_order.get("take_profit")

        if action == "HOLD":
            return {"result": "SKIP", "reason": "方向为HOLD"}

        try:
            if self.exchange == "hyperliquid":
                # P0: EXIT 前先取消所有 TP/SL 挂单
                if action == "EXIT":
                    try:
                        client.cancel_all_tpsl(coin)
                        logger.info(f"平仓前取消 TP/SL 挂单: {coin}")
                    except Exception as e:
                        logger.warning(f"取消 TP/SL 挂单失败({coin}): {e}")

                    result = client.close_position(
                        coin=coin,
                        tag="dreamos_auto",
                    )
                else:
                    if action == "LONG":
                        result = client.open_long(
                            coin=coin,
                            usdt_amount=position_size,
                            leverage=leverage,
                            tag="dreamos_auto",
                        )
                    elif action == "SHORT":
                        result = client.open_short(
                            coin=coin,
                            usdt_amount=position_size,
                            leverage=leverage,
                            tag="dreamos_auto",
                        )
                    else:
                        return {"error": f"未知动作: {action}"}

                if result.get("ok"):
                    self._last_trade_time[coin] = time.time()
                    self._save_trade_time_state()
                    # P0-3: 更新 4h 周期去重标记（持久化跨实例共享）
                    self._mark_4h_traded(coin)

                    # P0: 开仓成功后自动下 TP/SL 条件单（黑天鹅底线防护）
                    tpsl_result = None
                    if action in ("LONG", "SHORT") and stop_loss and take_profit:
                        try:
                            # 稍等 500ms 确保仓位已在交易所确认
                            time.sleep(0.5)
                            tpsl_result = client.set_tpsl_orders(
                                coin=coin,
                                stop_loss_price=float(stop_loss),
                                take_profit_price=float(take_profit),
                                is_market=True,
                            )
                            if tpsl_result.get("ok"):
                                logger.info(
                                    f"TP/SL 条件单已设置: {coin} | "
                                    f"SL={stop_loss} TP={take_profit} | "
                                    f"oids={tpsl_result.get('oids', [])}"
                                )
                            else:
                                logger.warning(
                                    f"TP/SL 条件单设置失败({coin}): {tpsl_result.get('error')}"
                                )
                        except Exception as e:
                            logger.warning(f"设置 TP/SL 条件单异常({coin}): {e}")
                            tpsl_result = {"ok": False, "error": str(e)}

                    # P2: 提取真实成交均价（平仓反馈用）
                    real_fill_price = 0.0
                    filled_info = result.get("filled") or {}
                    if isinstance(filled_info, dict):
                        try:
                            real_fill_price = float(filled_info.get("avgPx") or 0.0)
                        except (TypeError, ValueError):
                            real_fill_price = 0.0

                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "hyperliquid",
                        "details": result,
                        "tpsl_result": tpsl_result,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "real_fill_price": real_fill_price,
                    }
                else:
                    return {"result": "FAILED", "error": result}

            elif self.exchange == "okx":
                inst_id = f"{coin}-USDT"
                if action == "LONG":
                    result = client.market_buy(inst_id, position_size, tag="auto_trader")
                elif action == "SHORT":
                    result = client.market_sell(inst_id, position_size / trade_order.get("price", 1), tag="auto_trader")
                elif action == "EXIT":
                    result = client.close_position(inst_id, tag="auto_trader") if hasattr(client, "close_position") else {"ok": False, "error": "not_supported"}
                else:
                    return {"error": f"未知动作: {action}"}

                if result.get("ok"):
                    self._last_trade_time[coin] = time.time()
                    self._save_trade_time_state()
                    # P0-3: 更新 4h 周期去重标记（持久化跨实例共享）
                    self._mark_4h_traded(coin)
                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "okx",
                        "ord_id": result.get("ord_id"),
                        "position_size": position_size,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "tpsl_result": {"ok": False, "error": "okx_tpsl_not_implemented"},
                    }
                else:
                    return {"result": "FAILED", "error": result.get("raw", {})}

            elif self.exchange == "aster":
                # Aster v3 EVM 签名交易,调用 ml_trade_service 模块函数
                # P0-3 修复: EXIT 动作不需要设置杠杆,直接平仓
                if action == "EXIT":
                    # P0: 平仓前先取消所有 TP/SL 挂单
                    try:
                        positions, pos_err = client._aster_fetch_positions()
                        if pos_err or not positions:
                            return {"result": "SKIP", "reason": f"无持仓可平: {pos_err}"}
                        pos_qty = None
                        close_side = None
                        for p in positions:
                            if not isinstance(p, dict):
                                continue
                            if coin.upper() in str(p.get('symbol', '')).upper():
                                amt = float(p.get('position_amt') or p.get('positionAmt') or 0)
                                if abs(amt) > 0:
                                    pos_qty = abs(amt)
                                    close_side = 'sell' if amt > 0 else 'buy'
                                    break
                        if pos_qty is None:
                            return {"result": "SKIP", "reason": "无持仓可平"}
                        
                        # 获取持仓数量用于取消对应数量的条件单
                        qty_to_cancel = pos_qty
                        
                        # 取消 STOP_MARKET 和 TAKE_PROFIT_MARKET 订单
                        # Aster 没有批量取消 API，需要遍历订单取消
                        open_orders = client._aster_fetch_open_orders() if hasattr(client, '_aster_fetch_open_orders') else []
                        cancelled_count = 0
                        if isinstance(open_orders, list):
                            for o in open_orders:
                                if not isinstance(o, dict):
                                    continue
                                if coin.upper() in str(o.get('symbol', '')).upper():
                                    o_type = o.get('type', '')
                                    if o_type in ('STOP_MARKET', 'TAKE_PROFIT_MARKET'):
                                        try:
                                            client._aster_order_cancel(o.get('symbol'), o.get('orderId'))
                                            cancelled_count += 1
                                        except Exception:
                                            pass
                        logger.info(f"平仓前取消 TP/SL 挂单: {coin}, 已取消{cancelled_count}个")
                        
                        r = client._aster_market_order_qty(coin, close_side, pos_qty, reduce_only=True)
                        # P0-5 修复: EXIT 平仓后立即判断结果并 return,避免漏到下方开仓逻辑
                        close_ok = False
                        close_order_id = None
                        if isinstance(r, dict):
                            resp = r.get('resp', {})
                            if isinstance(resp, dict):
                                inner = resp.get('data', resp)
                                if isinstance(inner, dict):
                                    if inner.get('status') in ('FILLED', 'NEW', 'PARTIALLY_FILLED'):
                                        close_ok = True
                                        close_order_id = inner.get('orderId')
                        if close_ok:
                            logger.info(f"Aster 平仓成功: {coin} | side={close_side} qty={pos_qty}")
                            return {
                                "result": "SUCCESS",
                                "action": "EXIT",
                                "symbol": coin,
                                "exchange": "aster",
                                "ord_id": close_order_id,
                                "details": r,
                            }
                        else:
                            logger.warning(f"Aster 平仓失败({coin}): r={r if isinstance(r, (dict, list)) else type(r).__name__}")
                            return {"result": "FAILED", "error": f"平仓结果异常: {r if isinstance(r, (dict, list, str)) else type(r).__name__}"}
                    except Exception as e:
                        logger.warning(f"Aster 平仓异常({coin}): {e}")
                        return {"result": "FAILED", "error": str(e)}
                else:
                    # LONG/SHORT: 下单前设置杠杆(动态 1-5 倍)
                    target_lev = int(trade_order.get("leverage", DEFAULT_LEVERAGE))
                    target_lev = max(MIN_LEVERAGE, min(MAX_LEVERAGE, target_lev))
                    lev_ok = False
                    try:
                        lev_resp = client._aster_update_leverage(coin, target_lev)
                        lev_used = lev_resp.get('leverage_used') or lev_resp.get('leverage') if isinstance(lev_resp, dict) else None
                        # 已持仓币种会返回 skipped=True(杠杆无法修改)
                        if isinstance(lev_resp, dict) and lev_resp.get('skipped'):
                            # P0-3 修复: 验证现有杠杆是否在安全范围内
                            try:
                                positions, _ = client._aster_fetch_positions()
                                current_lev = None
                                if isinstance(positions, list):
                                    for p in positions:
                                        if not isinstance(p, dict):
                                            continue
                                        if coin.upper() in str(p.get('symbol', '')).upper():
                                            current_lev = int(p.get('leverage') or p.get('leverageSys') or 0)
                                            break
                                if current_lev and current_lev > MAX_LEVERAGE:
                                    logger.error(f"Aster 杠杆超限({coin}): 现有{current_lev}x > 最大{MAX_LEVERAGE}x, 拒绝下单")
                                    return {"result": "FAILED", "error": f"现有杠杆{current_lev}x超过安全上限{MAX_LEVERAGE}x,拒绝下单"}
                                logger.warning(f"Aster 杠杆无法修改({coin}, 已持仓,现有杠杆={current_lev or '未知'}x): {lev_resp.get('reason')}")
                                lev_ok = True
                            except Exception as verify_err:
                                logger.warning(f"Aster 杠杆验证失败({coin}): {verify_err}, 保守拒绝下单")
                                return {"result": "FAILED", "error": f"杠杆验证失败: {verify_err}"}
                        else:
                            # P0-3 修复: 验证杠杆确实设置成功
                            if lev_used and int(lev_used) > MAX_LEVERAGE:
                                logger.error(f"Aster 杠杆设置异常({coin}): 设置后{lev_used}x > 最大{MAX_LEVERAGE}x")
                                return {"result": "FAILED", "error": f"杠杆设置后{lev_used}x超过安全上限{MAX_LEVERAGE}x"}
                            logger.info(f"Aster 杠杆设置: {coin} → {lev_used or target_lev}x")
                            lev_ok = True
                    except Exception as e:
                        err_msg = str(e)
                        logger.error(f"Aster 设置杠杆失败({coin}, {target_lev}x): {err_msg}, 拒绝下单")
                        # P0-3: 杠杆设置失败时硬阻断,不下单
                        return {"result": "FAILED", "error": f"杠杆设置失败({err_msg}),为避免高杠杆风险不下单"}

                    if not lev_ok:
                        return {"result": "FAILED", "error": "杠杆设置未确认,不下单"}

                    if action == "LONG":
                        r = client._aster_market_order(coin, 'long', float(position_size),
                                                       reduce_only=False, allow_adjust=True)
                    elif action == "SHORT":
                        r = client._aster_market_order(coin, 'short', float(position_size),
                                                       reduce_only=False, allow_adjust=True)
                    else:
                        return {"error": f"未知动作: {action}"}

                # Aster 成功判断:resp 中 status == FILLED
                resp = r.get('resp', {}) if isinstance(r, dict) else {}
                ok = False
                order_id = None
                if isinstance(resp, dict):
                    inner = resp.get('data', resp)
                    if isinstance(inner, dict):
                        if inner.get('status') in ('FILLED', 'NEW', 'PARTIALLY_FILLED'):
                            ok = True
                            order_id = inner.get('orderId')

                if ok:
                    self._last_trade_time[coin] = time.time()
                    self._save_trade_time_state()
                    # P0-3: 更新 4h 周期去重标记（持久化跨实例共享）
                    self._mark_4h_traded(coin)

                    # P0: 开仓成功后自动下 TP/SL 条件单（黑天鹅底线防护）
                    tpsl_result = None
                    if action in ("LONG", "SHORT") and stop_loss and take_profit:
                        try:
                            time.sleep(0.5)
                            positions, _ = client._aster_fetch_positions()
                            pos_qty = None
                            if isinstance(positions, list):
                                for p in positions:
                                    if not isinstance(p, dict):
                                        continue
                                    if coin.upper() in str(p.get('symbol', '')).upper():
                                        amt = float(p.get('position_amt') or p.get('positionAmt') or 0)
                                        if abs(amt) > 0:
                                            pos_qty = abs(amt)
                                            break

                            if pos_qty is None:
                                pos_qty = position_size

                            if action == "LONG":
                                sl_side = "sell"
                                tp_side = "sell"
                            else:
                                sl_side = "buy"
                                tp_side = "buy"

                            sl_result = client._aster_stop_market_order_qty(
                                coin, sl_side, pos_qty, float(stop_loss), reduce_only=True
                            )
                            tp_result = client._aster_take_profit_market_order_qty(
                                coin, tp_side, pos_qty, float(take_profit), reduce_only=True
                            )

                            sl_ok = False
                            tp_ok = False
                            if isinstance(sl_result, dict):
                                sl_resp = sl_result.get('resp', {})
                                if isinstance(sl_resp, dict):
                                    sl_inner = sl_resp.get('data', sl_resp) if isinstance(sl_resp.get('data', {}), dict) else sl_resp
                                    sl_ok = isinstance(sl_inner, dict) and sl_inner.get('status') in ('NEW', 'FILLED', 'PARTIALLY_FILLED')
                            if isinstance(tp_result, dict):
                                tp_resp = tp_result.get('resp', {})
                                if isinstance(tp_resp, dict):
                                    tp_inner = tp_resp.get('data', tp_resp) if isinstance(tp_resp.get('data', {}), dict) else tp_resp
                                    tp_ok = isinstance(tp_inner, dict) and tp_inner.get('status') in ('NEW', 'FILLED', 'PARTIALLY_FILLED')

                            if sl_ok and tp_ok:
                                logger.info(
                                    f"Aster TP/SL 条件单已设置: {coin} | "
                                    f"SL={stop_loss} TP={take_profit} | "
                                    f"qty={pos_qty}"
                                )
                                tpsl_result = {"ok": True, "sl_result": sl_result, "tp_result": tp_result}
                            else:
                                logger.warning(
                                    f"Aster TP/SL 条件单设置失败({coin}): "
                                    f"SL={sl_result.get('resp', {}).get('msg', 'unknown')}, "
                                    f"TP={tp_result.get('resp', {}).get('msg', 'unknown')}"
                                )
                                tpsl_result = {"ok": False, "sl_result": sl_result, "tp_result": tp_result}
                        except Exception as e:
                            logger.warning(f"Aster 设置 TP/SL 条件单异常({coin}): {e}")
                            tpsl_result = {"ok": False, "error": str(e)}

                    return {
                        "result": "SUCCESS",
                        "action": action,
                        "symbol": coin,
                        "exchange": "aster",
                        "ord_id": order_id,
                        "details": r,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "tpsl_result": tpsl_result,
                    }
                else:
                    return {"result": "FAILED", "error": r}

            else:
                return {"error": f"不支持的交易所: {self.exchange}"}

        except Exception as e:
            return {"result": "ERROR", "error": str(e)}

    def _resolve_scenario_id(self, market_data: Dict[str, Any]) -> str:
        """识别当前场景 ID（供离场模块选择器使用）"""
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            scenario = ScenarioClassifier().classify(market_data)
            sid = getattr(scenario, "scenario_id", "")
            if sid:
                return sid
        except Exception:
            pass
        return self._current_context.get("scenario_id", "UNKNOWN")

    def _try_selector_exit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,
        market_data: Dict[str, Any],
        atr_pct: float,
        bars_held: int,
        scenario_id: str,
    ) -> Optional[Dict[str, Any]]:
        """基于回测表现的离场模块选择（overlay）

        v2.5 路由（默认启用择优）：
            EXIT_SELECTOR_ENABLED: 总开关，默认 1
            selector.select(scenario_id) → 返回 ExitModuleChoice:
              - module_name == "builtin" / fallback_level == 4: 场景级强降级（LOW/CHOP/RANGE）
                → 返回 None，走 check_exit 内置 ATR 时间衰减逻辑（震荡市越简单越好）
              - module_name == "simple" / fallback_level >= 3: 无足够回测数据，降级内置
              - 其它 (classic/yijing/fundamental): 按回测 score 择优执行
        Returns:
            dict (check_exit 格式) 或 None (回退到内置逻辑)
        """
        if not EXIT_SELECTOR_ENABLED:
            return None
        try:
            selector = self.get_exit_selector()
            if selector is None:
                return None
            choice = selector.select(scenario_id)
            # 场景级强降级（fallback_level=4，LOW/CHOP/RANGE）→ 内置 ATR（震荡市 builtin 胜率 40.3% > yijing 42%但 avg_pnl -0.2% 远差）
            if choice.module_name == "builtin" or choice.fallback_level == 4:
                return None
            # L3 = 无回测数据的默认选择，保持内置逻辑避免回归
            if choice.fallback_level >= 3:
                return None
            # simple 模块即内置逻辑的镜像，直接走内置路径以利用更精细的 regime/vol 因子
            if choice.module_name == "simple":
                return None
            adapter = selector.get_adapter(choice.module_name)
            if adapter is None or not adapter.is_available:
                return None

            position_age_sec = max(0.0, bars_held * 3600.0)
            if entry_price > 0:
                unrealized_pnl_pct = (
                    (current_price - entry_price) / entry_price
                    if direction == "LONG"
                    else (entry_price - current_price) / entry_price
                )
            else:
                unrealized_pnl_pct = 0.0

            # 1. 获取/更新 per-symbol 持仓状态（解决 leverage / trailing / mfe / max_dd 4 bug）
            pstate = self._position_exit_state.setdefault(symbol, {
                "leverage": DEFAULT_LEVERAGE,
                "trailing_armed": False,
                "trailing_stop_price": 0.0,
                "peak_price": entry_price,
                "trough_price": entry_price,
                "mfe_pnl_pct": 0.0,
                "max_dd_pct": 0.0,
                "entry_price": entry_price,
            })
            # entry_price 变化说明是新仓位，重置统计
            if pstate.get("entry_price", 0) != entry_price:
                pstate["entry_price"] = entry_price
                pstate["peak_price"] = entry_price
                pstate["trough_price"] = entry_price
                pstate["mfe_pnl_pct"] = 0.0
                pstate["max_dd_pct"] = 0.0
                pstate["trailing_armed"] = False
                pstate["trailing_stop_price"] = 0.0
            # 尝试从交易所持仓取真实 leverage（覆盖默认值）
            try:
                client = self.get_exchange_client()
                if client and self.exchange == "aster":
                    pos_list, _ = client._aster_fetch_positions()
                    for p in (pos_list or []):
                        coin = str(p.get("coin", "")).replace("-USDT", "").replace("-SWAP", "")
                        if coin == symbol and float(p.get("position_amt", 0) or 0) != 0:
                            pstate["leverage"] = float(p.get("leverage") or DEFAULT_LEVERAGE)
                            break
            except Exception:
                pass
            # 实时更新 peak/trough 和 mfe/max_dd
            if direction == "LONG":
                if current_price > pstate["peak_price"]:
                    pstate["peak_price"] = current_price
                    if entry_price > 0:
                        pstate["mfe_pnl_pct"] = max(pstate["mfe_pnl_pct"], (current_price - entry_price) / entry_price)
                if entry_price > 0 and pstate["peak_price"] > 0:
                    dd = (pstate["peak_price"] - current_price) / pstate["peak_price"]
                    pstate["max_dd_pct"] = max(pstate["max_dd_pct"], dd)
            else:
                if current_price < pstate["trough_price"] or pstate["trough_price"] == 0:
                    pstate["trough_price"] = current_price
                    if entry_price > 0:
                        pstate["mfe_pnl_pct"] = max(pstate["mfe_pnl_pct"], (entry_price - current_price) / entry_price)
                if entry_price > 0 and pstate["trough_price"] > 0:
                    dd = (current_price - pstate["trough_price"]) / pstate["trough_price"]
                    pstate["max_dd_pct"] = max(pstate["max_dd_pct"], dd)

            decision = adapter.evaluate(
                symbol=symbol,
                entry_price=entry_price,
                current_price=current_price,
                direction=direction,
                market_data=market_data,
                position_age_sec=position_age_sec,
                unrealized_pnl_pct=unrealized_pnl_pct,
                leverage=float(pstate["leverage"]),
                atr_pct=atr_pct,
                mfe_pnl_pct=float(pstate["mfe_pnl_pct"]),
                max_dd_pct=float(pstate["max_dd_pct"]),
                trailing_armed=pstate.get("trailing_armed", False),
                trailing_stop_price=float(pstate.get("trailing_stop_price", 0.0)),
                scenario_id=scenario_id,
            )
            # 回写跟踪止损状态（UnifiedExitDecision 暴露 new_trailing_armed/new_trailing_stop）
            new_armed = getattr(decision, "new_trailing_armed", None)
            new_stop = getattr(decision, "new_trailing_stop", 0.0)
            if isinstance(new_armed, bool):
                pstate["trailing_armed"] = new_armed
            if isinstance(new_stop, (int, float)) and new_stop > 0:
                pstate["trailing_stop_price"] = float(new_stop)

            # 补充 SL/TP（适配器未提供时用 StopTakeProfitEngine 计算）
            stop_loss = decision.stop_loss
            take_profit = decision.take_profit
            if stop_loss <= 0 or take_profit <= 0:
                try:
                    from dreamos.capabilities.trading.exit_strategy.stop_take_profit import calculate_stop_take_profit
                    regime = "ranging" if ("RANGE" in scenario_id or "CHOP" in scenario_id) else (
                        "trend_bull" if "BULL" in scenario_id else "trend_bear"
                    )
                    confidence = max(0.3, 0.8 - bars_held * 0.01)
                    sltp = calculate_stop_take_profit(
                        direction=direction,
                        entry_price=entry_price,
                        atr_pct=atr_pct,
                        confidence=confidence,
                        stop_strategy="atr",
                        take_strategy="ratio",
                        take_ratio=2.0,
                        min_rr_ratio=1.5,
                        market_regime=regime,
                    )
                    if stop_loss <= 0:
                        stop_loss = sltp.get("stop_loss", 0)
                    if take_profit <= 0:
                        take_profit = sltp.get("take_profit", 0)
                except Exception as e:
                    logger.warning(f"[selector] SL/TP 补充计算失败({symbol}): {e}")

            # RAISE_TP: 用模块提供的新止盈价
            if decision.action == "RAISE_TP" and decision.new_tp_price > 0:
                take_profit = decision.new_tp_price

            should_exit = decision.action in ("CLOSE", "REDUCE")
            exit_price = decision.exit_price if should_exit else 0.0
            if should_exit and exit_price <= 0:
                exit_price = current_price

            return {
                "exit": should_exit,
                "reason": f"[{choice.module_name}@L{choice.fallback_level}] {decision.reason}",
                "exit_price": exit_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "current_price": current_price,
                "bars_held": bars_held,
                "module": choice.module_name,
                "reduce_frac": decision.reduce_frac if decision.action == "REDUCE" else 0.0,
            }
        except Exception as e:
            logger.warning(f"[selector] 离场模块选择异常({symbol}), 回退内置逻辑: {e}")
            return None

    def check_exit(self, symbol: str, entry_price: float, direction: str) -> Dict[str, Any]:
        """检查离场条件 — 时间衰减 + 市场状态自适应止损

        持仓时间策略:
            0-20 根 K 线: 宽松止损，给仓位空间发展
            20-50 根: 线性收紧
            50+ 根: 紧凑止损 + 移动止盈

        市场状态叠加:
            震荡市 (ranging): regime_factor=1.5，避免被噪声扫出
            趋势市 (trend):   regime_factor=1.0，紧凑保护利润

        P1: 返回动态计算的 stop_loss / take_profit，供 modify_tpsl 更新交易所条件单
        """
        market_data = self._fetch_market_data(symbol)
        price = market_data.get("price", 0)
        if price == 0:
            return {"exit": False, "reason": "无法获取价格"}

        # 获取实时 ATR%
        atr_pct = market_data.get("atr_pct", 0.02)

        # 计算持仓 K 线数（基于开仓时间）
        bars_held = self._estimate_bars_held(symbol)

        # P2: 基于回测表现的离场模块选择（仅有回测数据时启用，否则回退内置逻辑）
        scenario_id = self._resolve_scenario_id(market_data)
        selector_result = self._try_selector_exit(
            symbol, entry_price, price, direction, market_data, atr_pct, bars_held, scenario_id
        )
        if selector_result is not None:
            return selector_result

        # 时间衰减因子: 0-20 根 = 1.5, 20-50 根线性衰减到 1.0, 50+ 根 = 1.0
        if bars_held <= 20:
            time_factor = 1.5
        elif bars_held <= 50:
            time_factor = 1.5 - (bars_held - 20) * (0.5 / 30)  # 1.5 → 1.0
        else:
            time_factor = 1.0

        # 市场状态因子：震荡市更宽，趋势市更紧
        regime = self._detect_regime_from_market_data(market_data, atr_pct)
        regime_factor = 1.5 if regime == "ranging" else 1.0

        # 币种波动率因子：以 BTC 为基准，高波动币种额外放宽
        symbol_vol_factor = self._calc_symbol_vol_factor(symbol, atr_pct)

        # 最终止损因子 = 时间因子 × 市场状态因子 × 币种波动率因子
        sl_factor = time_factor * regime_factor * symbol_vol_factor

        # P2 优化: 调用成熟模块 StopTakeProfitEngine 计算动态 SL/TP
        # 引擎内部根据 market_regime + symbol_volatility + confidence 动态调整 ATR 乘数
        # - 震荡市: ranging_multiplier=1.5（放大止损范围，避免被噪声扫出）
        # - 趋势市: trend_multiplier=0.8（缩小止损范围，保护利润）
        # - 高波动币种: high_vol_multiplier=1.3
        # - 低波动币种: low_vol_multiplier=0.8
        # SL 用 ATR 策略，TP 用 RATIO 策略（基于 SL 距离×2.0），保证最小 R:R=1.5
        try:
            # 优先用 dreamos 包路径，失败时回退到相对路径
            try:
                from dreamos.capabilities.trading.exit_strategy.stop_take_profit import calculate_stop_take_profit
            except ImportError:
                # dreamos 包不可用时，直接从文件路径加载
                # __file__ = .../dreamos/cli/auto_trader.py，向上一层到 dreamos/
                import importlib.util
                _dreamos_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                _stp_path = os.path.join(
                    _dreamos_root, "capabilities", "trading", "exit_strategy", "stop_take_profit.py"
                )
                _spec = importlib.util.spec_from_file_location("_stop_take_profit", _stp_path)
                _stp_mod = importlib.util.module_from_spec(_spec)
                # 注册到 sys.modules，避免 Python 3.9 dataclass 解析 __module__ 失败
                sys.modules["_stop_take_profit"] = _stp_mod
                _spec.loader.exec_module(_stp_mod)
                calculate_stop_take_profit = _stp_mod.calculate_stop_take_profit
            # 映射 regime -> MarketRegime 枚举值
            if regime == "ranging":
                market_regime_str = "ranging"
            elif direction == "LONG":
                market_regime_str = "trend_bull"
            else:
                market_regime_str = "trend_bear"
            # 映射 symbol_vol_factor -> SymbolVolatility 枚举值
            if symbol_vol_factor <= 0.8:
                symbol_vol_str = "low"
            elif symbol_vol_factor >= 1.2:
                symbol_vol_str = "high"
            else:
                symbol_vol_str = "medium"
            # 持仓时间越久置信度越低（时间衰减），传递给引擎缩小 ATR 乘数
            confidence = max(0.3, 0.8 - bars_held * 0.01)
            sltp_result = calculate_stop_take_profit(
                direction=direction,
                entry_price=entry_price,
                atr_pct=atr_pct,
                confidence=confidence,
                stop_strategy="atr",
                take_strategy="ratio",
                take_ratio=2.0,
                min_rr_ratio=1.5,
                market_regime=market_regime_str,
                symbol_volatility=symbol_vol_str,
            )
            stop_loss = sltp_result.get("stop_loss", 0)
            take_profit = sltp_result.get("take_profit", 0)
            tp_rationale = sltp_result.get("rationale", [])
            logger.debug(f"[check_exit] {symbol} StopTakeProfitEngine: regime={market_regime_str}, vol={symbol_vol_str}, SL={stop_loss}, TP={take_profit}, rationale={tp_rationale}")
        except Exception as e:
            logger.warning(f"[check_exit] StopTakeProfitEngine 调用失败，回退到硬编码公式: {e}")
            # 回退: 原硬编码公式
            sl_pct = atr_pct * 1.0 * sl_factor
            tp_pct = atr_pct * 2.0
            if direction == "LONG":
                stop_loss = entry_price * (1 - sl_pct)
                take_profit = entry_price * (1 + tp_pct)
            else:
                stop_loss = entry_price * (1 + sl_pct)
                take_profit = entry_price * (1 - tp_pct)

        if direction == "LONG":
            # 50+ 根 K 线后启用移动止盈
            if bars_held > 20:
                profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
                if profit_pct > 0:
                    # 移动止损：保本后逐步上移
                    trail_stop = entry_price * (1 + profit_pct * 0.5)  # 保护 50% 利润
                    stop_loss = max(stop_loss, trail_stop)

            if price <= stop_loss:
                return {"exit": True, "reason": f"止损触发: {price:.4f} <= {stop_loss:.4f} (持仓{bars_held}根, factor={sl_factor:.2f}={time_factor:.2f}×{regime_factor:.1f}×{symbol_vol_factor:.1f})", "exit_price": stop_loss,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}
            if price >= take_profit:
                return {"exit": True, "reason": f"止盈触发: {price:.4f} >= {take_profit:.4f} (持仓{bars_held}根)", "exit_price": take_profit,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}
        else:
            if bars_held > 20:
                profit_pct = (entry_price - price) / entry_price if entry_price > 0 else 0
                if profit_pct > 0:
                    trail_stop = entry_price * (1 - profit_pct * 0.5)
                    stop_loss = min(stop_loss, trail_stop)

            if price >= stop_loss:
                return {"exit": True, "reason": f"止损触发: {price:.4f} >= {stop_loss:.4f} (持仓{bars_held}根, factor={sl_factor:.2f}={time_factor:.2f}×{regime_factor:.1f}×{symbol_vol_factor:.1f})", "exit_price": stop_loss,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}
            if price <= take_profit:
                return {"exit": True, "reason": f"止盈触发: {price:.4f} <= {take_profit:.4f} (持仓{bars_held}根)", "exit_price": take_profit,
                        "stop_loss": stop_loss, "take_profit": take_profit, "current_price": price}

        return {
            "exit": False,
            "reason": f"继续持有 (持仓{bars_held}根, regime={regime}, SL factor={sl_factor:.2f}={time_factor:.2f}×{regime_factor:.1f}×{symbol_vol_factor:.1f}, atr={atr_pct:.4f})",
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "current_price": price,
            "bars_held": bars_held,
            "regime": regime,
            "sl_factor": round(sl_factor, 4),
        }

    def _estimate_bars_held(self, symbol: str) -> int:
        """估算持仓 K 线数

        基于 _last_trade_time 记录的开仓时间，按 1h 周期折算。
        如果没有记录，返回 0（按最宽松处理）。
        """
        entry_ts = self._last_trade_time.get(symbol, 0)
        if entry_ts == 0:
            return 0
        elapsed_hours = (time.time() - entry_ts) / 3600.0
        return max(1, int(elapsed_hours))

    def _detect_regime_from_market_data(self, market_data: Dict[str, Any], atr_pct: float) -> str:
        """从实时行情判断市场状态

        震荡市 (ranging): EMA 纠缠、价格在均线间反复
        趋势市 (trend):   EMA 多头/空头排列

        回退：用 ATR% 阈值判断
        """
        try:
            from dreamos.core.sense.scenario_classifier import ScenarioClassifier
            classifier = ScenarioClassifier()
            scenario = classifier.classify(market_data)
            if scenario.trend in ("BULL", "BEAR"):
                return "trend"
            return "ranging"
        except Exception:
            # 回退：ATR% 阈值
            if atr_pct > 0.03:
                return "trend"
            return "ranging"

    def _calc_symbol_vol_factor(self, symbol: str, atr_pct: float) -> float:
        """计算币种波动率因子（以 BTC 为基准）

        比较当前币种 ATR% 与 BTC ATR%，波动率越高的币种给越宽的止损缓冲。

        ratio = coin_atr / btc_atr
        ratio <= 1.0: 0.8  (比 BTC 还稳定，收紧)
        ratio 1.0-2.0: 1.0 (与 BTC 相当)
        ratio 2.0-3.0: 1.2 (中等高波动)
        ratio > 3.0:   1.4 (极端高波动)
        """
        symbol_upper = symbol.upper().strip()

        # BTC 自身是基准
        if symbol_upper in ("BTC", "BTCUSDT"):
            return 1.0

        # 获取 BTC 基准 ATR%
        btc_atr_pct = self._get_btc_atr_pct()
        if btc_atr_pct <= 0:
            # 无法获取 BTC 数据，用硬编码回退
            HIGH_VOL = {"SOL", "AVAX", "MATIC", "DOT", "LINK", "DOGE", "SHIB", "OP", "ARB"}
            if symbol_upper in HIGH_VOL:
                return 1.2
            return 1.0

        ratio = atr_pct / btc_atr_pct if btc_atr_pct > 0 else 1.0

        if ratio <= 1.0:
            return 0.8
        elif ratio <= 2.0:
            return 1.0
        elif ratio <= 3.0:
            return 1.2
        else:
            return 1.3

    _btc_atr_cache: Dict[str, Any] = {"ts": 0, "val": 0.0}

    def _get_btc_atr_pct(self) -> float:
        """获取 BTC 的 ATR%（带 5 分钟缓存）"""
        import time as _time
        now = _time.time()
        if self._btc_atr_cache["ts"] > 0 and (now - self._btc_atr_cache["ts"]) < 300:
            return self._btc_atr_cache["val"]

        try:
            btc_data = self._fetch_market_data("BTC")
            btc_atr = btc_data.get("atr_pct", 0.0)
            if btc_atr > 0:
                self._btc_atr_cache = {"ts": now, "val": btc_atr}
                return btc_atr
        except Exception:
            pass

        return 0.0

    def run_auto_trade(self, symbol: str) -> Dict[str, Any]:
        """运行完整自动化交易流程"""
        if not self.is_enabled():
            return {"result": "SKIP", "reason": "自动交易已禁用"}

        # P1-2: 检查该 symbol 是否因连续降级被暂停
        if symbol in self._suspended_symbols:
            logger.warning(f"Symbol {symbol} 因连续 {self.FALLBACK_SUSPEND_THRESHOLD} 次降级路径被暂停交易")
            return {"result": "SKIP", "reason": f"symbol {symbol} 已暂停(连续降级)"}

        start_time = time.time()
        result = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "steps": [],
            "final_result": "SKIP",
        }

        try:
            result["steps"].append({"step": "analysis", "status": "running"})
            analysis = self.run_full_analysis(symbol)
            if analysis.get("error"):
                result["steps"].append({"step": "analysis", "status": "failed", "error": analysis["error"]})
                result["final_result"] = "ANALYSIS_FAILED"
                return result
            result["steps"].append({"step": "analysis", "status": "completed", "confidence": analysis.get("confidence")})

            # TradingAgent.run() 把最终决策放在顶层 action/confidence
            # 同时尝试从 outputs.A5.trade_order 获取详细的订单参数(可能为空)
            a5_output = analysis.get("outputs", {}).get("A5", {})
            trade_order = a5_output.get("trade_order", {})
            direction = trade_order.get("action") or analysis.get("action", "HOLD")

            # 置信度优先从顶层取(TradingAgent 最终决策),其次从 A5 取
            confidence = analysis.get("confidence") or a5_output.get("confidence", 0)

            # v2.6 入场模块选择器 overlay（ENTRY_SELECTOR_ENABLED=1，默认启用）
            # 有回测数据（fallback_level <3 或 场景级降级 L5）时，用 EntryModuleSelector 推荐的模块覆盖 direction/confidence
            # 低置信/LOW 震荡 → 返回 None → 回退原逻辑
            scenario_id_2 = self._resolve_scenario_id(self._current_context.get("market_data", {}))
            _entry_override = self._try_selector_entry(
                symbol=symbol,
                scenario_id=scenario_id_2,
                candles_1h_rows=None,
                market_data=self._current_context.get("market_data", {}),
            )
            if _entry_override is not None:
                logger.info(
                    f"入场选择器覆盖原决策({direction} conf={confidence:.2f}) "
                    f"→ {_entry_override['direction']} conf={_entry_override['confidence']:.2f} "
                    f"[{_entry_override['module_name']}] "
                    f"src={_entry_override['source_scenario']}: {_entry_override.get('reason','')[:80]}"
                )
                direction = _entry_override["direction"]
                confidence = _entry_override["confidence"]
                result["steps"].append({
                    "step": "entry_selector_override",
                    "status": "applied",
                    "module": _entry_override["module_name"],
                    "source_scenario": _entry_override["source_scenario"],
                    "fallback_level": _entry_override["fallback_level"],
                    "direction": direction,
                    "confidence": confidence,
                    "reason": _entry_override.get("reason", ""),
                })

            # P1-2: 降级路径检测与告警
            is_fallback = not trade_order or not trade_order.get("entry_price")
            # 决策日志: 便于监控 A5 执行情况 (之前正常流程静默,无法从日志确认 A5 是否执行)
            path = analysis.get("_path", "unknown")
            if trade_order and trade_order.get("entry_price"):
                logger.info(
                    f"Symbol {symbol} A5正常执行 | path={path} dir={direction} "
                    f"conf={confidence:.2f} entry={trade_order.get('entry_price')} "
                    f"size={trade_order.get('position_size')} "
                    f"SL={trade_order.get('stop_loss')} TP={trade_order.get('take_profit')}"
                )
            if is_fallback and direction != "HOLD":
                self._fallback_counts[symbol] = self._fallback_counts.get(symbol, 0) + 1
                count = self._fallback_counts[symbol]
                logger.warning(f"Symbol {symbol} 降级路径触发 (连续 {count}/{self.FALLBACK_SUSPEND_THRESHOLD})")
                if count >= self.FALLBACK_SUSPEND_THRESHOLD:
                    self._suspended_symbols.add(symbol)
                    logger.error(f"Symbol {symbol} 连续 {count} 次降级,已暂停交易")
                    result["steps"].append({"step": "decision", "status": "suspended", "reason": f"连续 {count} 次降级路径"})
                    result["final_result"] = "SUSPENDED_FALLBACK"
                    return result
            else:
                # 正常 trade_order,重置降级计数
                if self._fallback_counts.get(symbol, 0) > 0:
                    logger.info(f"Symbol {symbol} 降级计数重置 (A5 正常输出)")
                self._fallback_counts[symbol] = 0

            # A5 已执行但 trade_order 为空: A4/A7 门禁主动拒绝, 尊重决策不构造 fallback
            if not trade_order and direction != "HOLD" and a5_output:
                a5_rationale = a5_output.get("rationale", [])
                reject_reason = a5_rationale[-1] if a5_rationale else "A5门禁拒绝"
                logger.info(f"Symbol {symbol} A5门禁拒绝交易 ({reject_reason}), 不构造fallback")
                result["steps"].append({"step": "decision", "status": "gate_rejected", "reason": reject_reason})
                result["final_result"] = "GATE_REJECTED"
                return result

            # A5 未在链路中执行 (a5_output 为空), 用缓存的 market_data 构造最小订单
            if not trade_order and direction != "HOLD":
                market_data = self._current_context.get("market_data", {})
                price = market_data.get("price", 0)
                # 价格为 0 说明行情数据获取失败(如 symbol 不存在),跳过下单
                if price <= 0:
                    result["steps"].append({"step": "decision", "status": "hold", "reason": f"行情数据无效(price={price})"})
                    result["final_result"] = "HOLD"
                    return result
                atr = market_data.get("atr14", 0) or price * 0.02
                atr_pct = (atr / price) if price > 0 else 0.02
                # P0-6: Kelly 动态仓位 & 杠杆（置信度 × 波动率 × 账户权益）
                # 优先获取真实账户余额；取不到时 60 USDT 兜底
                acc_eq: Optional[float] = None
                try:
                    client = self.get_exchange_client()
                    if client and self.exchange == "aster":
                        summary = client._aster_fetch_account_summary()
                        if isinstance(summary, dict) and summary.get("ok"):
                            s = summary.get("summary", {}) or {}
                            acc_eq = float(s.get("totalWalletBalance", 0) or 0) or None
                except Exception as e:
                    logger.warning(f"获取账户余额失败,Kelly 用默认兜底: {e}")
                dyn = calc_dynamic_position_and_leverage(
                    confidence=confidence,
                    atr_pct=atr_pct,
                    account_equity=acc_eq,
                    direction=direction,
                    min_lev=MIN_LEVERAGE,
                    max_lev=MAX_LEVERAGE,
                    threshold=CONFIDENCE_THRESHOLD,
                    symbol=symbol,
                )
                position_size = dyn["position_size"]
                if direction == "LONG":
                    stop_loss = round(price * (1 - atr_pct * 1.5), 4)
                    take_profit = round(price * (1 + atr_pct * 3.0), 4)
                else:
                    stop_loss = round(price * (1 + atr_pct * 1.5), 4)
                    take_profit = round(price * (1 - atr_pct * 3.0), 4)
                trade_order = {
                    "action": direction,
                    "coin": symbol,
                    "entry_price": price,
                    "position_size": position_size,
                    "leverage": int(dyn["leverage"]),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "risk_per_trade": position_size * atr_pct,
                    "_kelly": dyn,
                }
                logger.info(
                    f"构造 trade_order (A5无输出,Kelly模型): {direction} {symbol} @ {price} | "
                    f"size={position_size}USDT lev={int(dyn['leverage'])}x | "
                    f"eq={dyn['account_equity']} kelly={dyn['kelly_pct']:.2%} conf={dyn['confidence_score']:.2f} vol={dyn['vol_score']:.2f} | "
                    f"SL={stop_loss} TP={take_profit}"
                )

            if direction == "HOLD":
                logger.info(f"Symbol {symbol} 决策HOLD | path={path} conf={confidence:.2f}")
                result["steps"].append({"step": "decision", "status": "hold", "reason": "方向为HOLD"})
                result["final_result"] = "HOLD"
                return result

            # 对称门槛：多空同等置信度要求
            threshold = 0.62 if direction == "SHORT" else 0.62
            if confidence < threshold:
                logger.info(f"Symbol {symbol} 置信度不足 | dir={direction} conf={confidence:.2f} < {threshold}")
                result["steps"].append({"step": "decision", "status": "rejected", "reason": f"置信度不足({confidence:.2f} < {threshold}, 方向={direction})"})
                result["final_result"] = "CONFIDENCE_TOO_LOW"
                return result

            # 4h 周期去重：1h 调度但开仓基于 4h 指标，避免同一 4h 周期内重复开仓
            current_ts = int(time.time() * 1000)
            current_4h_ts = (current_ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
            last_4h_ts = self._last_trade_4h_ts.get(symbol, 0)
            if last_4h_ts == current_4h_ts:
                logger.info(f"Symbol {symbol} 4h周期去重 | dir={direction} conf={confidence:.2f}")
                result["steps"].append({"step": "decision", "status": "rejected", "reason": f"4h 周期内已开仓(当前周期={current_4h_ts}, 上次={last_4h_ts})"})
                result["final_result"] = "DUPLICATE_4H"
                return result

            logger.info(f"Symbol {symbol} 决策通过 | dir={direction} conf={confidence:.2f} entry={trade_order.get('entry_price')}")
            result["steps"].append({"step": "decision", "status": "approved", "direction": direction, "confidence": confidence})

            result["steps"].append({"step": "risk_check", "status": "running"})
            risk_result = self.check_risk_control(symbol, trade_order)
            if not risk_result["passed"]:
                result["steps"].append({"step": "risk_check", "status": "failed", "reason": risk_result["reason"]})
                result["final_result"] = "RISK_REJECTED"
                return result
            result["steps"].append({"step": "risk_check", "status": "passed"})

            result["steps"].append({"step": "execution", "status": "running"})
            exec_result = self.execute_trade(trade_order)
            if exec_result.get("result") == "SUCCESS":
                result["steps"].append({"step": "execution", "status": "completed", "ord_id": exec_result.get("ord_id")})
                result["final_result"] = "TRADE_EXECUTED"
                # 断点3修复：记录交易反馈（实盘成交，收益待离场时回填）
                self.record_trade_feedback({
                    "direction": direction,
                    "result": 0.0,  # 开仓时收益未知，离场时由 run_exit_check 回填
                    "expected_direction": self._current_context["expected_direction"],
                    "symbol": symbol,
                    "entry_price": trade_order.get("entry_price", 0),
                    "scenario_id": self._current_context["scenario_id"],
                    "pattern": self._current_context["pattern"],
                })
            elif exec_result.get("dry_run"):
                result["steps"].append({"step": "execution", "status": "dry_run", "details": exec_result})
                result["final_result"] = "DRY_RUN"
                # 模拟模式也记录反馈（用于压力测试和进化验证）
                self.record_trade_feedback({
                    "direction": direction,
                    "result": 0.0,
                    "expected_direction": self._current_context["expected_direction"],
                    "symbol": symbol,
                    "entry_price": trade_order.get("entry_price", 0),
                    "scenario_id": self._current_context["scenario_id"],
                    "pattern": self._current_context["pattern"],
                })
                self._try_trigger_evolution()
            else:
                result["steps"].append({"step": "execution", "status": "failed", "error": exec_result.get("error")})
                result["final_result"] = "EXECUTION_FAILED"

            result["execution_time"] = round(time.time() - start_time, 2)

        except Exception as e:
            result["error"] = str(e)
            result["final_result"] = "EXCEPTION"

        return result

    def run_exit_check(self, symbol: str, entry_price: float, direction: str) -> Dict[str, Any]:
        """运行离场检查"""
        exit_result = self.check_exit(symbol, entry_price, direction)

        if exit_result["exit"]:
            exec_result = self.execute_trade({
                "action": "EXIT",
                "coin": symbol,
                "entry_price": entry_price,
                "direction": direction,
            })
            exit_result["execution"] = exec_result

            # P0-1 修复：离场时回填实际收益率到反馈收集器（更新开仓记录，而非追加新记录）
            # P2: 持仓管家接真实成交回报 —— 实盘优先用交易所成交均价,dry_run 用决策估算价
            estimated_px = exit_result.get("exit_price", entry_price)
            exit_price, px_source = self._resolve_exit_price(exec_result, estimated_px)
            if entry_price > 0:
                if direction == "LONG":
                    ret = (exit_price - entry_price) / entry_price
                else:
                    ret = (entry_price - exit_price) / entry_price
                ret -= 0.0008  # 扣手续费
            else:
                ret = 0.0
            # P0-1: 使用 update_exit_feedback 回填开仓记录，闭合反馈环
            self.update_exit_feedback(symbol, entry_price, exit_price, ret)
            logger.info(f"离场反馈: {symbol} | 价格来源={px_source} | exit={exit_price} ret={ret:.4f}")
            self._try_trigger_evolution()

        return exit_result

    def run_exit_check_all(self) -> Dict[str, Any]:
        """检查所有持仓的离场条件并执行离场

        P0-2 修复：调度器定期调用此方法，检查所有未平仓持仓的
        止损/止盈条件，执行离场并回填实际收益率到反馈收集器。

        P1 动态调整：未触发离场时，根据时间衰减/移动止损动态更新交易所 TP/SL 条件单，
        确保即使程序离线，条件单也能反映最新风控状态。
        """
        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        # PROP-20260816 模块3: 对冲对合并PnL离场巡检（独立账本,先于单币巡检,
        # 异常不影响主离场流程）
        hedge_exit_report = self._run_hedge_exit_check(client)

        # 获取所有持仓
        positions = []
        try:
            if self.exchange == "aster":
                pos_list, err = client._aster_fetch_positions()
                if err:
                    return {"error": f"获取持仓失败: {err}"}
                # P0 修复: Aster API 返回字段名 coin/entry_px，下方循环期望
                # symbol/entry_price，之前不匹配导致 checked=0 离场检查失效
                for p in (pos_list or []):
                    if not isinstance(p, dict):
                        continue
                    if float(p.get("position_amt", 0) or 0) == 0:
                        continue
                    positions.append({
                        "symbol": p.get("coin", ""),
                        "entry_price": float(p.get("entry_px", 0) or 0),
                        "position_amt": float(p.get("position_amt", 0) or 0),
                        "leverage": float(p.get("leverage") or 1),
                        "mark_price": float(p.get("mark_px", 0) or 0),
                        "unrealized_pnl": float(p.get("unrealized_pnl_u", 0) or 0),
                    })
            elif self.exchange == "hyperliquid":
                acct = client.get_account()
                for coin, pos in acct.get("positions", {}).items():
                    size = float(pos.get("size", 0))
                    if abs(size) > 0:
                        positions.append({
                            "symbol": coin,
                            "position_amt": size,
                            "entry_price": float(pos.get("entry_px", 0)),
                        })
            elif self.exchange == "okx":
                # OKX 通过 get_account_status 获取持仓
                status = self.get_account_status()
                if "error" in status:
                    return status
                # OKX spot 通常无持仓
                positions = []
        except Exception as e:
            logger.warning(f"获取持仓异常: {e}")
            return {"error": f"获取持仓异常: {e}"}

        # PROP-20260816 P2: 交易所侧平仓对账 (修复 F-2)
        # 上次快照中存在、本次交易所已消失的持仓 = TP/SL 在交易所侧触发,
        # 查 fills 确认真实成交价后回填认知层;确认不到只记日志不喂认知。
        self._reconcile_disappeared_positions(positions)
        self._save_position_snapshot(positions)

        if not positions:
            logger.info("离场检查: 无持仓")
            return {"result": "NO_POSITIONS", "checked": 0, "hedge": hedge_exit_report,
                    "timestamp": datetime.now().isoformat()}

        results = []
        exit_count = 0
        tpsl_updated = 0

        for pos in positions:
            symbol = str(pos.get("symbol", "")).replace("-USDT", "").replace("-SWAP", "")
            entry_price = float(pos.get("entry_price") or pos.get("entryPx") or 0)
            amt = float(pos.get("position_amt") or pos.get("positionAmt") or 0)

            if entry_price <= 0 or abs(amt) <= 0:
                continue

            direction = "LONG" if amt > 0 else "SHORT"

            # 检查离场条件（同时返回动态 SL/TP）
            exit_result = self.check_exit(symbol, entry_price, direction)

            if exit_result.get("exit"):
                # 执行离场
                exec_result = self.execute_trade({
                    "action": "EXIT",
                    "coin": symbol,
                    "entry_price": entry_price,
                    "direction": direction,
                })

                # P0-1 修复：回填实际收益率（更新开仓记录，闭合反馈环）
                # P2: 持仓管家接真实成交回报 —— 实盘优先用交易所成交均价,dry_run 用决策估算价
                estimated_px = exit_result.get("exit_price", entry_price)
                exit_price, px_source = self._resolve_exit_price(exec_result, estimated_px)
                if entry_price > 0:
                    if direction == "LONG":
                        ret = (exit_price - entry_price) / entry_price
                    else:
                        ret = (entry_price - exit_price) / entry_price
                    ret -= 0.0008  # 手续费
                else:
                    ret = 0.0

                # P0-1: 使用 update_exit_feedback 回填开仓记录
                self.update_exit_feedback(symbol, entry_price, exit_price, ret)

                # P1-3: 真实盈亏回填 DreamOS E层认知闭环 (失败不影响主流程)
                # 守卫: 仅 real_fill(交易所真实成交) 进认知层 —— dry_run/估算平仓
                # 是模拟值,喂入会污染 W/L/lessons(真单未平,认知先记假账)。
                if px_source == "real_fill":
                    self._feed_cognitive_loop(
                        symbol=symbol, direction=direction,
                        entry_price=entry_price, exit_price=exit_price,
                        ret=ret, position_amt=amt,
                        exit_reason=exit_result.get("reason", ""),
                        px_source=px_source,
                    )
                else:
                    logger.info(
                        f"P1-3 认知回填跳过(非真实成交): {symbol} | "
                        f"px_source={px_source} | ret={ret:.4f}"
                    )

                results.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "px_source": px_source,
                    "return": round(ret, 4),
                    "executed": True,
                    "reason": exit_result.get("reason", ""),
                    "exec_result": exec_result,
                })
                exit_count += 1
                logger.info(f"离场执行: {symbol} {direction} entry={entry_price} exit={exit_price}({px_source}) ret={ret:.4f} reason={exit_result.get('reason', '')}")
            else:
                # P1: 未离场时，动态更新交易所 TP/SL 条件单
                new_sl = exit_result.get("stop_loss")
                new_tp = exit_result.get("take_profit")
                tpsl_result = None

                if new_sl and new_tp and self.exchange == "hyperliquid" and hasattr(client, "modify_tpsl"):
                    try:
                        tpsl_result = client.modify_tpsl(
                            coin=symbol,
                            new_sl=float(new_sl),
                            new_tp=float(new_tp),
                            is_market=True,
                        )
                        if tpsl_result.get("ok"):
                            tpsl_updated += 1
                            logger.info(
                                f"TP/SL 已更新: {symbol} | "
                                f"SL={new_sl:.4f} TP={new_tp:.4f} | "
                                f"action={tpsl_result.get('action', 'modify')}"
                            )
                        else:
                            logger.debug(f"TP/SL 更新未变化或失败({symbol}): {tpsl_result.get('error')}")
                    except Exception as e:
                        logger.warning(f"TP/SL 动态更新异常({symbol}): {e}")
                        tpsl_result = {"ok": False, "error": str(e)}

                results.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit": False,
                    "reason": exit_result.get("reason", "继续持有"),
                    "stop_loss": new_sl,
                    "take_profit": new_tp,
                    "tpsl_result": tpsl_result,
                })

        # 如果有离场，触发进化
        if exit_count > 0:
            self._try_trigger_evolution()

        return {
            "result": "EXIT_CHECK_DONE",
            "checked": len(results),
            "exits": exit_count,
            "holds": len(results) - exit_count,
            "tpsl_updated": tpsl_updated,
            "details": results,
            "hedge": hedge_exit_report,
            "timestamp": datetime.now().isoformat(),
        }

    # ── PROP-20260816 模块3: 对冲对离场分支 ──────────────────────────────

    def _run_hedge_exit_check(self, client) -> Dict[str, Any]:
        """对冲对合并PnL离场巡检（独立账本 hedge_positions.json）。

        有 OPEN 对: 拉标记价 → 合并PnL ≥+4% / ≤-6% 时双腿同平。
        无 OPEN 对返回 {}；异常只记日志,不影响主离场流程。
        """
        try:
            from dreamos.capabilities.trading.hedge_executor import HedgeExecutor

            hedge = HedgeExecutor(dry_run=self.dry_run)
            pair = hedge.get_open_pair()
            if pair is None:
                return {}
            mids_fn = getattr(client, "get_all_mids", None)
            if mids_fn is None:
                return {"pair_id": pair.pair_id, "actions": [], "skipped": "no_price_source"}
            mids = mids_fn() or {}
            prices = {
                pair.long_symbol: float(mids.get(pair.long_symbol, 0) or 0),
                pair.short_symbol: float(mids.get(pair.short_symbol, 0) or 0),
            }
            actions = hedge.manage_exits(prices)
            if actions:
                logger.info(f"对冲对离场巡检: {actions}")
            return {"pair_id": pair.pair_id, "actions": actions}
        except Exception as e:
            logger.warning(f"对冲对离场巡检失败(不影响主流程): {e}")
            return {"error": str(e)}

    # ── PROP-20260816 P2: 交易所侧平仓对账 (修复 F-2) ─────────────────────────────

    @staticmethod
    def _norm_snapshot_symbol(raw: str) -> str:
        """归一化持仓 symbol 作为快照 key (去 USDT/SWAP/PERP 后缀)。"""
        sym = str(raw or "").upper()
        for suffix in ("-USDT", "-SWAP", "-PERP", "USDT"):
            sym = sym.replace(suffix, "")
        return sym or str(raw or "").upper()

    def _load_position_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """加载上次巡检的持仓快照 {symbol: {entry_price,size,direction,ts}}。"""
        try:
            if self._snapshot_path.exists():
                with open(self._snapshot_path) as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"持仓快照加载失败: {e}")
        return {}

    def _save_position_snapshot(self, positions: List[Dict[str, Any]]) -> None:
        """保存本次持仓快照。持续持有的 symbol 保留首次观察 ts(对账窗口起点)。"""
        try:
            prev = self._load_position_snapshot()
            snap: Dict[str, Dict[str, Any]] = {}
            now = time.time()
            for p in positions or []:
                amt = float(p.get("position_amt", 0) or 0)
                if abs(amt) <= 0:
                    continue
                sym = self._norm_snapshot_symbol(p.get("symbol", ""))
                if not sym:
                    continue
                snap[sym] = {
                    "entry_price": float(p.get("entry_price", 0) or 0),
                    "size": abs(amt),
                    "direction": "LONG" if amt > 0 else "SHORT",
                    "ts": prev.get(sym, {}).get("ts", now),
                }
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._snapshot_path, "w") as f:
                json.dump(snap, f, indent=2)
        except Exception as e:
            logger.warning(f"持仓快照保存失败(不阻塞): {e}")

    def _reconcile_disappeared_positions(self, current_positions: List[Dict[str, Any]]) -> None:
        """快照 diff: 上次有、本次交易所消失的持仓 → 疑似交易所侧 TP/SL 平仓。"""
        try:
            prev = self._load_position_snapshot()
            if not prev:
                return
            current_syms = set()
            for p in current_positions or []:
                amt = float(p.get("position_amt", 0) or 0)
                if abs(amt) <= 0:
                    continue
                sym = self._norm_snapshot_symbol(p.get("symbol", ""))
                if sym:
                    current_syms.add(sym)
            for sym, snap in prev.items():
                if sym not in current_syms:
                    self._confirm_exchange_close(sym, snap or {})
        except Exception as e:
            logger.warning(f"P2对账异常(不阻塞): {e}")

    def _confirm_exchange_close(self, sym: str, snap: Dict[str, Any]) -> None:
        """查交易所 fills 确认单个 symbol 的平仓;确认不到 → 只记日志不喂认知。"""
        try:
            client = self.get_exchange_client()
            if not (self.exchange == "hyperliquid" and client is not None
                    and hasattr(client, "_info") and getattr(client, "user_addr", None)):
                logger.info(f"P2对账: {self.exchange} 暂不支持fills查询, 跳过 {sym}")
                return
            fills = client._info({"type": "userFills", "user": client.user_addr}) or []
            ts_ms = int(float(snap.get("ts", 0)) * 1000)
            close_fills = []
            for f in fills:
                if f.get("coin") != sym:
                    continue
                closed_pnl = float(f.get("closedPnl", 0) or 0)
                if closed_pnl == 0:
                    continue  # 只认真正减/平仓的成交
                if ts_ms > 0 and int(f.get("time", 0)) < ts_ms - 6 * 3600 * 1000:
                    continue  # 仅回溯首次观察前6小时窗口
                close_fills.append(f)
            if not close_fills:
                logger.info(f"P2对账: {sym} 已从交易所消失但未确认到平仓成交, 不喂认知")
                return
            total_sz = sum(abs(float(f.get("sz", 0))) for f in close_fills)
            if total_sz <= 0:
                return
            exit_px = sum(float(f.get("px", 0)) * abs(float(f.get("sz", 0))) for f in close_fills) / total_sz
            pnl = sum(float(f.get("closedPnl", 0) or 0) for f in close_fills)
            entry = float(snap.get("entry_price", 0) or 0)
            direction = snap.get("direction", "LONG")
            size = float(snap.get("size", 0) or 0)
            if entry <= 0 or exit_px <= 0:
                logger.info(f"P2对账: {sym} 入场/出场价缺失, 不喂认知")
                return
            if direction == "LONG":
                ret = (exit_px - entry) / entry
            else:
                ret = (entry - exit_px) / entry
            ret -= 0.0008  # 与 _feed_cognitive_loop 手续费口径一致
            self._feed_cognitive_loop(
                symbol=sym, direction=direction, entry_price=entry, exit_price=exit_px,
                ret=ret, position_amt=size,
                exit_reason=f"exchange_close|reconciled|closedPnl={pnl:.2f}",
                px_source="real_fill",
            )
            logger.info(
                f"P2对账成功: {sym} {direction} entry={entry} exit={exit_px:.4f} "
                f"pnl={pnl:.2f} 已回填认知层"
            )
        except Exception as e:
            logger.warning(f"P2对账 {sym} 失败(不阻塞): {e}")


    def _try_trigger_evolution(self):
        """检查反馈并尝试触发进化"""
        try:
            from dreamos.evolution.engine import EvolutionEngine

            engine = EvolutionEngine()
            collector = engine.get_feedback_collector()
            updates = engine._check_orchestration_optimization()
            if updates:
                logger.info(f"进化引擎触发优化: {len(updates)} 个场景更新")
                for update in updates:
                    logger.info(f"  {update['scenario_id']}: {update['old_pattern']} → {update['new_pattern']}")
        except Exception as e:
            logger.warning(f"触发进化引擎失败: {e}")

    def get_account_status(self) -> Dict[str, Any]:
        """获取账户状态"""
        client = self.get_exchange_client()
        if not client:
            return {"error": "无法连接交易所"}

        try:
            if self.exchange == "hyperliquid":
                acct = client.get_account()
                positions = acct.get("positions", {})
                position_list = []
                for coin, pos in positions.items():
                    position_list.append({
                        "coin": coin,
                        "size": pos.get("size", 0),
                        "entry_px": pos.get("entry_px", 0),
                    })
                return {
                    "exchange": "hyperliquid",
                    "total_eq": round(float(acct.get("equity", 0)), 2),
                    "margin": acct.get("margin", {}),
                    "positions": position_list,
                    "timestamp": datetime.now().isoformat(),
                }
            elif self.exchange == "okx":
                balance = client.get_balance()
                if not balance.get("ok"):
                    return {"error": balance.get("error", "未知错误")}

                return {
                    "exchange": "okx",
                    "total_eq": round(balance["total_eq"], 2),
                    "assets": {k: {"avail": round(v["avail"], 4), "total": round(v["total"], 4)}
                              for k, v in balance["assets"].items() if v["total"] > 0.0001},
                    "timestamp": datetime.now().isoformat(),
                }
            else:
                return {"error": f"不支持的交易所: {self.exchange}"}
        except Exception as e:
            return {"error": str(e)}
