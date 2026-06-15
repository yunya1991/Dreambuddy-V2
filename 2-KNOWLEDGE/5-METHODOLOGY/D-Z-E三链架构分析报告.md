# D-Z-E 三链架构分析报告 — 与GitHub成功经验对比

> 2026-06-15 | 源：3-CHAIN-DEVELOPMENT/ | 对标：BMAD v6, Parallax, GitHub Spec Kit, VS Code Multi-Agent

---

## 第一部分：现状评估

### D-Z-E 的独特优势（✅ 值得保留）

| 特色 | 详情 |
|:---|---|
| **物理门禁体系** | Gate 0-1-2-3 四层门禁，`chain_guard.py` 提供物理约束而非靠AI自觉 |
| **工具权限隔离** | D1只读→D2可读可写→E全工具，天然防止调研阶段乱改代码 |
| **跳步协议** | `override` 存证机制，用户说跳就跳但每条记录可审计 |
| **产出文件契约** | Z1→`_plan/z1-scan-report.md` → Z2 读取，形成文件接力而非对话记忆传递 |
| **7Step 集成** | D-Z-E 嵌入 7 步框架，与知识库/飞书/蒸馏形成完整工作流 |

### 行业对标来源

| 来源 | 核心贡献 | 适用 |
|:---|---|:---:|
| **BMAD v6** (bmad-code-org, 1913 commits) | 34+工作流、Scale-Adaptive AI、Skills Architecture、Dev Loop | ⭐⭐⭐⭐⭐ |
| **Parallax** (s2-streamstore, MIT) | Agent 隔离推理、对抗性队列、S2流持久化、Claude+Codex混合 | ⭐⭐⭐⭐⭐ |
| **GitHub Spec Kit** (微软/200+ stars) | Spec-Driven Development、AGENTS.md标准、宪法式约束 | ⭐⭐⭐⭐ |
| **VS Code Multi-Agent 2026** | Claude+Codex同编辑、Agent Sessions 管理、Open Ecosystem | ⭐⭐⭐⭐ |
| **HAMY LABS 9-subagent review** | 9个并行Agent做Code Review、Claude Code Subagent模式 | ⭐⭐⭐ |

---

## 第二部分：核心差距分析（7 Gaps）

### 🔴 Gap 1：Agent 同上下文污染（最严重）

| 维度 | 当前 D-Z-E | 行业最优实践 |
|:---|---|:---|
| E1写代码 | 在同一个对话窗口 | Claude写 → Codex审（**不同Agent、不同语境**） |
| E2验证 | "建议不读E1的推理过程"但**无物理约束** | Parallax: 每个Agent在**独立S2流**上运行 |
| D1调研 | 调研结果仅在对话记忆 | Parallax: 多个Agent独立调研同问题，再综合 |

**BMAD/Parallax 的做法：**
```
Parallax code-review "feature-x":
  Claude 写代码 → 写入 artifact file
  Codex 读 artifact → 独立审查（看不到Claude的推理过程）
  → 综合报告

当前 D-Z-E:
  E1 写代码 → E2 读同一对话中的E1代码 → 审查结果有偏
```

**建议：** E1 写完代码后，**用 `delegate_task` 或 `cronjob run` 另起上下文执行 E2**，禁止在同一 context window 内验证。

---

### 🔴 Gap 2：缺少对抗性并行推理

| 维度 | 当前 | Parallax |
|:---|---|:---|
| D1调研 | 单一路径搜索 | 3组Agent独立调研、互不可见、最后合成 |
| D2分析 | 一个分析结论 | Delphi模式：5个评估者独立估测、汇总、再迭代 |
| Z1代码扫描 | 一个人扫全量 | "攻守双方"：一个找问题可能，一个找不改可能 |

**建议：** 调研/规划阶段增加"对抗性模式"。比如 D1 用两个不同 prompt 方向的 Agent 跑同一个问题，结果交叉验证。

---

### 🔴 Gap 3：Spec 无代码追溯力

| 维度 | 当前 | GitHub Spec Kit |
|:---|---|:---|
| 规范位置 | D4 产出 markdown 描述 | 规范是**唯一真理源**，代码必须 trace 到 spec |
| 追踪 | 无 | `spec-to-code` traceability: 每行代码标注来源spec条目 |
| 验证 | 人工读 | 自动检查：代码实现是否覆盖了spec所有条目 |

**建议：** D4 产出的 spec 需要增加**可验证的断言**格式（类似测试用例级别的约束），E2 测试时验证这些断言。

---

### 🔴 Gap 4：缺少跨链反馈闭环

| 维度 | 当前 | BMAD Dev Loop |
|:---|---|:---|
| E2发现bug | 报告 → 修 → 结束 | 反馈到 spec 层面 → 修改plan → 重执行 |
| 系统学习 | 无 | "反射循环"：执行中发现的问题回到方法论层面改流程 |
| 知识回补 | 靠 Step 7 蒸馏（外层） | BMAD: 执行中的发现自动沉淀为 new skill |

