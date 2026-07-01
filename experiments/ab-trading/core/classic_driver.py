#!/usr/bin/env python3
"""
经典指标系统驱动层 (ClassicDriver)
==================================

作为 experiments 侧指向 ml_trade_service 的「指针」，
当大模型不可用时，完整接管交易（入场 + 离场 + 风控）。

设计原则（遵循 Experience #154595 教训）：
  1. 只做驱动不做实现：所有交易逻辑调用 ml_trade_service 接口
  2. 接口契约对齐：严格使用 ml_trade_service 已有 API，不自创逻辑
  3. 开关优先级明确：LLM可用性 > 配置开关 > 默认值

架构：
  ┌─────────────────────────────────────────────────────┐
  │  agent_b_runner.py                                  │
  │     │                                               │
  │     ▼                                               │
  │  ClassicDriver (本文件)                             │
  │     │                                               │
  │     ├── 入场：调用 /signals/v1 + /decision/entry    │
  │     ├── 离场：调用 /exit/features/latest + 执行     │
  │     ├── 持仓：调用 /tracker/stats                   │
  │     └── 信号：调用 /strategy/feeder/capabilities    │
  │                                                     │
  └─────────────┬───────────────────────────────────────┘
                │ HTTP API
                ▼
  ┌─────────────────────────────────────┐
  │  ml_trade_service.py (经典指标系统)  │
  └─────────────────────────────────────┘
"""

import os
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


# ── 配置 ───────────────────────────────────────────────────────────────────

DEFAULT_API_BASE = os.environ.get(
    "ML_TRADE_SERVICE_URL",
    "http://127.0.0.1:8092"
)

DEFAULT_TIMEOUT = float(os.environ.get("CLASSIC_DRIVER_TIMEOUT", "8.0"))

# 经典指标系统使用的策略列表（与 ml_trade_service 对齐）
DEFAULT_STRATEGIES = [
    "RegimeHybridStrategy",
    "BreakoutStrategy",
    "OttStrategy",
]

# 默认扫描币种
DEFAULT_COINS = [
    "BTC", "ETH", "SOL", "AVAX", "ARB", "SUI", "INJ", "LINK",
]

# ab_owner 标识：用于与其他策略体系隔离
AB_OWNER = "agent_b_classic"
BOOK_ID = "agent_b"
SYSTEM_ID = "classic_fallback"


# ── 数据类 ─────────────────────────────────────────────────────────────────

@dataclass
class ClassicEntrySignal:
    """经典指标入场信号"""
    coin: str
    side: str           # "long" / "short"
    strategy_id: str
    confidence: float
    reason: str
    signal_id: Optional[str] = None
    features: Dict = field(default_factory=dict)


@dataclass
class ClassicExitDecision:
    """经典指标离场决策"""
    coin: str
    should_exit: bool
    action: str         # "close" / "reduce" / "hold"
    reason: str
    confidence: float
    priority: str = ""
    suggested_price: float = 0.0
    features: Dict = field(default_factory=dict)


@dataclass
class DriverStatus:
    """驱动状态"""
    api_available: bool
    latency_ms: float = 0.0
    last_error: str = ""
    strategies_supported: List[str] = field(default_factory=list)


# ── 主驱动类 ────────────────────────────────────────────────────────────────

