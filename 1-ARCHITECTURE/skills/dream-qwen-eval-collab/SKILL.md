---
name: dream-qwen-eval-collab
description: "Orchestrates 5-step Qwen collab: user need → trae analysis → bsk calls Qwen research → trae evaluates & generates spec → user review. Invoke for Qwen/second-round eval, or complex 4-dim research (finance+github+modular+code)."
version: 1.0.0
created: 2026-09-21
updated: 2026-09-21
license: Internal
status: active
category: orchestration
triggers: [千问评估, 二轮评估, 回送千问, 老师评估, 蒸馏评估, 形成 SKILL, hermes 反思]
depends_on: [bsk, skill-creator]
provides: [qwen-eval-orchestration]
cognitive_links: [VM-1790001192903-2224e07e, VM-1790001702811-24bffe86]
---

## Autonomy Boundary

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


# Dream Qwen Eval Collab — 千问协作评估编排 SKILL

> 把"用户提需求 → trae 分析 → bsk 调用千问调研 → trae 评估制定 spec → 用户审阅"的 5 步协作流程固化为可复用编排，配合认知系统 `recall`/`record`/`verify` 形成自我进化闭环，结尾执行 hermes 反思决定是否再衍生新 SKILL。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-qwen-eval-collab/SKILL.md`（TRAE 调用入口，Skill 工具识别）
> - `1-ARCHITECTURE/skills/dream-qwen-eval-collab/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **用户新需求/假设**：用户提出需要调研的需求或假设性命题
   - 触发词：「我想」+ 调研关键词 /「是否可以」+ 探索关键词 /「假设」+ 验证关键词
2. **二轮评估**：用户对已有方案不满，希望送回千问二轮评估
   - 触发词：「二轮评估」「回送千问」「千问再评」「老师评估」「蒸馏评估」
3. **复杂探索**：涉及 4 维调研（传统金融 + github 代码实现 + 模块化模式适配 DreamOs/Deepseek Harness + 代码实际需求）
4. **hermes 反思**：流程结束后，用户希望反思是否形成/衍生新 SKILL
   - 触发词：「形成 SKILL」「反思」「hermes」「可复用经验」

---

## 二、5 步标准流程

### 步骤 1：用户需求分析（trae 主导）

**输入**：用户原始需求文本

**处理**：
1. 提取核心命题、约束条件、验收标准
2. 识别调研域：传统金融？技术实现？模块化模式？实际代码需求？
3. 识别工程约束（参考 `project_memory.md` 中的硬约束：HC-1a/HC-9/FAIL-OPEN/零回归/模块化开关）
4. 输出调研任务包

**输出**：调研任务包（YAML 结构）

```yaml
命题: <一句话陈述>
约束: [<列表>]
调研域:
  - 传统金融     # 经典理论/行业实践/论文
  - github 代码  # 现有成熟实现/参考仓库
  - 模块化模式   # 长期适配 DreamOs/Deepseek Harness
  - 实际代码需求 # 当前仓库代码状态/依赖/历史
工程上下文: <DreamOs/Harness 相关硬约束>
验收标准: <用户期望的可量化结果>
```

### 步骤 2：bsk 调用千问调研（bsk 自动化）

**前置环境变量**：
```bash
export PATH="$HOME/.local/bin:$PATH"
export BSK_HOME="<项目内 .bsk-home 绝对路径>"
```

**调用模板**（按顺序执行）：

