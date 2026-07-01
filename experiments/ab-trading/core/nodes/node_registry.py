#!/usr/bin/env python3
"""
节点注册表 (Node Registry)

位置: experiments/ab-trading/core/nodes/node_registry.py

设计原则:
- 与模块注册表(ModuleRegistry)对齐，粗-中-细三层结构
- 节点是模块的"执行实例"，一个模块可对应多个节点（不同配置）
- 支持从模块注册表自动生成节点注册
- 多维度索引（链/模块/标签/阶段等）

粗粒度: 链 (A/C/F/G/T)
中粒度: 模块 (module_id)
细粒度: 节点 (node_id) — 实际执行单元

节点类型:
- skill_node: 基于SKILL.md的执行节点
- api_node: 基于外部API的执行节点
- local_node: 基于本地规则的执行节点
- composite_node: 组合节点（包含多个子节点）
"""

import time
import threading
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field


# ============================================================
# 节点元数据
# ============================================================

@dataclass
class IOSchema:
    """输入输出Schema定义"""
    required_fields: List[str] = field(default_factory=list)
    optional_fields: List[str] = field(default_factory=list)
    field_types: Dict[str, str] = field(default_factory=dict)
    field_descriptions: Dict[str, str] = field(default_factory=dict)
    examples: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "field_types": self.field_types,
            "field_descriptions": self.field_descriptions,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "IOSchema":
        if not data:
            return cls()
        return cls(
            required_fields=data.get("required_fields", []),
            optional_fields=data.get("optional_fields", []),
            field_types=data.get("field_types", {}),
            field_descriptions=data.get("field_descriptions", {}),
            examples=data.get("examples", []),
        )


@dataclass
class NodeRetryPolicy:
    """节点重试策略"""
    enabled: bool = False
    max_retries: int = 3
    retry_on: List[str] = field(default_factory=lambda: ["timeout", "network_error"])
    backoff_strategy: str = "exponential"
    base_delay_ms: int = 100
    max_delay_ms: int = 10000

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "max_retries": self.max_retries,
            "retry_on": self.retry_on,
            "backoff_strategy": self.backoff_strategy,
            "base_delay_ms": self.base_delay_ms,
            "max_delay_ms": self.max_delay_ms,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "NodeRetryPolicy":
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            max_retries=data.get("max_retries", 3),
            retry_on=data.get("retry_on", []),
            backoff_strategy=data.get("backoff_strategy", "exponential"),
            base_delay_ms=data.get("base_delay_ms", 100),
            max_delay_ms=data.get("max_delay_ms", 10000),
        )


@dataclass
class NodeFallbackPolicy:
    """节点降级策略"""
    enabled: bool = False
    fallback_node_id: Optional[str] = None
    fallback_type: str = "local"
    fallback_reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "fallback_node_id": self.fallback_node_id,
            "fallback_type": self.fallback_type,
            "fallback_reason": self.fallback_reason,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "NodeFallbackPolicy":
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            fallback_node_id=data.get("fallback_node_id"),
            fallback_type=data.get("fallback_type", "local"),
            fallback_reason=data.get("fallback_reason", ""),
        )


