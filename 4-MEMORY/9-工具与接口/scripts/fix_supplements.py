#!/usr/bin/env python3
"""
阶段 2 审阅修复脚本:
  - B1: supplement 章节标题改为设计文档标准格式
  - C2: 本土触发条件填入专业中文触发词（2倍权重触发）
"""
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent / "0-元记忆" / "superpowers" / "skills"

LOCAL_TRIGGERS = {
    "brainstorming": [
        "brainstorming", "头脑风暴", "创意", "点子", "方案设计", "多方案对比",
        "需求澄清", "问问题", "spec 撰写", "架构设计", "HARD-GATE",
        "多问后做", "选方案", "发散", "收敛", "设计初稿", "思路",
        "方案对比", "需求分析", "设计认知", "集成方案", "系统设计",
    ],
    "test-driven-development": [
        "TDD", "测试驱动", "先写测试", "写单测", "补单测", "红-绿-重构",
        "red green refactor", "失败测试", "测试用例", "pytest", "写 UT",
        "单元测试", "测试先行", "红绿提交", "写失败测试", "回归测试",
        "写脚本", "写 Python", "Python 脚本", "开发代码", "写代码",
        "代码开发", "实现功能", "功能开发",
    ],
    "systematic-debugging": [
        "调试", "debug", "排错", "bug修复", "复现问题", "root cause",
        "根本原因", "定位问题", "bugfix", "查日志", "排查",
        "复现失败", "压力测试", "压测", "4 阶段调试", "防御式调试",
        "修复bug", "出现超时", "故障", "异常",
    ],
    "verification-before-completion": [
        "验证完成", "验收", "确认修复", "我搞定了", "我修好了",
        "verify", "验证修复", "最终确认", "it's fixed", "签字完成",
        "完成验收", "结果确认", "确认通过", "完成确认", "结束确认",
    ],
    "writing-plans": [
        "写计划", "实施计划", "任务分解", "生成计划", "拆分任务",
        "微任务", "2-5 分钟", "可执行计划", "task 列表", "实施步骤",
        "planning", "plans 生成", "排计划", "0.5-2h", "设计落地计划",
    ],
    "executing-plans": [
        "执行计划", "按计划走", "batch 执行", "批量执行", "checkpoint",
        "执行步骤", "逐 task 执行", "跑计划", "实施落地", "执行批处理",
        "写脚本", "写代码", "开发代码", "代码实现", "脚本实现",
        "功能实现", "实现开发", "写 Python", "Python 实现",
    ],
    "subagent-driven-development": [
        "SDD", "子代理开发", "派发 subagent", "派发任务", "两阶段审查",
        "review-reviewer", "implementer", "子智能体", "并发执行",
        "子代理 审查", "两阶段 review", "task-brief", "独立子任务",
    ],
    "dispatching-parallel-agents": [
        "并发派发", "并行 agent", "parallel", "并发任务", "多代理",
        "并行执行", "并行子任务", "批量并发", "子代理并发",
    ],
    "requesting-code-review": [
        "代码审查", "发起 review", "预审查", "代码评审", "request review",
        "pre-review", "CR 前自检", "发起 CR", "代码自查后提交",
    ],
    "receiving-code-review": [
        "处理审查意见", "review反馈", "review 修复", "review 回应",
        "处理评论", "code review 后续", "修复审查问题", "审查反馈处理",
    ],
    "using-git-worktrees": [
        "git worktree", "工作区隔离", "worktree", "多工作区",
        "分支切换隔离", "并行分支", "本地多分支开发",
    ],
    "finishing-a-development-branch": [
        "收尾分支", "合并分支", "PR 提交", "merge", "工作区清理",
        "分支清理", "开发完成 收尾", "discard 分支", "提交完成",
        "开发收尾", "commit 完成", "合并主干", "cleanup",
    ],
    "writing-skills": [
        "新技能", "创建 skill", "写 SKILL.md", "技能文档", "创建 Prompt",
        "技能规范", "SKILL.md 格式", "prompt 工程", "创建新的 Skill",
        "自定义技能", "写技能", "写代码", "写脚本", "写 Python",
        "代码开发", "开发代码", "程序实现", "编程", "脚本实现",
        "功能实现", "写程序", "Python 开发", "OKX 脚本", "下单脚本",
        "量化脚本", "策略脚本",
    ],
    "using-superpowers": [
        "superpowers 使用", "方法论介绍", "overview", "如何 superpowers",
        "技能使用说明", "superpowers 流程", "14 个 Skill 介绍",
    ],
}