```bash
# 1. 启动 daemon + 打开千问
bsk daemon start
bsk session open "https://www.qianwen.com"

# 2. 获取输入框 ref（千问输入框是 contenteditable 富文本）
bsk snapshot -i

# 3. 填入调研问题 — contenteditable 必须用 evaluate + execCommand insertText
#    bsk fill @e1 对 contenteditable 返回 rc=3 "无法确认"，是已知限制
bsk evaluate "document.querySelector('[contenteditable],textarea').focus();
              document.execCommand('insertText', false, '<调研问题>');
              document.querySelector('[contenteditable],textarea')
                .dispatchEvent(new InputEvent('input', {bubbles: true}));"

# 4. 点击发送按钮（ref 来自 snapshot -i）
bsk click @e<send_button_ref>

# 5. 等待千问回复完成（轮询直到 body.innerText 长度稳定）
bsk evaluate "const oldLen = document.body.innerText.length;
              await new Promise(r => setTimeout(r, 30000));
              const newLen = document.body.innerText.length;
              return JSON.stringify({stable: newLen === oldLen, length: newLen});"

# 6. 提取回复（长回复分段提取，避免 evaluate 返回截断）
bsk evaluate "return document.body.innerText.slice(-8000);"
```

**已知坑**（必须遵守）：

| 坑 | 现象 | 解决 |
|----|------|------|
| contenteditable 不响应 fill | `bsk fill @e1` rc=3 | 用 `evaluate` + `execCommand('insertText', false, text)` + `dispatchEvent(new InputEvent('input', {bubbles:true}))` |
| innerText 不触发状态更新 | 千问 React/ProseMirror 不识别输入 | 同上，必须 dispatch InputEvent |
| 长回复被截断 | `evaluate` 返回不完整 | 用 `body.innerText.slice(oldLen)` 分段提取 |
| 浏览器扩展丢失心跳 | `idle_secs=65` 后 session 被清理 | `bsk session start` 重建 |
| Assistant 消息选择器 | `evaluate` 取到用户输入 | 用 `[class*=assistant]`/`[class*=reply]` 过滤 |

**输出**：千问调研报告（markdown 文本）

### 步骤 3：trae 评估分析（trae 主导）

**输入**：千问调研报告 + 步骤 1 调研任务包

**评估维度**（5 维评分 0-10）：

| 维度 | 评分要点 |
|------|---------|
| 完整性 | 是否覆盖 4 维调研（传统金融 + github + 模块化 + 实际代码） |
| 可落地性 | 是否给出代码级实现路径 |
| 工程适配性 | 是否适配 DreamOs/Deepseek Harness 工程约束（HC-1a/HC-9/FAIL-OPEN/零回归） |
| 风险识别 | 是否识别潜在风险（FAIL-OPEN/零回归/HC-1a/HC-9） |
| 创新性 | 是否引入模块化模式或新视角 |

**评分阈值**：

| 综合评分 | 动作 |
|---------|------|
| ≥ 9.0 | 直接进入步骤 4 spec 合成 |
| 7.0–8.9 | 标注改进项（P0/P1/P2 优先级），二轮回送千问（重复步骤 2） |
| < 7.0 | 整个调研任务包回送千问重做 |

**输出**：评估报告 markdown（含评分 + 改进项列表）

### 步骤 4：spec 合成（trae 主导）

**输入**：评估报告 + 改进项列表

**spec 模板**（必须含以下小节）：

```markdown
# <项目名> — <阶段> 落地计划 + 最终方案

> 日期：YYYY-MM-DD
> 来源：千问 N 轮评估 + 本地整合
> 输入：<评估报告路径>
> bsk session：<session_id>

## 一、千问通用落地计划模板
（5 维度拆解：验收标准/依赖关系/估时/风险评估/TDD 要点 + N 周里程碑）

## 二、最终方案（基于评估报告 N 项改进 + 千问模板整合）
（P0/P1/P2 三阶段表，含 #/改进项/验收标准/依赖/估时/风险/TDD 要点）

## 三、生产准入门禁（如适用）
（Live Trading 前必须全绿）

## 四、落地执行原则
（TDD 红-绿-重构 + HC 合规 + FAIL-OPEN + 模块化开关 + 认知闭环）
```

**输出**：spec 文档路径（建议 `.trae/documents/<project>-phase<N>-landing-plan.md`）

### 步骤 5：用户审阅 + hermes 反思

**输入**：spec 文档

**处理**：
1. 输出 spec 路径给用户审阅
2. 用户确认后，调用认知系统 `record` 记录经验
3. **hermes 反思**：评估本次流程是否值得形成/衍生新 SKILL
   - 是 → 调用 `skill-creator` 创建新 SKILL
   - 否 → 仅 `record` 经验，不创建 SKILL

