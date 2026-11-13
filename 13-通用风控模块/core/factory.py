"""风控门禁工厂 — 13 层唯一构造入口
=================================
所有外部模块（22 Gateway / 50 adapter / 脚本）必须通过本工厂获取门禁，
禁止直接 `PreTradeGate()`（空注册表 → check 恒 PASS → 风控空转）。

Fail-Closed 契约：
    - 配置文件缺失/损坏 → WARN 日志 + 回落代码默认值，仍注册全部默认规则
    - 规则注册异常 → 重试一次空配置；仍失败则抛 RuntimeError（调用方拒开仓）
    - 任何情况下都不会返回「零规则」门禁
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .pre_trade_gate import PreTradeGate
from .registry import RuleCategory, RuleRegistry

try:
    from ..rules.gate_rules import register_default_gate_rules
except ImportError:  # 13 目录直接进 sys.path 时（22/50 的隔离加载方式）
    from rules.gate_rules import register_default_gate_rules

logger = logging.getLogger("risk.factory")

RISK_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = RISK_DIR / "config" / "risk_trading.json"

# 与 rules/gate_rules.py 中的代码默认值保持一致。
# 注意：PreTradeGate 按「规则名」取配置（config[rule_name]），因此 gate 段必须是
# {rule_name: {...}} 的两级结构，而非扁平的参数表。
DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.0",
    "gate": {
        "daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.10},
        "leverage_cap_check": {"max_leverage": 10.0, "default_leverage": 1.0},
        "concurrent_position_limit": {"max_concurrent_positions": 5},
        "consecutive_losses_limit": {"max_consecutive_losses": 5},
        "blackout_period_check": {"blackout_windows": []},
        "confidence_minimum": {"confidence_hard_min": 0.2, "confidence_soft_min": 0.4},
        "drawdown_warning_degrade": {"drawdown_warn_1": 0.05, "drawdown_warn_2": 0.08},
    },
}


def load_risk_config(config_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """读取风控配置；任何异常都回落代码默认值（并记录 WARN）。"""
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"配置根节点必须是 object，实际为 {type(data).__name__}")
        return data
    except Exception as exc:  # noqa: BLE001 — 配置缺失不得阻断风控
        logger.warning("[risk.factory] 读取配置失败，回落默认值 path=%s err=%s", path, exc)
        return copy.deepcopy(DEFAULT_CONFIG)


def _build_registry(config: Dict[str, Any]) -> RuleRegistry:
    registry = RuleRegistry()
    try:
        register_default_gate_rules(registry, config)
    except Exception as exc:  # noqa: BLE001
        logger.error("[risk.factory] 规则注册失败，按空配置重试: %s", exc)
        registry = RuleRegistry()
        register_default_gate_rules(registry, {})

    enabled = registry.get_enabled_rules(RuleCategory.GATE)
    if not enabled:
        raise RuntimeError("风控门禁规则注册失败：启用规则数为 0（fail-closed）")
    return registry


def create_gate(
    config: Optional[Dict[str, Any]] = None,
    config_path: Optional[str | Path] = None,
) -> PreTradeGate:
    """构造带默认规则的门禁实例（外部唯一入口）。

    Args:
        config: 直接给定的配置（优先）；None 时从 config_path / 默认路径读取。
        config_path: 配置文件路径；None 时使用 13/config/risk_trading.json。

    Returns:
        PreTradeGate: registry 中至少含 7 条启用门禁规则。

    Raises:
        RuntimeError: 规则注册完全失败（调用方必须按 fail-closed 处理）。
    """
    cfg = config if isinstance(config, dict) else load_risk_config(config_path)
    registry = _build_registry(cfg)
    return PreTradeGate(registry=registry, config=cfg.get("gate", {}))


def create_risk_engine(
    config: Optional[Dict[str, Any]] = None,
    config_path: Optional[str | Path] = None,
):
    """构造已注册默认规则的三层风控引擎（门禁+仓位+离场）。"""
    from .engine import RiskEngine

    cfg = config if isinstance(config, dict) else load_risk_config(config_path)
    engine = RiskEngine(cfg)
    engine.register_default_rules()

    enabled = engine.registry.get_enabled_rules(RuleCategory.GATE)
    if not enabled:
        raise RuntimeError("风控引擎门禁规则注册失败：启用规则数为 0（fail-closed）")
    return engine
