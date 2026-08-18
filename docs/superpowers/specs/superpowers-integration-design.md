# Superpowers 集成设计 — 认知环中的 Process Layer

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.3 |
| 创建日期 | 2026-07-31 |
| 状态 | Implemented（28/28 Task 已交付，75/75 单测通过；待 live 验收 + 7 天灰度） |
| 作者 | dreambuddy 认知系统组 |
| 关联文档 | [COGNITIVE_ARCHITECTURE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/COGNITIVE_ARCHITECTURE.md)、[cognitive_superpowers.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_superpowers.py)、[SUPERPOWERS_INTEGRATION_UPGRADE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/SUPERPOWERS_INTEGRATION_UPGRADE.md) |
| 上游标准 | [obra/superpowers](https://github.com/obra/superpowers) v6.2.0（14 个 SKILL.md） |

## 修订记录

| 日期 | 版本 | 修订内容 | 作者 |
|------|------|---------|------|
| 2026-07-31 | v1.0 | 初版，六节设计完整方案 | 认知系统组 |
| 2026-07-31 | v1.1 | 新增设计节 7：思维路径评测 + 飞书告警闭环 + 推理模型特质反哺 | 认知系统组 |
| 2026-07-31 | v1.2 | 新增附录 E：外部参考项目；设计节 7.3/7.4 加入 Hermes/superpowers-evals 参考实现引用 | 认知系统组 |
| 2026-08-01 | v1.3 | 实施完成：28/28 Task 交付 + 75 单测通过；状态 Draft→Implemented；新增附录 F 规格-实现偏差记录（Task 27 V6 结构 / Task 28 final_signoff 分发机制） | 认知系统组 |

---

## 目录

- [1. 总体架构](#1-总体架构)
- [2. 元认知流程层 — SKILL.md 存储/加载/索引](#2-元认知流程层--skillmd-存储加载索引)
- [3. recall 注入机制](#3-recall-注入机制)
- [4. 应用认知流程沉淀与元→应用映射改造](#4-应用认知流程沉淀与元应用映射改造)
- [5. 现有代码改造清单 + TS 层处置](#5-现有代码改造清单--ts-层处置)
- [6. 迁移策略与验收标准](#6-迁移策略与验收标准)
- [7. 思维路径评测与飞书告警闭环（推理模型特质）](#7-思维路径评测与飞书告警闭环推理模型特质)
- [附录 A：数据结构汇总](#附录-a数据结构汇总)
- [附录 B：退化映射表](#附录-b退化映射表)
- [附录 C：SKILL.md 格式红线](#附录-c-skillmd-格式红线)
- [附录 D：应急回滚操作清单](#附录-d-应急回滚操作清单)
- [附录 E：外部参考项目](#附录-e外部参考项目)
- [附录 F：规格-实现偏差记录（理论实践一致性）](#附录-f规格-实现偏差记录理论实践一致性)

---

## 1. 总体架构

### 1.1 在认知三要素中的位置

完整认知 = Knowledge（2-KNOWLEDGE 知识库）+ Memory（4-MEMORY 记忆系统）+ Process（Superpowers 流程层）。

Process Layer 分两层：
- **Layer 1 元认知流程**：原版 SKILL.md（总记忆层 L2），只增不改、允许系统性完善
- **Layer 2 应用认知流程**：Solution Paths（应用记忆层 L1），贝叶斯进化

这直接对齐 [COGNITIVE_ARCHITECTURE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/COGNITIVE_ARCHITECTURE.md) 第 4.4 节既有设计，**不新增认知层架构**，只替换 Layer 1 的内容来源（从自创 6 模板 → 原版 14 Skill）。

### 1.2 在认知闭环中的数据流

```
┌──────────────────────────────────────────────────────────────┐
│                    认知环（6 步完整流程）                        │
│                                                                  │
│ Step 1 recall      AI 启动任务 → MCP recall() 调用              │
│ ──────────────────► ├─ 从 2-KNOWLEDGE 检索：领域知识（不变）     │
│                     ├─ 从 4-MEMORY L2 检索：经验记忆（不变）     │
│                     └─ 新增：Process Layer 检索（本设计核心）    │
│                          ├─ 匹配的 SKILL.md 摘要（元认知流程）   │
│                          └─ 关联的 Solution Path（应用案例）     │
│                                                                  │
│ Step 2 Theory       → 定位 0-系统文档管理 SSoT（不变）           │
│ Step 3 Practice     → 生成代码（不变）                           │
│ Step 4 Execute      → 执行测试（不变）                           │
│ Step 5 A8 校验      → 一致性得分（不变）                         │
│                                                                  │
│ Step 6 贝叶斯+沉淀  git commit → cognitive_hook.py 触发          │
│ ◄────────────────── ├─ 提取行动链（文件变更+工具调用）           │
│                     ├─ 校验：行动链是否遵循 SKILL.md 步骤        │
│                     ├─ 生成 Solution Path（应用认知流程，C 级）  │
│                     ├─ 建立元→应用映射：SKILL ID → Solution Path│
│                     ├─ 贝叶斯更新：Solution Path C→B→A→S（不变）│
│                     └─ 可选：Supplement 完善（本土经验沉淀）     │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 与既有组件的边界

| 既有组件 | 改动 | 不改动 |
|---------|------|--------|
| Knowledge 2-KNOWLEDGE | — | 全不改动 |
| Memory L0 WorkingMemory | 注入时新增 process_block（SKILL+Solution Path） | context_block / scratch_block |
| Memory L1 应用记忆 | Solution Path 按原版 Skill ID 关联 | 其余记忆条目、贝叶斯更新算法 |
| Memory L2 总记忆 | 新增 `superpowers/skills/` 目录存 SKILL.md | MU-DEV/TRD/DOC/INF 元记忆文件 |
| cognitive_mcp_server | `recall` 新增 process 检索分支 | record/verify/stats/health |
| cognitive_daemon | 新会话后台预热 | 文件监听、会话管理 |
| cognitive_hook | commit 后新增流程校验+映射关联 | commit 提取、经验记录、verify 触发 |
| cognitive_session | Solution Path 关联 SKILL ID，不再自创 | 行动链记录、Solution Path 结构 |
| 贝叶斯更新算法 | — | v2 严格版 Beta-Binomial + 指数遗忘 |

### 1.4 核心不变性承诺

1. **SKILL.md 只增不改、允许系统性完善**：原版内容作为 base 保留；补充写入同级 `dreambuddy-supplement.md` 独立文件；未来从 upstream 同步时 diff 清晰。**禁止改动原版 frontmatter 分隔符**（详见附录 C）。
2. **AI 遵循靠 Prompt，不靠代码门禁**：原版设计是 AI 读 SKILL.md 后自主遵循 HARD-GATE。我们不在 GraphExecutor 或代码层拦截执行（TS 的 MethodologyExecutor 仅作交易系统专用，不进入通用认知环）。
3. **不新增抽象模板层**：删除 `TDD-001` 等自创 ID，映射键直接用原版 Skill name（`test-driven-development`、`systematic-debugging` 等）。
4. **应用认知层（Solution Path）继续贝叶斯进化**：原版 SKILL.md 的"信任度"通过应用层 Solution Path 的质量等级（C→B→A→S）体现，不给原版文件加置信度层。

---

## 2. 元认知流程层 — SKILL.md 存储/加载/索引

### 2.1 目录结构（与 GitHub 原版同构，方便 upstream 同步）

```
4-MEMORY/0-元记忆/
├── superpowers/
│   ├── skills/                           ← 原版 14 个 Skill 原样存放
│   │   ├── brainstorming/
│   │   │   ├── SKILL.md                  ← 原版文件（严禁动 frontmatter 分隔符）
│   │   │   ├── visual-companion.md       ← 原版附带文件（若有）
│   │   │   └── dreambuddy-supplement.md  ← 我们的本土补充（只增不改主载体）
│   │   ├── test-driven-development/
│   │   │   ├── SKILL.md
│   │   │   ├── testing-anti-patterns.md
│   │   │   └── dreambuddy-supplement.md
│   │   ├── systematic-debugging/
│   │   │   ├── SKILL.md
│   │   │   ├── root-cause-tracing.md
│   │   │   ├── defense-in-depth.md
│   │   │   ├── condition-based-waiting.md
│   │   │   └── dreambuddy-supplement.md
│   │   ├── verification-before-completion/
│   │   ├── writing-plans/
│   │   ├── executing-plans/
│   │   ├── subagent-driven-development/
│   │   ├── dispatching-parallel-agents/
│   │   ├── requesting-code-review/
│   │   ├── receiving-code-review/
│   │   ├── using-git-worktrees/
│   │   ├── finishing-a-development-branch/
│   │   ├── writing-skills/
│   │   └── using-superpowers/
│   │
│   ├── skills-index.json                 ← 启动时自动重建，关键词 + 元数据缓存
│   └── README.md                         ← 维护规则：upstream 同步、Supplement 写作、格式红线
│
├── process_templates.json                ← 旧版自创模板存档（迁移后废弃或只读保留历史映射）
└── template_mappings.json                ← 元→应用映射（键从 TDD-001 → test-driven-development）
```

**目录原则**：
- `skills/<name>/SKILL.md` 严格是 GitHub 原版路径形式，未来可用 `git subtree` / 脚本拉 diff 同步。
- `dreambuddy-supplement.md` 是我们的"只增不改"主载体——允许添加：① 我们场景下的适配说明（如"交易系统不用 git worktree，用 executionId 隔离"）；② 本土化触发条件；③ 常见 rationalization 补丁。**永不修改 SKILL.md 正文中的原版章节**。

### 2.2 加载器 SkillLoader（对应 cognitive_superpowers.py 改造）

**数据模型**（替换自创的 ProcessTemplate 字段）：

```python
@dataclass
class SuperpowersSkill:
    skill_id: str                    # 原版 name：test-driven-development
    display_name: str                # frontmatter name 原文
    description: str                 # frontmatter description
    version: str                     # "upstream v6.2.0 + dreambuddy supplement v1"
    raw_skill_md: str                # SKILL.md 原文（用于 recall 注入，AI 读原文最准确）
    hard_gates: List[str]            # 提取出的 <HARD-GATE> 内容（快速索引）
    checklists: List[str]            # 提取出的 Checklist（用于事后校验行动链）
    trigger_keywords: List[str]      # 汇总的触发词（name + desc + gates + checklists + supplement）
    supplement: Optional[str]        # dreambuddy-supplement.md 内容（如有，注入时拼接在原文尾部）
    md5_of_base: str                 # SKILL.md 原版内容 hash（用于 upstream 同步时检测更新）
    localized: bool                  # 是否存在 supplement
```

**加载流程**（吸收经验 95953 的格式红线）：

```
1. 遍历 skills/*/SKILL.md
   对每个文件：
   a. 校验格式红线（FAIL FAST，明确报错带文件路径+行号）：
      - 前 1 字节必须是 '-' 且第 1 行 == '---'
      - 存在闭合的 '---' 分隔第二行 frontmatter
      - 禁止用 '***' / '______' / '====' 做 frontmatter 分隔符
   b. 提取 frontmatter：name + description + (可选 version, tags, author)
   c. 提取 HARD-GATE：正则 <HARD-GATE>([\s\S]*?)<\/HARD-GATE>
   d. 提取 Checklist：正则 ^[-*]\s+\[.?\]\s+(.+)$ / gm
   e. 读同级 dreambuddy-supplement.md（若存在则 localized=true）
   f. 计算 md5_of_base（不含 supplement）
   g. 汇总 trigger_keywords：frontmatter + gates[] tokenize + checklists[] tokenize + supplement tokenize
2. 生成 skills-index.json（下次启动跳过解析直接加载缓存；hash 变了重解析）
3. 异常策略：单个 Skill 解析失败不影响其他 13 个（静默失败 + 告警日志）
```

### 2.3 关键词索引（服务于 recall 时的任务类型匹配）

索引**自动从文件内容构建**，不再硬编码（替代当前 [PROCESS_KEYWORDS](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_superpowers.py) 手写表）：

```python
# 自动构建示例
skill_index = {
  "brainstorming":               ["brainstorm", "创意", "设计", "spec", "需求澄清", "多问", "HARD-GATE before impl"],
  "test-driven-development":     ["tdd", "测试", "red green refactor", "写测试", "单测"],
  "systematic-debugging":        ["debug", "调试", "root cause", "排错", "复现", "定位", "4-phase"],
  "verification-before-completion": ["验证", "验收", "确认修复", "it's fixed"],
  "writing-plans":               ["plan", "计划", "分解", "task", "2-5 min", "微任务"],
  "executing-plans":             ["执行计划", "batch", "checkpoint"],
  "subagent-driven-development": ["sdd", "子代理", "subagent", "two-stage review"],
  "dispatching-parallel-agents": ["parallel", "并发", "dispatch"],
  "requesting-code-review":      ["review", "代码审查", "pre-review"],
  "receiving-code-review":       ["review反馈", "处理审查意见"],
  "using-git-worktrees":         ["worktree", "工作区隔离", "分支"],
  "finishing-a-development-branch": ["收尾", "merge", "PR", "discard", "cleanup"],
  "writing-skills":              ["新技能", "创建 skill", "写技能文档"],
  "using-superpowers":           ["介绍", "overview", "superpowers 用法"],
}
```

**检索评分算法**（改造 `retrieve_relevant_processes`）：

```
score = 0
for kw in trigger_keywords[skill_id]:
    if kw in query_lower: score += 1.0
score += matched_hard_gate_count * 0.3   # 命中 HARD-GATE 关键词加权
score += matched_checklist_count * 0.2
# 不引入自创 template.confidence——原版 Skill 没有置信度概念
返回 top_k（默认 2-3 个）
```

### 2.4 对认知会话 recall 注入的产物

当 recall 返回 `SuperpowersSkill[]` 时注入 WorkingMemory.process_block：

```markdown
# 🎯 流程建议（非约束，AI 自主选择；来自 Superpowers 标准规范 + 本土补充）

## [元认知] test-driven-development
> 原版 v6.2.0 + Dreambuddy Supplement v1
### 原文摘录（核心）
<把 SKILL.md 中 HARD-GATE + 前 ~600 字 Process 段注入>
### 本土补充
<dreambuddy-supplement.md：例如"交易策略代码节点红-绿-提交：测试写在 11-易经推理系统/tests/；sz 不足时跳过但要记录">
### 相关成功案例（应用认知层 top 2）
1. [B] APP-1785382661193 "NEAR 离场系统 TDD" — conf 0.72，4 次验证
2. [A] APP-1785292560413 "polling_trader 超时修复" — conf 0.81，8 次验证
```

三要素齐了：Knowledge（原版流程知识）+ Memory（本土历史经验）+ Process（可执行的步骤）。

---

## 3. recall 注入机制

### 3.1 注入触发的三条路径（互为冗余）

```
路径 A（主路径，必需）：AI 显式调用 MCP recall() 工具
  └─> 现在已经在跑，改造其返回值加 process_section

路径 B（静默兜底路径）：宿主 SessionStart hook 主动注入
  └─> 即使 AI 忘了调 recall，也能在会话一开始拿到流程建议
  └─> 对应 cognitive_install.py 中宿主适配层 + hooks/ 目录对接

路径 C（后台路径）：cognitive_daemon 检测到新会话创建，自动写入 WorkingMemory.process_block
  └─> 对"非交互型批量任务"（如后台策略回测）特别有用
```

三条路径都写入同一个目的地——**WorkingMemory 的新增 process_block**。

### 3.2 WorkingMemory 新增 process_block

现状：`task_block + context_block + scratch_block` 三分区。
改造：新增 `process_block`（第 4 分区，只读，AI 看到不能改），默认预算 3000 token。

```python
# working_memory_manager.py 改造点
class WorkingMemoryManager:
    DEFAULT_BUDGETS = {
        "task":    500,
        "context": 2000,
        "scratch": 1500,
        "process": 3000,   # 新增：流程建议（元+应用双层）
    }
    def __init__(...):
        self.process_block = MemoryBlock("process", max_tokens=3000)
        self.process_block._readonly = True  # 只有 recall 注入能写，AI 自身不能改写
```

`process_block` 的条目结构（由 recall 注入器生成，每一条是可独立展示的 Markdown 片段）：

```
process_block.items = {
  "P-meta-test-driven-development": """## [元认知流程] test-driven-development
> 原版 v6.2.0 + Dreambuddy Supplement v2 · 匹配度 0.82

### 硬约束 HARD-GATE（不满足直接阻断）
- 先写失败测试再写代码；如果先写了代码后补测试，删除代码重来。
- 测试未通过前，不提交 commit。
- 测试通过后必须立即 commit（红-绿-提交循环）。

### 关键步骤（节选）
1. 写一个失败测试，确认它真的失败（红）。
2. 写最小能让测试通过的实现，跑通（绿）。
3. 提交本次红→绿实现（git commit）。
4. 重构，再次跑通，提交重构 commit。

### Dreambuddy 本土补充
- 交易策略回测任务: 测试文件放在 11-易经推理系统/tests/，测试名 test_<策略名>_<场景>。
- 若 sz（可用资金）< 20 USDT，不强制跑实盘测试，但需要补 # sz_too_so_small_skip_live_test 标签并记录到 context_block。
- 成功案例:
  1. [A 级] "polling_trader 超时修复" — 8 次验证 conf 0.81
  2. [B 级] "离场系统 VETO 缓存修复" — 3 次验证 conf 0.72
""",
  "P-applied-APP-1785292560413": """## [应用认知案例] polling_trader 超时修复（B级 conf 0.72）
> 父模板: test-driven-development · 4 次成功 / 0 失败 · 持续 36min
> 任务类型: trading-system / python-development
### 行动链（可复刻）
1. 读 polling_trader.py 主循环定位 subprocess 调用。
2. 写失败测试 test_timeout_subprocess_poll 用 stub OKX 504。
3. 加入 subprocess.Popen + 异步等待队列，替换 Popen.communicate(timeout=)。
4. 测试通过（红→绿），commit。
5. 压测 3 轮，无误后 commit 重构。
### 产出
- 修改: polling_trader.py 5 处、新增 1 个测试文件
- 结论: 长超时任务必须用 Popen + 检查点轮询
""",
}
```

### 3.3 MCP recall 返回值改造（不破坏现有协议，增量加 `processes` 字段）

现状 `_handle_recall` 返回：
```json
{ "memories": [...], "count": N }
```

改造后：
```json
{
  "memories": [ ... ],
  "count": N,
  "processes": {
    "meta": [
      {
        "skill_id": "test-driven-development",
        "display_name": "Test-Driven Development",
        "match_score": 0.82,
        "match_reason": "命中关键词：tdd, 测试, 写测试, 单测 · 命中 HARD-GATE 2 条",
        "injection": "[Markdown 全文：HARD-GATE + 关键步骤 + Supplement + 应用案例 top 2]",
        "hard_gates": ["... list of extracted HARD-GATE ..."],
        "localized": true
      }
    ],
    "applied": [
      {
        "applied_id": "APP-1785292560413",
        "parent_skill": "test-driven-development",
        "title": "polling_trader 超时修复",
        "quality_level": "B",
        "confidence": 0.72,
        "verify_count": 4,
        "outcome_success": true,
        "injection": "[Markdown 摘要版 Solution Path（复刻用）]"
      }
    ],
    "process_block_markdown": "[可直接粘到 System Prompt 的全文汇总]"
  }
}
```

**兼容原则**：
- 宿主旧版本只看 `memories` 和 `count` → 照样工作，不受影响。
- 新版本宿主可以用 `processes` 字段渲染到更丰富的 UI，或直接取 `process_block_markdown` 注入 System Prompt。
- 静默模式加开关：`include_process=False` 时行为与现在完全一致（向后兼容）。

### 3.4 宿主 SessionStart hook（路径 B）

在 `cognitive_install.py` 基础上，对 Claude Code / TRAE / Cursor 三个宿主，加一条 SessionStart 自动触发的**静默 recall**：

```bash
# Claude Code 的 hooks/session-start.sh（示例）
#!/bin/sh
# SessionStart: 不打扰 AI，在后台把流程建议预取到 WorkingMemory
python3 -c "
from cognitive_loop_entry import CognitiveLoopEntry
cle = CognitiveLoopEntry()
first_msg = '${CLAUDE_INITIAL_MESSAGE:-empty}'
results = cle.recall(first_msg, include_process=True, top_k_memory=3, top_k_process=2)
cle.working_memory.load_process_block(results['processes']['process_block_markdown'])
" &
```

**不打扰原则**：这条注入是"预加载"，不抢占第一条 AI 回复的位置。AI 真正执行任务、调用 `recall()` 时，会看到 `process_block` 已预热——若本次关键词匹配结果不同，再做**增量替换**（仅替换 score 更低的条目），避免同一 process_block 在会话内反复抖动。

### 3.5 注入到 System Prompt 的最终形态

现状 `working_memory_manager.py:get_prompt_context()` 只展示 task/context/scratch。改造后在其末尾追加 `process_block` 段，且放在最底部（即最高优先级，AI 最后看到）：

```
## 当前工作记忆 (Working Memory)
任务ID: T-xxx
任务: 修复 NEAR 0% 强制平仓
目标: ...
状态: running

### 上下文
- 最近修改文件: polling_trader.py yijing_exit_system.py
- 信心阈值: 0.70 FORCE_CLOSE / 0.65 soft
...
### 草稿区
- ...

---
## 🎯 流程建议（非约束，可自由选择 · Dreambuddy Process Layer）
### [元认知] test-driven-development  匹配度 0.82 · 本土补充 v2
> 【HARD-GATE】先写失败测试再写代码；先写后补的必须删代码重来；测试不过不提交。
> 步骤: 红→绿→提交→重构→提交
> Dreambuddy 场景: sz<20 跳过实盘但要打标签；成功案例 2：[A]polling 修复、[B]VETO 缓存修复
### [元认知] systematic-debugging  匹配度 0.71 · 本土补充 v1
> 【HARD-GATE】不跳过 root-cause-tracing 第 4 阶段确认实验。
> Dreambuddy 场景: 交易 debug 必须看 /tmp/polling_trader_v3_2.log 对应时间戳。
### [应用案例] polling_trader 超时修复（B conf=0.72）
> 父: test-driven-development · 行动链 5 步 · 产出 1 个新测试 + 5 处源码修改
> 复刻要点: subprocess.Popen → Popen.communicate 必须死；异步检查点轮询；3 轮压测。

---
*工作记忆 Token 使用: 6823 tokens（process 2108 / context 2810 / task 112 / scratch 1793）*
```

### 3.6 去抖与稳定性守护

**问题**：同一会话中多次调用 recall，每次匹配结果可能抖动，process_block 来回跳 → 影响 AI 稳定。

**守护策略**（在 CognitiveLoopEntry.recall() 内部）：

```python
def recall(self, context, top_k=5, include_process=True, ...):
    # ... 已有的 memory 召回 ...

    if include_process:
        new = self._skill_loader.retrieve(context, top_meta=2, top_applied=2)
        # 合并策略（稳定优先，不是 score 优先）
        merged = {}
        # 保留旧的：如果旧条目 score ≥ new 中该 skill 最高 score * 0.9，继续留
        for pid, old in self.working_memory.process_block.items():
            meta_or_applied = extract_id(pid)
            new_score = new.get_score_for(meta_or_applied)
            if old.score >= new_score * 0.9:
                merged[pid] = old
        # 加新的：对 new 中还没在 merged 里的，替换掉 merged 中 score 最差的
        for pid, n in sorted(new.items()):
            if pid not in merged and len(merged) < 5:
                merged[pid] = n
            elif pid not in merged:
                worst_pid = min(merged.keys(), key=lambda p: merged[p].score)
                if n.score > merged[worst_pid].score:
                    del merged[worst_pid]
                    merged[pid] = n
        self.working_memory.process_block.items = merged
```

阈值 0.9 避免 0.81 vs 0.82 的小抖动；`len(merged) < 5` 限制最大条目，控制 process_block 的 token 预算（≈3000 token）。

---

## 4. 应用认知流程沉淀与元→应用映射改造

### 4.1 改造点总览：从自创 ID → 原版 Skill ID

| 组件 | 现状 | 改造后 |
|------|------|--------|
| `parent_template_id` 主键 | `TDD-001`, `DEBUG-001` 等 6 自创 | 14 个原版 Skill name + 扩展允许 |
| `session.recalled_processes` 数据 | 装的是 `ProcessTemplate` 对象（自创模板类） | 装 `SuperpowersSkill` 对象 + 补充应用层案例 |
| `TemplateMapping` 统计 | 基于自创 ID 的 success/fail | 基于原版 Skill ID，对同一 Skill 的多次应用路径合并聚合 |
| `verify_process_followed()` | 对比自创模板的 `steps: List[str]` 关键词 | 对比原版 SKILL.md 提取的 Checklist + HARD-GATE 文本 |
| 应用流程注册入口 | `register_applied_from_session(parent_template_id=自创ID)` | `register_applied_from_session(parent_skill_id=原版Skill ID)`，并新增 `parent_skill_name_to_id` 兼容映射器 |

### 4.2 会话开始：recalled_processes 的新数据结构

[cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py) 当前：
```python
self.recalled_processes: List[Any] = []   # 装的 ProcessTemplate(template_id='TDD-001', ...)
self._meta_processes: List[Any] = []      # 同上
```

改造后：
```python
self.recalled_processes: List[RecalledProcessItem] = []  # 强类型，结构清晰

@dataclass
class RecalledProcessItem:
    kind: Literal['meta', 'applied']   # 'meta' = 原版 SKILL.md；'applied' = 历史 Solution Path
    meta: Optional[SuperpowersSkill]   # kind='meta' 时，SKILL.md 解析结果（含 HARD-GATE、Checklist）
    applied: Optional[Dict]            # kind='applied' 时，应用认知流程摘要
    match_score: float                 # 本次召回的匹配分
    match_reason: str                  # 命中原因（调试用）
    skill_id: Optional[str]            # 原版 Skill ID（meta 时必填；applied 时 parent_skill_id）
    applied_id: Optional[str]          # applied 的 template_id（applied 时必填）
```

### 4.3 父 Skill 选择算法（从 6 模板 → 14 Skill 的正确匹配）

现状 `_deposit_applied_template` 对 `session._meta_processes` 按 `tmpl.confidence` 取最高分，置信度来自模板硬编码 0.85/0.80/...，**与会话实际行为无关**。

改造后：

```
Step 1：对每个被召回的 meta Skill（SuperpowersSkill 对象），计算"实际遵循度"：
         follow_score = (匹配的 Checklist 条目数 / Checklist 总数) * 0.6
                      + (匹配的 HARD-GATE 数 / HARD-GATE 总数) * 0.4
         遵循度门槛：follow_score ≥ 0.35（至少遵循 1/3 才算"真的用了这个 Skill"）

Step 2：在 follow_score ≥ 0.35 的 Skill 中，取 match_score 最高者作为主父 Skill。
         （如果多个 Skill 都被显著遵循，允许一个 applied 同时挂多个 parent_id。
          数据结构升级：TemplateMapping 支持 applied_id 对应多个 parent_id，
          统计时每条 mapping 独立计数。）

Step 3：如果没有 follow_score ≥ 0.35，说明本次会话走了自定义路径，
         parent_skill_id = 'custom-path'（特殊保留值，后续可在 supplement 中总结成新本土化 Skill）
```

### 4.4 事后校验：对照原版 Checklist/HARD-GATE

替换 `verify_process_followed(process, session.action_chain)` 为：

```python
def verify_skill_followed(skill: SuperpowersSkill, action_chain: list) -> dict:
    """
    事后校验：行动链 vs 原版 SKILL.md 的 Checklist + HARD-GATE。
    返回: {followed: bool, checklist_match: list, gate_violations: list, score: float, detail: str}
    """
    action_text = " ".join(str(a.get("detail", "")) for a in action_chain).lower()
    file_set = {a.get("file","") for a in action_chain if a["action_type"]=="file_change"}
    tools_used = {a.get("tool","") for a in action_chain if a["action_type"]=="tool_call"}
    commits = [a for a in action_chain if a["action_type"]=="git_commit"]

    checklist_matched, checklist_missed = [], []
    for item in skill.checklists:
        if _checklist_hit(item, action_text, file_set, tools_used, commits):
            checklist_matched.append(item)
        else:
            checklist_missed.append(item)

    gate_violations, gate_respected = [], []
    for gate in skill.hard_gates:
        if _gate_violated(gate, action_text, file_set, tools_used, commits):
            gate_violations.append(gate)
        else:
            gate_respected.append(gate)

    check_pct = len(checklist_matched) / max(1, len(skill.checklists))
    gate_pct  = len(gate_respected)  / max(1, len(skill.hard_gates))
    score     = check_pct * 0.6 + gate_pct * 0.4   # HARD-GATE 40% 权重（违反就是减分项）

    return {
        "followed": score >= 0.35,
        "score": round(score,2),
        "checklist_matched": checklist_matched,
        "checklist_missed": checklist_missed,
        "gate_violations": gate_violations,
        "gate_respected": gate_respected,
        "detail": (
            f"checklist {len(checklist_matched)}/{len(skill.checklists)} "
            f"HARD-GATE respected {len(gate_respected)}/{len(skill.hard_gates)}"
        ),
    }
```

**关键创新：HARD-GATE 的"违反"判定，不是正向匹配，是反向排除**。例如 TDD 的 HARD-GATE 是"如果先写了代码后补测试，删除代码重来"——判定条件就是：
- 行动链中出现 `写代码` 类动作（修改 .py/.ts）**先于** `写测试` 类动作（新增 /tests/ 或 `test_*.py`），且测试后没有再出现"删除该代码段"的记录，就判定违反 gate。
- 只看相对时序，不靠关键词语义瞎猜。

### 4.5 应用认知流程沉淀的新字段

`register_applied_from_session` 现在写进 applied JSON 的元数据太平。新增 5 个高价值字段：

```python
# applied ProcessTemplate.metadata 新增：
{
  # === 既有 ===
  "unit_id": "MU-DEV" | "MU-TRD" | ...
  "problem": "...",
  "action_count": 42,
  "files_touched": [...],
  "duration_minutes": 36.1,
  "success": True,
  "commit_hash": "abc123",
  "created_at": 1785500000,

  # === 新增（本次改造） ===
  "parent_skill_ids": ["test-driven-development", "systematic-debugging"],  # 可多个父 Skill
  "process_verify_report": {           # 本次会话事后校验结果（关键）
      "test-driven-development": {
          "score": 0.78,
          "followed": True,
          "checklist_matched": [3 items],
          "checklist_missed":  [1 item],
          "gate_violations": [],
      },
      "systematic-debugging": {"score": 0.41, "followed": False, ...}
  },
  "task_type": "trading-system",       # 沉淀时的 task_type（检索用）
  "reproducible_steps": [              # 从行动链合并后的人类可读步骤（5-15 条）
      "读 polling_trader.py 主循环定位 subprocess 调用",
      "写失败测试 test_timeout_subprocess_poll，stub OKX 504",
      "替换 communicate(timeout=) 为 Popen + 异步检查点轮询",
      "红→绿：测试通过后 commit",
      "3 轮压测无误后，commit 重构",
  ],
  "key_artifacts": {                   # 关键产物清单
      "added_files": ["11-易经推理系统/tests/test_timeout_subprocess_poll.py"],
      "modified_files": ["4-MEMORY/9-工具与接口/cognitive_session.py", ...],
      "debt_items": ["TODO: sz<20 实盘跳过需在 yijing_exit_system.py 也同样处理"],
  },
}
```

`reproducible_steps` 不是事后 LLM 生成，而是对行动链做**压缩合并**（相邻的同文件小 edit 合并、纯注释改动剔除），保证 100% 可追溯到 commit，消除幻觉。

### 4.6 迁移：把旧 mapping（TDD-001 → ...）映射回新版 Skill ID

`template_mappings.json` 目前存的是 `parent_id = TDD-001 / DEBUG-001`。迁移脚本做一张"退化兼容映射表"（完整表见附录 B）：

```python
LEGACY_TO_NEW = {
    "TDD-001":        "test-driven-development",
    "DEBUG-001":      "systematic-debugging",
    "REFACTOR-001":   "test-driven-development",   # 重构本质也走红-绿
    "REVIEW-001":     "requesting-code-review",
    "DESIGN-001":     "brainstorming",
    "TDD-DEBUG-001":  "subagent-driven-development",  # 复合流程 → SDD（两阶段审查复合）
}
```

迁移脚本同时做两件事：
1. 改写 `template_mappings.json` 的 `parent_id` 字段（old → new），同名冲突合并 success/fail 计数。
2. 给所有旧 applied JSON 的 `parent_skill_ids` 补退化值，`metadata.legacy_template_id = TDD-001` 留作溯源。

迁移后验证：`cognitive_superpowers.py --mapping` 输出后目测 parent_id 都是原版 Skill name，退化映射打上 `[LEGACY]` 标签。

---

## 5. 现有代码改造清单 + TS 层处置

### 5.1 TS 层（C 层交易 Planner）处置决策：改名保留，不删除，与认知层解耦

**结论**：两个 TS 文件不删，但**改名 + 注释澄清定位 + 断开与"Superpowers Skill 体系"的绑定**——它们本质是**交易 Planner 的节点质量门禁代码**，不是 Superpowers 的通用实现。和认知层的 Process Layer 是两条平行的独立职责链：

```
Process Layer（Python 认知层）     vs     C 层 Methodology Gate（TypeScript 交易 Planner）
  ├─ 载体：SKILL.md Markdown 注入         ├─ 载体：MethodologyExecutor 代码包装器
  ├─ 遵循机制：AI 读后自主 Prompt 自约束   ├─ 遵循机制：GraphExecutor 节点前后硬拦截检查
  ├─ 作用范围：所有开发任务（通用）         ├─ 作用范围：S5/developer/code 类交易策略开发节点
  └─ 结果：WorkingMemory.process_block     └─ 结果：节点执行时的 Spec 审查 + 质量审查报告
```

这两个体系互不冲突，甚至能互补——交易开发任务在 Planner 内部受 MethodologyExecutor 硬门禁约束，同时 AI 侧读着 process_block 里的原版 `test-driven-development` SKILL.md 自主遵循，双保险。

#### 具体改造：

| 文件 | 操作 | 改动点 |
|------|------|--------|
| [methodology-executor.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/methodology-executor.ts) | 改名注释（不删代码） | 1. L1-L23 头部注释：把"Claude Code Superpowers 7阶段方法论"改为「C 层交易节点质量门禁（借鉴 Superpowers 理念，不等价于 Superpowers Skill 体系，与认知层 Process Layer 解耦）」。<br>2. L6 去除与 Superpowers 7 阶段的直接绑定声明。<br>3. L14-L18 注释加一句：「注：更完整的方法论在通用认知层 Process Layer（SKILL.md）；本文件仅做 Planner 节点级代码门禁。」 |
| [superpowers-skill-adapter.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩/planner/superpowers-skill-adapter.ts) | 注释澄清 + 可选改名 | 1. L1-L16 头部：注释改为「SKILL.md 格式解析器（TypeScript 版）——仅用于把外部标准 SKILL.md 文档解析为 SkillCapability 对象，不负责执行；通用认知层对应实现位于 4-MEMORY/ 的 Python SkillLoader」。<br>2. （可选，低优先级）文件名改名为 `skill-md-parser.ts`，去掉"superpowers"字样。**不做也不影响功能**，建议留到本轮迁移的最后再做。 |

**不改造**：MethodologyExecutor 的 `wrapExecution` / `performTwoPhaseReview` 核心逻辑——它确实对交易开发节点有实际门禁价值（Spec 合规 + 置信度审查），保留它。

### 5.2 Python 层改造清单

#### 改 1：`cognitive_superpowers.py` — 核心骨架替换（设计节 2）

**位置**：[4-MEMORY/9-工具与接口/cognitive_superpowers.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_superpowers.py)

**删除的大块代码**（≈ 350 行，约 40%）：
- `DEFAULT_TEMPLATES`：整个 TDD-001 ~ TDD-DEBUG-001 6 个自创模板定义
- `ProcessTemplate` 类的 `confidence / estimated_tokens / applicable_stages / applicable_intents / success_ratio` 等硬编码字段
- `_DEFAULT_PROCESS_RULES` / `PROCESS_KEYWORDS` 手写硬编码表

**新增/替换**：
- `SuperpowersSkill` 数据类（设计节 2.2）
- `SkillLoader` 类：
  - `_validate_frontmatter_format(content, path)` — 格式红线校验
  - `_parse_skill_md(content)` — frontmatter + HARD-GATE + Checklist 提取
  - `_load_supplement(dir)` — 读同级 dreambuddy-supplement.md
  - `load_all()` — 遍历 `4-MEMORY/0-元记忆/superpowers/skills/*/SKILL.md`，异常隔离
  - `_rebuild_index_cache()` → 写 `skills-index.json`
  - `retrieve(context, top_meta, top_applied)` → 按设计节 2.3 评分算法召回
- `TemplateMappingRegistry` 小改：`TemplateMapping.parent_id` 从自创 ID 改为原版 Skill name；迁移时 `LEGACY_TO_NEW` 退化表（附录 B）写在该类 `_migrate_legacy_keys()` 静态方法里，启动时自动跑一次

#### 改 2：`working_memory_manager.py` — 新增 process_block（设计节 3.2）

**位置**：[4-MEMORY/9-工具与接口/working_memory_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/working_memory_manager.py)

改动量小（≈ 80 行新增）：
- `DEFAULT_BUDGETS` 加 `process: 3000`
- `__init__` 加 `self.process_block = MemoryBlock(...)` 并设 `_readonly = True`
- `load_process_block(markdown: str)` 公开方法：供 recall 写入
- `get_prompt_context()`：在末尾追加 process_block 段 Markdown 渲染
- `_report_token_usage()`：process_block 计入总账

#### 改 3：`cognitive_mcp_server.py` — recall 返回值加 processes 字段（设计节 3.3）

**位置**：[4-MEMORY/9-工具与接口/cognitive_mcp_server.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_mcp_server.py)

改动量中等（≈ 60 行新增）：
- `_handle_recall` 内：若 `include_process=True`（默认 True），调用 `cle.skill_loader.retrieve()`
- 组装 `processes` 字段（meta[] / applied[] / process_block_markdown），按设计节 3.3 JSON 结构
- 同时调用 `cle.working_memory.load_process_block(process_block_markdown)`
- 静默模式加开关：`include_process=False` 时行为与现在完全一致（向后兼容）

#### 改 4：`cognitive_session.py` — 流程关联大改（设计节 4）

**位置**：[4-MEMORY/9-工具与接口/cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py)

改动量中到大（≈ 180 行改造）：
- `session.recalled_processes` 字段类型改为 `List[RecalledProcessItem]`（设计节 4.2）
- `_deposit_applied_template`：父 Skill 选择算法改为设计节 4.3（follow_score = Checklist*0.6 + HARD-GATE*0.4，≥0.35 才算真用）；允许多 parent_id
- `post_hoc_verify` 的 `verify_process_followed` → 替换为 `verify_skill_followed`（设计节 4.4，含相对时序 HARD-GATE 判定）
- `register_applied_from_session`：applied.metadata 新增 5 字段（设计节 4.5）
- `reproducible_steps` 压缩函数 `_condense_action_chain(action_chain)` 新增

#### 改 5：`cognitive_install.py` + hooks/ — SessionStart 静默 recall（设计节 3.4，路径 B）

**位置**：[4-MEMORY/9-工具与接口/cognitive_install.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_install.py) + hooks/ 目录

改动量小（≈ 40 行脚本）：
- Claude Code / TRAE / Cursor 三个宿主的 `session-start.sh` / 对应 hook 文件：追加后台 Python 命令，实现预热
- 用 `&` 后台运行，不阻塞 AI 首条响应
- 预热写 WorkingMemory 时检测"已预热就跳过"

#### 改 6：`cognitive_daemon.py` — 后台新会话自动预热（设计节 3.1，路径 C）

**位置**：[4-MEMORY/9-工具与接口/cognitive_daemon.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_daemon.py)

改动量极小（≈ 20 行新增）：
- `on_new_session_created(session_id, initial_msg)` 事件处理：调用 SkillLoader 做初始召回，写入 WorkingMemory
- 对"非交互型批量任务"仅预热不触发用户侧提醒
- 与路径 B 做去重：如果 WorkingMemory.process_block 非空，跳过

### 5.3 新增文件清单

| 新增文件 | 说明 | 预估代码量 |
|---------|------|----------|
| `4-MEMORY/0-元记忆/superpowers/skills/*/SKILL.md` | 原版 14 个 Skill Markdown（拉 upstream 或手工导入） | 14 个 Markdown 文件 |
| `4-MEMORY/0-元记忆/superpowers/skills/*/dreambuddy-supplement.md` | 我们的本土补充（初始可为空 14 个占位文件） | 14 个 Markdown 占位 |
| `4-MEMORY/0-元记忆/superpowers/skills-index.json` | SkillLoader 自动生成的缓存 | 自动 ≈20KB |
| `4-MEMORY/0-元记忆/superpowers/README.md` | 维护规范 | ≈ 180 行 Markdown |
| `4-MEMORY/9-工具与接口/tests/test_skill_loader.py` | SkillLoader 单测 | ≈ 250 行 |
| `4-MEMORY/9-工具与接口/tests/test_process_recall.py` | recall + process_block + 去抖合并 单测 | ≈ 220 行 |
| `4-MEMORY/9-工具与接口/tests/test_applied_flow.py` | 父 Skill 选择 / verify / 迁移退化表 单测 | ≈ 280 行 |
| `4-MEMORY/9-工具与接口/scripts/migrate_legacy_mappings.py` | 一次性迁移脚本 | ≈ 120 行 |

### 5.4 废弃 / 存档的代码

不直接删除，移到 `4-MEMORY/_archive/` 目录加 `_ARCHIVED_` 前缀：

| 原位置 | 存档后 | 原因 |
|--------|--------|------|
| `cognitive_superpowers.py` 内 `DEFAULT_TEMPLATES` 6 个自创 ID 定义 | 提取为 `_ARCHIVED_legacy_process_templates.py` | 保留回溯：当时为什么自创 6 类、每类 step 原文 |
| `process_templates.json` 原目录 | 复制一份到 `_ARCHIVED_process_templates_backup_YYYYMMDD.json` | 迁移脚本回滚备份用 |
| `template_mappings.json` 旧版本 | 同上，备份一份迁移前快照 | — |

### 5.5 改动量总览

| 维度 | 数量 | 预估代码量 |
|------|------|----------|
| Python 改造文件 | 6 个 | ≈ 500 行改 / 300 行删 |
| TS 注释澄清 | 2 个 | ≈ 20 行注释改 |
| 新增文件 | 8 类（34 个 Markdown + 3 个测试 + 1 README + 1 迁移脚本 + 1 自动 JSON） | ≈ 850 行 |
| 归档 / 备份 | 3 个 | 0 行新增（仅搬迁） |
| 合计 | — | ≈ 改 520 + 删 300 + 增 850 = **净 +1070 行** |

---

## 6. 迁移策略与验收标准

### 6.1 迁移分四阶段执行（每阶段独立可验收，允许中途暂停）

```
阶段 1：基础设施搭建（无侵入，不影响线上）
  ├─ 1.1 拉取原版 14 个 SKILL.md → 4-MEMORY/0-元记忆/superpowers/skills/<name>/SKILL.md
  ├─ 1.2 创建 14 个 dreambuddy-supplement.md 占位文件
  ├─ 1.3 写 4-MEMORY/0-元记忆/superpowers/README.md（维护规范 + 格式红线）
  └─ 1.4 实现 SkillLoader 类 + skills-index.json 自动构建
  验收 1：SkillLoader.load_all() 解析 14 个 SKILL.md 全部成功；index.json 生成
  风险：低 · 可并行 · 不动现有 cognitive_*.py

阶段 2：单元测试 + 旧代码归档（隔离沙箱，不动主链路）
  ├─ 2.1 备份 process_templates.json / template_mappings.json 到 _ARCHIVED_*
  ├─ 2.2 提取 DEFAULT_TEMPLATES 到 _ARCHIVED_legacy_process_templates.py
  ├─ 2.3 写 test_skill_loader.py / test_process_recall.py / test_applied_flow.py
  ├─ 2.4 跑全量单测（独立 pytest，不接 daemon）
  └─ 2.5 跑 migrate_legacy_mappings.py（dry-run 模式，仅打印结果不写盘）
  验收 2：单测 100% 通过；dry-run 迁移输出符合预期；旧业务仍能跑
  风险：中 · 主要在测试代码 · 失败可重写不影响生产

阶段 3：主链路改造（动 cognitive_superpowers / working_memory / mcp_server / session）
  ├─ 3.1 cognitive_superpowers.py 删除自创 6 模板，替换为 SkillLoader + SuperpowersSkill
  ├─ 3.2 working_memory_manager.py 新增 process_block + get_prompt_context 渲染
  ├─ 3.3 cognitive_mcp_server.py recall 返回值加 processes 字段
  ├─ 3.4 cognitive_session.py 改 recalled_processes 数据结构 + verify_skill_followed + 5 字段
  └─ 3.5 跑阶段 2 的单测，确保全部通过
  验收 3：单测 100% 通过；cognitive_daemon 重启后能正常 record/recall；旧 mapping 自动迁移完成
  风险：高 · 这是关键阶段 · 失败立即触发回滚（见 6.4）

阶段 4：兜底路径 + 灰度上线
  ├─ 4.1 cognitive_install.py + hooks/session-start.sh 实现 SessionStart 静默 recall
  ├─ 4.2 cognitive_daemon.py 加 on_new_session_created 后台预热
  ├─ 4.3 跑 migrate_legacy_mappings.py（apply 模式，正式写盘）
  ├─ 4.4 灰度观察期 7 天：每天抽样检查 process_block 注入、mapping 统计累积
  └─ 4.5 阶段 4 结束后，TS 层注释澄清一次性提交
  验收 4：灰度期间无异常；新 applied 至少 5 条带 parent_skill_ids；mapping 统计正常累积
  风险：低 · 兜底路径独立可关 · 失败不影响主链路
```

### 6.2 九条验收标准

| # | 验收项 | 验证方式 | 通过条件 |
|---|--------|---------|---------|
| V1 | SKILL.md 格式合规 | SkillLoader 启动日志 | 14 个全部 `OK`，无 frontmatter 红线告警 |
| V2 | skills-index.json 自动重建 | 删除后重启 daemon | 5 秒内重新生成，14 个条目，md5 全部非空 |
| V3 | recall 返回 processes 字段 | `cognitive-cli recall "测试 TDD"` | JSON 含 `processes.meta` ≥ 1 条，`match_score > 0`，`hard_gates` 非空 |
| V4 | WorkingMemory.process_block 注入 | recall 后查 daemon 内部状态 | `process_block.items` 至少 2 条，token 占用 < 3500 |
| V5 | System Prompt 渲染 | `cognitive-cli working-memory dump` | 末尾出现 `## 🎯 流程建议` 段，含 HARD-GATE 文本 |
| V6 | 旧 mapping 迁移完成 | 迁移脚本 dry-run + apply | 所有 `parent_id` 都在 14 原版 Skill name 列表中（或 `custom-path`）；`legacy_template_id` 字段保留 |
| V7 | 事后校验生效 | 模拟一个完整会话 commit | applied 元数据含 `process_verify_report`，`score ∈ [0,1]`，`followed` 布尔值合理 |
| V8 | 异常隔离 | 故意写坏一个 SKILL.md（改 frontmatter 为 `***`）| SkillLoader 报错带文件路径，其余 13 个继续可用，daemon 不崩 |
| V9 | 向后兼容 | 旧版宿主用 `include_process=False` 调 recall | 返回 JSON 与改造前完全一致（仅 `memories` + `count`） |

### 6.3 风险点与缓解措施

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| SKILL.md upstream 拉取后格式不标准（frontmatter 用 `***`） | 中 | SkillLoader 解析失败 | 经验 95953 已吸收：加载器做格式校验，不合规文件跳过+告警，不影响其他 13 个 |
| 旧 applied JSON 缺 `parent_skill_ids` 字段，session 加载报错 | 高 | 历史案例无法召回 | 迁移脚本批量补字段（默认值 `["custom-path"]`），session 加载时再兜底 `metadata.get("parent_skill_ids", ["custom-path"])` |
| process_block token 预算超限（3000 不够装 2 meta + 2 applied） | 中 | System Prompt 截断 | SkillLoader.retrieve 默认 top_meta=2 top_applied=2；每条 meta 截 HARD-GATE + 前 600 字；applied 只装摘要不装全文；超限时按 match_score 淘汰最低分 |
| 同会话多次 recall 导致 process_block 抖动 | 中 | AI 看到流程建议来回变 | 设计节 3.6 去抖合并（0.9 阈值 + top 5 上限） |
| daemon 重启后 skills-index.json 没重建 | 低 | recall 返回空 processes | SkillLoader `__init__` 检测 index 缺失或 md5 不匹配时强制重建 |
| 迁移脚本误覆盖 mapping | 中 | 历史 success/fail 统计丢失 | 必须先 dry-run，对比结果人工确认后才 apply；apply 前自动备份 |
| 灰度期发现 follow_score 0.35 阈值过严 | 中 | 应用层无法关联元流程 | 阈值在 cognitive_session.py 用常量 `FOLLOW_SCORE_THRESHOLD = 0.35`，可热调；灰度第 3 天看分布，若 > 40% 会话是 custom-path，下调到 0.25 |

### 6.4 回滚条件（任一触发立即回滚到阶段 3 之前的状态）

1. **认知系统崩溃**：cognitive_daemon 启动失败或运行中 OOM，且修复耗时 > 30 分钟 → 立即回滚 cognitive_superpowers.py / cognitive_session.py 到改造前 git commit
2. **recall 接口异常率 > 20%**：灰度期内 `cognitive-cli recall` 调用失败率超阈值 → 关闭 `include_process` 默认开关（`False`），让 recall 退回老协议
3. **数据损坏**：`template_mappings.json` 或 applied JSON 出现字段缺失导致历史案例无法加载 → 用 `_ARCHIVED_*_backup_YYYYMMDD.json` 覆盖恢复
4. **AI 行为异常**：process_block 注入后 AI 出现"反复纠结流程选择不干活"或"硬套 SKILL.md 步骤导致任务跑偏" → 关闭 SessionStart hook（路径 B）和 daemon 后台预热（路径 C），仅保留显式 recall（路径 A）

完整回滚操作见附录 D。

### 6.5 灰度观察期检查表（阶段 4 上线后 7 天，每天一次）

| 检查项 | 命令 | 期望 |
|--------|------|------|
| daemon 健康 | `cognitive-cli healthcheck` | `status: healthy` |
| SKILL.md 完整性 | `cognitive-cli skills list` | 14 个全部 `loaded` |
| recall 命中率 | `cognitive-cli stats recall` | `process_hit_rate > 60%` |
| process_block 注入次数 | 日志统计 | 每天 ≥ 5 次（说明三路径都在工作） |
| 新 applied 关联率 | `cognitive-cli stats applied` | 灰度期间新 applied 中 `parent_skill_ids != ['custom-path']` 的比例 > 60% |
| mapping 统计累积 | `cognitive-cli stats mapping` | 至少 1 个 Skill 的 success 计数 ≥ 3 |
| 异常日志 | `grep -i error /tmp/cognitive-daemon.log` | 无 `SkillLoader` / `process_block` 相关 ERROR |

### 6.6 完成后的"认知闭环"状态（设计目标）

迁移完成后，[COGNITIVE_ARCHITECTURE.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/COGNITIVE_ARCHITECTURE.md) 第 4.4 节设计的会话闭环真正打通：

```
任务开始
  ↓ recall 注入: 领域知识 + 经验记忆 + 元认知流程（SKILL.md）+ 应用案例（Solution Path）
  ↓ AI 阅读流程建议，自主遵循 HARD-GATE
  ↓ 执行任务（行动链记录）
  ↓ commit 触发 cognitive_hook
  ↓ 事后校验: 行动链 vs SKILL.md 的 Checklist + HARD-GATE
  ↓ 沉淀: Solution Path（带 parent_skill_ids + process_verify_report）
  ↓ 贝叶斯更新: Solution Path 置信度 C→B→A→S
  ↓ (可选) Supplement 完善: 多次验证的本土经验写入 dreambuddy-supplement.md
  ↓ 下次同类任务 recall 时，能召回更精准的流程 + 更高质量的案例
```

**"用得越久越聪明"** 真正成立：原版 SKILL.md 是静态基线，应用层 Solution Path 通过贝叶斯进化提升质量，supplement 沉淀本土经验——三层叠加，每次 recall 都比上次更准。

---

## 7. 思维路径评测与飞书告警闭环（推理模型特质）

### 7.1 设计动机

设计节 1–6 解决了"流程注入+沉淀"的基础设施，但缺一个关键环节：**注入的流程建议是否真的让 AI 做得更好？** 没有评测，就无法区分"AI 自身能力强"与"process_block 注入有效"——这违背 project_memory 的硬约束"优化落地必须回测验证+贝叶斯参数优化"。

本节引入**思维路径评测闭环**，借鉴 [16-调控系统/evolution_loop.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/16-调控系统/core/evolution_loop.py) 的进化循环模式，应用到认知层——**好则学习（升 Solution Path 质量等级），有历史则先评测**，这正是推理模型的特质。

### 7.2 闭环全景

```
任务结束（commit 触发 cognitive_hook）
  ↓
[1] 压缩思维链+行动链 → 生成评测样本
  ↓
[2] A/B 对比评测（有 process_block vs 无 process_block 的成效差异）
  ↓
[3] 决策分支
    ├─ 路径优势显著(得分↑) → 学习: 升级 Solution Path 质量等级 + 更新 supplement
    ├─ 路径异常/bug/退化(得分↓) → 飞书告警 + 触发回滚条件（设计节 6.4）
    └─ 表现平庸 → 标记"待观察"，不立即学习也不告警
  ↓
[4] 反哺下次 recall
    └─ process_block 注入时附带"历史评测得分"+"验证次数"
        （让 AI 像推理模型一样参考历史决策质量）
```

### 7.3 思维链/行动链压缩（评测样本生成）

> **参考实现**：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 的 `trajectory_compressor.py` — 借鉴其"trajectory → 压缩样本"的工程模式（相邻合并/纯注释剔除/关键决策点提取），避免重复造轮。实施时先研究其源码再适配我们的 action_chain 数据结构。

**现状**：[cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py) 的 `action_chain` 已记录所有文件变更/工具调用/commit，但未做"思维链"压缩。

**新增**：`_compress_thought_chain(action_chain, reasoning_log) → EvaluationSample`

```python
@dataclass
class EvaluationSample:
    session_id: str
    task_summary: str                    # 任务一句话描述
    skill_ids_injected: List[str]        # 本次注入的 process_block 包含哪些 Skill
    thought_chain_compressed: List[str]  # 思维链压缩：5-15 个关键决策点
    action_chain_compressed: List[str]   # 行动链压缩：reproducible_steps（设计节 4.5 已有）
    hard_gate_violations: List[str]      # 本次违反的 HARD-GATE 列表
    outcome_metrics: Dict[str, float]    # 成效指标（见 7.4）
    timestamp: int
```

**思维链压缩规则**（不靠 LLM 生成，纯结构化提取，消除幻觉）：
1. 从 `reasoning_log`（AI 思考过程的工具调用上下文）提取"关键决策点"：每次 `recall()` 调用、每次 `verify` 调用、每次 `_deposit_applied_template` 触发
2. 相邻的纯查询动作合并（如连续 3 次 Read 同一文件 → 1 条"查阅文件 X"）
3. 纯注释/空行 edit 剔除
4. 输出 5-15 条人类可读步骤，与 `reproducible_steps`（行动链压缩）形成"思维-行动"对照

### 7.4 A/B 对比评测（思维路径优势验证）

> **参考实现**：[prime-radiant-inc/superpowers-evals](https://github.com/prime-radiant-inc/superpowers-evals) 的 drill eval harness — 借鉴其"如何测试一个 Skill 是否真的让 AI 做得更好"的测试方法论（测试用例定义、评分标准、CI 集成）。我们的 `evaluation_engine.py` 在其基础上增加 A/B 对比层（有注入 vs 无注入的成效差异）。

**评测基准**：同任务跑两次，对比"有 process_block 注入" vs "无注入"的成效差异。

**成效指标**（`outcome_metrics`）：

| 指标 | 定义 | 数据来源 |
|------|------|---------|
| `task_completion_success` | 任务是否成功完成（0/1） | session.success |
| `hard_gate_violation_count` | 违反 HARD-GATE 次数 | verify_skill_followed 报告 |
| `rework_count` | 重做次数（同文件被反复修改） | action_chain 统计 |
| `tool_call_efficiency` | 有效工具调用占比（非查询类/总调用） | action_chain 统计 |
| `duration_minutes` | 任务耗时 | session.end - session.start |
| `follow_score` | 对 Skill 的实际遵循度（设计节 4.3） | verify_skill_followed.score |

**A/B 实施策略**（不要求每次任务都跑两遍，成本太高）：

```
策略 1（默认，低成本）：历史对照
  └─ 当前会话（有注入）的 outcome_metrics vs 同类任务历史均值（无注入基线）
  └─ 历史基线从 16-调控系统的 exit-evaluations 历史数据中统计

策略 2（抽样，中成本）：影子对照
  └─ 10% 的会话做"影子运行"：任务完成后，用无 process_block 的配置重跑一次
  └─ 对比两次 outcome_metrics 差异

策略 3（关键变更，高成本）：全量 A/B
  └─ 仅在 Superpowers 集成上线初期（阶段 4 灰度前 7 天）做全量 A/B
  └─ 验证 process_block 注入的整体收益，灰度结束后切回策略 1
```

**思维路径优势得分**：

```python
def compute_path_advantage(current: EvaluationSample, baseline: EvaluationSample) -> float:
    """
    返回 [-1.0, 1.0]：正值表示 process_block 注入有优势，负值表示退化
    """
    scores = []
    # 成功率提升
    scores.append(+1.0 if current.task_completion_success and not baseline.task_completion_success else 0)
    # HARD-GATE 违反减少
    if baseline.hard_gate_violation_count > 0:
        reduction = (baseline.hard_gate_violation_count - current.hard_gate_violation_count) / baseline.hard_gate_violation_count
        scores.append(reduction * 0.3)
    # 重做次数减少
    if baseline.rework_count > 0:
        scores.append((baseline.rework_count - current.rework_count) / baseline.rework_count * 0.2)
    # 耗时减少（不超过 30% 权重，避免为快而牺牲质量）
    if baseline.duration_minutes > 0:
        time_reduction = (baseline.duration_minutes - current.duration_minutes) / baseline.duration_minutes
        scores.append(max(-0.3, min(0.3, time_reduction * 0.3)))
    # follow_score 提升
    scores.append((current.follow_score - baseline.follow_score) * 0.2)

    return max(-1.0, min(1.0, sum(scores)))
```

### 7.5 学习/回滚决策（基于评测得分）

```
path_advantage = compute_path_advantage(current, baseline)

if path_advantage >= +0.2:
    → 学习：升级 Solution Path 质量等级
    ├─ C → B：连续 2 次 path_advantage ≥ +0.2
    ├─ B → A：连续 4 次 path_advantage ≥ +0.2
    ├─ A → S：连续 8 次 path_advantage ≥ +0.2 + 人工抽检确认
    └─ 更新 dreambuddy-supplement.md（若同一本土经验被验证 ≥ 3 次）

elif path_advantage <= -0.2 or hard_gate_violation_count >= 2:
    → 异常：触发飞书告警 + 评估是否回滚
    ├─ 单次异常：告警 + 标记 Solution Path "待观察"
    ├─ 连续 2 次 path_advantage ≤ -0.2：降级质量等级（B → C）
    ├─ 连续 3 次 path_advantage ≤ -0.2 或 hard_gate 违反率 > 30%：
    │   触发设计节 6.4 回滚条件 + 飞书告警
    └─ 回滚后该 Solution Path 标记 "quarantined"（隔离），recall 时不再召回

else:
    → 平庸：标记 "observational"，不学习也不告警
    └─ 累积 5 次 observational 后重新评估
```

### 7.6 飞书告警闭环（回滚条件联动）

**集成现有组件**：[15-监控告警系统/feishu_alert.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/15-监控告警系统/feishu_alert.py) 已实现飞书告警能力，本节定义触发规则和告警内容。

**触发条件**（与设计节 6.4 回滚条件一一对应）：

| 回滚条件 | 飞书告警级别 | 告警内容 |
|---------|------------|---------|
| 认知系统崩溃（daemon OOM/启动失败） | 🔴 Critical | daemon PID、崩溃时间、最后日志 10 行、建议回滚命令 |
| recall 异常率 > 20% | 🔴 Critical | 异常率、失败样本 3 条、建议关闭 `include_process` |
| 数据损坏（mapping/applied JSON 字段缺失） | 🔴 Critical | 损坏文件路径、缺失字段、建议恢复命令 |
| AI 行为异常（process_block 注入导致跑偏） | 🟡 Warning | 会话 ID、异常表现描述、建议关闭路径 B/C |
| path_advantage ≤ -0.2 连续 2 次 | 🟡 Warning | Skill ID、得分、退化指标对比 |
| HARD-GATE 违反率 > 30%（周统计） | 🟡 Warning | Skill ID、违反次数、典型违反案例 |

**告警消息格式**（接入 feishu_alert.py）：

```python
def _build_alert_message(condition: str, level: str, context: dict) -> dict:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"{'🔴' if level=='Critical' else '🟡'} 认知系统告警 · {condition}"},
                "template": "red" if level == "Critical" else "yellow",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**触发时间**: {datetime.now()}"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**触发条件**: {condition}"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**上下文**: ```{json.dumps(context, ensure_ascii=False, indent=2)}```"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**建议操作**: 见 superpowers-integration-design.md 附录 D"}},
                {"tag": "action", "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "查看设计文档"}, "url": "docs/superpowers/specs/superpowers-integration-design.md"},
                    {"tag": "button", "text": {"tag": "plain_text", "content": "查看 daemon 日志"}, "url": "/tmp/cognitive-daemon.log"},
                ]},
            ],
        },
    }
```

**告警去重**：同一 condition + 同一 Skill ID 的告警，10 分钟内只发一次（避免刷屏）。

### 7.7 反哺 recall（推理模型特质的体现）

**核心改动**：process_block 注入时，每条 Solution Path 附带"历史评测得分"+"验证次数"，让 AI 像推理模型一样参考历史决策质量做选择。

[设计节 3.2](#32-workingmemory-新增-process_block) 的 process_block 条目结构扩展：

```markdown
### [应用案例] polling_trader 超时修复（B conf=0.72）
> 父: test-driven-development · 行动链 5 步 · 产出 1 个新测试 + 5 处源码修改
> 复刻要点: subprocess.Popen → Popen.communicate 必须死；异步检查点轮询；3 轮压测。
> 📊 历史评测: path_advantage +0.38 · 验证 8 次 · 最近 3 次均优势 · 无 HARD-GATE 违反
```

新增的 `📊 历史评测` 行让 AI 在选择复刻路径时有数据支撑：
- `path_advantage +0.38`：这条路径历史表现优秀（正值=有优势）
- `验证 8 次`：样本量足够，置信度高
- `最近 3 次均优势`：近期仍然有效，不是过时经验
- `无 HARD-GATE 违反`：路径合规

**反之**，如果某条 Solution Path 是 `quarantined` 状态，recall 时直接过滤不召回，避免 AI 复刻已退化的路径。

### 7.8 实施改造点（增量于设计节 5）

| 改造点 | 文件 | 说明 |
|--------|------|------|
| 思维链压缩 | [cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py) | 新增 `_compress_thought_chain()`，生成 EvaluationSample |
| A/B 评测引擎 | 新增 `4-MEMORY/9-工具与接口/evaluation_engine.py` | `compute_path_advantage()` + 历史基线管理 |
| 学习/回滚决策 | [cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py) | `_deposit_applied_template` 调用评测引擎，根据得分决定升/降级 |
| 飞书告警集成 | 新增 `4-MEMORY/9-工具与接口/alert_bridge.py` | 桥接 cognitive_hook → 15-监控告警系统/feishu_alert.py |
| Solution Path 质量等级扩展 | [cognitive_superpowers.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_superpowers.py) | 增加 `quarantined` 状态 + `path_advantage_history` 字段 |
| recall 过滤 | [cognitive_mcp_server.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_mcp_server.py) | retrieve 时过滤 quarantined，注入时附带历史评测 |
| 历史评测数据 | 新增 `4-MEMORY/0-元记忆/evaluation_history.jsonl` | 每次评测追加一行，供历史基线统计 |

### 7.9 验收标准（增量于设计节 6.2）

| # | 验收项 | 验证方式 | 通过条件 |
|---|--------|---------|---------|
| V10 | 思维链压缩生效 | 完成一个会话后查 EvaluationSample | thought_chain_compressed 5-15 条，无幻觉 |
| V11 | A/B 评测输出 path_advantage | 跑 5 个样本任务 | 每个任务输出 [-1.0, 1.0] 区间得分 |
| V12 | 学习决策生效 | 模拟 path_advantage ≥ +0.2 连续 2 次 | Solution Path 自动 C → B |
| V13 | 飞书告警触发 | 模拟 daemon 崩溃 | 飞书收到 🔴 Critical 卡片，含崩溃上下文 |
| V14 | quarantined 过滤 | 把一条 Solution Path 标记 quarantined | recall 不再召回该条 |
| V15 | 历史评测反哺 | recall 后查 process_block | 应用案例含 `📊 历史评测` 行 |

### 7.10 与设计节 6 迁移策略的关系

本节扩展**不改变**设计节 6 的四阶段迁移节奏，而是作为**阶段 4 灰度期的核心验证手段**：

- 阶段 4 灰度 7 天内，用 A/B 评测（策略 3 全量 A/B）验证 process_block 注入的整体收益
- 灰度结束后切回策略 1（历史对照），作为长期持续评测机制
- 飞书告警从阶段 4 第一天就启用，与回滚条件联动

**如果灰度期 A/B 评测显示 path_advantage 平均值 < 0**（注入无优势甚至有负面影响），触发回滚条件 1（认知系统效果不达预期），回到设计节 6.4 的回滚流程。

---

## 附录 A：数据结构汇总

### A.1 SuperpowersSkill（元认知流程数据类）

```python
@dataclass
class SuperpowersSkill:
    skill_id: str                    # 原版 name：test-driven-development
    display_name: str                # frontmatter name 原文
    description: str                 # frontmatter description
    version: str                     # "upstream v6.2.0 + dreambuddy supplement v1"
    raw_skill_md: str                # SKILL.md 原文
    hard_gates: List[str]            # 提取出的 <HARD-GATE> 内容
    checklists: List[str]            # 提取出的 Checklist
    trigger_keywords: List[str]      # 汇总的触发词
    supplement: Optional[str]        # dreambuddy-supplement.md 内容
    md5_of_base: str                 # SKILL.md 原版内容 hash
    localized: bool                  # 是否存在 supplement
```

### A.2 RecalledProcessItem（会话内召回项）

```python
@dataclass
class RecalledProcessItem:
    kind: Literal['meta', 'applied']
    meta: Optional[SuperpowersSkill]
    applied: Optional[Dict]
    match_score: float
    match_reason: str
    skill_id: Optional[str]
    applied_id: Optional[str]
```

### A.3 applied ProcessTemplate.metadata（应用认知流程，含新增 5 字段）

```python
{
  # 既有字段
  "unit_id": str,
  "problem": str,
  "action_count": int,
  "files_touched": List[str],
  "duration_minutes": float,
  "success": bool,
  "commit_hash": str,
  "created_at": int,

  # 新增字段
  "parent_skill_ids": List[str],          # 可多个父 Skill
  "process_verify_report": Dict[str, Dict],  # {skill_id: {score, followed, ...}}
  "task_type": str,                       # "trading-system" / "python-development" 等
  "reproducible_steps": List[str],        # 5-15 条人类可读步骤
  "key_artifacts": {                      # 关键产物清单
      "added_files": List[str],
      "modified_files": List[str],
      "debt_items": List[str],
  },
}
```

### A.4 MCP recall 返回值（processes 字段）

```json
{
  "processes": {
    "meta": [{
      "skill_id": str,
      "display_name": str,
      "match_score": float,
      "match_reason": str,
      "injection": str,
      "hard_gates": List[str],
      "localized": bool
    }],
    "applied": [{
      "applied_id": str,
      "parent_skill": str,
      "title": str,
      "quality_level": str,
      "confidence": float,
      "verify_count": int,
      "outcome_success": bool,
      "injection": str,
      "path_advantage": float,
      "quarantined": bool
    }],
    "process_block_markdown": str
  }
}
```

### A.5 EvaluationSample（思维路径评测样本，设计节 7.3）

```python
@dataclass
class EvaluationSample:
    session_id: str
    task_summary: str                    # 任务一句话描述
    skill_ids_injected: List[str]        # 本次注入的 process_block 包含哪些 Skill
    thought_chain_compressed: List[str]  # 思维链压缩：5-15 个关键决策点
    action_chain_compressed: List[str]   # 行动链压缩：reproducible_steps
    hard_gate_violations: List[str]      # 本次违反的 HARD-GATE 列表
    outcome_metrics: Dict[str, float]    # 成效指标（见设计节 7.4）
    timestamp: int
```

### A.6 Solution Path 质量等级扩展（设计节 7.5）

```python
# ProcessTemplate.quality_level 扩展状态：
# 原有: "S" | "A" | "B" | "C" | "D"
# 新增: "quarantined"（隔离，recall 不召回）

# ProcessTemplate 新增字段：
{
  "path_advantage_history": List[float],     # 历次 path_advantage 得分
  "evaluation_count": int,                   # 评测次数
  "last_evaluated_at": int,                  # 最近评测时间戳
  "consecutive_positive": int,               # 连续正向次数（用于自动升级）
  "consecutive_negative": int,               # 连续负向次数（用于自动降级/隔离）
}
```

---

## 附录 B：退化映射表

旧自创模板 ID → 原版 Skill name 的退化兼容映射（1→1，允许"不够精准"警告）：

| 旧 ID | 新 Skill ID | 说明 |
|-------|------------|------|
| `TDD-001` | `test-driven-development` | 直接对应 |
| `DEBUG-001` | `systematic-debugging` | 直接对应 |
| `REFACTOR-001` | `test-driven-development` | 重构本质也走红-绿（退化） |
| `REVIEW-001` | `requesting-code-review` | 直接对应 |
| `DESIGN-001` | `brainstorming` | 设计阶段对应头脑风暴（退化） |
| `TDD-DEBUG-001` | `subagent-driven-development` | 复合流程 → SDD（两阶段审查复合，退化） |

**迁移脚本行为**：
1. 改写 `template_mappings.json` 的 `parent_id` 字段（old → new），同名冲突合并 success/fail 计数。
2. 给所有旧 applied JSON 的 `parent_skill_ids` 补退化值，`metadata.legacy_template_id = TDD-001` 留作溯源。
3. 退化映射在 `cognitive_superpowers.py --mapping` 输出时打上 `[LEGACY]` 标签。

---

## 附录 C：SKILL.md 格式红线

吸收经验 95953 的核心教训，对所有 SKILL.md 文件制定"不可破坏规则"：

### C.1 frontmatter 严格三段结构

```
---
name: skill-name
description: skill description
---
```

- 文件起始必须严格为三段结构 `---\n<yaml>\n---\n`
- 后续编辑只允许改动 yaml 键值，**不允许替换分隔符**
- 如需插入分隔线，仅能出现在 frontmatter 结束之后的 Markdown 正文中

### C.2 禁止的分隔符

以下字符**绝对不允许**作为 frontmatter 分隔符：
- `***`（三颗星）
- `______`（下划线）
- `====`（等号）
- `--- ` 后接非空格字符（必须是纯 `---` 结束）

### C.3 补丁落盘操作规范

对"精确替换"的补丁操作：
1. 必须先用 Read 精确截取目标片段（包含首尾分隔符的完整块）
2. 再用 Edit 以"最小 diff"替换
3. 若历史中存在多版本头部（例如既出现过 `---` 又出现过 `***`），要以当前文件实际内容为准构造 old_string
4. **避免凭记忆替换**——这是经验 95953 失败的直接原因

### C.4 SkillLoader 校验逻辑

```python
def _validate_frontmatter_format(content: str, path: str) -> None:
    """格式红线校验，FAIL FAST"""
    lines = content.split('\n')
    if not lines or lines[0].strip() != '---':
        raise SkillFormatError(f"{path}: 第 1 行必须是 '---'，实际是 '{lines[0] if lines else '(空)'}'")
    # 扫描闭合的 ---
    frontmatter_end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            frontmatter_end = i
            break
        # 禁止的分隔符检测
        if lines[i].strip() in ('***', '______', '===='):
            raise SkillFormatError(
                f"{path}: 第 {i+1} 行出现禁止的分隔符 '{lines[i].strip()}'，"
                f"frontmatter 必须用 '---' 分隔"
            )
    if frontmatter_end is None:
        raise SkillFormatError(f"{path}: frontmatter 未闭合，缺少第二个 '---'")
```

---

## 附录 D：应急回滚操作清单

任一回滚条件（6.4）触发时，按以下步骤操作：

### D.1 关闭兜底注入（最快，影响最小）

```bash
# 1. 关闭 SessionStart hook（路径 B）
mv hooks/session-start.sh hooks/session-start.sh.disabled

# 2. 让 daemon 重载配置（关闭路径 C）
pkill -HUP cognitive_daemon
```

### D.2 recall 退回老协议（中等影响）

```bash
# 编辑环境变量或 cognitive_mcp_server.py 配置
export COGNITIVE_RECALL_INCLUDE_PROCESS=false

# 重启 daemon
pkill -f cognitive_daemon
nohup python3 cognitive_loop_entry.py daemon > /tmp/cognitive-daemon.log 2>&1 &
```

### D.3 彻底回滚代码（最大影响，仅在系统崩溃时使用）

```bash
# 1. 回滚阶段 3 的代码改动
git revert <阶段3的merge commit>

# 2. 用备份恢复 mapping
python3 scripts/migrate_legacy_mappings.py --restore
# 或手动覆盖
cp 4-MEMORY/_archive/_ARCHIVED_template_mappings_backup_YYYYMMDD.json \
   4-MEMORY/0-元记忆/template_mappings.json

# 3. 重启 daemon
pkill -f cognitive_daemon
nohup python3 cognitive_loop_entry.py daemon > /tmp/cognitive-daemon.log 2>&1 &

# 4. 验证 daemon 健康
python3 cognitive_loop_entry.py healthcheck
```

### D.4 数据损坏恢复

```bash
# 1. 恢复 template_mappings.json
cp 4-MEMORY/_archive/_ARCHIVED_template_mappings_backup_YYYYMMDD.json \
   4-MEMORY/0-元记忆/template_mappings.json

# 2. 恢复 process_templates.json（如有损坏）
cp 4-MEMORY/_archive/_ARCHIVED_process_templates_backup_YYYYMMDD.json \
   4-MEMORY/0-元记忆/process_templates.json

# 3. 重启 daemon
pkill -f cognitive_daemon
nohup python3 cognitive_loop_entry.py daemon > /tmp/cognitive-daemon.log 2>&1 &
```

---

## 附录 E：外部参考项目

本设计借鉴了三个 GitHub 成熟项目的工程实践，以增强工程可实践性和科学性。借鉴关系如下：

### E.1 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — 认知闭环整体参考

| 维度 | 信息 |
|------|------|
| Stars | 30k+（截至 2026-07） |
| 协议 | MIT |
| 定位 | "The self-improving AI agent with a built-in learning loop" |
| 与我们的对应点 | 整个认知闭环（学习循环+记忆+技能自创+评测） |

**借鉴点**：

| Hermes 组件 | 我们的设计对应 | 借鉴方式 |
|------------|--------------|---------|
| `trajectory_compressor.py` | 设计节 7.3 思维链压缩 | **直接参考实现模式**：相邻合并/纯注释剔除/关键决策点提取，适配我们的 action_chain |
| Agent-curated memory + periodic nudges | 设计节 4 Solution Path 沉淀 | 参考其"策展式记忆"——被动更新+主动提醒结合 |
| Autonomous skill creation after complex tasks | 设计节 4.6 supplement 完善 | 参考其"复杂任务后自动生成技能"的触发条件 |
| Skills self-improve during use | 设计节 7.5 学习/回滚决策 | 参考其"使用中自我改进"的评测机制 |
| FTS5 session search + LLM summarization | 我们的 recall 机制 | 参考其全文搜索+LLM 摘要的跨会话召回 |
| `batch_runner.py` + `mini_swe_runner.py` | 设计节 7.4 A/B 评测策略 2 影子对照 | 参考其批量轨迹生成+影子运行的工程化实现 |
| Honcho dialectic user modeling | 我们未涉及（可选未来方向） | 不借鉴，记录为可选方向 |
| agentskills.io open standard | 设计节 2.1 SKILL.md 格式 | **确认我们的格式选择符合开放标准** |

**关键启示**：Hermes 的 "Research-ready: Batch trajectory generation, trajectory compression for training the next generation of tool-calling models" 定位，与我们设计节 7 的评测目标完全一致——认知系统不只是辅助 AI，还要产生可用于评测和训练的轨迹数据。

### E.2 [obra/superpowers](https://github.com/obra/superpowers) v6.2.0 — 元认知流程层上游

| 维度 | 信息 |
|------|------|
| Stars | 25.9 万（截至 2026-07） |
| 协议 | MIT |
| 版本 | v6.2.0（2026-07-24） |
| 定位 | "A complete software development methodology for your coding agents" |
| 与我们的对应点 | 设计节 1-6 元认知流程层（SKILL.md 存储/加载/索引） |

**借鉴点**：

| Superpowers 组件 | 我们的设计对应 | 借鉴方式 |
|-----------------|--------------|---------|
| 14 个 SKILL.md（v6.2.0） | 设计节 2.1 目录结构 | **直接作为 upstream base**，拉取到 `4-MEMORY/0-元记忆/superpowers/skills/` |
| SessionStart hook | 设计节 3.4 路径 B | 参考其 hook 实现模式（已支持 11 个宿主） |
| 7 阶段工作流 | 设计节 1.2 认知闭环 | 确认我们的工作流顺序与原版一致 |
| 11 个宿主适配 | 设计节 3.4 宿主 SessionStart hook | 参考其多宿主适配模式（Claude Code / TRAE / Cursor） |
| v6.2.0 SDD plan-scoped workspace | 设计节 4 应用认知流程 | 参考其 SDD 工作区隔离+修复循环模式 |

**关键确认**：
- 14 个 Skill 清单与我们设计节 1 完全一致 ✓
- SKILL.md 格式（YAML frontmatter + Markdown 正文）与我们设计节 2.2 一致 ✓
- SessionStart hook 机制与我们设计节 3.4 一致 ✓

### E.3 [prime-radiant-inc/superpowers-evals](https://github.com/prime-radiant-inc/superpowers-evals) — 思维路径评测参考

| 维度 | 信息 |
|------|------|
| 协议 | MIT（推测，与 Superpowers 主仓一致） |
| 定位 | Superpowers 官方的 Skill 行为评估框架 |
| 与我们的对应点 | 设计节 7.4 A/B 评测 |

**借鉴点**：

| superpowers-evals 组件 | 我们的设计对应 | 借鉴方式 |
|----------------------|--------------|---------|
| drill eval harness | 设计节 7.4 evaluation_engine.py | **参考测试方法论**：如何定义 Skill 行为测试用例、如何评分、如何 CI 集成 |
| pre-commit hooks | 设计节 6.2 验收标准 | 参考其"评估纳入 CI"的模式（我们用 V1-V15 验收标准） |
| 测试用例定义模式 | 设计节 7.4 成效指标 | 参考其"如何测试一个 Skill 是否真的让 AI 做得更好"的标准方法 |

**关键启示**：设计节 7.4 的 A/B 评测不应该从零实现，应参考 drill eval harness 的测试方法论，在其基础上增加 A/B 对比层（有注入 vs 无注入的成效差异）。

### E.4 借鉴关系总结

```
设计节 1-6（元认知流程层）
  └─ upstream base: obra/superpowers v6.2.0（14 个 SKILL.md）
  └─ 格式标准: agentskills.io open standard
  └─ 多宿主适配: 参考 Superpowers 的 11 个宿主适配模式

设计节 7（思维路径评测闭环）
  └─ 思维链压缩: 参考 Hermes 的 trajectory_compressor.py
  └─ A/B 评测: 参考 superpowers-evals 的 drill eval harness
  └─ 学习循环: 参考 Hermes 的 "Skills self-improve during use"
  └─ 批量评测: 参考 Hermes 的 batch_runner.py + mini_swe_runner.py

整体认知闭环
  └─ 学习循环架构: 参考 Hermes 的 "built-in learning loop"
  └─ 策展式记忆: 参考 Hermes 的 "Agent-curated memory + periodic nudges"
  └─ 跨会话召回: 参考 Hermes 的 "FTS5 session search + LLM summarization"
```

### E.5 实施时的参考研究步骤

实施阶段 1（设计节 6.1）之前，建议先做以下参考研究：

1. **克隆 hermes-agent 仓库**，重点研究：
   - `trajectory_compressor.py` 的压缩算法（输入/输出/合并规则）
   - `batch_runner.py` 的批量运行模式
   - `mini_swe_runner.py` 的影子运行实现
   - `skills/` 目录的自创技能机制

2. **克隆 superpowers-evals 仓库**，重点研究：
   - drill eval harness 的测试用例定义格式
   - 评分标准（如何判定一个 Skill "有效"）
   - pre-commit hooks 的 CI 集成方式

3. **拉取 superpowers v6.2.0**，重点研究：
   - 14 个 SKILL.md 的完整内容（作为 upstream base）
   - `hooks/` 目录的 SessionStart hook 实现
   - `.claude-plugin` / `.cursor-plugin` 等多宿主适配模式

研究产出：每个项目写一份"参考研究报告"（Markdown），记录可借鉴的具体代码片段和设计模式，存入 `docs/superpowers/research/` 目录。

---

## 附录 F：规格-实现偏差记录（理论实践一致性）

> 本附录记录实施过程中规格（本设计文档）与代码实现之间的偏差，遵循 A8 SKILL 理论实践一致性原则。每条偏差含：规格描述、实际实现、偏差原因、影响评估、对齐措施。

### F.1 Task 27 V6 验证结构偏差

| 维度 | 内容 |
|------|------|
| **规格描述** | 设计节 6.2 V6 校验假设 mapping 结构含 `parent_skill_ids` / `legacy_template_id` 字段（计划文档 Step 3 的验证代码片段） |
| **实际实现** | Task 13 迁移脚本（`migrate_legacy_mappings.py`）采用 `mappings[].parent_id` 原地改写结构：旧 `parent_id = "TDD-001"` → 新 `parent_id = "test-driven-development"`，未保留 `legacy_template_id` 字段 |
| **偏差原因** | Task 13 设计时选择最小侵入式原地改写（保留 `applied_id` / `success_count` / `fail_count` 不变，仅改 `parent_id`），避免引入冗余 legacy 字段增加 schema 复杂度 |
| **影响评估** | 低风险。迁移后 `parent_id` 均为合法原版 Skill name，recall/mapping 统计功能不受影响；唯一损失是无法从迁移后数据反推原始 legacy ID（但 `template_mappings.json.bak_*` 备份保留了迁移前完整数据） |
| **对齐措施** | V6 验证按实际结构执行（校验 `parent_id ∈ 14 原版 Skill name ∪ {custom-path}`），已通过。本设计文档 V6 描述更新为以 `parent_id` 合法性为准 |

### F.2 Task 28 final_signoff 分发机制偏差

| 维度 | 内容 |
|------|------|
| **规格描述** | 计划文档 Task 28 Step 2 的 `run_all_acceptance()` 直接调用 `_check_vN()` 返回 `AcceptanceItem` |
| **实际实现** | `run_all_acceptance()` 经 `_run_acceptance_check(vid)` 分发 `passed`，配合 `ACCEPTANCE_META` 静态表（vid → name/method/criteria）构建 `AcceptanceItem`；`_check_vN()` 的 `actual` 字段通过 `_LAST_ITEMS` 缓存回填 |
| **偏差原因** | 计划的直接调用方式会使单测（`test_final_signoff.py` mock `_run_acceptance_check`）触发真实 subprocess 调用 `cognitive_loop_entry.py`，导致单测依赖 daemon 部署状态、运行缓慢且不可重复。引入分发层后单测可 mock `_run_acceptance_check` 返回 True（无 subprocess），真实运行仍经 `_run_acceptance_check` → `_check_vN()` 走完整 CLI 检查 |
| **影响评估** | 无功能损失。真实运行行为与规格一致（15 项 V1-V15 全量检查）；单测覆盖分发逻辑与 V14 quarantined 过滤，通过 3/3 |
| **对齐措施** | `final_signoff.py` 保留分发层设计；`_check_vN()` 函数完整实现 CLI 检查逻辑（未被删除），供真实运行使用。本偏差属工程优化，不回写设计文档正文 |

### F.3 偏差管理原则

1. **记录而非隐藏**：所有规格-实现偏差记录于此附录，确保理论实践可追溯（A8 SKILL）
2. **最小化偏差**：每条偏差经评估确认无功能损失或低风险后才落地
3. **备份兜底**：涉及数据结构变更的偏差（如 F.1）保留迁移前备份（`.bak_*`），支持 `--restore` 回滚
4. **单测守护**：偏差不破坏现有单测（75/75 通过），新增逻辑配套单测覆盖

---

*文档结束。v1.3：28/28 Task 已交付，75/75 单测通过。待部署 daemon 后运行 live V1-V15 验收 + 7 天灰度观察，全过后正式签收（设计节 6.6 认知闭环状态达成）。*
