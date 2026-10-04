---
name: dream-bugfix-workflow
description: "Orchestrates bugfix: symptom collect → reproduce → root cause (5why) → fix proposal → TDD verify → hermes reflection. Invoke for bug fix, root cause analysis."
version: 1.0.0
created: 2026-09-21
updated: 2026-09-21
license: Internal
status: active
category: orchestration
triggers: [bug 修复, 根因分析, 5why, 缺陷修复]
depends_on: [dream-contradiction-theory, auto-repair, test-driven-development, tee-red-green-progress]
provides: [bugfix-orchestration]
cognitive_links: [VM-1790001702811-24bffe86]
---

# Dream Bugfix Workflow — Bug 修复工作流 SKILL

> 把"现象收集 → 复现验证 → 根因分析（5why + 矛盾识别）→ 修复方案 → TDD 验证 → hermes 反思"的 6 步 bug 修复流程固化为可复用编排，元 SKILL 为 `dream-qwen-eval-collab`，结尾执行 hermes 反思决定是否再衍生新 SKILL。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-bugfix-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-bugfix-workflow/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **bug 修复**：用户报告了一个 bug，需要系统性修复（不是一次性小修）
   - 触发词：「bug 修复」「根因分析」「5why」「缺陷修复」
2. **回归事故**：现有测试或生产出现非预期行为，需要根因 + 回归测试
3. **`auto-repair` 升级**：`auto-repair` 健康检查发现问题但无法自动修复，需转人工根因分析
4. **hermes 反思**：修复结束后，用户希望反思是否形成/衍生新 SKILL
   - 触发词：「形成 SKILL」「反思」「hermes」「可复用经验」

**与 `auto-repair` / `dream-tdd-dev-workflow` 的边界**：`auto-repair` 是健康检查 + 浅层自动修复；本 SKILL 用于根因不在表面的 bug。本 SKILL 步骤 5 的 TDD 验证复用 `dream-tdd-dev-workflow` 的 RED/GREEN 纪律，但起点是"先写回归测试复现 bug"，不是从零开发新模块。

---

## 二、6 步标准流程

### 步骤 1：现象收集（复现步骤 + 环境 + 日志）

**输入**：用户 bug 报告（文本/截图/日志片段）

**处理**：
1. 提取现象描述：期望行为 vs 实际行为
2. 提取复现步骤（编号化，可被他人照做）
3. 提取环境信息：模块/版本/数据/时间窗/并发情况
4. 收集相关日志/trace/报错堆栈
5. 评估影响面（是否破坏 FAIL-OPEN / 零回归 / 交易决策）

**输出**：bug 现象卡（YAML）

```yaml
现象:
  期望行为: <应该发生的>
  实际行为: <实际发生的>
  影响面: <FAIL-OPEN/零回归/交易决策/数据完整性>
复现步骤:
  1. <步骤 1>
  2. <步骤 2>
  3. <步骤 3>
环境:
  模块: <file_path 或模块名>
  版本: <commit/版本号>
  数据: <数据特征>
  时间窗: <发生时间范围>
  并发: <是否并发场景>
日志:
  - <关键日志行 1>
  - <关键日志行 2>
堆栈: |
  <报错堆栈，若有>
```

### 步骤 2：复现验证（最小复现用例）

**输入**：bug 现象卡

**处理**：
1. 按复现步骤在本地/测试环境复现
2. 若无法复现，回到步骤 1 补充环境/数据细节（不要跳过复现直接猜根因）
3. 构造**最小复现用例**（剥离无关因素，最小输入触发 bug）
4. 记录复现成功率（10 次复现几次）

**已知坑**（必须遵守）：

| 坑 | 现象 | 解决 |
|----|------|------|
| 无法复现 | 本地跑不出来 | 多半是环境/数据差异，回到步骤 1 补细节，不要凭空猜 |
| 间歇性复现 | 10 次只复现 2 次 | 多半是并发/时序/缓存，标注"间歇性"，步骤 3 重点查时序 |
| 复现步骤太长 | 步骤 7 步以上 | 逐步裁剪，找到最小输入，否则根因分析会被噪音淹没 |
| 凭记忆改代码 | 跳过复现直接改 | 禁止。不复现就无法验证修复，也无法写回归测试 |

**输出**：最小复现用例 + 复现成功率

### 步骤 3：根因分析（5why + 矛盾识别）

**输入**：最小复现用例 + bug 现象卡

