#!/usr/bin/env python3
"""
write_health_status.py — 系统健康状态写入脚本

各系统在运行结束后调用此脚本，将自己的状态写入 health_dashboard.json。
元链治理（周日22:00）读取后产出综合周报。

用法：
    python3 write_health_status.py <system_name> <status> <findings_json>
    
参数：
    system_name:  系统标识符 (trading-evolution|memory-evolution|token-optimization|
                  index-audit|knowledge-sync|gate-audit|meta-governance)
    status:      状态 (🟢|🟡|🔴)
    findings_json: JSON 格式的发现摘要，如 '["学习5篇", "1篇高价值"]'
    
示例：
    python3 write_health_status.py trading-evolution 🟢 '["学习5篇","1篇高价值"]'
    python3 write_health_status.py index-audit 🟢 '["索引100%一致"]'
"""

import json
import os
import sys
from datetime import datetime

DASHBOARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "3-EVOLUTION",
    "health_dashboard.json"
)

VALID_SYSTEMS = {
    "trading-evolution": "交易进化",
    "memory-evolution": "记忆进化",
    "token-optimization": "Token优化",
    "index-audit": "索引审计",
    "knowledge-sync": "知识库同步",
    "gate-audit": "思维链门禁审计",
    "meta-governance": "元链治理",
}


def load_dashboard():
    """读取现有 dashboard，不存在则返回默认结构"""
    if os.path.exists(DASHBOARD_PATH):
        with open(DASHBOARD_PATH, "r") as f:
            return json.load(f)
    return {
        "updated_at": datetime.now().isoformat(),
        "systems": {},
        "tracked_issues": []
    }


def save_dashboard(data):
    """写回 dashboard"""
    os.makedirs(os.path.dirname(DASHBOARD_PATH), exist_ok=True)
    with open(DASHBOARD_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def merge_issues(existing, new_findings, system_name, status):
    """合并发现项到 tracked_issues

    只有 🟡(警告) 和 🔴(严重) 级别的问题才加入跟踪。
    🟢 的正常发现仅做日志记录，不跟踪。
    """
    if status == "🟢":
        # 标记此系统的旧问题为已修复
        for issue in existing:
            if issue.get("system") == system_name and issue["status"] == "unresolved":
                issue["status"] = "resolved"
                issue["resolved_at"] = datetime.now().isoformat()
        return existing

    for finding in new_findings:
        # 检查是否已在 tracked_issues 中
        found = False
        for issue in existing:
            if issue.get("system") == system_name and finding in issue.get("title", ""):
                issue["last_detected"] = datetime.now().isoformat()
                issue["status"] = "unresolved"  # 重新激活
                found = True
                break
        if not found:
            existing.append({
                "id": f"{system_name}-{len(existing)+1}",
                "title": finding,
                "status": "unresolved",
                "first_detected": datetime.now().isoformat(),
                "last_detected": datetime.now().isoformat(),
                "system": system_name
            })
    return existing


def main():
    if len(sys.argv) < 4:
        print(f"用法: {sys.argv[0]} <system_name> <status> <findings_json>")
        print(f"有效系统: {', '.join(VALID_SYSTEMS.keys())}")
        sys.exit(1)
    
    system_name = sys.argv[1]
    status = sys.argv[2]
    
    if system_name not in VALID_SYSTEMS:
        print(f"错误: 未知系统 '{system_name}'")
        print(f"有效选项: {', '.join(VALID_SYSTEMS.keys())}")
        sys.exit(1)
    
    if status not in ("🟢", "🟡", "🔴"):
        print(f"错误: 状态必须是 🟢 🟡 或 🔴")
        sys.exit(1)
    
    try:
        findings = json.loads(sys.argv[3])
    except json.JSONDecodeError:
        print(f"错误: findings 必须是有效 JSON 数组")
        sys.exit(1)
    
    # 读取/初始化 dashboard
    dashboard = load_dashboard()
    
    # 更新系统状态
    dashboard["systems"][system_name] = {
        "name_cn": VALID_SYSTEMS[system_name],
        "status": status,
        "last_run": datetime.now().isoformat(),
        "findings": findings,
        "issues_count": len([f for f in findings if "问题" in f or "风险" in f or "告警" in f or "失败" in f])
    }
    
    # 合并追踪问题
    dashboard["tracked_issues"] = merge_issues(
        dashboard.get("tracked_issues", []),
        findings,
        system_name,
        status
    )
    
    # 标记已修复问题（当前报告没提到但之前有）
    current_findings = set(findings)
    for issue in dashboard.get("tracked_issues", []):
        if issue.get("system") == system_name and issue["status"] == "unresolved":
            # 如果之前的问题在当前 findings 中没提到，标记为可能已修复
            if not any(issue["title"] in f for f in current_findings):
                issue["status"] = "resolved"
                issue["resolved_at"] = datetime.now().isoformat()
    
    dashboard["updated_at"] = datetime.now().isoformat()
    save_dashboard(dashboard)
    
    print(f"✅ [{system_name}] 状态写入完成: {status}")
    print(f"   发现: {findings}")
    print(f"   追踪问题: {len(dashboard['tracked_issues'])} 个")


if __name__ == "__main__":
    main()
