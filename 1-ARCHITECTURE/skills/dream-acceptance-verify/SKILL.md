---
name: dream-acceptance-verify
description: "Bug修复/功能完成后的强制证据验收门禁：症状复测+日志证据+回归+影响面+边界五维验证，产出四文件验收包。AI宣称'完成/修复/通过'前必须调用，禁止靠感觉验收。"
version: 1.0.0
created: 2026-10-09
updated: 2026-10-09
license: Internal
status: active
category: orchestration
triggers: [验收, acceptance, 修复验证, 功能验收, 日志验收, 完成验证, 验收通过, bug修复完成]
depends_on: [verification-before-completion, dream-bugfix-workflow, dream-tdd-dev-workflow]
provides: [acceptance-gate, log-evidence-verify, symptom-retest]
cognitive_links: []
---

## Autonomy Boundary

可自主执行：
- 五维证据采集与判定
- 日志grep与产物检查
- 测试运行与exit code捕获
- git diff范围核查
- 验收报告生成与认知record

需用户确认：
- 验收不通过时是否阻塞commit/发布
- 涉及实盘交易的验收执行
- 验收标准的临时放宽

禁止：
- 无证据宣称"修复完成/功能可用"
- 跳过日志验收维度
- 用"应该/大概/看起来"替代可执行证据
- 篡改或选择性裁剪验收日志


# Dream Acceptance Verify — Bug修复/功能验收强制门禁

> 把"症状复测 → 日志证据 → 回归测试 → 影响面核查 → 边界验证"的五维证据验收固化为可复用编排。本 SKILL 是 AI 完成 bug 修复或功能开发后的**最后一道证据门禁**，专门捕获"改了代码但原症状没消失""日志里查不到修复证据""回归没跑就宣称完成"等反模式——这是用户反复踩到的坑。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-acceptance-verify/SKILL.md`（TRAE 调用入口，本文件）
> - `1-ARCHITECTURE/skills/dream-acceptance-verify/SKILL.md`（项目级索引发现）

> **与相邻 SKILL 的边界**：
> - `verification-before-completion`：通用铁律（宣称完成前必须有新鲜证据），本 SKILL 是其**具体操作清单**
> - `dream-bugfix-workflow` 步骤5（TDD 验证）：只覆盖测试 RED/GREEN，本 SKILL 补充**症状复测+日志证据+影响面**
> - `dream-module-post-dev-verify-workflow`：模块级 API 接入/文档验收，本 SKILL 是**单 bug/单功能**的症状级验收
> - `dream-tdd-dev-workflow`：开发期 RED-GREEN-REFACTOR，本 SKILL 是 GREEN 之后的**验收收口**

---

## 一、为何需要本 SKILL（痛点来源）

> 用户原话（2026-10-09）：「避免 AI 靠感觉工作，我们反复验收或者遗忘验收」

典型事故（反模式）：

| 反模式 | 表现 | 后果 |
|--------|------|------|
| 靠感觉验收 | "应该修好了"、"看起来没问题" | 原 bug 仍在，上线后复发 |
| 遗忘验收 | 改完代码直接宣称完成，不跑验证 | 回归未覆盖，破坏已有功能 |
| 反复验收 | 同一内容重复验证，浪费时间 | 效率低下，且可能掩盖真正漏项 |
| 无日志证据 | 只跑单元测试，不查运行日志 | 生产路径未触发，测试 GREEN 但线上仍坏 |
| 静默复现 | repro.log 无明确标记行，无法判断是否真复现 | "A silent log is not a reproduction" |

**核心铁律**：

```
NO COMPLETION CLAIM WITHOUT 5-DIMENSION EVIDENCE
没有五维证据，不得宣称完成
```

---

## 二、何时调用（触发条件）

满足以下任一条件即**必须**调用本 SKILL（不可跳过）：

1. **bug 修复完成**：`dream-bugfix-workflow` 步骤5 TDD GREEN 之后
   - 触发词：「bug 修好了」「修复完成」「验证一下修复」「retest」
2. **功能开发完成**：`dream-tdd-dev-workflow` GREEN 之后、commit 之前
   - 触发词：「功能做完了」「验收」「acceptance」「功能可用了」
3. **AI 正准备宣称完成/通过/修好**：任何"完成态"表述前
   - 触发词：「完成」「通过」「修好」「done」「fixed」「works」
4. **用户主动要求验收**：「验收一下」「看看日志」「确认修复」
5. **认知事件驱动**：`record` 时 `tags` 含 `acceptance-verify`，自动触发

**不触发的场景**：
- 纯文档变更（无代码改动）→ 调用 `dream-doc-sync-workflow`
- 模块级 API 接入验收 → 调用 `dream-module-post-dev-verify-workflow`
- 代码审查阶段 → 不调用本 SKILL（审查不是验收）

---

## 三、核心约束（硬规则）

| 编号 | 约束 | 说明 |
|------|------|------|
| HC-1 | 五维缺一不可 | 症状/日志/回归/影响面/边界，缺一项即不通过 |
| HC-2 | 日志验收强制 | 必须有可 grep 的日志标记证明修复路径真的执行了 |
| HC-3 | 证据必须新鲜 | 本次会话内刚跑的命令输出，不得引用历史结果 |
| HC-4 | exit code 必须捕获 | 测试/构建命令的 exit code 是 PASS/FAIL 的唯一判据 |
| HC-5 | repro.log 必须有标记行 | 静默日志不算复现（"A silent log is not a reproduction"） |
| HC-6 | 改动范围必须核查 | git diff 不得超出修复方案声明的范围 |
| HC-7 | 验收报告必须归档 | 四文件包缺一不可，否则验收无效 |
| HC-8 | FAIL-OPEN 但必记录 | 验收不通过不强制阻塞 commit，但必须如实标记红旗 |

---

## 四、五维证据验收模型

```
┌─────────────────────────────────────────────────┐
│              验收五维证据模型                      │
├──────────┬──────────────────────────────────────┤
│ 维度 1   │ 症状复测（Symptom Retest）            │
│          │ 原 bug 症状是否消失 / 功能是否按预期工作 │
├──────────┼──────────────────────────────────────┤
│ 维度 2   │ 日志证据（Log Evidence）★强制          │
│          │ 日志中可 grep 到修复后的预期行为标记     │
├──────────┼──────────────────────────────────────┤
│ 维度 3   │ 回归证据（Regression）                 │
│          │ 相关测试套件全绿，exit code = 0        │
├──────────┼──────────────────────────────────────┤
│ 维度 4   │ 影响面（Impact Surface）               │
│          │ git diff 范围与修复方案一致，无意外扩散  │
├──────────┼──────────────────────────────────────┤
│ 维度 5   │ 边界验证（Boundary）                   │
│          │ 边界/负面场景未引入新问题               │
└──────────┴──────────────────────────────────────┘
```

---

## 五、6 步标准验收流程

### 步骤 1：验收准备（明确验收目标与证据要求）

**输入**：
- bug 修复：`dream-bugfix-workflow` 的根因报告 + 修复方案 + 回归测试
- 功能开发：需求描述 + 验收标准 + 测试用例

**处理**：

```markdown
## 验收目标
- 修复/功能：<一句话描述>
- 原症状/预期行为：<具体可观察的行为>
- 验收通过标准：<可量化判定，如"日志出现 XXX 标记 + 测试 exit=0">