@dataclass
class NodeInfo:
    """节点信息（执行单元元数据）

    细粒度：实际可执行的最小单元
    对应中粒度的 module_id，一个模块可生成多个节点变体
    """
    node_id: str
    name: str
    description: str = ""
    version: str = "1.0"

    # 所属关系（粗-中-细）
    chain: str = ""
    module_id: str = ""
    category: str = ""

    # 节点类型
    node_type: str = "local_node"  # skill_node / api_node / local_node / composite_node

    # 执行配置
    timeout_ms: int = 30000
    estimated_tokens: int = 0
    estimated_latency_ms: int = 1000
    confidence_range: List[float] = field(default_factory=lambda: [0.0, 100.0])

    # 输入输出Schema
    input_schema: IOSchema = field(default_factory=IOSchema)
    output_schema: IOSchema = field(default_factory=IOSchema)

    # 策略
    retry_policy: NodeRetryPolicy = field(default_factory=NodeRetryPolicy)
    fallback_policy: NodeFallbackPolicy = field(default_factory=NodeFallbackPolicy)

    # 适用范围
    applicable_stages: List[str] = field(default_factory=list)
    applicable_intents: List[str] = field(default_factory=list)
    market_conditions: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # 执行器（本地节点直接绑定函数，远程节点通过适配器调用）
    handler: Optional[Callable] = None
    handler_name: str = ""

    # 状态
    status: str = "active"
    deprecated: bool = False

    # 元数据
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "chain": self.chain,
            "module_id": self.module_id,
            "category": self.category,
            "node_type": self.node_type,
            "timeout_ms": self.timeout_ms,
            "estimated_tokens": self.estimated_tokens,
            "estimated_latency_ms": self.estimated_latency_ms,
            "confidence_range": self.confidence_range,
            "input_schema": self.input_schema.to_dict(),
            "output_schema": self.output_schema.to_dict(),
            "retry_policy": self.retry_policy.to_dict(),
            "fallback_policy": self.fallback_policy.to_dict(),
            "applicable_stages": self.applicable_stages,
            "applicable_intents": self.applicable_intents,
            "market_conditions": self.market_conditions,
            "tags": self.tags,
            "handler_name": self.handler_name,
            "status": self.status,
            "deprecated": self.deprecated,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "NodeInfo":
        return cls(
            node_id=data["node_id"],
            name=data.get("name", data["node_id"]),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            chain=data.get("chain", ""),
            module_id=data.get("module_id", ""),
            category=data.get("category", ""),
            node_type=data.get("node_type", "local_node"),
            timeout_ms=data.get("timeout_ms", 30000),
            estimated_tokens=data.get("estimated_tokens", 0),
            estimated_latency_ms=data.get("estimated_latency_ms", 1000),
            confidence_range=data.get("confidence_range", [0.0, 100.0]),
            input_schema=IOSchema.from_dict(data.get("input_schema")),
            output_schema=IOSchema.from_dict(data.get("output_schema")),
            retry_policy=NodeRetryPolicy.from_dict(data.get("retry_policy")),
            fallback_policy=NodeFallbackPolicy.from_dict(data.get("fallback_policy")),
            applicable_stages=data.get("applicable_stages", []),
            applicable_intents=data.get("applicable_intents", []),
            market_conditions=data.get("market_conditions", []),
            tags=data.get("tags", []),
            handler_name=data.get("handler_name", ""),
            status=data.get("status", "active"),
            deprecated=data.get("deprecated", False),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            extra=data.get("extra", {}),
        )


# ============================================================
# 节点注册表
# ============================================================

