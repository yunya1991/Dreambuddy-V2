"""
CapitalControlComponent 主组件
===============================

对外暴露的唯一入口：
- evaluate(systems=None) -> CapitalSnapshot
- get_capital_advice(system, action) -> Dict
- get_snapshot() -> Optional[CapitalSnapshot]
- health_check() -> Dict

使用方式::

    from capital_control import CapitalControlComponent, CapitalMode

    component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    snapshot = component.evaluate()
    print(snapshot.health, snapshot.total_equity)

设计约束（Spec 4.7）：
  * evaluate() 仅通过 unified_position_query.fetch_all_positions() 的结果
    获取 equity，避免直接重复调 OKX / HL API。
  * 单系统失败不影响整体（Spec 6.4）——失败系统置 fallback_used=True。
  * 60s 缓存：同一进程内短时间连续 evaluate() 复用上次结果。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_CORE_DIR = Path(__file__).resolve().parent  # capital_control
_16_CORE_DIR = _CORE_DIR.parent  # 16-调控系统/core
_PROJECT_DIR = _16_CORE_DIR.parents[1]  # dreambuddy-v2
_RISK_DIR = _PROJECT_DIR / "13-通用风控模块"
_RISK_CORE_DIR = _RISK_DIR / "core"
for _p in (_16_CORE_DIR, _RISK_DIR, _RISK_CORE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from core.registry import (  # noqa: E402
        DEFAULT_RULES,
        RuleCategory,
        RuleRegistry,
    )
except ImportError:
    from registry import (  # noqa: E402
        DEFAULT_RULES,
        RuleCategory,
        RuleRegistry,
    )

from .types import (  # noqa: E402
    AccountType,
    CapitalMode,
    CapitalResult,
    CapitalSnapshot,
    HealthLevel,
    assess_health,
    calc_margin_pressure,
    now_iso,
)

# 系统 → rule 名 & account type 映射
# 注意：hyperliquid 规则覆盖 agent_a/agent_b/agent_c_memory 三个系统
_SYSTEM_RULE_MAP: Dict[str, str] = {
    "v15_martin": "capital.okx_live",
    "yijing_bcrm": "capital.okx_simulated",
    "agent_a": "capital.hyperliquid",
    "agent_b": "capital.hyperliquid",
    "agent_c_memory": "capital.hyperliquid",
    "three_screen": "capital.aster",
}

_DEFAULT_SYSTEMS: List[str] = list(_SYSTEM_RULE_MAP.keys())

_DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.0",
    "mode": "dynamic",
    "enabled_systems": list(_DEFAULT_SYSTEMS),
    "cache_ttl_sec": 60,
    "health_thresholds": {
        "healthy_used_pct_max": 50.0,
        "warning_used_pct_max": 80.0,
    },
    "fallback_static_budget": {
        "v15_martin": 260.0,
        "yijing_bcrm": 150.0,
        "agent_a": 60.0,
        "agent_b": 60.0,
        "agent_c_memory": 0.0,
        "three_screen": 200.0,
    },
    "account_mapping": {
        "v15_martin": "okx_live",
        "yijing_bcrm": "okx_simulated",
        "agent_a": "hyperliquid",
        "agent_b": "hyperliquid",
        "agent_c_memory": "hyperliquid",
        "three_screen": "aster",
    },
    "phase2": {
        "enabled": False,
        "high_pressure_actions_to_block": ["RAISE_TP"],
        "high_pressure_confidence_multiplier": 0.8,
    },
}


# ---------------------------------------------------------------------------
# 主组件
# ---------------------------------------------------------------------------


class CapitalControlComponent:
    """账户资金调控通用组件。"""

    def __init__(
        self,
        mode: Optional[CapitalMode] = None,
        config_path: Optional[Path] = None,
        registry: Optional[RuleRegistry] = None,
        cache_ttl: Optional[int] = None,
    ):
        # 1) 定位默认配置路径
        if config_path is None:
            config_path = _16_CORE_DIR.parent / "config" / "capital_control.json"
        self._config_path: Path = Path(config_path)

        # 2) 加载配置（文件不存在则用默认）
        self._config: Dict[str, Any] = self._load_config(self._config_path)

        # 3) 模式：参数 > 配置文件 > 默认 DYNAMIC
        if mode is not None:
            self._mode = mode
        else:
            mode_str = str(self._config.get("mode", "dynamic")).lower()
            self._mode = CapitalMode.FIXED if mode_str == "fixed" else CapitalMode.DYNAMIC

        # 4) 缓存 TTL：参数 > 配置文件 > 默认 60s
        if cache_ttl is not None:
            self._cache_ttl = int(cache_ttl)
        else:
            self._cache_ttl = int(self._config.get("cache_ttl_sec", 60))

        # 5) 实例化 Registry + 载入所有 @register_capital 规则
        if registry is None:
            registry = RuleRegistry()
            # import 四个 capital_rules 子模块 → 触发装饰器注册到 DEFAULT_RULES
            from .capital_rules import (  # noqa: F401  (副作用：注册)
                aster_rule,
                hyperliquid_rule,
                okx_live_rule,
                okx_simulated_rule,
            )
            registry.load_defaults()
        self._registry: RuleRegistry = registry

        # 6) 按 enabled_systems 启停对应规则（disable 不在名单里的 rule）
        enabled_systems = self._enabled_systems_list()
        rules_to_enable = {_SYSTEM_RULE_MAP[s] for s in enabled_systems if s in _SYSTEM_RULE_MAP}
        for ri in self._registry.get_rules(RuleCategory.CAPITAL):
            if ri.name in rules_to_enable:
                self._registry.enable(ri.name)
            else:
                self._registry.disable(ri.name)

        # 7) 缓存
        self._lock = threading.RLock()
        self._last_snapshot: Optional[CapitalSnapshot] = None
        self._last_eval_ts: float = 0.0

    # ------------------------------------------------------------------
    # 初始化工具
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: Path) -> Dict[str, Any]:
        cfg = dict(_DEFAULT_CONFIG)
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                if isinstance(file_cfg, dict):
                    # 浅合并顶层；嵌套 dict 也合并
                    for k, v in file_cfg.items():
                        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                            new_dict = dict(cfg[k])
                            new_dict.update(v)
                            cfg[k] = new_dict
                        else:
                            cfg[k] = v
        except (OSError, json.JSONDecodeError):
            # 文件损坏时仍使用默认（保证组件可用）
            pass
        cfg["enabled_systems"] = [
            s for s in cfg.get("enabled_systems") or []
            if s in _SYSTEM_RULE_MAP
        ] or list(_DEFAULT_SYSTEMS)
        return cfg

    def _enabled_systems_list(self, override: Optional[Iterable[str]] = None) -> List[str]:
        if override is not None:
            return [s for s in override if s in _SYSTEM_RULE_MAP]
        return list(self._config.get("enabled_systems") or _DEFAULT_SYSTEMS)

    def _rule_config(self, rule_name: str) -> Dict[str, Any]:
        return {"fallback_static_budget": self._config.get("fallback_static_budget", {})}

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def evaluate(self, systems: Optional[List[str]] = None) -> CapitalSnapshot:
        """执行资金调控评估。

        流程：
          1. 如距离上次 evaluate < cache_ttl 秒，直接返回缓存快照。
          2. 调用 fetch_all_positions() 拉取全局 positions_result（60s 缓存兜底）。
          3. 按 enabled_systems 遍历，对每个系统调用注册好的 rule handler。
          4. 聚合为 CapitalSnapshot，含健康判定 + 建议。
        """
        with self._lock:
            now_ts = time.time()
            if (
                self._last_snapshot is not None
                and (now_ts - self._last_eval_ts) < self._cache_ttl
                and systems is None
            ):
                return self._last_snapshot

            snapshot = self._do_evaluate(systems=systems)
            self._last_snapshot = snapshot
            self._last_eval_ts = time.time()
            return snapshot

    def get_capital_advice(self, system: str, action: str = "HOLD") -> Dict[str, Any]:
        """二期接口：为指定系统+动作返回资金压力建议。

        返回结构（稳定，向后兼容）::

            {
              "allowed": bool,
              "reason": str,
              "max_position_usdt": float,
              "current_avail": float,
              "margin_pressure": "LOW" | "MEDIUM" | "HIGH",
              "used_pct": float,
              "total_eq": float,
              "phase2_enabled": bool,
            }
        """
        snap = self._last_snapshot or self.evaluate()
        result = snap.by_system.get(system)
        phase2_enabled = bool(self._config.get("phase2", {}).get("enabled", False))

        if result is None:
            return {
                "allowed": True,
                "reason": "system_not_in_capital_registry",
                "max_position_usdt": 0.0,
                "current_avail": 0.0,
                "margin_pressure": "LOW",
                "used_pct": 0.0,
                "total_eq": 0.0,
                "phase2_enabled": phase2_enabled,
            }

        pressure = calc_margin_pressure(result.used_pct)
        blocked_actions = set(
            self._config.get("phase2", {}).get("high_pressure_actions_to_block", [])
        )
        conf_mult = float(
            self._config.get("phase2", {}).get("high_pressure_confidence_multiplier", 0.8)
        )

        allowed = True
        reason_parts: List[str] = []
        if pressure == "HIGH" and phase2_enabled and action in blocked_actions:
            allowed = False
            reason_parts.append(
                f"high_pressure_{action}_blocked(mult={conf_mult})"
            )
        if result.fallback_used:
            reason_parts.append("fallback_to_static_budget")

        # 简单 max_position_usdt：可用余额的 20%
        max_position_usdt = round(max(0.0, result.avail_balance) * 0.2, 2)

        return {
            "allowed": allowed,
            "reason": "; ".join(reason_parts) or "ok",
            "max_position_usdt": max_position_usdt,
            "current_avail": round(result.avail_balance, 2),
            "margin_pressure": pressure,
            "used_pct": round(result.used_pct, 2),
            "total_eq": round(result.total_eq, 2),
            "phase2_enabled": phase2_enabled,
            "confidence_multiplier": conf_mult,
            "blocked_actions": sorted(blocked_actions) if phase2_enabled else [],
        }

    def get_snapshot(self) -> Optional[CapitalSnapshot]:
        """返回最近一次 evaluate() 的快照缓存。"""
        return self._last_snapshot

    def health_check(self) -> Dict[str, Any]:
        """组件健康检查——用于 16-调控系统统一健康监控。"""
        snap = self._last_snapshot
        evaluated = False
        if snap is None:
            try:
                snap = self.evaluate()
                evaluated = True
            except Exception as exc:
                return {
                    "ok": False,
                    "error": f"evaluate_failed: {exc}",
                    "registry_rules_loaded": len(
                        self._registry.get_rules(RuleCategory.CAPITAL)
                    ),
                    "mode": self._mode.value,
                    "config_path": str(self._config_path),
                }
        return {
            "ok": True,
            "evaluated": evaluated,
            "health": snap.health.value if snap else HealthLevel.CRITICAL.value,
            "mode": self._mode.value,
            "total_systems": len(snap.by_system) if snap else 0,
            "total_equity": snap.total_equity if snap else 0.0,
            "systems_with_fallback": [
                s for s, r in (snap.by_system if snap else {}).items() if r.fallback_used
            ],
            "registry_rules_loaded": len(self._registry.get_rules(RuleCategory.CAPITAL)),
            "config_path": str(self._config_path),
            "cache_ttl_sec": self._cache_ttl,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _lazy_fetch_positions(self) -> Dict[str, Any]:
        try:
            from unified_position_query import fetch_all_positions

            result = fetch_all_positions()
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            return {"_fetch_error": str(exc)}

    def _do_evaluate(self, systems: Optional[List[str]] = None) -> CapitalSnapshot:
        target_systems = self._enabled_systems_list(systems)
        positions_result = self._lazy_fetch_positions()

        # 构建 rule → 命中的 systems
        rule_to_systems: Dict[str, List[str]] = {}
        for sys_name in target_systems:
            rule_name = _SYSTEM_RULE_MAP.get(sys_name)
            if not rule_name:
                continue
            rule_to_systems.setdefault(rule_name, []).append(sys_name)

        by_system: Dict[str, CapitalResult] = {}
        static_budgets = self._config.get("fallback_static_budget", {})
        account_mapping = self._config.get("account_mapping", {})

        # 共享上下文：mode + positions_result（使 rules 复用 fetch_all_positions 缓存）
        base_context: Dict[str, Any] = {
            "mode": self._mode,
            "positions_result": positions_result,
        }

        for rule_name, attached_systems in rule_to_systems.items():
            rule_info = self._registry.get_rule(rule_name)
            handler = self._registry.get_handler(rule_name) if rule_info else None
            if handler is None or not (rule_info and rule_info.enabled):
                # rule 未注册或禁用 → 各系统走静态兜底
                for s in attached_systems:
                    by_system[s] = self._static_fallback_result(
                        system=s,
                        reason=f"rule_{rule_name}_missing_or_disabled",
                        static_budget=static_budgets.get(s, 0.0),
                        account_mapping=account_mapping,
                    )
                continue

            try:
                rule_config = self._rule_config(rule_name)
                if rule_name == "capital.hyperliquid":
                    # 对 HL，若覆盖多个系统，让 handler 返回字典
                    ctx = dict(base_context)
                    if len(attached_systems) == 1:
                        ctx["target_system"] = attached_systems[0]
                    raw = handler(context=ctx, config=rule_config)
                    if isinstance(raw, dict):
                        # {system: CapitalResult}
                        for s, r in raw.items():
                            if s in attached_systems:
                                by_system[s] = r
                        # 未覆盖的系统兜底（一般不会触发）
                        for s in attached_systems:
                            if s not in by_system:
                                by_system[s] = self._static_fallback_result(
                                    s, "hyperliquid_handler_missing_entry",
                                    static_budgets.get(s, 0.0), account_mapping,
                                )
                    else:
                        # 单个结果
                        for s in attached_systems:
                            by_system[s] = self._static_fallback_result(
                                s, "hyperliquid_handler_bad_shape",
                                static_budgets.get(s, 0.0), account_mapping,
                            )
                else:
                    # 其他 rule：handler 单对单；一对多时循环并在 context 里写 target_system（当前实际 1:1）
                    for s in attached_systems:
                        try:
                            ctx = dict(base_context)
                            ctx["target_system"] = s
                            raw = handler(context=ctx, config=rule_config)
                            if isinstance(raw, CapitalResult):
                                # 确认 system 名匹配（handler 默认写 v15_martin / yijing_bcrm / three_screen）
                                if raw.system != s:
                                    raw = CapitalResult(
                                        system=s,
                                        account_type=raw.account_type,
                                        mode=raw.mode,
                                        total_eq=raw.total_eq,
                                        avail_balance=raw.avail_balance,
                                        used_margin=raw.used_margin,
                                        used_pct=raw.used_pct,
                                        fallback_used=raw.fallback_used,
                                        fallback_reason=raw.fallback_reason,
                                        timestamp=raw.timestamp or now_iso(),
                                        extra=dict(raw.extra),
                                    )
                                by_system[s] = raw
                            else:
                                by_system[s] = self._static_fallback_result(
                                    s, f"handler_bad_return_type:{type(raw).__name__}",
                                    static_budgets.get(s, 0.0), account_mapping,
                                )
                        except Exception as inner:
                            by_system[s] = self._static_fallback_result(
                                s, f"handler_error:{inner}",
                                static_budgets.get(s, 0.0), account_mapping,
                            )
            except Exception as outer:
                for s in attached_systems:
                    if s not in by_system:
                        by_system[s] = self._static_fallback_result(
                            s, f"rule_execution_failed:{outer}",
                            static_budgets.get(s, 0.0), account_mapping,
                        )

        return self._aggregate(by_system)

    def _static_fallback_result(
        self,
        system: str,
        reason: str,
        static_budget: float,
        account_mapping: Dict[str, str],
    ) -> CapitalResult:
        account_str = account_mapping.get(system, "unknown")
        if account_str == "okx_live":
            at = AccountType.OKX_LIVE
        elif account_str == "okx_simulated":
            at = AccountType.OKX_SIMULATED
        elif account_str == "hyperliquid":
            at = AccountType.HYPERLIQUID
        elif account_str == "aster":
            at = AccountType.ASTER
        else:
            at = AccountType.UNKNOWN
        static_budget_f = float(static_budget or 0.0)
        return CapitalResult(
            system=system,
            account_type=at,
            mode=self._mode,
            total_eq=static_budget_f,
            avail_balance=static_budget_f,
            used_margin=0.0,
            used_pct=0.0,
            fallback_used=True,
            fallback_reason=reason,
            timestamp=now_iso(),
            extra={},
        )

    def _aggregate(self, by_system: Dict[str, CapitalResult]) -> CapitalSnapshot:
        total_eq = 0.0
        total_avail = 0.0
        total_used = 0.0
        any_fallback = False
        any_unavailable = False
        recommendations: Dict[str, str] = {}
        by_account: Dict[str, CapitalResult] = {}

        for s, r in by_system.items():
            total_eq += float(r.total_eq or 0.0)
            total_avail += float(r.avail_balance or 0.0)
            total_used += float(r.used_margin or 0.0)
            if r.fallback_used:
                any_fallback = True
                if r.fallback_reason and (
                    "unified_fetch_failed" in r.fallback_reason
                    or "system_data_missing" in r.fallback_reason
                    or "handler_error" in r.fallback_reason
                    or "rule_execution_failed" in r.fallback_reason
                ):
                    any_unavailable = True
                recommendations[s] = f"fallback:{r.fallback_reason}"
            pressure = calc_margin_pressure(r.used_pct)
            if pressure == "HIGH":
                recommendations.setdefault(s, "")
                recommendations[s] = (
                    (recommendations[s] + "; " if recommendations[s] else "")
                    + f"margin_pressure=HIGH({r.used_pct}%)"
                )
            # by_account：同一账户出现多个系统时，取 equity 最大者（Agent A/B/C 同账户 HL）
            account_key = r.account_type.value
            existing = by_account.get(account_key)
            if existing is None or (r.total_eq or 0.0) > (existing.total_eq or 0.0):
                by_account[account_key] = r

        overall_used_pct = 0.0
        if total_eq > 0:
            overall_used_pct = round(total_used * 100.0 / total_eq, 2)
        health = assess_health(
            overall_used_pct=overall_used_pct,
            any_system_fallback=any_fallback,
            any_system_unavailable=any_unavailable,
            thresholds=self._config.get("health_thresholds"),
        )

        return CapitalSnapshot(
            timestamp=now_iso(),
            mode=self._mode,
            by_system=by_system,
            total_equity=round(total_eq, 2),
            total_avail=round(total_avail, 2),
            total_used=round(total_used, 2),
            overall_used_pct=overall_used_pct,
            health=health,
            recommendations=recommendations,
            by_account=by_account,
            extra={
                "registry_rules_loaded": len(
                    self._registry.get_rules(RuleCategory.CAPITAL)
                ),
                "cache_ttl_sec": self._cache_ttl,
            },
        )


__all__ = ["CapitalControlComponent", "DEFAULT_RULES"]