SCOPE_NOTES = {
    "brainstorming": "适用: 方案设计 / 需求澄清 / 多选项决策；不适用: 已有明确方案且不允许讨论的硬编码任务",
    "test-driven-development": "适用: Python/TS 确定性代码 / 交易策略 / 回测；不适用: 纯视觉 UI / 仅配置改动",
    "systematic-debugging": "适用: 交易系统 Bug / Python 脚本异常 / polling 超时 / 缓存；不适用: 纯外部环境（网络/交易所）故障",
    "verification-before-completion": "适用: 任何声称完成 / 修复 / 通过 的任务；不适用: 尚未实现的阶段",
    "writing-plans": "适用: 设计需落地 / ≥ 3 步的任务 / 文档转实施计划；不适用: 一行命令可完成的琐碎任务",
    "executing-plans": "适用: 已有 plan 的多步执行；不适用: 无 plan 直接上手的探索性任务",
    "subagent-driven-development": "适用: ≥ 2 小时 / 跨模块 / 可独立拆分的开发；不适用: <30 分钟单文件改动",
    "dispatching-parallel-agents": "适用: 3+ 无依赖子任务；不适用: 强前后依赖的串行任务",
    "requesting-code-review": "适用: 提交前预查 / 跨模块重构 / 核心逻辑修改；不适用: 纯文档 / 注释修改",
    "receiving-code-review": "适用: 收到 review comments 后；不适用: 尚未发起 CR",
    "using-git-worktrees": "适用: 多分支并行调试 / 长期任务隔离；不适用: 单分支小改动",
    "finishing-a-development-branch": "适用: 开发完成 / PR 提交 / merge 后清理；不适用: 分支未达到完成态",
    "writing-skills": "适用: 本土方法论标准化 / 经验沉淀为标准；不适用: 临时一次性方案",
    "using-superpowers": "适用: 向用户/AI介绍方法论；不适用: 日常具体开发任务",
}

ADAPT_NOTES = {
    "brainstorming": "原版 10% 时间硬门槛太死。我们场景：若已有 2+ 历史成功案例可从 L2 recall 直接命中，允许缩短至 5%。",
    "test-driven-development": "sz<20 USDT 时允许跳过实盘测试，但必须在 applied.metadata 中打标签 `# sz_too_so_small_skip_live_test` 并记录理由。",
    "systematic-debugging": "交易系统 debug 必须同时查三个日志源：/tmp/polling_trader_*.log + /tmp/cognitive-daemon.log + OKX 账户资产历史；否则不允许开 fix。",
    "verification-before-completion": "对于交易代码，额外加一条 VETO：若回测最大回撤 +5% 以上即使单元通过，也视为验证失败，必须附优化补丁。",
    "writing-plans": "实施计划粒度：0.5-2h/task，若总时长预估 > 10h 视为大型计划，建议拆阶段并每个阶段单独 review checkpoint。",
    "executing-plans": "执行中每完成 3 个 task 做 checkpoint 验证（对照 plan 清单），偏离 > 30% 自动触发重写计划子任务（暂停当前执行）。",
    "subagent-driven-development": "我们环境 SDD 派发到 general_purpose_task / Skill 机制，不派发到真正独立进程；两阶段 review 由当前主 agent 串联完成。",
    "dispatching-parallel-agents": "同时并发不超过 3 个（终端数限制 5，留给 daemon/交易系统 2 个）；超过 3 个按队列串行。",
    "requesting-code-review": "无人评审时，用自动 lint + test coverage + cognitive_superpowers.verify_process_followed() 三元组合作为替代审查。",
    "receiving-code-review": "审查意见 > 8 条或 > 2 个文件涉及核心逻辑时，必须先补单测覆盖，再开始修复意见。",
    "using-git-worktrees": "我们交易环境 executionId 隔离机制已覆盖此需求。原版 git worktree 不推荐使用，避免多进程共享账户冲突。",
    "finishing-a-development-branch": "所有分支清理前必须先跑：`pytest 4-MEMORY/9-工具与接口/tests/ -q` 无 FAILED；否则禁止 discard 或 merge。",
    "writing-skills": "本土自创 Skill 命名：前缀 `local-`（如 `local-trading-debug`），避免与 upstream 新增 Skill 冲突。",
    "using-superpowers": "遇到任务时不强制推荐 14 个 Skill；优先从应用层 L2 召回同类 Solution Path，无结果才用元流程建议。",
}