class NodeRegistry:
    """
    节点注册表

    管理所有可执行节点的元数据，支持：
    - 动态注册 / 注销
    - 多维度索引查询
    - 从模块注册表自动生成
    - 与适配器框架对接
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._nodes: Dict[str, NodeInfo] = {}

        # 索引
        self._by_chain: Dict[str, Set[str]] = {}
        self._by_module: Dict[str, Set[str]] = {}
        self._by_category: Dict[str, Set[str]] = {}
        self._by_type: Dict[str, Set[str]] = {}
        self._by_tag: Dict[str, Set[str]] = {}
        self._by_stage: Dict[str, Set[str]] = {}

        # 执行统计
        self._call_count: Dict[str, int] = {}
        self._total_latency: Dict[str, float] = {}

    # ============================================================
    # 注册 / 注销
    # ============================================================

    def register(self, node: NodeInfo, handler: Optional[Callable] = None) -> bool:
        """注册节点

        Args:
            node: 节点信息
            handler: 执行函数（可选，本地节点使用）

        Returns:
            bool - 是否成功
        """
        with self._lock:
            if node.node_id in self._nodes and not node.deprecated:
                # 已存在，更新
                existing = self._nodes[node.node_id]
                node.created_at = existing.created_at
                node.updated_at = time.time()
            else:
                node.created_at = time.time()
                node.updated_at = time.time()

            if handler:
                node.handler = handler
                node.handler_name = getattr(handler, '__name__', str(handler))

            self._nodes[node.node_id] = node
            self._index_node(node)
            return True

    def unregister(self, node_id: str) -> bool:
        """注销节点"""
        with self._lock:
            if node_id not in self._nodes:
                return False
            node = self._nodes[node_id]
            node.status = "inactive"
            node.deprecated = True
            node.updated_at = time.time()
            self._rebuild_indexes()
            return True

    def remove(self, node_id: str) -> bool:
        """彻底移除节点（慎用）"""
        with self._lock:
            if node_id not in self._nodes:
                return False
            del self._nodes[node_id]
            self._rebuild_indexes()
            return True

    # ============================================================
    # 查询
    # ============================================================

    def get(self, node_id: str) -> Optional[NodeInfo]:
        """获取节点信息"""
        with self._lock:
            return self._nodes.get(node_id)

    def has(self, node_id: str) -> bool:
        """节点是否存在且活跃"""
        with self._lock:
            node = self._nodes.get(node_id)
            return node is not None and node.status == "active" and not node.deprecated

    def get_handler(self, node_id: str) -> Optional[Callable]:
        """获取节点执行函数"""
        node = self.get(node_id)
        if node and node.handler:
            return node.handler
        return None

    def get_all(self, include_deprecated: bool = False) -> List[NodeInfo]:
        """获取所有节点"""
        with self._lock:
            if include_deprecated:
                return list(self._nodes.values())
            return [n for n in self._nodes.values() if not n.deprecated]

    def count(self, include_deprecated: bool = False) -> int:
        """节点数量"""
        with self._lock:
            if include_deprecated:
                return len(self._nodes)
            return sum(1 for n in self._nodes.values() if not n.deprecated)

    def query(self,
              chain: Optional[str] = None,
              module_id: Optional[str] = None,
              category: Optional[str] = None,
              node_type: Optional[str] = None,
              tag: Optional[str] = None,
              stage: Optional[str] = None,
              active_only: bool = True) -> List[NodeInfo]:
        """
        多条件查询节点

        Args:
            chain: 所属链 (A/C/F/G/T)
            module_id: 所属模块ID
            category: 分类
            node_type: 节点类型
            tag: 标签
            stage: 适用阶段
            active_only: 只返回活跃节点

        Returns:
            匹配的节点列表
        """
        with self._lock:
            candidates = set(self._nodes.keys())

            if chain and chain in self._by_chain:
                candidates &= self._by_chain[chain]

            if module_id and module_id in self._by_module:
                candidates &= self._by_module[module_id]

            if category and category in self._by_category:
                candidates &= self._by_category[category]

            if node_type and node_type in self._by_type:
                candidates &= self._by_type[node_type]

            if tag and tag in self._by_tag:
                candidates &= self._by_tag[tag]

            if stage and stage in self._by_stage:
                candidates &= self._by_stage[stage]

            results = []
            for nid in candidates:
                node = self._nodes[nid]
                if active_only and (node.status != "active" or node.deprecated):
                    continue
                results.append(node)

            return results

    # ============================================================
    # 从模块注册表生成节点
    # ============================================================

    def generate_from_module_registry(self, module_registry: Any) -> int:
        """
        从模块注册表自动生成节点注册

        一个模块至少生成一个节点，根据配置可生成多个变体

        Args:
            module_registry: 模块注册表实例

        Returns:
            int - 新注册的节点数量
        """
        count = 0
        modules = module_registry.get_all()

        for mod in modules:
            # 每个模块生成一个主节点
            node = self._module_to_node(mod)
            if self.register(node):
                count += 1

        return count

    def _module_to_node(self, mod: Any) -> NodeInfo:
        """将模块信息转换为节点信息"""
        adapter_type = mod.adapter.get('type', 'local')
        node_type_map = {
            'skill': 'skill_node',
            'api': 'api_node',
            'local': 'local_node',
        }
        node_type = node_type_map.get(adapter_type, 'local_node')

        node = NodeInfo(
            node_id=mod.id,
            name=mod.name,
            description=mod.description,
            version=mod.version,
            chain=mod.chain,
            module_id=mod.id,
            category=mod.category,
            node_type=node_type,
            timeout_ms=mod.estimated_latency_ms * 3 or 30000,
            estimated_tokens=mod.estimated_tokens,
            estimated_latency_ms=mod.estimated_latency_ms,
            confidence_range=mod.confidence_range,
            applicable_stages=mod.applicable_stages,
            applicable_intents=mod.applicable_intents,
            market_conditions=mod.market_conditions,
            tags=mod.tags,
            retry_policy=NodeRetryPolicy(
                enabled=mod.fallback.get('enabled', False),
                max_retries=2,
            ),
            fallback_policy=NodeFallbackPolicy(
                enabled=mod.fallback.get('enabled', False),
                fallback_node_id=mod.fallback.get('fallback_module'),
                fallback_reason=mod.fallback.get('fallback_reason', ''),
            ),
        )

        return node

    # ============================================================
    # 统计
    # ============================================================

    def record_call(self, node_id: str, latency_ms: float):
        """记录一次调用"""
        with self._lock:
            self._call_count[node_id] = self._call_count.get(node_id, 0) + 1
            self._total_latency[node_id] = self._total_latency.get(node_id, 0) + latency_ms

    def get_node_stats(self, node_id: str) -> Dict:
        """获取节点统计"""
        with self._lock:
            count = self._call_count.get(node_id, 0)
            total = self._total_latency.get(node_id, 0)
            return {
                "call_count": count,
                "total_latency_ms": total,
                "avg_latency_ms": total / count if count > 0 else 0,
            }

    def get_stats(self) -> Dict:
        """获取整体统计"""
        with self._lock:
            by_chain_stats = {}
            for chain, node_set in self._by_chain.items():
                by_chain_stats[chain] = len(node_set)

            return {
                "total": self.count(),
                "by_chain": by_chain_stats,
                "by_type": {k: len(v) for k, v in self._by_type.items()},
                "by_module_count": len(self._by_module),
                "total_calls": sum(self._call_count.values()),
            }

    # ============================================================
    # 内部方法
    # ============================================================

    def _index_node(self, node: NodeInfo):
        """添加节点到索引（调用方需持有锁）"""
        self._add_to_index(self._by_chain, node.chain, node.node_id)
        self._add_to_index(self._by_module, node.module_id, node.node_id)
        self._add_to_index(self._by_category, node.category, node.node_id)
        self._add_to_index(self._by_type, node.node_type, node.node_id)
        for tag in node.tags:
            self._add_to_index(self._by_tag, tag, node.node_id)
        for stage in node.applicable_stages:
            self._add_to_index(self._by_stage, stage, node.node_id)

    def _add_to_index(self, index: Dict, key: str, value: str):
        if not key:
            return
        if key not in index:
            index[key] = set()
        index[key].add(value)

    def _rebuild_indexes(self):
        """重建所有索引（调用方需持有锁）"""
        self._by_chain.clear()
        self._by_module.clear()
        self._by_category.clear()
        self._by_type.clear()
        self._by_tag.clear()
        self._by_stage.clear()

        for node in self._nodes.values():
            if not node.deprecated:
                self._index_node(node)


# ============================================================
# 全局注册表单例
# ============================================================

_global_node_registry: Optional[NodeRegistry] = None
_global_node_lock = threading.Lock()


def get_node_registry() -> NodeRegistry:
    """获取全局节点注册表单例"""
    global _global_node_registry
    if _global_node_registry is None:
        with _global_node_lock:
            if _global_node_registry is None:
                _global_node_registry = NodeRegistry()
    return _global_node_registry


def register_node(node: NodeInfo, handler: Optional[Callable] = None) -> bool:
    """便捷函数：注册节点"""
    return get_node_registry().register(node, handler)


def get_node(node_id: str) -> Optional[NodeInfo]:
    """便捷函数：获取节点"""
    return get_node_registry().get(node_id)


def get_node_handler(node_id: str) -> Optional[Callable]:
    """便捷函数：获取节点处理器"""
    return get_node_registry().get_handler(node_id)


__all__ = [
    "IOSchema",
    "NodeRetryPolicy",
    "NodeFallbackPolicy",
    "NodeInfo",
    "NodeRegistry",
    "get_node_registry",
    "register_node",
    "get_node",
    "get_node_handler",
]
