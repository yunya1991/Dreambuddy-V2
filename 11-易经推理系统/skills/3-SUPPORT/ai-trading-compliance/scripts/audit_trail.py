#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审计轨迹管理器 (Audit Trail Manager)

负责:
1. 将合规审查结果写入审计日志
2. 支持查询和回放
3. 管理审计日志的存储和归档
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class AuditTrailManager:
    """
    审计轨迹管理器

    存储格式:
    - 每个合规审查生成一条审计记录
    - 存储为 JSON Lines 格式 (append-only)
    - 支持按 trace_id 查询
    """

    def __init__(self, audit_dir: str = None):
        """
        初始化审计轨迹管理器

        Args:
            audit_dir: 审计日志存储目录
        """
        if audit_dir is None:
            # 默认：脚本所在目录的 ../audit/
            script_dir = Path(__file__).parent
            audit_dir = str(script_dir.parent / "audit")

        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

        # 审计日志文件 (按日期)
        self.current_log_file = self._get_log_file_path()

        print(f"  审计轨迹管理器初始化完成")
        print(f"    存储目录: {self.audit_dir}")
        print(f"    当前日志: {self.current_log_file.name}")

    def record(self, receipt: Dict[str, Any]) -> None:
        """
        记录合规审查结果到审计日志

        Args:
            receipt: 合规回执字典
        """
        # 构建审计记录
        audit_record = self._build_audit_record(receipt)

        # 写入日志文件 (append)
        with open(self.current_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(audit_record, ensure_ascii=False) + '\n')

        print(f"    ✓ 审计记录已写入: {audit_record['audit_id']}")

    def query(
        self,
        trace_id: Optional[str] = None,
        decision: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        查询审计记录

        Args:
            trace_id: 按 trace_id 过滤
            decision: 按决策过滤 (pass/warn/fail)
            start_time: 开始时间 (ISO 8601 格式)
            end_time: 结束时间 (ISO 8601 格式)

        Returns:
            List[Dict]: 匹配的审计记录列表
        """
        results = []

        # 遍历所有日志文件
        for log_file in sorted(self.audit_dir.glob("audit_*.jsonl")):
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 应用过滤条件
                    if trace_id and record.get("trace_id") != trace_id:
                        continue

                    if decision and record.get("decision") != decision:
                        continue

                    if start_time and record.get("timestamp", "") < start_time:
                        continue

                    if end_time and record.get("timestamp", "") > end_time:
                        continue

                    results.append(record)

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取审计统计信息

        Returns:
            Dict: 统计数据
        """
        stats = {
            "total_records": 0,
            "by_decision": {"pass": 0, "warn": 0, "fail": 0},
            "by_change_type": {},
            "by_risk_level": {},
            "log_files": 0
        }

        # 遍历所有日志文件
        for log_file in self.audit_dir.glob("audit_*.jsonl"):
            stats["log_files"] += 1

            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    stats["total_records"] += 1

                    # 按决策统计
                    decision = record.get("decision", "unknown")
                    stats["by_decision"][decision] = stats["by_decision"].get(decision, 0) + 1

                    # 按变更类型统计
                    change_type = record.get("change_classification", {}).get("change_type", "unknown")
                    stats["by_change_type"][change_type] = stats["by_change_type"].get(change_type, 0) + 1

                    # 按风险等级统计
                    risk_level = record.get("change_classification", {}).get("risk_level", "unknown")
                    stats["by_risk_level"][risk_level] = stats["by_risk_level"].get(risk_level, 0) + 1

        return stats

    def archive_old_logs(self, days: int = 30) -> int:
        """
        归档旧日志文件

        Args:
            days: 归档多少天前的日志

        Returns:
            int: 归档的文件数量
        """
        # TODO: Phase 2 - 实现日志归档逻辑
        print(f"  ⚠️ 日志归档功能尚未实现 (Phase 2)")
        return 0

    def _build_audit_record(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        """构建审计记录"""
        # 生成审计 ID
        audit_id = f"AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"

        # 构建记录
        record = {
            "audit_id": audit_id,
            "timestamp": datetime.now().isoformat(),
            "decision": receipt.get("decision"),
            "change_classification": receipt.get("change_classification"),
            "hard_constraints_checked": receipt.get("hard_constraints_checked"),
            "blockers": receipt.get("blockers", []),
            "warnings": receipt.get("warnings", []),
            "required_actions": receipt.get("required_actions", []),
            "rollout_requirements": receipt.get("rollout_requirements"),
            "audit_fields": receipt.get("audit_fields", {})
        }

        return record

    def _get_log_file_path(self) -> Path:
        """获取当前日志文件路径 (按日期)"""
        today = datetime.now().strftime("%Y%m%d")
        return self.audit_dir / f"audit_{today}.jsonl"


def test_audit_trail():
    """测试审计轨迹管理器"""
    # 创建管理器
    manager = AuditTrailManager()

    # 测试记录
    test_receipt_pass = {
        "decision": "pass",
        "change_classification": {
            "change_type": "R2",
            "risk_level": "P1"
        },
        "hard_constraints_checked": {
            "prod_write_prohibited_without_approval": True
        },
        "blockers": [],
        "warnings": [],
        "required_actions": [],
        "rollout_requirements": {
            "mode": "canary"
        },
        "audit_fields": {
            "doc_refs": ["doc1_v1.0"],
            "trace_id": "trace_001",
            "artifacts": [],
            "approver_roles": ["risk_owner"]
        }
    }

    print("\n测试 1: 记录合规回执 (pass)")
    manager.record(test_receipt_pass)

    test_receipt_fail = {
        "decision": "fail",
        "change_classification": {
            "change_type": "R3",
            "risk_level": "P0"
        },
        "hard_constraints_checked": {},
        "blockers": [
            {
                "id": "H001",
                "title": "SSoT 引用缺失",
                "evidence": ""
            }
        ],
        "warnings": [],
        "required_actions": [
            {
                "id": "ACTION_H001",
                "title": "修复 SSoT 引用",
                "how": "添加 doc_refs"
            }
        ],
        "rollout_requirements": {
            "mode": "disabled"
        },
        "audit_fields": {
            "doc_refs": [],
            "trace_id": "trace_002",
            "artifacts": [],
            "approver_roles": []
        }
    }

    print("\n测试 2: 记录合规回执 (fail)")
    manager.record(test_receipt_fail)

    # 测试查询
    print("\n测试 3: 查询审计记录")
    results = manager.query(decision="pass")
    print(f"  查询结果 (decision=pass): {len(results)} 条")

    # 测试统计
    print("\n测试 4: 获取统计信息")
    stats = manager.get_statistics()
    print(f"  总记录数: {stats['total_records']}")
    print(f"  按决策: {stats['by_decision']}")


if __name__ == "__main__":
    test_audit_trail()
