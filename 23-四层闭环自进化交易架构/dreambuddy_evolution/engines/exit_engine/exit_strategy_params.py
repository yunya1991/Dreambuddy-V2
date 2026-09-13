"""ExitStrategyParams — 离场策略参数化基因

对应 Phase 5 参数自适应闭环：离场策略参数作为基因写入
gene_data/strategy_genes/conditions/，不修改 strategy_gene.py 4 个冻结接口。

参数字段：
  - trailing_retrace_pct: 移动止盈回调百分比（默认 0.05 = 5%）
  - sl_tighten_factor: 止损收紧因子（默认 0.7 = 收紧 30%）
  - tp_extend_factor: 止盈扩展因子（默认 1.2 = 扩展 20%）
  - force_close_threshold: 强制平仓 R_total 阈值（默认 -0.5）
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class ExitStrategyParams:
    """离场策略参数基因"""

    trailing_retrace_pct: float = 0.05
    sl_tighten_factor: float = 0.7
    tp_extend_factor: float = 1.2
    force_close_threshold: float = -0.5

    def to_gene_json(self) -> dict:
        """序列化为基因 JSON 结构（写入 strategy_genes/conditions/）

        遵循 condition schema：
          - gene_id: 唯一标识
          - category: 枚举值（exit / risk / trend）
          - condition_type: 枚举值（indicator / threshold）
          - code_ref: 代码引用
        """
        return {
            "gene_id": "CD-EXIT-PARAMS-001",
            "category": "exit",
            "condition_type": "threshold",
            "expression": "exit_strategy_params",
            "parameters": {
                "trailing_retrace_pct": {
                    "value": self.trailing_retrace_pct,
                    "range": {"low": 0.02, "high": 0.10},
                },
                "sl_tighten_factor": {
                    "value": self.sl_tighten_factor,
                    "range": {"low": 0.5, "high": 0.9},
                },
                "tp_extend_factor": {
                    "value": self.tp_extend_factor,
                    "range": {"low": 1.0, "high": 1.5},
                },
                "force_close_threshold": {
                    "value": self.force_close_threshold,
                    "range": {"low": -0.8, "high": -0.2},
                },
            },
            "code_ref": {
                "file": "23-四层闭环自进化交易架构/dreambuddy_evolution/engines/exit_engine/exit_strategy_params.py",
                "lines": {"low": 1, "high": 60},
            },
            "version": "1.0",
        }

    def to_json_str(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_gene_json(), ensure_ascii=False, indent=2)