## 证据要求清单
- [ ] 症状复测证据
- [ ] 日志证据（强制）
- [ ] 回归证据
- [ ] 影响面证据
- [ ] 边界证据
```

**判定**：验收目标不明确 → 终止，要求用户补充。

---

### 步骤 2：症状复测（Symptom Retest）

**核心原则**：用**与复现 bug 时完全相同的步骤**复测。

**处理**：

```bash
# 1. 执行原复现步骤（相同输入、相同环境、相同条件）
<复现命令>

# 2. 捕获输出，确认原症状消失
#    - bug 修复：原报错/异常不再出现
#    - 功能开发：预期行为出现

# 3. 记录 exit code
echo "exit=$?"
```

**判定**：

| 状态 | 判定 | 处置 |
|------|------|------|
| 原症状消失 + 行为符合预期 | ✅ 通过 | 进入步骤 3 |
| 原症状仍存在 | 🚩 不通过 | 修复无效，回到开发阶段 |
| 行为部分符合 | ⚠️ 部分通过 | 记录差异，评估是否可接受 |
| 无法复测（环境不具备） | ⚠️ 降级 | 必须在报告中标注 `no-symptom-retest`，不得宣称完全通过 |

**输出**：症状复测日志 `repro_after.log`（含明确的 observed 标记行）

---

### 步骤 3：日志证据（Log Evidence）★强制项

**核心原则**：代码路径必须在日志中留下可 grep 的标记，证明修复路径真的执行了。

**处理**：

```bash
# 1. 定位日志文件
#    - 项目日志目录：<subsystem>/logs/ 或 artifacts/
#    - 服务日志：/tmp/<service>.log 或 docker logs

