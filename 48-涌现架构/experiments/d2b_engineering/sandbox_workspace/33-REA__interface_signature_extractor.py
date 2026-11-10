"""33-REA/interface_signature_extractor.py — D2-B 生成方案骨架。

设计依据: 缺口: 架构图仅记录 import 边，不记录接口签名/参数契约，holdout 复原时无法校验接口一致性。预期: 架构图节点含公开接口签名（函数名+参数+返回类型），可用于 interface_mismatch 检测。方案: 用 ast 提取每个公开函数的签名（name + args + return annotation），写入架构图节点的 interface_signature 字段，供 interface_mismatch 检测。

实施步骤:
#   1. 对每个 python_file 节点用 ast.parse 提取公开函数（非 _ 开头）
#   2. 记录 function name + args (name, annotation, default) + return annotation
#   3. 将 interface_signature 字段写入 architecture_graph 对应节点
#   4. interface_mismatch 检测: 比较 call 边两端的签名兼容性
#   5. 输出 mismatch 清单（参数数量/类型不匹配）
"""

from __future__ import annotations


def extract_signatures(*args, **kwargs):
    """方案入口（骨架：未实现，门禁通过后按步骤实施）。"""
    raise NotImplementedError("D2-B 骨架：45 门禁通过后按 design_rationale 步骤实施")
