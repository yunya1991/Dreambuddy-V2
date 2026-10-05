"""
DreamOS — 统一能力注册表数据模型

定义所有"能力提供者"（节点、subagent、交易所、子系统）和
"能力消费者"（策略、意图）共用的能力规格数据结构。

借鉴 Meta Muse Gadgets 设计：设备通过统一协议声明自身能力，
Agent 在运行时发现并匹配，不满足时优雅降级。

核心类:
    - CapabilitySpec        能力规格（提供者声明"能做什么"）
    - StrategyRequirement   策略需求（消费者声明"需要什么"）
    - MatchResult           匹配结果（需求 ∩ 提供）
    - CapabilityMatcher     匹配引擎
    - ProviderType          提供者类型枚举
    - CapabilityStatus      能力状态枚举
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# 枚举定义
# ============================================================

class ProviderType(str, Enum):
    """能力提供者类型"""
    NODE = "node"              # DreamOS 节点 (BaseNode)
    SUBAGENT = "subagent"      # DSH subagent
    EXCHANGE = "exchange"      # 交易所/账户
    SUBSYSTEM = "subsystem"    # 外部子系统（三屏/易经/V15）
    STRATEGY = "strategy"      # 策略本身（声明需求）


class CapabilityStatus(str, Enum):
    """能力状态"""
    AVAILABLE = "available"        # 可用
    DEGRADED = "degraded"          # 降级可用
    UNAVAILABLE = "unavailable"    # 不可用


# ============================================================
# 能力规格 — 提供者声明"能做什么"
# ============================================================

@dataclass
class CapabilitySpec:
    """能力规格

    所有能力提供者（节点、subagent、交易所、子系统）用同一结构声明能力。

    示例:
        CapabilitySpec(
            capability_id="trading.futures",
            category="trading",
            name="永续合约交易",
            description="USDT 本位永续合约",
            provider_id="OKX",
            provider_type=ProviderType.EXCHANGE,
            properties={"supported": True, "settlement": "usdt_swap"},
            status=CapabilityStatus.AVAILABLE,
        )
    """
    capability_id: str
    category: str                          # trading / data / analysis / execution / integration / governance
    name: str = ""
    description: str = ""
    provider_id: str = ""
    provider_type: ProviderType = ProviderType.NODE
    properties: Dict[str, Any] = field(default_factory=dict)
    requirements: List[str] = field(default_factory=list)   # 依赖的其他能力 ID
    status: CapabilityStatus = CapabilityStatus.AVAILABLE
    degraded_reason: str = ""
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "provider_id": self.provider_id,
            "provider_type": self.provider_type.value if isinstance(self.provider_type, ProviderType) else self.provider_type,
            "properties": dict(self.properties),
            "requirements": list(self.requirements),
            "status": self.status.value if isinstance(self.status, CapabilityStatus) else self.status,
            "degraded_reason": self.degraded_reason,
            "tags": list(self.tags),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CapabilitySpec":
        provider_type = d.get("provider_type", ProviderType.NODE)
        if isinstance(provider_type, str):
            provider_type = ProviderType(provider_type)
        status = d.get("status", CapabilityStatus.AVAILABLE)
        if isinstance(status, str):
            status = CapabilityStatus(status)
        return cls(
            capability_id=d["capability_id"],
            category=d.get("category", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            provider_id=d.get("provider_id", ""),
            provider_type=provider_type,
            properties=dict(d.get("properties", {})),
            requirements=list(d.get("requirements", [])),
            status=status,
            degraded_reason=d.get("degraded_reason", ""),
            tags=list(d.get("tags", [])),
            version=d.get("version", "1.0"),
        )


# ============================================================
# 策略需求 — 消费者声明"需要什么"
# ============================================================

@dataclass
class StrategyRequirement:
    """策略能力需求

    策略通过此结构声明运行所需的能力，供 CapabilityMatcher 做匹配。

    示例:
        StrategyRequirement(
            strategy_id="v15_martin",
            required_capabilities=["trading.futures", "trading.leverage"],
            preferred_capabilities=["analysis.macro"],
            excluded_capabilities=[],
            min_properties={"trading.leverage": {"max": 5}},
        )
    """
    strategy_id: str
    required_capabilities: List[str] = field(default_factory=list)
    preferred_capabilities: List[str] = field(default_factory=list)
    excluded_capabilities: List[str] = field(default_factory=list)
    min_properties: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "required_capabilities": list(self.required_capabilities),
            "preferred_capabilities": list(self.preferred_capabilities),
            "excluded_capabilities": list(self.excluded_capabilities),
            "min_properties": {k: dict(v) for k, v in self.min_properties.items()},
        }


# ============================================================
# 匹配结果
# ============================================================

@dataclass
class MatchResult:
    """能力匹配结果

    Attributes:
        is_fulfilled:        需求是否满足（required 全部满足且无冲突）
        missing_required:    缺失的必需能力 ID
        missing_preferred:   缺失的优先能力 ID
        conflicts:           冲突的能力 ID（excluded 但实际存在）
        degraded_suggestion: 降级建议文本（preferred 缺失时生成）
    """
    is_fulfilled: bool = False
    missing_required: List[str] = field(default_factory=list)
    missing_preferred: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    degraded_suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_fulfilled": self.is_fulfilled,
            "missing_required": list(self.missing_required),
            "missing_preferred": list(self.missing_preferred),
            "conflicts": list(self.conflicts),
            "degraded_suggestion": self.degraded_suggestion,
        }


# ============================================================
# 能力匹配引擎
# ============================================================

class CapabilityMatcher:
    """能力匹配引擎

    将策略需求 (StrategyRequirement) 与账户/交易所可用能力 (List[CapabilitySpec]) 做匹配，
    返回 MatchResult。纯规则/数据驱动，不调用 LLM。

    匹配规则:
        1. required_capabilities 全部在可用能力中 → 满足必需
        2. excluded_capabilities 任一出现在可用能力中 → 冲突
        3. min_properties 对 properties 数值字段做下限比较
        4. is_fulfilled = 必需满足 AND 无冲突 AND min_properties 全部满足
    """

    @staticmethod
    def match(requirement: StrategyRequirement,
              available: List[CapabilitySpec]) -> MatchResult:
        """执行能力匹配

        Args:
            requirement: 策略需求
            available:   当前可用的能力列表（交易所 + subagent + 子系统等）

        Returns:
            MatchResult
        """
        # 提取可用能力 ID 集合（仅 available 状态的能力才视为可用）
        available_ids = {
            cap.capability_id
            for cap in available
            if cap.status == CapabilityStatus.AVAILABLE
        }
        # 所有能力（含 degraded）用于冲突检测
        all_ids = {cap.capability_id for cap in available}

        # 1. 必需能力检查
        missing_required = [
            cap_id for cap_id in requirement.required_capabilities
            if cap_id not in available_ids
        ]

        # 2. 优先能力检查
        missing_preferred = [
            cap_id for cap_id in requirement.preferred_capabilities
            if cap_id not in available_ids
        ]

        # 3. 冲突能力检查（excluded 但实际存在）
        conflicts = [
            cap_id for cap_id in requirement.excluded_capabilities
            if cap_id in all_ids
        ]

        # 4. min_properties 下限校验
        prop_failures = []
        cap_props = {cap.capability_id: cap.properties for cap in available}
        for cap_id, min_vals in requirement.min_properties.items():
            props = cap_props.get(cap_id, {})
            for key, min_val in min_vals.items():
                actual = props.get(key)
                if actual is None:
                    prop_failures.append(f"{cap_id}.{key} 缺失")
                elif isinstance(actual, (int, float)) and isinstance(min_val, (int, float)):
                    if actual < min_val:
                        prop_failures.append(f"{cap_id}.{key}={actual} < {min_val}")
                elif isinstance(actual, list) and isinstance(min_val, (int, float)):
                    if not any(isinstance(v, (int, float)) and v >= min_val for v in actual):
                        prop_failures.append(f"{cap_id}.{key} 无 >= {min_val} 的值")

        # 5. 生成降级建议
        degraded_suggestion = ""
        if missing_preferred and not missing_required:
            parts = [f"缺少优先能力: {', '.join(missing_preferred)}"]
            if "analysis.macro" in missing_preferred:
                parts.append("建议降级为纯技术面策略，跳过宏观面分析")
            if "analysis.sentiment" in missing_preferred:
                parts.append("建议跳过情绪面，仅依赖技术指标")
            degraded_suggestion = "；".join(parts)
        elif missing_required:
            degraded_suggestion = f"必需能力缺失: {', '.join(missing_required)}，策略无法运行"

        # 6. 综合判定
        is_fulfilled = (
            len(missing_required) == 0
            and len(conflicts) == 0
            and len(prop_failures) == 0
        )

        if prop_failures:
            degraded_suggestion = (degraded_suggestion + "；" if degraded_suggestion else "") + \
                                  "属性不满足: " + "；".join(prop_failures)

        return MatchResult(
            is_fulfilled=is_fulfilled,
            missing_required=missing_required,
            missing_preferred=missing_preferred,
            conflicts=conflicts,
            degraded_suggestion=degraded_suggestion,
        )