**record 模板**：

```
record(
  content="[千问评估协作] <命题一句话> | 评分 <X.X>→<Y.Y> | 改进项 <N 项> | spec: <路径>",
  quality_level="B",
  tags="千问评估,协作流程,bsk,hermes反思,可复用,<域标签>"
)
```

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 用户原始需求 | 调研任务包（YAML） |
| 步骤 2 | 调研任务包 | 千问调研报告（markdown） |
| 步骤 3 | 千问报告 + 任务包 | 评估报告（含评分 + 改进项） |
| 步骤 4 | 评估报告 | spec 文档（路径） |
| 步骤 5 | spec 文档 | 用户审阅 + 认知 record + 可选新 SKILL |

---

## 四、bsk 硬约束（不可违反）

1. bsk 是腾讯 BrowserSkill 0.3.0，通过 DSH 插件 `@wxg-prc-cpg/browser-skill-dsh-plugin@^0.3.0` 接入 harness
2. **不要重写** `cordis-plugin-browser`
3. `BSK_HOME` 必须指向项目内 `.bsk-home/`（不污染用户主目录）
4. contenteditable 必须用 `evaluate` + `execCommand insertText`，不用 `fill`
5. 长回复分段提取，用 `body.innerText.slice(oldLen)`
6. 浏览器断连（`idle_secs=65`）时重建 session
7. Agent Window 模式（独立窗口，不抢占用户标签页），避免 tab borrow（需用户确认）

认知系统记忆参考：`VM-1789997066421-26445d69`（bsk 硬约束 B 级）

---

## 五、hermes 反思决策树

```
本次流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步）
│   ├── 涉及 bsk 自动化（≥ 1 步）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性任务
    ├── 无 bsk 自动化
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

**延伸建议**：调研/开发/bug 修复/工程管理四个域都建议形成对应的协作 SKILL（用户原话），可在 hermes 反思时优先评估是否需要衍生：

| 域 | 建议延伸 SKILL | 触发词 |
|----|---------------|--------|
| 调研 | `dream-research-workflow` | 「深度调研」「市场调研」「技术调研」 |
| 开发 | `dream-tdd-dev-workflow` | 「TDD 开发」「红-绿-重构」 |
| bug 修复 | `dream-bugfix-workflow` | 「bug 修复」「根因分析」 |
| 工程管理 | `dream-eng-mgmt-workflow` | 「工程管理」「排期」「里程碑」 |

---

## 六、认知闭环（record + recall + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="千问评估协作 <本次命题关键词>", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="<本次流程摘要> | 评分 <X>→<Y> | spec: <路径>",
       quality_level="B",
       tags="千问评估,协作流程,bsk,hermes反思,可复用,<域标签>")

# 如已验证某条已有记忆
verify(memory_id="VM-xxx", success=true)
```

**已沉淀的认知记忆**（可 recall 复用）：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| `VM-1789997066421-26445d69` | B | bsk 硬约束（腾讯 BrowserSkill + DSH 插件 + 不重写 cordis-plugin-browser） |
| `VM-1790000355655-0124d10d` | B | 千问评估协作流程 8 步 + 5 个坑 + 自动化要点 |
| 本 SKILL 创建后新增 | B | SKILL 落地经验，tags 含「SKILL,千问评估,hermes反思」 |

---

## 七、相关 SKILL 与文档

| 类型 | 名称 | 用途 |
|------|------|------|
| 上游 | `dream-contradiction-theory` | A0 矛盾分析（命题拆解） |
| 上游 | `dream-strategy-research` | A1 深度调研（多源研究） |
| 工具 | `bsk`（腾讯 BrowserSkill） | 浏览器自动化（千问调研） |
| 下游 | `tee-red-green-progress` | TDD 红-绿-重构循环（spec 落地） |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-21 | 初始版本，5 步流程 + bsk 调用模板 + hermes 反思决策树 |