**处理**：
1. 用 **5why** 逐层追问根因（不止于表面原因）
2. 复用 `dream-contradiction-theory`（A0 矛盾分析）识别底层矛盾：系统设计中两个合理诉求的张力导致了 bug
3. 区分**根因**（root cause，设计/假设层面的缺陷）与**触发因素**（trigger，诱发表面的条件）
4. 若根因触及硬约束（HC-1a/HC-9/FAIL-OPEN/零回归），标注为"硬约束级根因"，修复方案必须显式处理

**5why 示例**（bug：风控裁决 reduce_size 后实际下单未缩减）：

```
现象：风控返回 reduce_size(reduced_size_pct=0.5)，但下单量仍是原 size

Why 1：为什么下单量没缩减？
  → 执行器没调用 RiskExpression.effective_size_multiplier()
Why 2：为什么执行器没调用？
  → 执行器读的是 RiskExpression.reduced_size_pct 字段，以为是"缩减比例"（0.5=减50%）
     但实际语义是"保留比例"（0.5=保留50%），字段命名歧义
Why 3：为什么字段命名歧义没被发现？
  → from_dict/build 工厂没有校验 reduced_size_pct ∈ [0,1]，且无文档注释
Why 4：为什么没有校验和注释？
  → TDD 阶段只测了"正常路径"，没测"字段语义边界"和"非法值 FAIL-OPEN"
Why 5：为什么 TDD 漏测边界？
  → dream-tdd-dev-workflow 步骤 1 的"边界条件"清单没把"字段语义二义性"列为边界
     → 根因：边界条件清单缺少"语义二义字段"这一类

根因：边界条件清单不完整 + 字段命名二义 + 工厂无校验
触发因素：执行器误读字段语义
底层矛盾： expressive API（字段语义自解释）vs performant API（执行器直接读字段少一次方法调用）
硬约束级根因：触及 FAIL-OPEN（非法值未拒）+ 零回归（修复需改工厂+执行器）
```

**输出**：根因报告（含 5why 链 + 根因 + 触发因素 + 底层矛盾 + 硬约束级根因标注）

### 步骤 4：修复方案（不破坏现有测试）

**输入**：根因报告 + bug 现象卡

**处理**：
1. 针对**根因**设计修复（不只修触发因素，否则同类 bug 会复发）
2. 列出修复改动清单（文件/模块/接口），每项标注是否触现有接口
3. 评估对现有测试的影响（零回归前提：现有测试不应被破坏；若被破坏，必须说明为什么）
4. 识别修复的副作用，设计缓解措施
5. 若根因是硬约束级，修复方案必须显式补强该硬约束

**修复方案模板**：

```markdown
## 修复方案

### 根因修复（必须）
- <改动 1：file_path → 改动描述 → 是否触现有接口>
- <改动 2：...>

### 触发因素缓解（建议）
- <改动 3：...>

### 现有测试影响
- <测试 A：不受影响>
- <测试 B：需更新，原因：字段语义澄清后断言需同步>

### 副作用与缓解
- 副作用：<描述>
- 缓解：<措施>

### 硬约束补强
- FAIL-OPEN：工厂增加 reduced_size_pct ∈ [0,1] 校验，非法 → None
- 零回归：改动限于 risk_expression.py + executor.py，独立模块
```

**输出**：修复方案文档（含改动清单 + 影响评估 + 副作用缓解）

### 步骤 5：TDD 验证（先写回归测试再修复）

**输入**：修复方案 + 最小复现用例

**处理**（复用 `dream-tdd-dev-workflow` 的 RED/GREEN 纪律 + `tee-red-green-progress`）：
1. **先写回归测试**复现 bug（这是 RED：测试当前会失败，因为 bug 存在）
2. 运行确认 RED（回归测试失败 = bug 被测试捕获）
3. 实施修复方案
4. 运行确认 GREEN（回归测试通过 = bug 已修复）
5. 跑全量回归确认**零回归**（原有测试全绿）
6. 若步骤 4 标注某测试需更新，一并处理

**回归测试示例**（对应步骤 3 的 5why）：

```python
# test_risk_expression_bugfix.py（先写，RED）
def test_reduce_size_field_is_retention_ratio():
    # 回归 bug：reduced_size_pct=0.5 应保留 50%，不是减 50%
    from dreambuddy.risk_expression import RiskExpression
    v = RiskExpression.reduce_size(reduced_size_pct=0.5)
    assert v.effective_size_multiplier() == 0.5  # 保留 50%

def test_factory_reduces_invalid_pct_fails_open():
    # 回归 bug：非法 pct 应 FAIL-OPEN
    from dreambuddy.risk_expression import RiskExpression
    assert RiskExpression.reduce_size(reduced_size_pct=1.5) is None  # 非法 → None
    assert RiskExpression.reduce_size(reduced_size_pct=-0.1) is None

def test_executor_applies_size_multiplier():
    # 回归 bug：执行器必须调用 effective_size_multiplier()
    from dreambuddy.executor import apply_risk
    order = apply_risk(original_size=100, risk=mock_reduce_size(0.5))
    assert order.size == 50  # 100 * 0.5
```

