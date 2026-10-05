#!/usr/bin/env python3
"""批量为 11-易经推理系统/skills/ 下的 SKILL.md 注入 ## Autonomy Boundary 段落。

按目录分类注入不同的自主性边界：
- 1-TRADE: 交易执行类，严格禁止自主下单
- 2-INTELLIGENCE: 情报分析类，可自主分析
- 3-SUPPORT: 运营支持类，可自主执行运营任务
- 0-CORE: 核心治理类，可自主执行治理
- 4-GENERIC: 通用工具类，可自主执行工具操作
"""
import glob
import os
import re

BOUNDARIES = {
    "1-TRADE": """## Autonomy Boundary

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
""",

    "2-INTELLIGENCE": """## Autonomy Boundary

可自主执行：
- 情报收集与整理
- 数据分析与报告生成
- 知识库检索与匹配
- 市场情绪与资金流分析

需用户确认：
- 无（分析类操作均可自主执行）

禁止：
- 输出未经验证的虚假信息
- 将分析结论直接作为交易指令执行
""",

    "3-SUPPORT": """## Autonomy Boundary

可自主执行：
- 运营数据统计与报表生成
- 系统状态监控与告警
- 文档生成、同步与归档
- 成本与效率分析

需用户确认：
- 涉及资金变动的操作
- 修改系统核心配置

禁止：
- 未经授权修改生产环境配置
- 执行不可逆的破坏性操作
""",

    "0-CORE": """## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- 架构同步校验
- 代码审查与合并建议
- 知识库与记忆管理

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批
""",

    "4-GENERIC": """## Autonomy Boundary

可自主执行：
- 工具调用与数据转换
- 文档格式转换（Markdown/JSON/CSV）
- 通用查询与搜索操作
- 技能发现与注册

需用户确认：
- 无（通用工具操作可自主执行）

禁止：
- 执行破坏性操作（删除/覆盖重要文件）
- 访问未授权的外部资源
""",
}

DEFAULT_BOUNDARY = """## Autonomy Boundary

可自主执行：
- 数据查询与分析
- 报告生成与文档处理

需用户确认：
- 任何涉及资金或交易的操作
- 修改系统核心配置

禁止：
- 未经用户确认执行交易操作
- 执行不可逆的破坏性操作
"""


def detect_category(filepath: str) -> str:
    """根据路径检测 SKILL 分类"""
    parts = filepath.replace("\\", "/").split("/")
    for part in parts:
        if part in BOUNDARIES:
            return part
    return "DEFAULT"


def insert_boundary(content: str, boundary: str) -> str:
    """在 frontmatter 之后插入 Autonomy Boundary 段落"""
    # 已有则跳过
    if "## Autonomy Boundary" in content or "## 自主性边界" in content:
        return content

    # 匹配 frontmatter（--- ... ---）
    fm_match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
    if fm_match:
        end_pos = fm_match.end()
        return content[:end_pos] + "\n" + boundary + "\n" + content[end_pos:]
    else:
        # 无 frontmatter，在文件开头插入
        return boundary + "\n" + content


def main():
    base = "11-易经推理系统/skills"
    files = glob.glob(f"{base}/**/SKILL.md", recursive=True)

    modified = 0
    skipped = 0
    by_category = {}

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        if "## Autonomy Boundary" in content or "## 自主性边界" in content:
            skipped += 1
            continue

        category = detect_category(fpath)
        boundary = BOUNDARIES.get(category, DEFAULT_BOUNDARY)
        new_content = insert_boundary(content, boundary)

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(new_content)

        modified += 1
        by_category[category] = by_category.get(category, 0) + 1
        print(f"[OK] {category}: {fpath}")

    print(f"\n=== Summary ===")
    print(f"Total files: {len(files)}")
    print(f"Modified: {modified}")
    print(f"Skipped (already has boundary): {skipped}")
    print(f"By category: {by_category}")


if __name__ == "__main__":
    main()
