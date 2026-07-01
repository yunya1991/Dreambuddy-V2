#!/usr/bin/env python3
"""
G层桥接器 - 连接运行时三层与存储三层

位置: experiments/ab-trading/core/g_graph_storage/bridge.py

职责：
1. 将 S层意图识别结果 映射到 G.B 蓝图
2. 将 A层图编排结果 映射到 G.A 架构图
3. 将 C层执行结果 映射到 G.C 时间线
4. 执行完成后自动归档压缩

协作关系：
  运行时：S(意图) → A(编排) → C(执行)
           ↓          ↓          ↓
  桥接：  bridge_s_to_b  bridge_a_to_a  bridge_c_to_c
           ↓          ↓          ↓
  存储：   G.B        G.A        G.C
"""

import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .types import (
    BlueprintGraph,
    ArchitectureGraph,
    ChronicleGraph,
    BNode,
    ANode,
    CNode,
    BEdge,
    AEdge,
    CEdge,
    NodeStatus,
    NodeType,
    ComponentType,
    NodeMetadata,
    _gen_id,
)

from .manager import GraphStorageManager
from .compressor import CompressionStrategy


# ============================================================
# G层桥接器
# ============================================================

class GraphStorageBridge:
    """G层桥接器

    连接运行时三层（S/A/C）与存储三层（G.B/G.A/G.C）
    """

    def __init__(
        self,
        storage_manager: Optional[GraphStorageManager] = None,
        auto_archive: bool = False,
        auto_compress: bool = False,
        compression_ratio: float = 0.5,
        compression_strategy: CompressionStrategy = CompressionStrategy.VALUE_PRIORITY,
    ):
        """
        Args:
            storage_manager: 存储管理器（None则创建新的）
            auto_archive: 是否自动归档
            auto_compress: 是否自动压缩
            compression_ratio: 压缩率
            compression_strategy: 压缩策略
        """
        self.storage = storage_manager or GraphStorageManager()
        self.auto_archive = auto_archive
        self.auto_compress = auto_compress
        self.compression_ratio = compression_ratio
        self.compression_strategy = compression_strategy

        # 执行上下文追踪
        self._active_executions: Dict[str, Dict] = {}  # exec_id -> {bp, arch, chron}

    # ============================================================
    # S层 → G.B ：意图到蓝图
    # ============================================================

    def create_blueprint_from_intent(
        self,
        intent_result: Any,
        name: Optional[str] = None,
    ) -> BlueprintGraph:
        """
        从意图识别结果创建蓝图（S → G.B）

        Args:
            intent_result: 意图识别结果（IntentRecognitionResult）
            name: 蓝图名称

        Returns:
            BlueprintGraph
        """
        # 提取信息
        objective = getattr(intent_result, 'objective', None)
        blueprint = getattr(intent_result, 'blueprint', None)

        bp_name = name or (objective.title if objective else "未命名意图")
        bp_description = objective.description if objective else ""

        # 创建蓝图
        bp = self.storage.create_blueprint(bp_name, bp_description)

        # 创建根节点
        root = BNode(
            id="root",
            name=bp_name,
            type=ComponentType.COMPONENT,
            description=bp_description,
        )
        bp.add_node(root)
        bp.root_id = "root"
        self.storage.save_blueprint(bp)

        # 如果有 ExecutionBlueprint，展开为模块节点
        if blueprint:
            self._expand_blueprint_from_execution_bp(bp, blueprint)

        return bp

    def _expand_blueprint_from_execution_bp(
        self,
        bp: BlueprintGraph,
        execution_bp: Any,
    ):
        """从 ExecutionBlueprint 展开 G.B 节点"""
        node_sequence = getattr(execution_bp, 'node_sequence', [])
        kr_to_nodes = getattr(execution_bp, 'kr_to_nodes', {})

        root = bp.get_root()
        if not root:
            return

        prev_id = "root"

        # 按KR分组创建模块节点
        for kr_id, node_ids in kr_to_nodes.items():
            # 每个KR对应一个B层模块
            module_id = f"mod_{kr_id}"
            module_name = f"模块_{kr_id}"
            module = BNode(
                id=module_id,
                name=module_name,
                type=ComponentType.MODULE,
                parent_id=prev_id,
            )
            bp.add_node(module)
            root.children.append(module_id)

            edge = BEdge(
                source=prev_id,
                target=module_id,
                data_flow_type="control",
            )
            bp.add_edge(edge)

            prev_id = module_id

        self.storage.save_blueprint(bp)

    # ============================================================
    # A层 → G.A ：图编排到架构图
    # ============================================================

    def create_architecture_from_orchestration(
        self,
        blueprint_id: str,
        node_sequence: List[str],
        execution_mode: str = "sequential",
    ) -> Optional[ArchitectureGraph]:
        """
        从图编排结果创建架构图（A → G.A）

        Args:
            blueprint_id: 蓝图ID
            node_sequence: 节点序列
            execution_mode: 执行模式

        Returns:
            ArchitectureGraph
        """
        # 直接用展开器
        arch = self.storage.create_architecture_from_blueprint(blueprint_id)
        if not arch:
            return None

        # 如果有自定义节点序列，更新架构图
        if node_sequence:
            # 清空原有节点，重新创建
            arch.nodes.clear()
            arch.edges.clear()

            prev_id = None
            for i, node_id in enumerate(node_sequence):
                anode = ANode(
                    id=f"a_{node_id}",
                    name=node_id,
                    type=NodeType.STEP,
                    requires=[prev_id] if prev_id else [],
                )
                arch.add_node(anode)

                if i == 0:
                    arch.entry_node_id = anode.id

                if prev_id:
                    edge = AEdge(source=prev_id, target=anode.id)
                    arch.add_edge(edge)

                prev_id = anode.id

            self.storage.save_architecture(arch)

        return arch

    # ============================================================
    # C层 → G.C ：执行结果到时间线
    # ============================================================

    def create_chronicle_from_execution(
        self,
        architecture_id: str,
        execution_id: Optional[str] = None,
    ) -> Optional[ChronicleGraph]:
        """
        创建执行时间线（C → G.C 初始化）

        Args:
            architecture_id: 架构图ID
            execution_id: 执行ID

        Returns:
            ChronicleGraph
        """
        chron = self.storage.create_chronicle_from_architecture(
            architecture_id, execution_id
        )

        if chron:
            self._active_executions[chron.execution_id] = {
                "chronicle_id": chron.id,
                "architecture_id": architecture_id,
            }

        return chron

    def update_chronicle_node(
        self,
        execution_id: str,
        node_id: str,
        status: Optional[NodeStatus] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        inputs: Optional[Dict] = None,
        outputs: Optional[Dict] = None,
        token_cost: int = 0,
        logs: Optional[List[str]] = None,
    ) -> bool:
        """
        更新时间线节点状态（C层执行中调用）

        Args:
            execution_id: 执行ID
            node_id: 节点ID
            status: 节点状态
            start_time: 开始时间
            end_time: 结束时间
            inputs: 输入
            outputs: 输出
            token_cost: Token消耗
            logs: 日志

        Returns:
            bool - 是否成功
        """
        exec_info = self._active_executions.get(execution_id)
        if not exec_info:
            return False

        chron_id = exec_info["chronicle_id"]

        update_data: Dict[str, Any] = {}
        if status is not None:
            update_data["status"] = status
        if start_time is not None:
            update_data["start_time"] = start_time
        if end_time is not None:
            update_data["end_time"] = end_time
        if inputs is not None:
            update_data["inputs"] = inputs
        if outputs is not None:
            update_data["outputs"] = outputs
        if token_cost:
            update_data["token_cost"] = token_cost
        if logs is not None:
            update_data["logs"] = logs

        # 找到对应的 CNode ID（可能是 c_ 前缀）
        chron = self.storage.get_chronicle(chron_id)
        if not chron:
            return False

        cnode_id = None
        for cid, cnode in chron.nodes.items():
            if cnode.architecture_node_id == f"a_{node_id}" or cid == node_id or cid == f"c_{node_id}":
                cnode_id = cid
                break

        if not cnode_id:
            return False

        return self.storage.update_chronicle_node(chron_id, cnode_id, update_data)

    # ============================================================
    # 自动归档压缩
    # ============================================================

    def archive_execution(
        self,
        execution_id: str,
        compress: Optional[bool] = None,
    ) -> Optional[Dict]:
        """
        归档执行（执行完成后调用）

        Args:
            execution_id: 执行ID
            compress: 是否压缩（None则使用默认配置）

        Returns:
            归档结果信息
        """
        exec_info = self._active_executions.get(execution_id)
        if not exec_info:
            return None

        chron_id = exec_info["chronicle_id"]
        chron = self.storage.get_chronicle(chron_id)
        if not chron:
            return None

        result = {
            "execution_id": execution_id,
            "chronicle_id": chron_id,
            "archived": True,
            "compressed": False,
            "compression_result": None,
        }

        # 压缩
        should_compress = compress if compress is not None else self.auto_compress
        if should_compress:
            comp_result = self.storage.compress_full(chron_id)
            if comp_result and comp_result.success:
                result["compressed"] = True
                result["compression_result"] = comp_result.to_dict()

        # 从活跃执行中移除
        if execution_id in self._active_executions:
            del self._active_executions[execution_id]

        return result

    # ============================================================
    # 便捷方法：完整流程
    # ============================================================

    def start_execution(
        self,
        intent_result: Any,
        name: Optional[str] = None,
    ) -> Tuple[BlueprintGraph, ArchitectureGraph, ChronicleGraph]:
        """
        开始一个执行流程（S → G.B → G.A → G.C）

        Args:
            intent_result: 意图识别结果
            name: 执行名称

        Returns:
            (BlueprintGraph, ArchitectureGraph, ChronicleGraph)
        """
        # S → G.B
        bp = self.create_blueprint_from_intent(intent_result, name)

        # G.B → G.A
        node_sequence = getattr(
            getattr(intent_result, 'blueprint', None),
            'node_sequence', []
        ) if getattr(intent_result, 'blueprint', None) else []

        if node_sequence:
            arch = self.create_architecture_from_orchestration(
                bp.id, node_sequence
            )
        else:
            arch = self.storage.create_architecture_from_blueprint(bp.id)

        if not arch:
            raise RuntimeError("创建架构图失败")

        # G.A → G.C
        execution_id = _gen_id("exec")
        chron = self.create_chronicle_from_execution(arch.id, execution_id)
        if not chron:
            raise RuntimeError("创建时间线失败")

        return bp, arch, chron

    def finish_execution(
        self,
        execution_id: str,
    ) -> Optional[Dict]:
        """
        结束执行并归档

        Args:
            execution_id: 执行ID

        Returns:
            归档结果
        """
        return self.archive_execution(execution_id, compress=self.auto_compress)

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取桥接器统计"""
        stats = self.storage.get_stats()
        stats["active_executions"] = len(self._active_executions)
        stats["auto_archive"] = self.auto_archive
        stats["auto_compress"] = self.auto_compress
        return stats
