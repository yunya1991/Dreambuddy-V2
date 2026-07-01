"""
Layer 3: B层工程化（落地：从线/网到可执行图）

将OKR层的目标结构，映射为可执行的工程蓝图。

5步工程化：
1. 节点展开：KR → 具体模块节点
2. 依赖映射：KR依赖 → 节点依赖（DAG）
3. 拓扑排序：DAG → 可执行序列
4. 并行识别：识别可并行执行的节点组
5. 工程配置：超时、重试、降级等工程参数
"""

from .blueprint_builder import BlueprintBuilder

__all__ = [
    'BlueprintBuilder',
]