```bash
pytest test_risk_expression_bugfix.py -v   # 预期：3 failed → RED（bug 存在）
# 实施修复...
pytest test_risk_expression_bugfix.py -v   # 预期：3 passed → GREEN（bug 已修）
pytest -q                                  # 全量回归零回归
```

**输出**：回归测试文件 + RED/GREEN 日志 + 全量回归日志

### 步骤 6：hermes 反思

**输入**：修复后的代码 + 回归测试 + 全量回归日志

**处理**：
1. 输出修复改动 + 回归测试路径给用户审阅
2. 用户确认后，调用认知系统 `record` 记录经验
3. **hermes 反思**：评估本次流程是否值得形成/衍生新 SKILL（决策树见第五节）
4. 特别评估：根因是否暴露了某类系统性问题（如边界条件清单模式缺失）→ 若是，调用 `skill-creator` 衍生新 SKILL（如"dream-boundary-checklist"）

**record 模板**：

```
record(
  content="[Bug修复] <bug一句话> | 5why根因: <根因一句话> | 回归测试 <N> | 全量回归 <原> passed | 改动: <文件数>",
  quality_level="B",
  tags="bug修复,协作流程,5why根因,hermes反思,可复用,<域标签>"
)
```

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 用户 bug 报告 | bug 现象卡（YAML） |
| 步骤 2 | bug 现象卡 | 最小复现用例 + 复现率 |
| 步骤 3 | 最小复现用例 + 现象卡 | 根因报告（5why + 矛盾 + 硬约束级标注） |
| 步骤 4 | 根因报告 | 修复方案（改动清单 + 影响评估） |
| 步骤 5 | 修复方案 + 复现用例 | 回归测试 + RED/GREEN/零回归 日志 |
| 步骤 6 | 修复后代码 + 回归测试 | 用户审阅 + 认知 record + 可选新 SKILL |

---

## 四、相关 SKILL 与文档

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `dream-qwen-eval-collab` | 本 SKILL 的元编排，hermes 反思决策树来源 |
| 上游 | `dream-contradiction-theory` | A0 矛盾分析（步骤 3 识别底层矛盾） |
| 工具 | `auto-repair` | 健康检查 + 浅层自动修复（可触发本 SKILL 升级） |
| 工具 | `test-driven-development` | TDD 纪律（步骤 5 回归测试 RED/GREEN） |
| 工具 | `tee-red-green-progress` | TEE Task N→N+1 红绿机制（步骤 5 复用） |
| 兄弟 | `dream-tdd-dev-workflow` | 步骤 5 的 TDD 纪律来源（区别：本 SKILL 起点是"复现 bug"非"新模块"） |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、hermes 反思决策树

> 引用元 SKILL `dream-qwen-eval-collab` 第五节决策树（来源记忆 `VM-1790001702811-24bffe86`，B 级硬约束）。

```
本次 bug 修复流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 6 步满足）
│   ├── 根因暴露系统性问题（如某类边界条件模式缺失）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL（如 dream-boundary-checklist）
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性小修（如拼写错误）
    ├── 根因表面，无系统性问题
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

**bug 修复特有反思**：根因报告中的"底层矛盾"和"硬约束级根因"是否值得沉淀为新的硬约束或新的检查清单 SKILL？若是，优先衍生。

---

## 六、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="bug 修复 <模块/现象关键词>", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="<本次 bug 修复摘要> | 5why根因: <一句话> | 回归测试 <N> | 改动: <文件数>",
       quality_level="B",
       tags="bug修复,协作流程,5why根因,hermes反思,可复用,<域标签>")

# 如已验证某条已有记忆
verify(memory_id="VM-xxx", success=true)
```

**已沉淀的认知记忆**（可 recall 复用）：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| `VM-1790001702811-24bffe86` | B | hermes 反思决策树硬约束（4 延伸 SKILL 配套） |
| `VM-1789621219116-d9c6395b` | B | E2 验收经验（HC-1b 假阳性 / 惰性求值 — bug 修复常复用） |
| `VM-1789993099772-45aec081` | B | 风控表达增强（reduced_size_pct 保留比例语义 — 5why 示例来源） |
| 本 SKILL 创建后新增 | B | bug 修复落地经验，tags 含「SKILL,bug修复,5why根因,hermes反思」 |

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-21 | 初始版本，6 步流程 + 5why 示例 + TDD 回归验证 + hermes 反思决策树 |