# 2. 触发修复路径（运行相关命令/接口）
<触发命令>

# 3. grep 修复标记（必须是代码中明确打印的日志行）
grep -n "<修复标记关键字>" <日志路径>

# 4. 确认日志行包含预期值（非空、非默认、非错误）
```

**日志标记要求**（借鉴 polling_trader.py 实践）：

```python
# 修复代码中必须有明确的日志标记，便于 grep 验收
logger.info("[ACCEPTANCE] <修复点> executed: key=%s value=%s", key, value)
```

**判定**：

| grep 结果 | 含义 | 处置 |
|-----------|------|------|
| 命中 + 值符合预期 | ✅ 日志证据通过 | 进入步骤 4 |
| 命中但值异常 | 🚩 修复逻辑有问题 | 回到开发阶段 |
| 0 命中 | 🚩 修复路径未执行 | 检查：路径是否被调用？日志级别是否开启？ |
| 日志文件不存在 | 🚩 从未运行 | 必须先触发运行 |

**反模式**（禁止）：
- ✗ "代码逻辑看起来对" 替代日志证据
- ✗ 用 print 而非 logger（print 不进日志文件，无法 grep）
- ✗ 日志标记不含具体值（"修复完成" 不如 "修复完成: size=50" 可验证）

**输出**：日志证据片段（grep 结果 + 上下文 3 行）

---

### 步骤 4：回归证据（Regression）

**处理**：

```bash
# 1. 运行回归测试套件（本次改动相关的测试 + 全量回归）
pytest <相关测试路径> -v --tb=short
echo "exit=$?"

# 2. 运行全量回归（零回归约束）
pytest -q
echo "exit=$?"
```

**判定**：

| 状态 | 判定 | 处置 |
|------|------|------|
| 全部 GREEN + exit=0 | ✅ 通过 | 进入步骤 5 |
| 有 FAIL | 🚩 不通过 | 必须修复后重跑 |
| 有 ERROR | 🚩 不通过 | 必须修复后重跑 |
| 有 SKIP 且无说明 | ⚠️ 需说明 | 记录跳过原因，不得隐瞒 |
| 0 tests collected | 🚩 无测试 | 必须补测试（TDD 反模式） |

**输出**：测试日志 `test.log`（含 exit code 行）

---

### 步骤 5：影响面核查（Impact Surface）

**处理**：

```bash
# 1. 查看本次改动范围
git diff --stat

# 2. 与修复方案声明的改动清单对比
#    - 是否有方案外的文件被改动？
#    - 是否有意外的依赖变更？
```

**判定**：

| 状态 | 判定 | 处置 |
|------|------|------|
| diff 范围 = 修复方案声明 | ✅ 通过 | 进入步骤 6 |
| diff 超出声明范围 | 🚩 红旗 | 评估额外改动是否必要，必要则更新方案，否则回退 |
| 改动了 lockfile/生成文件 | ⚠️ 警告 | 确认是否必须，非必须则移除 |

**输出**：`fix.diff`（git diff 输出）

---

### 步骤 6：边界验证（Boundary）

**处理**：对修复点周围至少 3 个边界/负面场景做验证：

```bash
# 边界场景示例（根据实际修复点调整）：
# - 空输入 / 零值 / 极大值
# - 非法参数（FAIL-OPEN 验证）
# - 并发/重复调用
# - 依赖模块不可用时的降级行为

<边界测试命令>
```

**判定**：

| 状态 | 判定 | 处置 |
|------|------|------|
| 边界场景行为符合预期（含 FAIL-OPEN 降级） | ✅ 通过 | 验收完成 |
| 边界场景引入新问题 | 🚩 不通过 | 必须修复 |
| 边界场景未覆盖 | ⚠️ 需补充 | 至少覆盖 3 个场景 |

**输出**：边界测试结果

---

## 六、四文件验收包（Acceptance Bundle）

每次验收必须产出以下 4 个文件，归档到 `acceptance_bundles/<日期>_<标识>/`：

```
acceptance_bundles/20261009_fix_xxx/
├── repro_after.log     # 步骤2 症状复测日志（必须含 observed= 标记行）
├── fix.diff            # 步骤5 git diff 改动
├── test.log            # 步骤4 测试日志（必须含 exit=0 行）
└── acceptance_report.md  # 五维验收报告
```

**acceptance_report.md 模板**：

```markdown
# 验收报告

