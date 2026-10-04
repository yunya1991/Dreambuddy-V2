---
name: dream-feature-landing-workflow
description: "Orchestrates DreamOS feature landing: backend contract/hook changes → 3.1-FRONTEND API+component+store adaptation → FAIL-OPEN validation (tsc+tests+HTTP200). Invoke when implementing SPEC tasks (D/F/O/M series) or landing new DreamOS features."
version: 1.0.0
created: 2026-09-29
updated: 2026-09-29
license: Internal
status: active
category: orchestration
triggers: [功能落地, SPEC 实现, D系列, F系列, O系列, M系列, 前端组件, 后端契约]
depends_on: [dream-tdd-dev-workflow, dream-bugfix-workflow]
provides: [feature-landing-orchestration]
cognitive_links: [VM-1790637585625-24b3c177, VM-1790638546711-8b0314db, VM-1790638839003-f7c51b1b, VM-1790639230039-bffe5a3c, VM-1790639349844-cb840ff5]
---

# DreamOS Feature Landing Workflow — DreamOS 功能落地流程 SKILL

> 把"后端契约/钩子改动 → 3.1-FRONTEND API+组件+store 适配 → FAIL-OPEN 验证"的功能落地循环固化为可复用编排。覆盖 SPEC 任务（D 决策层 / F 前端层 / O 编排层 / M 中台层）的端到端落地。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-feature-landing-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-feature-landing-workflow/SKILL.md`（项目级索引发现）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **SPEC 任务落地**：用户要求实现 SPEC-A/SPEC-B 中的 D/F/O/M 系列任务
   - 触发词：「推进 SPEC」「实现 D1」「落地 F4」「O3 持久化」「M1 中台」
2. **后端+前端联动功能**：需要同时改动后端 Python 模块和前端 3.1-FRONTEND
3. **组件移植/新增**：从 3-FRONTEND 移植组件到 3.1-FRONTEND，或新增前端组件
4. **契约升级**：后端数据结构新增字段，需前端适配消费

---

## 二、核心约束（硬规则）

| 编号 | 约束 | 说明 |
|------|------|------|
| HC-1 | 前端只改 3.1-FRONTEND | 禁止在 3-FRONTEND 新增代码，3-FRONTEND 是参考源 |
| HC-2 | FAIL-OPEN | 所有降级路径必须返回安全默认值，不阻塞主流程 |
| HC-3 | 向后兼容 | 新增字段必须带默认值，不破坏现有调用方 |
| HC-4 | 类型先行 | 先改 types/store，再改实现，最后改 UI |
| HC-5 | 验证三件套 | tsc 零新增错误 + 后端测试 exit 0 + 页面 HTTP 200 |

---

## 三、标准落地流程（5 步）

### Step 1: 后端契约/钩子改动

**适用**：D 系列（决策层）、O 系列（编排层）、M 系列（中台层）

1. **类型定义**：在对应 `types.py` 中新增数据类/字段
   - 字段必须有默认值（向后兼容）
   - dataclass 字段顺序：无默认值在前，有默认值在后
   - 必须实现 `to_dict()` 序列化
2. **核心逻辑**：在主模块中实现功能
   - 对齐已有阈值常量（如 CDriveAgent 的 CONF_SKIP=0.75）
   - 降级用 try/except 包裹，返回安全默认值
3. **序列化**：如果是 State/Checkpoint 等核心结构，更新 `to_dict()` 和 `from_dict()`

### Step 2: 前端类型适配

**适用**：所有涉及前端消费的功能

1. **chain-store.ts**：在 `ChainTraceNode` 或对应 interface 中新增字段
   - 可选字段用 `?:`，不破坏已有数据
2. **类型归位**：如果是组件 props，定义独立 interface
3. **导入检查**：确保从 `@/stores` 正确导出

### Step 3: 前端 API 路由

**适用**：F 系列（前端层）+ 需要数据传递的 D/O/M

1. **路由位置**：`3.1-FRONTEND/src/app/api/<feature>/route.ts`
2. **数据提取**：从 `result.execution_summary` 或 `result.metadata` 提取后端数据
3. **注入节点**：在 `chain_trace.nodes` 构建时注入新字段
   - 注意两个分支：`plannerResult`（动态编排）和 `executedChain`（S 链降级）
   - 两个分支都要注入，否则部分请求无数据
4. **Next.js 15 注意**：`[id]` 动态路由中 `params` 是 Promise，需 `await params`

### Step 4: 前端组件

1. **组件位置**：`3.1-FRONTEND/src/components/features/<domain>/`
2. **组件原则**：
   - 可展开/折叠（避免占用过多空间）
   - 空数据安全渲染（`data && <Component/>`）
   - 复用 V3 原子组件（V3Badge/V3Card/V3StatusDot）
3. **集成点**：在 MessageItem / ChainTracker / 对应页面中导入渲染
4. **V3Badge 注意**：属性是 `variant` 不是 `tone`，值为 `"default"/"success"` 等

### Step 5: FAIL-OPEN 验证

1. **tsc 检查**：
   ```bash
   cd 3.1-FRONTEND && npx tsc --noEmit
   ```
   - 只关注本次改动文件的错误，预存错误（Prisma 类型等）不处理
2. **后端测试**：
   ```bash
   cd 1-ARCHITECTURE/dream-harness-bridge && pytest packages/python-server/ -q
   ```
   - exit 0 为通过
3. **页面验证**：启动 dev 服务器，确认相关页面 HTTP 200
   ```bash
   cd 3.1-FRONTEND && npm run dev -- -p 3001
   ```
4. **API 验证**：curl/POST 关键 API，确认返回数据结构正确

---

## 四、数据持久化约定

| 数据类型 | 存储路径 | 说明 |
|----------|----------|------|
| 产物中台 | `scheduler_data/artifacts/{type}/{id}.json` | M1 产物归一 |
| 检查点 | `scheduler_data/checkpoints/` | O3 Checkpoint |
| 前端 API 访问 | `process.cwd() + '../1-ARCHITECTURE/dreamos/scheduler_data/...'` | 相对路径 |

---

## 五、关键阈值参考（CDriveAgent）

```python
CONF_SKIP = 0.75           # > 0.75: 跳过四步循环
CONF_RECALL_ONLY = 0.65    # 0.65-0.75: 只 recall
CONF_FULL_LOOP = 0.50      # < 0.50: 全链路
DEBATE_CLOSE_GAP = 0.15    # Bull/Bear 接近触发第二轮
JEV_PASS = 0.85            # jeval noul >= 0.85 放行
JEV_BLOCK = 0.50           # jeval noul < 0.50 阻止
```

---

## 六、认知闭环

任务完成后执行：
1. `record(content=..., quality_level="B", tags="功能落地,xxx域")` 记录经验
2. 如验证了已有记忆，`verify(memory_id=..., success=True)`
3. hermes 反思：评估是否衍生新 SKILL

---

## 七、已落地案例（本会话）

| 任务 | 类型 | 后端改动 | 前端改动 |
|------|------|----------|----------|
| D1 | 契约升级 | subagent_types 4 字段 | — |
| F2 | 组件 | — | SynthesisChart 8 类图表 |
| F3 | 可视化 | — | cdrive_steps + ChainTracker |
| O3 | 持久化 | State/Checkpoint/Checkpointer thread_id+resume | — |
| F4 | UI | CDriveDecision debate 字段 | BullBearDebate 组件 |
| D2 | 决策升级 | effort_level + 多轮辩论 | — |
| O2 | 决策模型 | Reflector jev_judge_fn | — |
| O1 | 编排 | GraphStore Pregel+DeltaChannel | — |
