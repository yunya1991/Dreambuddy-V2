"""
Dreambuddy OS — Node 基类实现

提供 Node 接口的具体实现，子类只需实现 execute() 方法。

设计:
    - Node (ABC)        在 shared/interfaces.py — 纯接口
    - BaseNode          在本文件 — 带常用默认行为的基类
    - FunctionNode      在 adapters/function_adapter.py — 包装函数
    - 具体节点          在 os-nodes/ — A0/A1/... 业务节点

BaseNode 额外提供:
    - 自动计时（latency_ms 自动填充）
    - 自动错误处理（捕获异常转为 FAILED NodeResult）
    - 可选 LLM 客户端注入
    - 配置注入
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.interfaces import Node
from dreamos.shared.llm_client import LLMClient, get_default_client
from dreamos.shared.utils import Timer
from dreamos.shared.errors import ErrorCode
from dreamos.shared.capability import CapabilitySpec, ProviderType, CapabilityStatus


class BaseNode(Node):
    """节点基类 — 带常用默认行为

    子类只需实现 execute_core()，BaseNode 会:
        1. 自动计时
        2. 自动捕获异常转为 NodeResult
        3. 调用 validate() 做输入校验
        4. 失败时调用 fallback()

    用法:
        class A0Node(BaseNode):
            node_id = "A0"
            name = "矛盾论"
            chain = "A"

            def execute_core(self, state: State) -> NodeResult:
                # 业务逻辑
                return NodeResult(node_id="A0", confidence=0.7, direction="LONG")
    """

    # 元信息（子类重写）
    node_id: str = ""
    name: str = ""
    description: str = ""
    chain: str = ""
    tags: list = []
    required_capabilities: list = []  # 执行前必须可用的能力 ID 列表

    def __init__(self, llm: Optional[LLMClient] = None, config: Optional[Dict[str, Any]] = None):
        self._llm = llm
        self._config = config or {}

    @property
    def llm(self) -> LLMClient:
        """LLM 客户端（延迟初始化）"""
        if self._llm is None:
            self._llm = get_default_client()
        return self._llm

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    # ── 能力声明（统一能力注册表）────────────────────────

    @property
    def capabilities(self) -> list:
        """节点能力规格列表

        优先级:
            1. 实例显式设置的 _explicit_capabilities（通过 setter）
            2. 子类在类属性中显式声明的 capabilities 列表（会 shadow 本 property）
            3. 从 chain/tags 自动推断（结果缓存在 _inferred_capabilities，确保状态可更新）

        注: 若子类定义了 `capabilities = [...]` 类属性，会直接覆盖本 property，
        返回该列表；本 property 仅在子类未声明时被调用，走推断逻辑。
        """
        explicit = getattr(self, "_explicit_capabilities", None)
        if explicit:
            return explicit
        # 子类显式声明的类属性会 shadow 此 property，走到这里说明未声明 → 推断
        # 缓存推断结果，确保 update_node_capability_status 修改的对象可被再次读取
        inferred = getattr(self, "_inferred_capabilities", None)
        if inferred is None:
            inferred = self.infer_capabilities()
            self._inferred_capabilities = inferred
        return inferred

    @capabilities.setter
    def capabilities(self, value):
        self._explicit_capabilities = value

    def infer_capabilities(self) -> list:
        """从 chain / tags 自动推断节点能力（向后兼容）

        未显式声明 capabilities 的现有节点通过此方法获得基础能力描述。
        """
        caps = []
        chain = getattr(self, "chain", "") or ""
        tags = getattr(self, "tags", []) or []
        node_id = getattr(self, "node_id", "")

        # 按 chain 推断核心能力
        chain_map = {
            "A": ("analysis.reasoning", "矛盾论/策略设计/辩证分析"),
            "C": ("analysis.technical", "技术指标分析"),
            "F": ("analysis.fundamental", "基本面分析"),
            "G": ("governance", "治理/审批"),
            "T": ("execution.trade", "交易执行"),
            "I": ("analysis.intelligence", "情报监控"),
        }
        if chain in chain_map:
            cap_id, desc = chain_map[chain]
            caps.append(CapabilitySpec(
                capability_id=cap_id,
                category=cap_id.split(".")[0],
                name=getattr(self, "name", "") or cap_id,
                description=desc,
                provider_id=node_id,
                provider_type=ProviderType.NODE,
                status=CapabilityStatus.AVAILABLE,
                tags=[chain] if chain else [],
            ))

        # 按 tags 推断附加能力
        if "external" in tags:
            caps.append(CapabilitySpec(
                capability_id="integration.subsystem",
                category="integration",
                name="外部子系统集成",
                description="封装外部子系统（三屏/易经/V15 等）",
                provider_id=node_id,
                provider_type=ProviderType.SUBSYSTEM,
                status=CapabilityStatus.AVAILABLE,
            ))
        if "dsh" in tags:
            module = next((t for t in tags if t not in ("dsh", "external")), "")
            caps.append(CapabilitySpec(
                capability_id=f"analysis.{module}" if module else "analysis.dsh",
                category="analysis",
                name=f"DSH {module} subagent" if module else "DSH subagent",
                provider_id=node_id,
                provider_type=ProviderType.SUBAGENT,
                status=CapabilityStatus.AVAILABLE,
            ))

        # 兜底：至少一条
        if not caps:
            caps.append(CapabilitySpec(
                capability_id=f"node.{node_id or 'unknown'}",
                category="node",
                name=getattr(self, "name", "") or node_id or "Node",
                provider_id=node_id,
                provider_type=ProviderType.NODE,
                status=CapabilityStatus.AVAILABLE,
            ))
        return caps

    # ── 子类实现这个方法 ────────────────────────────────

    def execute_core(self, state: State) -> NodeResult:
        """子类实现的核心执行逻辑（不包含错误处理和计时）

        默认返回一个 SUCCESS 结果。
        """
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=0.0,
            error=f"{self.node_id} 未实现 execute_core()",
        )

    # ── 模板方法（不要重写） ────────────────────────────

    def execute(self, state: State) -> NodeResult:
        """执行入口（模板方法，不要重写）

        流程:
            1. validate(state) → 校验失败返回 FAILED
            2. execute_core(state) → 自动计时
            3. 异常 → 标记 FAILED，调用 fallback
            4. F 链信号平滑 — EWMA + MAD 异常过滤（仅 F 链节点）
        """
        # 输入校验
        err = self.validate(state)
        if err:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                error_code=ErrorCode.DATA_001,
                error=f"输入校验失败: {err}",
                confidence=0.0,
            )

        # 优雅降级 — 检查 required_capabilities 是否可用
        missing = self._check_capabilities()
        if missing:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                direction="HOLD",
                confidence=0.0,
                warnings=[f"依赖能力不可用，降级执行: {', '.join(missing)}"],
            )

        # 执行 + 计时
        timer = Timer(self.node_id)
        try:
            with timer:
                result = self.execute_core(state)
        except Exception as e:
            # 异常 → 尝试降级
            try:
                result = self.fallback(state)
            except Exception as fallback_err:
                result = NodeResult(
                    node_id=self.node_id,
                    status=NodeStatus.FAILED,
                    error_code=ErrorCode.EXEC_002,
                    error=f"执行异常: {e}; 降级也失败: {fallback_err}",
                    confidence=0.0,
                )

        # 填充计时
        if result.latency_ms == 0:
            result.latency_ms = timer.elapsed_ms
        result.node_id = result.node_id or self.node_id

        # F 链信号平滑 — EWMA + MAD 异常过滤
        if getattr(self, "chain", "") == "F" and result.status.value == "SUCCESS":
            self._smooth_f_signal(result)

        # 能力状态同步 — 根据执行结果更新 capability status
        self._sync_capability_status(result)

        return result

    def _sync_capability_status(self, result: NodeResult) -> None:
        """根据执行结果同步节点能力状态

        将 NodeResult.status 映射为 CapabilityStatus:
            SUCCESS   → AVAILABLE
            DEGRADED  → DEGRADED
            FAILED    → UNAVAILABLE

        直接修改 node.capabilities 中缓存的 CapabilitySpec 对象状态，
        NodeRegistry.get_node_capabilities() 读取时即可看到最新状态。
        """
        try:
            from dreamos.shared.capability import CapabilityStatus
        except Exception:  # noqa: BLE001
            return

        status_map = {
            NodeStatus.SUCCESS: CapabilityStatus.AVAILABLE,
            NodeStatus.DEGRADED: CapabilityStatus.DEGRADED,
            NodeStatus.FAILED: CapabilityStatus.UNAVAILABLE,
        }
        target = status_map.get(result.status)
        if target is None:
            return

        caps = self.capabilities
        for cap in caps:
            if hasattr(cap, "status"):
                cap.status = target

    def _check_capabilities(self) -> Optional[List[str]]:
        """检查 required_capabilities 是否在注册表中可用

        Returns:
            None — 全部满足或无需检查
            List[str] — 缺失/不可用的能力 ID 列表
        """
        required = getattr(self, "required_capabilities", []) or []
        if not required:
            return None

        try:
            from dreamos.registry.node_registry import get_default_registry
            from dreamos.shared.capability import CapabilityStatus
        except Exception:  # noqa: BLE001
            return None

        try:
            registry = get_default_registry()
        except Exception:  # noqa: BLE001
            return None

        missing: List[str] = []
        for cap_id in required:
            providers = registry.find_nodes_by_capability(cap_id)
            available = any(
                getattr(c, "status", None) == CapabilityStatus.AVAILABLE
                for node in providers
                for c in (getattr(node, "capabilities", []) or [])
                if getattr(c, "capability_id", None) == cap_id
            )
            if not available:
                missing.append(cap_id)
        return missing or None

    def _smooth_f_signal(self, result: NodeResult) -> None:
        """对 F 链节点输出做信号平滑（就地修改 result）

        1. 从 outputs 中提取 *_score 字段
        2. EWMA 平滑 + MAD 鲁棒限幅
        3. 调整 confidence（偏离原始值越大，置信度衰减）
        """
        try:
            from dreamos.capabilities.trading.signal_smoother import get_smoother

            outputs = result.outputs
            if not outputs:
                return

            # 查找 score 字段（命名规律：{module}_score）
            score_key = None
            for key in outputs:
                if key.endswith("_score") and isinstance(outputs[key], (int, float)):
                    score_key = key
                    break

            if score_key is None:
                return

            raw_score = float(outputs[score_key])
            raw_conf = result.confidence or 0.5

            smoother = get_smoother()
            smoothed_score, adj_conf = smoother.smooth(self.node_id, raw_score, raw_conf)

            # 平滑后 score 覆盖
            outputs[score_key] = round(smoothed_score, 4)
            # 记录原始值供追溯
            outputs[f"_raw_{score_key}"] = round(raw_score, 4)
            outputs["_smoothed"] = True

            # 仅在异常值检测触发时调整 confidence
            # 正常平滑不降低 confidence，避免过度惩罚
            result.confidence = round(adj_conf, 4)
        except Exception as e:
            # 平滑失败不影响原始信号
            pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.node_id} [{self.chain}]>"