ANTI_PATTERNS = {
    "brainstorming": [
        "先写代码再回头想设计",
        "单方案死磕不生成对比",
        "跳过 HARD-GATE 直接实现",
    ],
    "test-driven-development": [
        "先写代码后补测试也叫 TDD（严格禁止）",
        "先写 mock 绿测再写代码（没有红阶段的不算）",
        "测试只覆盖 happy path 无边界值",
    ],
    "systematic-debugging": [
        "猜 root cause 直接 patch，不做最小复现",
        "4 阶段调试跳过 确认实验，一修就上线",
        "日志不看就说 环境问题 甩锅",
    ],
    "verification-before-completion": [
        "看起来对 就算完成，不跑回归测试",
        "只测成功案例，不测失败案例和超时",
        "声称 修复 但没给 commit hash 和证据链接",
    ],
    "writing-plans": [
        "计划 = 标题列表，具体步骤无 0.5-2h 粒度",
        "task 写 实现 xxx 不拆文件路径 / 函数名 / Consumes/Produces",
        "计划写得过长（> 40 task），实际执行到第 10 条就失效",
    ],
    "executing-plans": [
        "跳 task 不记录，偷偷插入计划外任务不补 checkpoint",
        "连续 5 步失败还在死磕，不触发重写计划",
        "完成后不对比实际产出 vs 计划差异，直接 claim 全部完成",
    ],
    "subagent-driven-development": [
        "子任务无自包含性，依赖前一个的实现细节",
        "派发出的 task 描述含糊，reviewer 靠猜",
        "一阶段 review 一次就过，不做 second-look",
    ],
    "dispatching-parallel-agents": [
        "并发子任务之间共享状态文件，后写者覆盖",
        "并发数超过终端限制，所有任务互相 kill",
        "无依赖的串行任务硬并发，反而增加调度开销",
    ],
    "requesting-code-review": [
        "大而全 PR 超 800 行提交要求 review",
        "lint 没跑 / 测试不过就发起 CR",
        "注释和 commit message 不写，reviewer 必须猜",
    ],
    "receiving-code-review": [
        "每条 comment 最小改法 patch，不理会结构性意见",
        "不理解的评论直接 done，不改代码",
        "review 后新增未覆盖的代码路径不补测试",
    ],
    "using-git-worktrees": [
        "worktree 与主工作区共用 venv，pip 污染互相覆盖",
        "git worktree add 后不 clean，切换分支后未提交的变更丢失",
        "本土已用 executionId 隔离，强行再加 worktree 导致双层隔离 bug",
    ],
    "finishing-a-development-branch": [
        "未跑回归测试就合并",
        "分支删了但 commit message 没写 traceability（指向 session_id / doc）",
        "遗留 TODO/FIXME 不记录，下一次再回来根本看不懂",
    ],
    "writing-skills": [
        "自创 Skill 不加 local- 前缀，上游同步后名字冲突",
        "SKILL.md 没有 HARD-GATE 和 Checklist，全是流程描述",
        "Frontmatter 分隔符乱改，导致 SkillLoader FAIL FAST 无法加载",
    ],
    "using-superpowers": [
        "每个任务都硬塞 7 阶段，2 分钟的活也走 brainstorm → plan → SDD → review",
        "不区分任务复杂度，所有 task 都强制 superpowers 模式",
        "把 Skill 当命令执行，不是建议参考",
    ],
}

SUCCESS_PLACEHOLDER = [
    "[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）",
]


def build_supplement(skill_id: str) -> str:
    triggers = LOCAL_TRIGGERS.get(skill_id, [])
    scope = SCOPE_NOTES.get(skill_id, "[ ] 待定")
    adapt = ADAPT_NOTES.get(skill_id, "[ ] 待定")
    antis = ANTI_PATTERNS.get(skill_id, ["[ ] 待补充本土反模式"])

    trigger_lines = []
    for i in range(0, len(triggers), 2):
        grp = triggers[i:i+2]
        bullet = " / ".join(grp)
        trigger_lines.append(f"- [x] {bullet}")
    if not trigger_lines:
        trigger_lines.append("- [ ] 待补充本土触发词")

    anti_lines = [f"- [ ] {a}" for a in antis]
    success_lines = SUCCESS_PLACEHOLDER[:]

    return (
        f"# Dreambuddy Supplement — {skill_id}\n"
        f"\n"
        f"> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)\n"
        f"> **上游 Skill**: {skill_id}\n"
        f"> **最后更新**: 2026-08-01\n"
        f"> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）\n"
        f"\n"
        f"## 1. 本 Skill 在 Dreambuddy 场景的适用范围\n"
        f"\n"
        f"{scope}\n"
        f"\n"
        f"## 2. 本土化适配说明\n"
        f"\n"
        f"{adapt}\n"
        f"\n"
        f"## 3. 常见 Rationalization 反模式\n"
        f"\n"
        f"{chr(10).join(anti_lines)}\n"
        f"\n"
        f"## 4. 本土触发条件\n"
        f"\n"
        f"注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。\n"
        f"建议至少命中 2 个以上关键词再视为高相关。\n"
        f"\n"
        f"{chr(10).join(trigger_lines)}\n"
        f"\n"
        f"## 5. 本土成功案例链接\n"
        f"\n"
        f"（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）\n"
        f"\n"
        f"{chr(10).join(success_lines)}\n"
    )


def main():
    count_ok = 0
    count_skipped = 0
    for skill_dir in sorted(SKILLS_ROOT.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_id = skill_dir.name
        sup_path = skill_dir / "dreambuddy-supplement.md"
        if skill_id not in LOCAL_TRIGGERS:
            print(f"SKIP {skill_id} 无本地触发词配置")
            count_skipped += 1
            continue
        content = build_supplement(skill_id)
        old_content = sup_path.read_text(encoding="utf-8") if sup_path.exists() else ""
        sup_path.write_text(content, encoding="utf-8")
        print(f"OK   {skill_id:35s}  触发词{len(LOCAL_TRIGGERS[skill_id]):2d}个  反模式{len(ANTI_PATTERNS[skill_id]):2d}条  旧{len(old_content):4d}→新{len(content):4d}字节")
        count_ok += 1
    print(f"\n合计：{count_ok} 个 OK，{count_skipped} 个 SKIP")


if __name__ == "__main__":
    main()
