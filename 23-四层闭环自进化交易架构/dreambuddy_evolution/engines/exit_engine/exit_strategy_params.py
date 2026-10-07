"""ExitStrategyParams — 离场策略参数化基因

对应 Phase 5 参数自适应闭环：离场策略参数作为基因写入
gene_data/strategy_genes/conditions/，不修改 strategy_gene.py 4 个冻结接口。

参数字段（12 个，全部可进化）：
  原始 4 参数：
    - trailing_retrace_pct: 移动止盈回调百分比（默认 0.05 = 5%）
    - sl_tighten_factor: 止损收紧因子（默认 0.7 = 收紧 30%）
    - tp_extend_factor: 止盈扩展因子（默认 1.2 = 扩展 20%）
    - force_close_threshold: 强制平仓 R_total 阈值（默认 -0.5）
  新增 8 参数（v1.14 参数扩展）：
    - trailing_arm_pct: trailing 触发阈值（默认 0.04）
    - break_even_arm_pct: 保本位触发阈值（默认 0.02）
    - partial_tp_r1: 第一批止盈 R 倍数（默认 1.0）
    - partial_tp_pct1: 第一批止盈比例（默认 0.5）
    - tp_decay_base_pct: TP 衰减初始间距（默认 0.06）
    - tp_decay_floor_pct: TP 衰减下限间距（默认 0.015）
    - tp_decay_grace_hours: TP 衰减宽限期（默认 12）
    - soft_vote_cooldown_sec: 软投票冷却期（默认 14400）
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class ExitStrategyParams:
    """离场策略参数基因（12 参数，全部可进化）"""

    # --- 原始 4 参数 ---
    trailing_retrace_pct: float = 0.05
    sl_tighten_factor: float = 0.7
    tp_extend_factor: float = 1.2
    force_close_threshold: float = -0.5

    # --- 新增 8 参数（v1.14）---
    trailing_arm_pct: float = 0.04
    break_even_arm_pct: float = 0.02
    partial_tp_r1: float = 1.0
    partial_tp_pct1: float = 0.5
    tp_decay_base_pct: float = 0.06
    tp_decay_floor_pct: float = 0.015
    tp_decay_grace_hours: int = 12
    soft_vote_cooldown_sec: int = 14400

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
                "trailing_arm_pct": {
                    "value": self.trailing_arm_pct,
                    "range": {"low": 0.02, "high": 0.08},
                },
                "break_even_arm_pct": {
                    "value": self.break_even_arm_pct,
                    "range": {"low": 0.01, "high": 0.05},
                },
                "partial_tp_r1": {
                    "value": self.partial_tp_r1,
                    "range": {"low": 0.5, "high": 2.0},
                },
                "partial_tp_pct1": {
                    "value": self.partial_tp_pct1,
                    "range": {"low": 0.1, "high": 1.0},
                },
                "tp_decay_base_pct": {
                    "value": self.tp_decay_base_pct,
                    "range": {"low": 0.03, "high": 0.10},
                },
                "tp_decay_floor_pct": {
                    "value": self.tp_decay_floor_pct,
                    "range": {"low": 0.01, "high": 0.05},
                },
                "tp_decay_grace_hours": {
                    "value": self.tp_decay_grace_hours,
                    "range": {"low": 0, "high": 48},
                },
                "soft_vote_cooldown_sec": {
                    "value": self.soft_vote_cooldown_sec,
                    "range": {"low": 0, "high": 86400},
                },
            },
            "code_ref": {
                "file": "23-四层闭环自进化交易架构/dreambuddy_evolution/engines/exit_engine/exit_strategy_params.py",
                "lines": {"low": 1, "high": 120},
            },
            "version": "1.1",
        }

    def to_json_str(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_gene_json(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "ExitStrategyParams":
        """从基因 JSON 字典反序列化为 ExitStrategyParams.

        支持两种格式：
        1. 基因格式（含 parameters 嵌套结构）：{"parameters": {"key": {"value": v, ...}}}
        2. 扁平格式：{"key": v, ...}
        FAIL-OPEN: 缺少字段使用默认值。
        """
        # 基因格式：提取 parameters 中的 value
        if "parameters" in d and isinstance(d["parameters"], dict):
            params = {}
            for k, v in d["parameters"].items():
                if isinstance(v, dict) and "value" in v:
                    params[k] = v["value"]
            return cls(**params)
        # 扁平格式：直接使用
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