class ClassicDriver:
    """
    经典指标系统驱动
    
    作为 agent_b 在无 LLM 时的完整回退方案，
    通过 HTTP API 驱动 ml_trade_service 完成全链路交易。
    """

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = DEFAULT_TIMEOUT,
        strategies: Optional[List[str]] = None,
        coins: Optional[List[str]] = None,
        per_trade_usdc: float = 30.0,
        max_positions: int = 3,
        leverage: int = 3,
    ):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.strategies = strategies or DEFAULT_STRATEGIES
        self.coins = coins or DEFAULT_COINS
        self.per_trade_usdc = per_trade_usdc
        self.max_positions = max_positions
        self.leverage = leverage
        
        self._session = None
        self._status = DriverStatus(
            api_available=False,
            strategies_supported=[],
        )
        
        # 冷却机制：防止重复触发
        self._entry_cooldowns: Dict[str, float] = {}  # coin -> expiry_ts
        self._exit_cooldowns: Dict[str, float] = {}   # coin -> expiry_ts
        self._entry_cooldown_sec = 300  # 5分钟
        self._exit_cooldown_sec = 90    # 90秒

    # ── 基础工具 ────────────────────────────────────────────────────────

    @property
    def session(self):
        if self._session is None and requests is not None:
            self._session = requests.Session()
        return self._session

    def is_available(self) -> bool:
        """检查 ml_trade_service 是否可用"""
        try:
            if self.session is None:
                return False
            t0 = time.time()
            resp = self.session.get(
                f"{self.api_base}/health",
                timeout=min(self.timeout, 3.0),
            )
            ok = resp.status_code == 200
            self._status.api_available = ok
            self._status.latency_ms = (time.time() - t0) * 1000
            if not ok:
                self._status.last_error = f"health_status_{resp.status_code}"
            return ok
        except Exception as e:
            self._status.api_available = False
            self._status.last_error = str(e)
            return False

    def get_status(self) -> DriverStatus:
        """获取驱动状态"""
        return self._status

    def _post(self, path: str, data: Dict) -> Optional[Dict]:
        """统一 POST 封装"""
        try:
            if self.session is None:
                return None
            url = f"{self.api_base}{path}"
            resp = self.session.post(url, json=data, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            self._status.last_error = f"{path}_status_{resp.status_code}"
            return None
        except Exception as e:
            self._status.last_error = f"{path}_error_{e}"
            return None

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """统一 GET 封装"""
        try:
            if self.session is None:
                return None
            url = f"{self.api_base}{path}"
            resp = self.session.get(url, params=params or {}, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            self._status.last_error = f"{path}_status_{resp.status_code}"
            return None
        except Exception as e:
            self._status.last_error = f"{path}_error_{e}"
            return None

    # ── 策略能力查询 ────────────────────────────────────────────────────

    def get_strategy_capabilities(self) -> List[Dict]:
        """查询支持的策略列表"""
        data = self._get("/strategy/feeder/capabilities")
        if data and data.get("ok"):
            strategies = data.get("strategies", [])
            self._status.strategies_supported = [
                s.get("strategy_id", "") for s in strategies
            ]
            return strategies
        return []

    # ── 入场：信号扫描 + 决策 ────────────────────────────────────────────

    def scan_entry_signals(
        self,
        coins: Optional[List[str]] = None,
        min_confidence: float = 0.55,
    ) -> List[ClassicEntrySignal]:
        """
        扫描入场信号（调用 /decision/entry 接口）
        
        对每个币种 + 策略组合调用决策接口，
        返回满足置信度门槛的信号列表。
        
        注：直接用 decision/entry 而不是 signals/v1，因为：
        - signals/v1 是信号注入接口（外部系统推送信号用）
        - decision/entry 内部会自动计算策略信号 + 风控门控
        """
        if not self.is_available():
            return []
        
        coins_to_scan = coins or self.coins
        signals: List[ClassicEntrySignal] = []
        now = time.time()
        
        for strategy_id in self.strategies:
            for coin in coins_to_scan:
                # 检查冷却
                ck = f"{coin}_{strategy_id}"
                if ck in self._entry_cooldowns and now < self._entry_cooldowns[ck]:
                    continue
                
                signal = self._query_single_signal(coin, strategy_id)
                if signal and signal.confidence >= min_confidence:
                    signals.append(signal)
                
                # 短暂间隔，避免请求过快
                time.sleep(0.02)
        
        # 按置信度排序
        signals.sort(key=lambda x: x.confidence, reverse=True)
        return signals

    def _query_single_signal(self, coin: str, strategy_id: str) -> Optional[ClassicEntrySignal]:
        """查询单个币种+策略的信号（通过 decision/entry）"""
        data = self._post("/decision/entry", {
            "pair": coin,
            "side": "long",
            "strategy_id": strategy_id,
            "ab_owner": AB_OWNER,
            "book_id": BOOK_ID,
            "system_id": SYSTEM_ID,
            "size": self.per_trade_usdc,
            "leverage": self.leverage,
        })
        
        if not data or not data.get("ok"):
            return None
        
        confidence = float(data.get("pc", 0) or 0)
        side = str(data.get("side", "long") or "long").lower()
        decision = str(data.get("decision", "hold") or "hold")
        
        # 保存完整决策数据到 features 供后续复用
        features = data.get("market_features", {}) or {}
        features["_decision_data"] = data
        
        return ClassicEntrySignal(
            coin=coin,
            side=side,
            strategy_id=strategy_id,
            confidence=confidence,
            reason=f"{strategy_id} pc={confidence:.3f}, decision={decision}",
            signal_id=data.get("event_id"),
            features=features,
        )

    def decide_entry(
        self,
        signal: ClassicEntrySignal,
        position_size_usdc: Optional[float] = None,
    ) -> Tuple[bool, str, Dict]:
        """
        入场决策（直接使用 signal 中已缓存的决策结果）
        
        设计说明：
        scan_entry_signals 已经通过 /decision/entry 获取了完整的决策结果，
        这里直接复用，避免重复 API 调用。
        signal.decision_data 中保存了原始决策响应。
        
        返回: (approved, reason, decision_data)
        """
        dec_data = signal.features.get("_decision_data")
        if not dec_data:
            # 如果没有缓存的数据，重新调用一次
            data = self._post("/decision/entry", {
                "pair": signal.coin,
                "side": signal.side,
                "strategy_id": signal.strategy_id,
                "event_id": signal.signal_id,
                "ab_owner": AB_OWNER,
                "book_id": BOOK_ID,
                "system_id": SYSTEM_ID,
                "size": position_size_usdc or self.per_trade_usdc,
                "leverage": self.leverage,
            })
            if not data:
                return False, "decision_api_error", {}
            dec_data = data
        
        api_ok = dec_data.get("ok", False)
        approved = api_ok and dec_data.get("decision") == "open"
        reason = dec_data.get("reason", "") if not approved else "approved"
        
        # 设置冷却
        if approved:
            ck = f"{signal.coin}_{signal.strategy_id}"
            self._entry_cooldowns[ck] = time.time() + self._entry_cooldown_sec
        
        return approved, reason, dec_data

    # ── 离场：评估 + 执行 ────────────────────────────────────────────────

    def evaluate_exit(
        self,
        coin: str,
        current_price: float,
        position_side: str,
        entry_price: float,
        position_size_usdt: float,
        leverage: int = 3,
        hold_sec: float = 0.0,
    ) -> ClassicExitDecision:
        """
        离场评估（调用 /exit/features/latest + 本地决策）
        
        注：完整的离场逻辑复用 classic_exit_system.py（L0~P3 全优先级），
        此处作为 API 模式的封装入口。
        """
        # 检查冷却
        if coin in self._exit_cooldowns and time.time() < self._exit_cooldowns[coin]:
            return ClassicExitDecision(
                coin=coin,
                should_exit=False,
                action="hold",
                reason="exit_cooldown",
                confidence=0.0,
            )
        
        # 获取离场特征
        features_data = self._get("/exit/features/latest", {"pair": coin})
        features = {}
        if features_data and features_data.get("ok"):
            features = features_data.get("features", {}) or {}
        
        # 优先使用 ClassicExitSystem（统一离场模块）
        exit_decision = self._evaluate_with_classic_system(
            coin=coin,
            current_price=current_price,
            position_side=position_side,
            entry_price=entry_price,
            position_size_usdt=position_size_usdt,
            leverage=leverage,
            hold_sec=hold_sec,
            features=features,
        )
        
        # 设置冷却
        if exit_decision.should_exit:
            self._exit_cooldowns[coin] = time.time() + self._exit_cooldown_sec
        
        return exit_decision

    def _evaluate_with_classic_system(
        self,
        coin: str,
        current_price: float,
        position_side: str,
        entry_price: float,
        position_size_usdt: float,
        leverage: int,
        hold_sec: float,
        features: Dict,
    ) -> ClassicExitDecision:
        """使用 ClassicExitSystem 统一离场模块评估"""
        try:
            # 尝试导入统一离场模块
            classic_path = Path(__file__).parent.parent.parent.parent / "10-经典指标系统"
            import sys
            if str(classic_path) not in sys.path:
                sys.path.insert(0, str(classic_path))
            
            from classic_exit_system import (
                ClassicExitSystem, PositionState, ExitAction, ExitConfig,
            )
            
            exit_sys = ClassicExitSystem(api_base=self.api_base)
            
            is_long = position_side.upper() in ("LONG", "BUY")
            unrealized_pnl_pct = (
                (current_price - entry_price) / entry_price if is_long
                else (entry_price - current_price) / entry_price
            )
            
            pos = PositionState(
                coin=coin,
                side="long" if is_long else "short",
                entry_price=entry_price,
                current_price=current_price,
                position_age_sec=hold_sec,
                unrealized_pnl_pct=unrealized_pnl_pct,
                leverage=float(leverage),
            )
            
            decision = exit_sys.evaluate_full(pos, regime="trend")
            
            return ClassicExitDecision(
                coin=coin,
                should_exit=decision.action in (ExitAction.CLOSE, ExitAction.REDUCE),
                action=decision.action.value,
                reason=decision.reason,
                confidence=decision.confidence,
                priority=decision.priority.value if decision.priority else "",
                suggested_price=decision.suggested_price,
                features=features,
            )
        except Exception as e:
            # 降级：简单止损止盈判断
            return self._evaluate_exit_simple(
                coin, current_price, position_side,
                entry_price, leverage,
            )

    def _evaluate_exit_simple(
        self,
        coin: str,
        current_price: float,
        position_side: str,
        entry_price: float,
        leverage: int,
    ) -> ClassicExitDecision:
        """简单回退：基础止损止盈"""
        is_long = position_side.upper() in ("LONG", "BUY")
        
        if is_long:
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price
        
        # 含杠杆的有效盈亏
        pnl_eff = pnl_pct * leverage
        
        # -6% 止损（含杠杆）
        if pnl_eff <= -0.06:
            return ClassicExitDecision(
                coin=coin, should_exit=True, action="close",
                reason="stop_loss_simple", confidence=0.9,
                priority="p0", suggested_price=current_price,
            )
        
        # +12% 止盈（含杠杆）
        if pnl_eff >= 0.12:
            return ClassicExitDecision(
                coin=coin, should_exit=True, action="close",
                reason="take_profit_simple", confidence=0.8,
                priority="p2", suggested_price=current_price,
            )
        
        return ClassicExitDecision(
            coin=coin, should_exit=False, action="hold",
            reason="no_signal", confidence=0.0,
        )

    # ── 持仓查询 ────────────────────────────────────────────────────────

    def get_tracker_stats(self, sync: bool = False) -> Optional[Dict]:
        """获取持仓统计（调用 /tracker/stats）"""
        params = {"sync": "1" if sync else "0"}
        return self._get("/tracker/stats", params=params)

    # ── 完整周期执行 ────────────────────────────────────────────────────

    def run_full_cycle(
        self,
        active_positions: Dict[str, Dict],
        get_price_fn,
        execute_entry_fn,
        execute_exit_fn,
    ) -> Dict[str, Any]:
        """
        执行一个完整的经典指标交易周期
        
        Args:
            active_positions: 当前持仓 {coin: position_dict}
            get_price_fn: 获取价格的函数 fn(coin) -> float
            execute_entry_fn: 执行开仓的函数 fn(coin, side, size, leverage, tag) -> result
            execute_exit_fn: 执行平仓的函数 fn(coin, reason, tag) -> result
        
        Returns:
            {
                "entries": [...],  # 开仓结果
                "exits": [...],    # 平仓结果
                "signals": [...],  # 扫描到的信号
            }
        """
        result = {
            "entries": [],
            "exits": [],
            "signals": [],
            "api_available": self.is_available(),
        }
        
        if not result["api_available"]:
            return result
        
        now = time.time()
        
        # Step 1: 检查现有持仓的离场
        for coin, pos in list(active_positions.items()):
            try:
                price = get_price_fn(coin)
                if price <= 0:
                    continue
                
                hold_sec = now - pos.get("entry_ts", now)
                exit_dec = self.evaluate_exit(
                    coin=coin,
                    current_price=price,
                    position_side=pos.get("action", "LONG"),
                    entry_price=pos.get("entry_price", price),
                    position_size_usdt=pos.get("position_size_usdt", 0),
                    leverage=pos.get("leverage", self.leverage),
                    hold_sec=hold_sec,
                )
                
                if exit_dec.should_exit:
                    exit_result = execute_exit_fn(
                        coin, exit_dec.reason, "classic_driver",
                    )
                    result["exits"].append({
                        "coin": coin,
                        "reason": exit_dec.reason,
                        "result": exit_result,
                    })
            except Exception as e:
                result["exits"].append({"coin": coin, "error": str(e)})
        
        # Step 2: 扫描入场信号（如果还有额度）
        current_pos_count = len(active_positions) - len(result["exits"])
        if current_pos_count < self.max_positions:
            signals = self.scan_entry_signals()
            result["signals"] = [
                {"coin": s.coin, "side": s.side, "strategy": s.strategy_id, "conf": s.confidence}
                for s in signals
            ]
            
            # 取前 N 个信号尝试开仓
            slots = self.max_positions - current_pos_count
            for sig in signals[:slots * 2]:  # 多取一些，跳过已有持仓的币种
                if sig.coin in active_positions:
                    continue
                if any(e["coin"] == sig.coin for e in result["entries"]):
                    continue
                
                approved, reason, dec_data = self.decide_entry(sig)
                if approved:
                    entry_result = execute_entry_fn(
                        sig.coin, sig.side.upper(),
                        self.per_trade_usdc, self.leverage,
                        f"classic_{sig.strategy_id}",
                    )
                    result["entries"].append({
                        "coin": sig.coin,
                        "side": sig.side,
                        "strategy": sig.strategy_id,
                        "confidence": sig.confidence,
                        "result": entry_result,
                    })
                    slots -= 1
                    if slots <= 0:
                        break
        
        return result


# ── 便捷函数 ───────────────────────────────────────────────────────────────

def check_llm_available() -> bool:
    """检查 LLM 是否可用（与 experiments 侧保持一致）"""
    try:
        from core.llm_client import llm_available, llm_quota_ok
        return llm_available() != "none" and llm_quota_ok("a9_exit")
    except Exception:
        return False


def should_use_classic_driver() -> bool:
    """判断是否应该使用经典指标驱动（无 BAC 架构时使用）
    默认走 BAC 全量链路，LLM 只是增强选项。
    只有显式设置 FORCE_CLASSIC_DRIVER 时才走经典模式。
    """
    if os.environ.get("FORCE_CLASSIC_DRIVER", "").lower() in ("1", "true", "yes"):
        return True
    return False