## 基本信息
- 验收对象：<bug/功能描述>
- 验收时间：YYYY-MM-DD HH:MM
- 验收人：AI / 用户
- 关联 commit：<sha>

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 症状复测 | ✅/🚩/⚠️ | repro_after.log 第N行 observed=... | |
| 日志证据 | ✅/🚩/⚠️ | grep 命中 <标记> 值=<value> | 强制项 |
| 回归测试 | ✅/🚩/⚠️ | test.log exit=0, N passed | |
| 影响面 | ✅/🚩/⚠️ | fix.diff 改动 M 文件 | |
| 边界验证 | ✅/🚩/⚠️ | 3 场景全通过 | |

## 红旗清单
- <如有红旗，逐条列出>

## 验收结论
- [ ] 五维全通过 → 验收通过
- [ ] 有红旗 → 验收不通过，需修复后重验

## 签字
AI 验收：<日期>
用户确认：<日期>（可选）
```

---

## 七、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 修复方案/需求 | 验收目标 + 证据清单 |
| 步骤 2 | 复现步骤 | `repro_after.log` |
| 步骤 3 | 日志路径 + 标记 | 日志证据片段 |
| 步骤 4 | 测试路径 | `test.log`（含 exit code） |
| 步骤 5 | git diff | `fix.diff` |
| 步骤 6 | 边界场景 | 边界测试结果 |
| 收口 | 全部证据 | 四文件验收包 + 认知 record |

---

## 八、多领域调研（Step 2 — MANDATORY）

> **项目硬约束**（VM-1790765308904）：SKILL 创建前必须做多领域调研。本节调研 5 域：工程实践 + GitHub 生态 + 产品管理 + AI Agent + 项目自身。

### 8.1 工程实践域（DZone Retesting + GSD Debugger）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| "Can't reproduce → can't verify fixed" | GSD Debugger Golden Rule | 步骤 2 症状复测必须用原复现步骤 |
| Retesting 7 步流程 | DZone Agile Best Practices | 步骤 2-6 对应：复现→理解→复测→边界→回归→staging→文档 |
| 证据质量分级 | GSD Debugger | 强证据（直接可观察/可重复/明确）vs 弱证据（传闻/模糊） |
| "Retesting isn't documented didn't happen" | DZone | 步骤 7 四文件验收包强制归档 |

**关键洞察**：GSD Debugger 的 Golden Rule 是本 SKILL 的基石——如果不能用原步骤复现并确认症状消失，任何"修复完成"的宣称都是无效的。

### 8.2 GitHub 生态域（evidence-verification + OSS Patch Bundle）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| 四文件包（issue/repro/patch/test） | OSS Patch Bundle（dev.to） | 步骤 7 四文件验收包 |
| "A silent log is not a reproduction" | OSS Patch Bundle | HC-5 repro.log 必须有标记行 |
| 证据类型四分类 | evidence-verification skill | 五维证据模型（扩展为症状+日志+回归+影响面+边界） |
| exit code 是唯一判据 | evidence-verification | HC-4 必须捕获 exit code |
| "Show, don't tell" | evidence-verification | 全文核心原则 |

**关键洞察**：OSS Patch Bundle 的四文件包设计极其精巧——repro.log 必须非零退出（证明 bug 存在），test.log 必须 exit=0（证明修复有效），两个日志的 exit code 对比就是修复有效的铁证。本 SKILL 借鉴此模式，但增加了日志证据维度（针对生产路径验证）。

### 8.3 产品管理域（UAT Checklist + Amazon DoD）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| 追溯链 Requirement→Test→Result→Evidence | UAT Checklist（Sicily Labs） | 步骤 1 验收目标 → 步骤 2-6 证据 → 步骤 7 报告 |
| "Tested ≠ Accepted ≠ Ready" 三态分离 | UAT Checklist | 验收结论区分"通过/不通过/有红旗" |
| Definition of Done | Amazon PR/FAQ + Agile | 五维全通过才算 DoD |
| Failed test 必须 retest | UAT Checklist | 步骤 4 FAIL 必须修复后重跑 |

**关键洞察**：UAT 的"Tested ≠ Accepted ≠ Ready"三态分离防止了"测试过了就算验收通过"的误区。本 SKILL 的验收结论明确区分三态，且要求用户确认（可选）才最终生效。

### 8.4 AI Agent 域（independent-testing + evidence-verification）

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| Source-of-Truth 优先级 | independent-testing | 验收标准优先级：需求 > 验收标准 > 实现代码 |
| 黑盒测试优先 | independent-testing | 步骤 2 症状复测用原步骤，不依赖代码理解 |
| "Do not mark PASS because coder says" | independent-testing | HC-3 证据必须新鲜，不得信任 AI 自我报告 |
| 风险分级 P0-P3 | independent-testing | 步骤 6 边界场景按风险优先级覆盖 |

**关键洞察**：independent-testing 的"Do not mark PASS because the coder says which internal component changed"直接针对 AI 靠感觉验收的反模式——AI 不能因为"我改了 X"就宣称修复，必须有独立证据。

### 8.5 项目自身实践域

**核心借鉴**：

| 模式 | 来源 | 在本 SKILL 的应用 |
|------|------|-------------------|
| "不打日志则无法从日志 grep 验证上线" | polling_trader.py L17220 注释 | HC-2 日志验收强制 + 日志标记要求 |
| "文档→代码→日志三者对比"审计 | 11-易经推理系统 CHANGELOG | 五维证据的交叉验证思想 |
| "验收合格后追加变更日志" | ENGINEERING_INDEX.md | 步骤 7 验收报告归档 |
| FAIL-OPEN 原则 | 项目全局硬约束 | HC-8 验收不通过不阻塞但必记录 |

**关键洞察**：项目自身的 polling_trader.py 注释已经隐含了"日志可 grep 验证"的工程纪律，本 SKILL 将其正式化为强制验收维度。

### 8.6 调研总结：5 域融合的设计决策

| 设计决策 | 借鉴来源 | 体现在 SKILL 的 |
|----------|----------|-----------------|
| 五维证据模型 | evidence-verification + UAT 追溯链 | 第四节 |
| 日志验收强制 | polling_trader.py 实践 + GSD evidence | HC-2 + 步骤 3 |
| 四文件验收包 | OSS Patch Bundle | 第六节 |
| repro.log 必须有标记行 | OSS "silent log is not reproduction" | HC-5 |
| exit code 唯一判据 | evidence-verification | HC-4 |
| 症状复测用原步骤 | GSD Golden Rule | 步骤 2 |
| "靠感觉"禁令 | independent-testing + verification-before-completion | 核心铁律 + HC-3 |
| FAIL-OPEN 但必记录 | 项目全局约束 | HC-8 |

---

## 九、相关 SKILL 与工具

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `verification-before-completion` | 通用铁律，本 SKILL 的原则基础 |
| 上游 | `dream-bugfix-workflow` | bug 修复流程，步骤5 GREEN 后调用本 SKILL |
| 上游 | `dream-tdd-dev-workflow` | TDD 开发，GREEN 后调用本 SKILL |
| 同构 | `dream-module-post-dev-verify-workflow` | 模块级 API/文档验收（本 SKILL 是症状级） |
| 下游 | `dream-code-commit-sync-workflow` | 验收通过后驱动 commit |
| 工具 | `Grep` | 步骤 3 日志证据 grep |
| 工具 | `pytest` | 步骤 4 回归测试 |
| 工具 | `git diff` | 步骤 5 影响面核查 |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 十、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 |
|----------|---------|
| 无法复现原症状 | 🚩 红旗，记录 `cannot-reproduce`，不得宣称修复有效 |
| 日志文件不存在 | 🚩 日志证据维度不通过，必须先触发运行 |
| grep 0 命中 | 🚩 检查日志级别/路径/标记拼写，仍不命中则修复路径未执行 |
| 测试环境不具备 | ⚠️ 降级，标注 `no-test-env`，仅靠日志+症状证据，不得宣称完全通过 |
| git diff 超出范围 | 🚩 评估额外改动，必要则更新方案，否则回退 |
| 边界场景未覆盖 | ⚠️ 至少覆盖 3 个，否则标注 `insufficient-boundary` |
| 四文件包缺失 | 🚩 验收无效，必须补齐 |
| 认知 record 失败 | 不阻塞验收，仅本地日志记录 |

**核心原则**：验收永不阻塞开发主流程，但所有红旗必须在验收报告和认知 record 中如实标记，由用户决定是否阻塞 commit/发布。

---

## 十一、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-09 | 初始版本，五维证据模型 + 6 步流程 + 四文件验收包 + 5 域调研。来源：用户痛点「AI 靠感觉工作、反复验收或遗忘验收」+ 工程实践调研（DZone/GSD/OSS Patch/UAT/independent-testing）+ 项目自身 polling_trader 日志实践 |
