#!/usr/bin/env python3
"""D5: Subagent 注册到 NodeRegistry + Pydantic schema

将 8 个 DSH subagent 显式注册到 DreamOS NodeRegistry,
提供统一的 Node 接口适配器 + 输出 schema 定义。

参考 AI-Hedge-Fund ANALYST_CONFIG 18-agent 注册表模式。

M3: 百炼与 DSH Subagent 接入路径 (v0.3 增量)
- 提供 LLM provider 钩子: set_llm_fn_provider() 全局注入
- create_subagent_nodes(llm_fn=None) 可选注入, 跳过 risk_agent (HC-3 纯算法)
- register_subagents_with_bailian() 便捷函数: 从 dreamos QwenLLMClient 注入
- HC-1 FAIL-OPEN: 无 LLM key/调用失败 → 走规则降级, 不破坏现有测试
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from subagent_types import SubagentOutput


# LLM 函数类型: (prompt: str) -> str
LLMFn = Callable[[str], str]


# ============================================================
# D5.1: Subagent 输出 Schema (Pydantic 风格类型定义)
# ============================================================

# 8 个 subagent 的元数据清单 (注册表 SSoT)
SUBAGENT_REGISTRY_CONFIG: List[Dict[str, Any]] = [
    {
        "node_id": "DSH_TECHNICAL",
        "name": "技术面 Subagent",
        "module": "technical",
        "capability_id": "analysis.technical",
        "chain": "C",
        "tags": ["dsh", "technical", "indicators"],
        "description": "C1/C2/C3 技术指标 → EMA排列/RSI14/MACD 信号 + line 图表",
        "data_source": "technical_agent",
    },
    {
        "node_id": "DSH_SENTIMENT",
        "name": "情绪面 Subagent",
        "module": "sentiment",
        "capability_id": "analysis.sentiment",
        "chain": "C",
        "tags": ["dsh", "sentiment", "fgi"],
        "description": "F1 情绪指标 → 新闻情绪/FGI 信号 + gauge+line 图表",
        "data_source": "sentiment_agent",
    },
    {
        "node_id": "DSH_MACRO",
        "name": "宏观面 Subagent",
        "module": "macro",
        "capability_id": "analysis.macro",
        "chain": "C",
        "tags": ["dsh", "macro", "fundamental"],
        "description": "宏观经济指标 → 利率/通胀/GDP 信号",
        "data_source": "macro_agent",
    },
    {
        "node_id": "DSH_FLOW",
        "name": "资金面 Subagent",
        "module": "flow",
        "capability_id": "analysis.flow",
        "chain": "C",
        "tags": ["dsh", "flow", "capital"],
        "description": "资金流向指标 → 主力资金/北向资金 信号",
        "data_source": "flow_agent",
    },
    {
        "node_id": "DSH_VALUATION",
        "name": "估值面 Subagent",
        "module": "valuation",
        "capability_id": "analysis.valuation",
        "chain": "C",
        "tags": ["dsh", "valuation", "fundamental"],
        "description": "估值指标 → PE/PB/DCF 信号",
        "data_source": "valuation_agent",
    },
    {
        "node_id": "DSH_ONCHAIN",
        "name": "链上面 Subagent",
        "module": "onchain",
        "capability_id": "analysis.onchain",
        "chain": "C",
        "tags": ["dsh", "onchain", "crypto"],
        "description": "链上数据 → 活跃地址/交易所余额 信号",
        "data_source": "onchain_agent",
    },
    {
        "node_id": "DSH_RISK",
        "name": "风险面 Subagent",
        "module": "risk",
        "capability_id": "analysis.risk",
        "chain": "C",
        "tags": ["dsh", "risk", "var"],
        "description": "风险指标 → VaR95/VaR99/压力损失 信号 + heatmap 图表 (纯算法, 不调 LLM)",
        "data_source": "risk_agent",
    },
    {
        "node_id": "DSH_PORTFOLIO",
        "name": "组合面 Subagent",
        "module": "portfolio",
        "capability_id": "analysis.portfolio",
        "chain": "C",
        "tags": ["dsh", "portfolio", "rebalance"],
        "description": "仓位/再平衡指标 → 漂移度/总仓位 信号 + pie+bar 图表 (LLM 综合)",
        "data_source": "portfolio_agent",
    },
]


def get_subagent_config(module: str) -> Optional[Dict[str, Any]]:
    """按 module 名获取 subagent 配置"""
    for cfg in SUBAGENT_REGISTRY_CONFIG:
        if cfg["module"] == module:
            return cfg
    return None


# ============================================================
# D5.2: SubagentNode 适配器 (Node 接口 → subagent.execute)
# ============================================================

class SubagentNode:
    """Subagent → Node 接口适配器

    将 DSH subagent 包装为 DreamOS Node, 注册到 NodeRegistry。
    execute() 从 state 提取 node_output, 调用 subagent.execute,
    返回 NodeResult (含 SubagentOutput 序列化)。
    """

    def __init__(self, config: Dict[str, Any], subagent: Any):
        self.node_id = config["node_id"]
        self.name = config["name"]
        self.chain = config["chain"]
        self.tags = config.get("tags", [])
        self.description = config.get("description", "")
        self.module = config["module"]
        self.capability_id = config.get("capability_id", f"analysis.{config['module']}")
        self._subagent = subagent
        self._capabilities: Optional[List] = None

    @property
    def capabilities(self) -> List:
        """声明该 subagent 的细粒度能力（供 NodeRegistry 查询）

        延迟创建并缓存，避免启动时导入 dreamos.shared.capability 失败（FAIL-OPEN）。
        """
        if self._capabilities is None:
            try:
                from dreamos.shared.capability import (
                    CapabilitySpec, ProviderType, CapabilityStatus,
                )
                self._capabilities = [CapabilitySpec(
                    capability_id=self.capability_id,
                    category="analysis",
                    name=self.name,
                    description=self.description,
                    provider_id=self.node_id,
                    provider_type=ProviderType.SUBAGENT,
                    status=CapabilityStatus.AVAILABLE,
                    tags=list(self.tags),
                )]
            except Exception:  # noqa: BLE001 FAIL-OPEN: 导入失败返回空列表
                self._capabilities = []
        return self._capabilities

    def execute(self, node_output: dict) -> SubagentOutput:
        """执行 subagent (适配 Node 接口)

        Args:
            node_output: 节点输出 dict (含 indicators/rationale/direction/confidence)
        Returns:
            SubagentOutput
        """
        return self._subagent.execute(node_output)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "chain": self.chain,
            "tags": self.tags,
            "description": self.description,
            "module": self.module,
        }


# ============================================================
# D5.3: 注册函数 (M3: 支持 LLM 注入)
# ============================================================

# 全局 LLM provider 钩子: 返回 LLMFn 或 None (FAIL-OPEN)
# 外部 (IPC server / dreamos 启动) 通过 set_llm_fn_provider() 注入
_llm_fn_provider: Optional[Callable[[], Optional[LLMFn]]] = None


def set_llm_fn_provider(provider: Optional[Callable[[], Optional[LLMFn]]]) -> None:
    """注入全局 LLM provider (用于 M3 百炼接入)

    provider 是无参 callable, 返回 LLMFn 或 None.
    设计为延迟解析, 避免无 API key 时启动失败.
    """
    global _llm_fn_provider
    _llm_fn_provider = provider


def get_llm_fn_provider() -> Optional[Callable[[], Optional[LLMFn]]]:
    """获取当前 LLM provider"""
    return _llm_fn_provider


def _resolve_llm_fn(explicit: Optional[LLMFn] = None) -> Optional[LLMFn]:
    """解析当前 LLM fn (优先显式参数, 其次全局 provider, 最后 None)"""
    if explicit is not None:
        return explicit
    if _llm_fn_provider is not None:
        try:
            return _llm_fn_provider()
        except Exception:  # noqa: BLE001 FAIL-OPEN
            return None
    return None


def make_bailian_llm_fn() -> Optional[LLMFn]:
    """从 dreamos QwenLLMClient 构造百炼 LLM fn

    HC-10 容错: 延迟导入 dreamos, 无 QWEN_API_KEY 时返回 None.
    包装为 (prompt: str) -> str 接口, 异常时返回空串 (FAIL-OPEN).
    """
    try:
        from dreamos.shared.llm_client import get_default_client, make_messages, LLMResponse  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    try:
        client = get_default_client()
    except Exception:  # noqa: BLE001
        return None

    # NoOpLLMClient 兜底 — 不注入, 走规则降级更可预测
    if type(client).__name__ == "NoOpLLMClient":
        return None

    def _fn(prompt: str) -> str:
        try:
            msgs = make_messages(user=prompt)
            resp: LLMResponse = client.chat(msgs)
            return resp.content or ""
        except Exception:  # noqa: BLE001 FAIL-OPEN
            return ""

    return _fn


# 缓存的 handler LLM fn (避免每次 IPC 调用都重新构造)
_cached_handler_llm_fn: Optional[LLMFn] = None
_cached_handler_llm_fn_resolved: bool = False


def get_handler_llm_fn() -> Optional[LLMFn]:
    """获取 handler 层共享的百炼 LLM fn (缓存, M3 IPC 闭环)

    IPC handler (handle_technical_agent 等) 调用此函数获取共享 LLM fn.
    首次调用解析, 后续缓存; 无 API key 时返回 None (FAIL-OPEN 走规则降级).
    """
    global _cached_handler_llm_fn, _cached_handler_llm_fn_resolved
    if not _cached_handler_llm_fn_resolved:
        _cached_handler_llm_fn = make_bailian_llm_fn()
        _cached_handler_llm_fn_resolved = True
    return _cached_handler_llm_fn


def reset_handler_llm_fn_cache() -> None:
    """重置缓存 (测试用)"""
    global _cached_handler_llm_fn, _cached_handler_llm_fn_resolved
    _cached_handler_llm_fn = None
    _cached_handler_llm_fn_resolved = False


def create_subagent_nodes(llm_fn: Optional[LLMFn] = None) -> List[SubagentNode]:
    """创建 8 个 SubagentNode 实例 (延迟导入 subagent)

    Args:
        llm_fn: 可选 LLM 函数注入 (M3 百炼接入).
            None 时尝试全局 provider, 仍 None 则 FAIL-OPEN 走规则降级.
            risk_agent 始终跳过 (HC-3: 风险面纯算法, 不调 LLM).
    """
    resolved_llm = _resolve_llm_fn(llm_fn)
    nodes: List[SubagentNode] = []
    for cfg in SUBAGENT_REGISTRY_CONFIG:
        module_name = cfg["data_source"]
        try:
            # 延迟导入避免循环依赖
            mod = __import__(module_name)
            agent_cls = getattr(mod, _agent_class_name(cfg["module"]))
            # HC-3: risk_agent 纯算法, 不注入 LLM
            if cfg["module"] == "risk":
                agent = agent_cls()
            else:
                agent = agent_cls(llm_fn=resolved_llm) if resolved_llm is not None else agent_cls()
            nodes.append(SubagentNode(cfg, agent))
        except Exception:  # noqa: BLE001 FAIL-OPEN: 注册失败不阻断
            pass
    return nodes


def _agent_class_name(module: str) -> str:
    """module 名 → Agent 类名"""
    return f"{module.capitalize()}Agent"


def register_subagents(registry: Optional[Any] = None,
                       llm_fn: Optional[LLMFn] = None) -> int:
    """将 8 个 subagent 注册到 NodeRegistry

    Args:
        registry: NodeRegistry 实例, None 时用全局默认注册表
        llm_fn: 可选 LLM 函数注入 (M3)

    Returns:
        成功注册的节点数
    """
    if registry is None:
        try:
            from dreamos.registry.node_registry import get_default_registry
            registry = get_default_registry()
        except Exception:  # noqa: BLE001
            return 0

    nodes = create_subagent_nodes(llm_fn=llm_fn)
    count = 0
    for node in nodes:
        try:
            registry.register(node)
            count += 1
        except Exception:  # noqa: BLE001 已存在则跳过
            pass
    return count


def register_subagents_with_bailian(registry: Optional[Any] = None) -> int:
    """M3 便捷函数: 用百炼 (dreamos QwenLLMClient) 注入并注册

    无 API key / dreamos 不可用时降级为 None, 走规则降级.
    """
    llm_fn = make_bailian_llm_fn()
    if llm_fn is None:
        # 仍注册但走 FAIL-OPEN
        return register_subagents(registry=registry, llm_fn=None)
    return register_subagents(registry=registry, llm_fn=llm_fn)


def list_registered_subagents(registry: Optional[Any] = None) -> List[Dict[str, Any]]:
    """列出已注册的 subagent 节点"""
    if registry is None:
        try:
            from dreamos.registry.node_registry import get_default_registry
            registry = get_default_registry()
        except Exception:  # noqa: BLE001
            return []

    try:
        nodes = registry.list_nodes(tag="dsh")
        return [n.to_dict() if hasattr(n, "to_dict") else {"node_id": getattr(n, "node_id", "?")}
                for n in nodes]
    except Exception:  # noqa: BLE001
        return []