**建议：** 增加一个 **Feedback Loop**：E2 发现的设计级问题应生成正式反馈（写文件到 `_plan/feedback-e2.md`），通知 D/Z 系列更新。而不是只在单次对话里修 bug。

---

### 🟡 Gap 5：Token 成本意识缺失

| 维度 | 当前 | BMAD Web Bundles |
|:---|---|:---|
| 规划阶段 | 用 deepseek-v4-pro (最贵) | 用 Gemini/web LLM 做规划（flat-rate订阅） |
| 执行阶段 | 同模型 | 切换到专用模型 |
| 预算跟踪 | 7Step 无 token 预估 | 每步预估 token + 总预算显示 |

**建议：** 在 D-Z-E 的每步加入预估 token 消耗（D1调研轻量、D2分析中等、E1执行最重），让用户决策是否切换到更便宜模型。

---

### 🟡 Gap 6：缺少 "Orchestrator 视角"

| 维度 | 当前 | VS Code Agent Sessions |
|:---|---|:---|
| 全链可视化 | 无 | Agent Sessions view: 每个agent有状态/进度/Token |
| 中间干预 | 只能通过对话 | 点击agent直接对话 + 重定向 |
| 工作流状态 | chain_guard.py 文件 | 统一的Dashboard面板 |

**建议：** 增加一个 `chain-report` 命令，输出当前 D-Z-E 项目全景状态（进度、耗时、token、产出文件列表），类似飞书Base的记录视图。

---

### 🟡 Gap 7：AGENTS.md 标准化不足

| 维度 | 当前 | Spec Kit + AGENTS.md |
|:---|---|:---|
| AGENTS.md 定位 | 内部使用规范 | 跨Agent的标准协议文件 |
| 角色定义 | AGENTS.md 内有步骤 | AGENTS.md 定义agent角色、工具、行为边界 |
| 标准化 | 无 | AGENTS.md + `.claude/` + `.github/` 形成标准协议 |

**建议：** 将 `AGENTS.md` 补充为标准的**Agent 角色与工具契约**声明，明确每个 D/Z/E 角色的工具清单、触发条件、输出格式。

---

## 第三部分：改进优先级

| 优先级 | Gap | 影响面 | 改动量 |
|:---:|:---|:---:|:---:|
| **P0** | Gap 1: Agent 上下文隔离 | E2验证质量 | 中（加 delegate_task） |
| **P0** | Gap 2: 对抗性并行调研 | D系列信息全面性 | 中（并行 delegate） |
| **P1** | Gap 4: 反馈闭环 | 系统性学习 | 中（加 feedback file） |
| **P1** | Gap 3: Spec 可追溯性 | 验收准确度 | 大（改 D4 格式） |
| **P2** | Gap 5: Token 成本意识 | 成本控制 | 小（加预估提示） |
| **P2** | Gap 6: 全景可视化 | 使用体验 | 小（chain-report 命令） |
| **P2** | Gap 7: AGENTS.md 标准化 | 协议清晰度 | 小（补充角色声明） |

---

## 第四部分：关键改进方案（快速见效）

### 方案 A：E1→E2 上下文隔离（P0，半天）

```
当前: E1写代码 → 同窗口 E2审查
改为: E1写代码 → artifacts/ + state/ 记录产出
        → delegate_task 启动 E2（全新上下文）
        → E2 读产出文件 + Z4 验收方案 → 独立审查
        → 审查结果写入 _plan/feedback-e2.md
```

### 方案 B：D1 对抗性调研（P0，半天）

```
当前: D1一次性搜索→分析→结论
改为: D1-A 调研  +  delegate_task  D1-B 调研（不同搜索方向）
        → 交叉验证两路调研结果
        → 标注共识点 / 分歧点
        → D2 分析时优先处理分歧点
```

### 方案 C：E2→D 反馈闭环（P1，半天）

```
E2 发现问题 → 写入 _plan/feedback-e2.md
           → 如果有设计级问题 → gateway 提示 "需更新D4 spec"
           → 用户确认后 → 重新走 D4→Z3→E1 sub-loop
           → 非设计级问题 → 直接 E1 修 + E2 回归
```

---

## 结论

D-Z-E 的设计理念（物理门禁、工具隔离、文件接力）在**架构层面**领先于大多数开源方案——行业普遍还在靠 AI"自觉"遵守规范。

**两个最值得优先改进的 P0 项：**
1. ⚡ **Agent 上下文隔离** — 用 `delegate_task` 在不同 context 做 E2 验证
2. ⚡ **对抗性调研** — D1 阶段开两个独立调研任务交叉验证

这两个改了以后，D-Z-E 就从"同一个人流水线检查"升级为"多 Agent 团队协作验证"——对标 Parallax 和 BMAD 的成熟模式，但保持物理门禁和文件接力两家独有的优势。

_最后更新：2026-06-15 | 源：Dreambuddy-V2 三链开发系统 vs GitHub 行业实践_
