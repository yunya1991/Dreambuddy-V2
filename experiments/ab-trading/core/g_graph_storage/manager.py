#!/usr/bin/env python3
"""
G层 - 图存储管理器（统一入口）

位置: experiments/ab-trading/core/g_graph_storage/manager.py

职责：
1. 统一管理 G 层所有图（B/A/C 三层）
2. 提供 CRUD 操作
3. 持久化存储
4. 压缩/展开的统一调度
5. 版本管理

G层 = Graph Storage Layer（图存储/压缩层）
  G.B - Blueprint（蓝图级）
  G.A - Architecture（架构级）
  G.C - Chronicle（记录级）

协作关系：
  运行时三层：S(意图) → A(编排) → C(执行)
       ↓          ↓          ↓
  存储三层：  G.B        G.A        G.C
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .types import (
    BlueprintGraph,
    ArchitectureGraph,
    ChronicleGraph,
    CompressionResult,
    CompressionStrategy,
    _gen_id,
)
from .compressor import GraphCompressor
from .expander import GraphExpander


# ============================================================
# 图存储管理器
# ============================================================

class GraphStorageManager:
    """G层图存储管理器

    操作系统级的图存储与压缩能力统一入口
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        default_compression_strategy: CompressionStrategy = CompressionStrategy.VALUE_PRIORITY,
        default_compression_ratio: float = 0.5,
        auto_compress: bool = False,
    ):
        """
        Args:
            storage_path: 存储路径（None 表示内存模式）
            default_compression_strategy: 默认压缩策略
            default_compression_ratio: 默认压缩率
            auto_compress: 是否自动压缩
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self.default_strategy = default_compression_strategy
        self.default_ratio = default_compression_ratio
        self.auto_compress = auto_compress

        # 内存存储
        self._blueprints: Dict[str, BlueprintGraph] = {}
        self._architectures: Dict[str, ArchitectureGraph] = {}
        self._chronicles: Dict[str, ChronicleGraph] = {}

        # 版本链
        self._version_chains: Dict[str, List[str]] = {}  # base_id -> version_ids

        # 组件
        self.compressor = GraphCompressor(
            strategy=default_compression_strategy,
            target_ratio=default_compression_ratio,
        )
        self.expander = GraphExpander()

        # 如果有存储路径，确保目录存在
        if self.storage_path:
            self.storage_path.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # Blueprint 操作
    # ============================================================

    def create_blueprint(
        self,
        name: str,
        description: str = "",
        root_id: Optional[str] = None,
    ) -> BlueprintGraph:
        """创建蓝图"""
        bp = BlueprintGraph(
            name=name,
            description=description,
            root_id=root_id or "root",
        )
        self._blueprints[bp.id] = bp
        self._save_if_persistent()
        return bp

    def get_blueprint(self, blueprint_id: str) -> Optional[BlueprintGraph]:
        """获取蓝图"""
        return self._blueprints.get(blueprint_id)

    def save_blueprint(self, blueprint: BlueprintGraph):
        """保存蓝图"""
        blueprint.updated_at = time.time()
        self._blueprints[blueprint.id] = blueprint
        self._save_if_persistent()

    def list_blueprints(self) -> List[BlueprintGraph]:
        """列出所有蓝图"""
        return list(self._blueprints.values())

    def delete_blueprint(self, blueprint_id: str) -> bool:
        """删除蓝图"""
        if blueprint_id in self._blueprints:
            del self._blueprints[blueprint_id]
            self._save_if_persistent()
            return True
        return False

    # ============================================================
    # Architecture 操作
    # ============================================================

    def create_architecture_from_blueprint(
        self,
        blueprint_id: str,
    ) -> Optional[ArchitectureGraph]:
        """从蓝图展开创建架构图"""
        blueprint = self.get_blueprint(blueprint_id)
        if not blueprint:
            return None

        arch = self.expander.expand_blueprint_to_architecture(blueprint)
        self._architectures[arch.id] = arch
        self._save_if_persistent()
        return arch

    def get_architecture(self, arch_id: str) -> Optional[ArchitectureGraph]:
        """获取架构图"""
        return self._architectures.get(arch_id)

    def save_architecture(self, arch: ArchitectureGraph):
        """保存架构图"""
        arch.updated_at = time.time()
        self._architectures[arch.id] = arch
        self._save_if_persistent()

    # ============================================================
    # Chronicle 操作
    # ============================================================

    def create_chronicle_from_architecture(
        self,
        arch_id: str,
        execution_id: Optional[str] = None,
    ) -> Optional[ChronicleGraph]:
        """从架构图展开创建时间线"""
        arch = self.get_architecture(arch_id)
        if not arch:
            return None

        chron = self.expander.expand_architecture_to_chronicle(arch, execution_id)
        self._chronicles[chron.id] = chron
        self._save_if_persistent()
        return chron

    def get_chronicle(self, chron_id: str) -> Optional[ChronicleGraph]:
        """获取时间线"""
        return self._chronicles.get(chron_id)

    def save_chronicle(self, chron: ChronicleGraph):
        """保存时间线"""
        chron.updated_at = time.time()
        self._chronicles[chron.id] = chron
        self._save_if_persistent()

    def update_chronicle_node(
        self,
        chron_id: str,
        node_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """更新时间线节点"""
        chron = self.get_chronicle(chron_id)
        if not chron:
            return False

        node = chron.get_node(node_id)
        if not node:
            return False

        # 更新字段
        if "start_time" in update_data:
            node.start_time = update_data["start_time"]
        if "end_time" in update_data:
            node.end_time = update_data["end_time"]
        if "inputs" in update_data:
            node.inputs.update(update_data["inputs"])
        if "outputs" in update_data:
            node.outputs.update(update_data["outputs"])
        if "logs" in update_data:
            node.logs.extend(update_data["logs"])
        if "status" in update_data:
            node.metadata.status = update_data["status"]
        if "token_cost" in update_data:
            node.metadata.token_cost = update_data["token_cost"]

        self.save_chronicle(chron)
        return True

    # ============================================================
    # 压缩操作
    # ============================================================

    def compress_chronicle(
        self,
        chron_id: str,
        target_ratio: Optional[float] = None,
        strategy: Optional[CompressionStrategy] = None,
    ) -> Optional[CompressionResult]:
        """压缩时间线"""
        chron = self.get_chronicle(chron_id)
        if not chron:
            return None

        result = self.compressor.compress_chronicle(
            chron, target_ratio, strategy
        )

        if result.success and result.compressed_chronicle:
            # 保存压缩后的版本
            self._chronicles[result.compressed_chronicle.id] = result.compressed_chronicle
            self._add_to_version_chain(chron_id, result.compressed_chronicle.id)
            self._save_if_persistent()

        return result

    def compress_full(
        self,
        chron_id: str,
        target_ratio: Optional[float] = None,
    ) -> Optional[CompressionResult]:
        """完整压缩：C → A → B"""
        chron = self.get_chronicle(chron_id)
        if not chron:
            return None

        arch = self.get_architecture(chron.architecture_id)
        bp = self.get_blueprint(arch.blueprint_id) if arch else None

        if not arch or not bp:
            return None

        result, compressed_bp = self.compressor.compress_to_blueprint(
            chron, arch, bp
        )

        if result.success:
            # 保存压缩后的版本
            if result.compressed_chronicle:
                self._chronicles[result.compressed_chronicle.id] = result.compressed_chronicle
            if result.compressed_architecture:
                self._architectures[result.compressed_architecture.id] = result.compressed_architecture
            if result.compressed_blueprint:
                self._blueprints[result.compressed_blueprint.id] = result.compressed_blueprint
            self._save_if_persistent()

        return result

    # ============================================================
    # 展开操作
    # ============================================================

    def expand_blueprint(
        self,
        blueprint_id: str,
        execution_id: Optional[str] = None,
    ) -> Optional[Tuple[ArchitectureGraph, ChronicleGraph]]:
        """完整展开：B → A → C"""
        bp = self.get_blueprint(blueprint_id)
        if not bp:
            return None

        arch, chron = self.expander.expand_full(bp, execution_id)

        self._architectures[arch.id] = arch
        self._chronicles[chron.id] = chron
        self._add_to_version_chain(blueprint_id, arch.id)
        self._save_if_persistent()

        return arch, chron

    # ============================================================
    # 版本管理
    # ============================================================

    def _add_to_version_chain(self, base_id: str, version_id: str):
        """添加到版本链"""
        if base_id not in self._version_chains:
            self._version_chains[base_id] = []
        self._version_chains[base_id].append(version_id)

    def get_version_chain(self, base_id: str) -> List[str]:
        """获取版本链"""
        return self._version_chains.get(base_id, [])

    # ============================================================
    # 持久化
    # ============================================================

    def _save_if_persistent(self):
        """如果配置了持久化，保存到磁盘"""
        if self.storage_path:
            self.save_to_disk()

    def save_to_disk(self):
        """保存到磁盘"""
        if not self.storage_path:
            return

        data = {
            "blueprints": {
                bid: bp.to_dict()
                for bid, bp in self._blueprints.items()
            },
            "architectures": {
                aid: arch.to_dict()
                for aid, arch in self._architectures.items()
            },
            "chronicles": {
                cid: chron.to_dict()
                for cid, chron in self._chronicles.items()
            },
            "version_chains": self._version_chains,
            "saved_at": time.time(),
        }

        save_file = self.storage_path / "graph_storage.json"
        with open(save_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_disk(self) -> bool:
        """从磁盘加载"""
        if not self.storage_path:
            return False

        save_file = self.storage_path / "graph_storage.json"
        if not save_file.exists():
            return False

        try:
            with open(save_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 注意：这里只做简单的加载演示
            # 完整的反序列化需要更复杂的处理
            self._version_chains = data.get("version_chains", {})
            return True
        except Exception:
            return False

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_chronicles = len(self._chronicles)
        compressed_count = sum(
            1 for c in self._chronicles.values()
            if c.compression_level > 0
        )

        return {
            "blueprints_count": len(self._blueprints),
            "architectures_count": len(self._architectures),
            "chronicles_count": total_chronicles,
            "compressed_chronicles": compressed_count,
            "version_chains_count": len(self._version_chains),
            "storage_path": str(self.storage_path) if self.storage_path else "memory_only",
            "default_strategy": self.default_strategy.value,
            "default_ratio": self.default_ratio,
            "auto_compress": self.auto_compress,
        }
