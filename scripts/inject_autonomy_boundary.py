#!/usr/bin/env python3
"""批量为治理系统扫描的所有 SKILL.md 注入 ## Autonomy Boundary 段落。

按 SKILL category 注入差异化边界：
- trading: 交易执行类，严格禁止自主下单 + escalation_required
- orchestration: 编排类，可自主编排禁止直接交易
- tooling: 工具类，可自主执行工具操作禁止破坏性操作
- trigger: 触发类，可自主触发分析禁止直接交易
- meta: 元治理类，可自主治理禁止直接 merge
- system-kernel: 系统内核类，可自主监控禁止改核心配置
- uncategorized: 按目录推断（6-TRADING→交易严格, 1-ARCHITECTURE→治理, .trae→开发工具, ...）

注入位置：frontmatter 之后作为第一个 ## 段落。
已有 Autonomy Boundary 的跳过。
"""
import re
import sys
from pathlib import Path

# 复用治理系统索引
_GOVERNANCE_DIR = Path(__file__).resolve().parents[1] / "1-ARCHITECTURE" / "skills" / "dream-skill-index-governance"
if _GOVERNANCE_DIR.exists():
    sys.path.insert(0, str(_GOVERNANCE_DIR))
    from skill_indexer import ALL_SKILL_ROOTS, scan_skills
else:
    print("[ERROR] governance dir not found")
    sys.exit(1)


# ── 边界模板（按 category）─────────────────────────────

BOUNDARY_TRADING = """## Autonomy Boundary

可自主执行：
- 市场数据查询、技术指标计算
- 策略信号生成与验证
- 风险评估与仓位计算建议
- 回测与历史数据分析

需用户确认（escalation_required）：
- 任何实盘交易操作（开仓/平仓/加仓/减仓）
- 修改交易参数（止损/止盈/仓位大小）
- 调用交易所 API 执行订单

禁止自主执行：
- 未经用户确认直接下单
- 绕过风控网关执行交易
"""

BOUNDARY_ORCHESTRATION = """## Autonomy Boundary

可自主执行：
- 任务编排与流程调度
- 节点间数据流转发
- 编排优化与节点选择
- 执行状态监控与汇报

需用户确认：
- 涉及实盘交易的编排执行
- 修改核心编排规则

禁止：
- 将编排结论直接作为交易指令执行
- 绕过风控或审批流程
"""

BOUNDARY_TOOLING = """## Autonomy Boundary

可自主执行：
- 工具调用与数据转换
- 文档格式转换（Markdown/JSON/CSV）
- 通用查询与搜索操作
- 代码生成与重构建议

需用户确认：
- 执行破坏性操作（删除/覆盖重要文件）
- 修改系统核心配置

禁止：
- 未经授权执行不可逆操作
- 访问未授权的外部资源
"""

BOUNDARY_TRIGGER = """## Autonomy Boundary

可自主执行：
- 信号检测与触发判断
- 触发条件评估与告警
- 触发后通知与日志记录

需用户确认：
- 触发后自动执行交易操作

禁止：
- 将触发信号直接转化为交易订单
- 绕过人工确认执行高风险操作
"""

BOUNDARY_META = """## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- SKILL 索引与生命周期管理
- 架构同步校验
- 代码审查与合并建议

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批
"""

BOUNDARY_SYSTEM_KERNEL = """## Autonomy Boundary

可自主执行：
- 系统状态监控与健康检查
- 性能指标采集与告警
- 内核模块自检与日志

需用户确认：
- 修改系统核心配置
- 执行内核级热重启

禁止：
- 未经授权修改系统内核参数
- 执行可能导致系统不可用的操作
"""

BOUNDARY_DEFAULT = """## Autonomy Boundary

可自主执行：
- 数据查询与分析
- 报告生成与文档处理
- 通用计算与转换

需用户确认：
- 任何涉及资金或交易的操作
- 修改系统核心配置
- 执行不可逆的破坏性操作

禁止：
- 未经用户确认执行交易操作
- 绕过风控或审批流程
"""

BOUNDARY_MEMORY = """## Autonomy Boundary

可自主执行：
- 记忆检索与查询
- 经验编码与存储建议
- 记忆统计与健康检查

需用户确认：
- 删除或覆盖已有记忆
- 修改记忆系统核心配置

禁止：
- 未经确认删除重要记忆
- 写入未经验证的虚假经验
"""


CATEGORY_MAP = {
    "trading": BOUNDARY_TRADING,
    "trade": BOUNDARY_TRADING,
    "orchestration": BOUNDARY_ORCHESTRATION,
    "tooling": BOUNDARY_TOOLING,
    "trigger": BOUNDARY_TRIGGER,
    "meta": BOUNDARY_META,
    "system-kernel": BOUNDARY_SYSTEM_KERNEL,
    "memory": BOUNDARY_MEMORY,
}


def infer_boundary_by_path(skill_path: Path) -> str:
    """对于 uncategorized 的 SKILL，按目录路径推断 boundary。"""
    path_str = str(skill_path)
    if "6-TRADING" in path_str or "hermes/skills/trading" in path_str or "ab-trading" in path_str:
        return BOUNDARY_TRADING
    if "1-ARCHITECTURE/skills" in path_str:
        return BOUNDARY_META
    if ".trae/skills" in path_str or "superpowers" in path_str:
        return BOUNDARY_TOOLING
    if "trading-cognition" in path_str:
        return BOUNDARY_MEMORY
    return BOUNDARY_DEFAULT


def select_boundary(category: str, skill_path: Path) -> str:
    """根据 category 选择 boundary，uncategorized 时按路径推断。"""
    boundary = CATEGORY_MAP.get(str(category).lower().strip())
    if boundary:
        return boundary
    return infer_boundary_by_path(skill_path)


def insert_boundary(content: str, boundary: str) -> str:
    """在 frontmatter 之后插入 Autonomy Boundary 段落。"""
    if "## Autonomy Boundary" in content or "## 自主性边界" in content:
        return content

    fm_match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
    if fm_match:
        end_pos = fm_match.end()
        return content[:end_pos] + "\n" + boundary + "\n" + content[end_pos:]
    else:
        return boundary + "\n" + content


def main():
    entries = scan_skills(ALL_SKILL_ROOTS)

    modified = 0
    skipped = 0
    by_category = {}

    for entry in entries:
        # 只处理 active 状态的 SKILL
        if getattr(entry, "status", "active") != "active":
            continue

        skill_path = entry.path
        try:
            content = skill_path.read_text(encoding="utf-8")
        except Exception:
            continue

        if "## Autonomy Boundary" in content or "## 自主性边界" in content:
            skipped += 1
            continue

        category = str(getattr(entry, "category", "uncategorized"))
        boundary = select_boundary(category, skill_path)
        new_content = insert_boundary(content, boundary)

        try:
            skill_path.write_text(new_content, encoding="utf-8")
            modified += 1
            cat_key = category if category in CATEGORY_MAP else f"path-inferred({category})"
            by_category[cat_key] = by_category.get(cat_key, 0) + 1
            print(f"[OK] {cat_key}: {entry.name}")
        except Exception as e:
            print(f"[FAIL] {entry.name}: {e}")

    print(f"\n=== Summary ===")
    print(f"Modified: {modified}")
    print(f"Skipped (already has boundary): {skipped}")
    print(f"By category: {by_category}")


if __name__ == "__main__":
    main()
