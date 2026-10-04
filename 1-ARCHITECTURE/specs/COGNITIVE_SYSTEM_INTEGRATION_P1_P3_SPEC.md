# 大认知系统接入 P1-P3 推进 SPEC (SPEC-COG-P1P3)

> **版本**: v0.3 (P2 已验收)
> **日期**: 2026-10-04
> **状态**: 🟢 P0/P1/P2 已完成 · P3 待推进 · 紧接 P0 完成（[SPEC-COG-INT](./COGNITIVE_SYSTEM_INTEGRATION_SPEC.md)）后续推进
> **作者**: dreambuddy-v2 接入层
> **调研方法**: recall 5 条 P0/Skill 协同经验 + P0 实施实测 + 三大系统协同记忆
>
> **与既有文档关系**:
> | 既有文档 | 关系 |
> |----------|------|
> | [COGNITIVE_SYSTEM_INTEGRATION_SPEC.md](./COGNITIVE_SYSTEM_INTEGRATION_SPEC.md) (P0 SPEC) | **直接续篇**：本 SPEC §一 引用 P0 完成状态 |
> | [VM-1790871057901](../../4-MEMORY/) (P0 认知-Skill 协同 post-hook) | **P1 M5 接入参考**：record→cognitive_links / verify→shadow→active 已实现 |
> | [VM-1790865488067](../../4-MEMORY/) (三大系统协同调研) | **P2 数据流参考**：TAG_HOOKS 是唯一自动化桥梁 |
> | [VM-1790914497936](../../4-MEMORY/) (三大系统审计+断链修复) | **P1/P2 验收参考**：57 skill 测试 + 13 TAG_HOOKS 测试全通过 |

---

## 一、P0 完成状态回顾（2026-10-04）

### 1.1 已落盘文件清单（9 个新文件 + 2 个改造）

**M1 认知 HTTP 网关**：
- `3.1-FRONTEND/scripts/cognitive_adapter.py` — Python 单次请求 adapter
- `3.1-FRONTEND/src/lib/cognitive-client.ts` — TS callCognitive + spawn + 10s 超时 + FAIL-OPEN
- `3.1-FRONTEND/src/app/api/cognitive/{recall,record,verify,stats,health}/route.ts` × 5

**M2 前端 store 重构**：
- `3.1-FRONTEND/src/stores/memory-store.ts` — 6 个 fetch action + useCognitiveAutoLoad + degraded 状态
- `3.1-FRONTEND/src/components/features/memory/MemoryTimeline.tsx` — useEffect 自动 fetch + 真实数据展示 + 降级 banner

### 1.2 验收结果

- ✅ 5 个 HTTP 端点全通（curl 实测）
- ✅ dashboard 显示真实 525 条记忆（S26/A24/B90/C380/D4）
- ✅ Memory/Distill/Consolidation 三层全 healthy
- ✅ record 写入 VM-1791112487457
- ✅ verify 触发贝叶斯升级（confidence 0.3→0.4）
- ✅ FAIL-OPEN degraded banner 就位

### 1.3 P0 关键技术决策（P1+ 继承）

| 决策 | 来源 | P1+ 复用点 |
|------|------|----------|
| stdout 重定向 stderr 避免 Python 污染 | dream-harness-bridge P0-5 (VM-1789618914215) | M5 skill_indexer adapter 同模式 |
| 单次 spawn 模式（非长连接） | P0 实测验证 | M5 doc_sync_trigger adapter 同模式 |
| FAIL-OPEN degraded 状态在 store 层 | P0 实测验证 | userMemoryStore 同模式 |
| quality A+B 映射 DZE/BAC 概念 | P0 实测验证 | P2 概念对齐基础 |
| runtime='nodejs' + force-dynamic | P0 实测验证 | 所有新 API Route 同设置 |

---

## 二、P1 详细 SPEC — 用户层 + Skill 索引接入

### 2.1 范围

| 模块 | 任务 | 文件数 |
|------|------|--------|
| M3 用户层独立 | user_memory.db + 4 API 端点 + userMemoryStore | ~6 新文件 |
| M4 dashboard 子页 | 5 子路由 + tab 导航 | ~6 新文件 |
| M5a Skill 索引接入 | skill_indexer HTTP 包裹 + SkillIndexView | ~3 新文件 |

### 2.2 M3 用户层独立（硬约束：与平台 VM 物理隔离）

**数据模型**（SQLite schema）：

```sql
-- 文件路径: 3.1-FRONTEND/data/user_memory.db
-- 独立 SQLite, 与 cognitive_memory.db 物理隔离
CREATE TABLE user_preferences (
  user_id TEXT NOT NULL,         -- P1 默认 "default", P3 接入 auth
  pref_key TEXT NOT NULL,
  pref_value TEXT,
  updated_at INTEGER,
  PRIMARY KEY (user_id, pref_key)
);
CREATE TABLE user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  session_id TEXT,
  topic TEXT,
  summary TEXT,
  created_at INTEGER
);
CREATE TABLE user_notes (
  id TEXT PRIMARY KEY,            -- user:note:xxx
  user_id TEXT NOT NULL,
  title TEXT,
  content TEXT,
  tags TEXT,
  created_at INTEGER,
  updated_at INTEGER
);
```

**API 端点**：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/user-memory/preferences` | GET | 读取当前用户所有偏好 |
| `/api/user-memory/preferences` | POST | 写入/更新偏好（key+value） |
| `/api/user-memory/notes` | GET/POST | 笔记 CRUD |
| `/api/user-memory/notes/[id]` | DELETE | 删除笔记 |

**Store**：`3.1-FRONTEND/src/stores/user-memory-store.ts`（Zustand + fetch + FAIL-OPEN degraded）

**命名空间硬约束**（P0 SPEC §七继承）：
- ❌ 用户层 API 禁止写 `cognitive_memory.db`
- ❌ 用户笔记不可自动升级为 VM（必须经 P3 人工审批）
- ✅ 用户层数据可独立备份/导出

### 2.3 M5a Skill 索引接入

**已有后端能力**（VM-1790871057901）：
- `1-ARCHITECTURE/skills/dream-skill-index-governance/skill_indexer.py` 存在
- `record_hook` / `verify_hook` 已实现
- `cognitive_links` 双向链接已闭合
- `skill_lifecycle_writer` 升级 shadow→active 已实现

**M5a 接入**（不改后端）：
- 新增 `3.1-FRONTEND/scripts/skill_index_adapter.py` — 单次 spawn 模式包裹 skill_indexer
- 新增 `3.1-FRONTEND/src/app/api/skills/index/route.ts` — GET 返回 Skill 列表
- 新增 `3.1-FRONTEND/src/components/features/memory/SkillIndexView.tsx` — 展示 Skill + 生命周期徽章 + cognitive_links 数量

**Skill 数据契约**：
```typescript
interface SkillItem {
  skill_id: string;
  display_name: string;
  status: 'shadow' | 'active' | 'deprecated';
  cognitive_links_count: number;  // 关联 VM 记忆数
  last_verified: string | null;
  hard_gates: string[];
}
```

### 2.4 M4 dashboard 子页

**路由改造**：`/dashboard/memory` 保留为概览，新增 4 子页（tab 切换）：

| 子路由 | 内容 | 数据源 |
|--------|------|--------|
| `/dashboard/memory` (默认) | 概览：stats + 最近 VM + 健康状态 | P0 已实现 |
| `/dashboard/memory/user` | 用户偏好 / 会话 / 笔记 | M3 user_memory.db |
| `/dashboard/memory/skills` | Skill 列表 + 生命周期 | M5a skill_indexer |
| `/dashboard/memory/dze` | 工程链压缩（保留原 DZEChainView） | 静态 |

**Tab 导航组件**：`3.1-FRONTEND/src/components/features/memory/MemoryTabNav.tsx`

### 2.5 P1 验收清单

- [ ] `curl /api/user-memory/preferences` 返回空数组（初始状态）
- [ ] `curl -X POST /api/user-memory/preferences -d '{"key":"risk_tolerance","value":"low"}'` 写入成功
- [ ] `curl /api/user-memory/notes -X POST ...` 写入笔记，再 GET 返回该笔记
- [ ] `user_memory.db` 与 `cognitive_memory.db` 物理隔离（不同文件路径）
- [ ] `user_memory.db` 内无任何 `VM-` 前缀记录
- [ ] `curl /api/skills/index` 返回 ≥1 个 Skill（项目 154+ skills 中）
- [ ] `/dashboard/memory/user` 可读写用户偏好
- [ ] `/dashboard/memory/skills` 显示 Skill 列表 + 生命周期徽章
- [ ] agent-browser snapshot 子页 tab 可切换

---

## 三、P2 详细 SPEC — 文档索引 + 概念对齐

### 3.1 范围

| 模块 | 任务 | 文件数 |
|------|------|--------|
| M5b 文档索引接入 | doc_sync_trigger HTTP 包裹 + DocIndexView | ~3 新文件 |
| 概念对齐 | DZE/BAC 映射 4-MEMORY 7 类记忆分类轴 | 改造 DZEChainView |

### 3.2 M5b 文档索引接入

**已有后端能力**：
- `1-ARCHITECTURE/dreamos/core/compute/doc_sync_trigger.py` 存在
- `_load_cognitive_record_fn()` 已自动接入认知 record（VM-1790871681293）
- doc-sync TAG_HOOKS 已落地

**M5b 接入**（不改后端）：
- 新增 `3.1-FRONTEND/scripts/doc_index_adapter.py` — 单次 spawn 模式包裹 doc_sync_trigger 的 read-only 接口
- 新增 `3.1-FRONTEND/src/app/api/docs/index/route.ts` — GET 返回文档索引
- 新增 `3.1-FRONTEND/src/app/api/docs/sync/route.ts` — POST 手动触发 doc-sync
- 新增 `3.1-FRONTEND/src/components/features/memory/DocIndexView.tsx`

**文档数据契约**：
```typescript
interface DocItem {
  path: string;
  last_synced: string | null;
  cognitive_linked: boolean;     // 是否已写入 VM 记忆
  category: string;               // 五件套分类
}
```

### 3.3 概念对齐 — DZE 三链映射 4-MEMORY 7 类记忆

**对齐表**（基于 P0 quality 映射经验扩展）：

| DZE 链 | 4-MEMORY 分类轴 | 用途 |
|---------|----------------|------|
| D（设计链） | 3-架构记忆 + 0-元记忆 | 需求→架构→评审 |
| Z（工程链） | 5-通用经验 + 1-原则记忆 | 编码→测试→部署 |
| E（评估链） | 2-方法论记忆 + 4-信息记忆单元 | 自动评估→人工审核→发布 |

**改造**：`DZEChainView.tsx` 每个链节点显示对应分类轴的真实记忆数（从 stats 拉取）

### 3.4 P2 验收清单（2026-10-04 全部通过）

- [x] `curl /api/docs/index` 返回 262 个文档
- [x] `/dashboard/memory/docs` 显示文档索引 + last_synced + cognitive_linked 状态 + 4 统计卡片 + 手动同步按钮
- [x] `curl -X POST /api/docs/sync` 手动触发 doc-sync，返回 VM-1791114339582
- [x] DZEChainView 顶部"4-MEMORY 分类轴分布"卡片，D/Z/E 三链显示 knowledge=1/experience=473/observation=2
- [x] 文档变更触发 doc-sync record 入 `cognitive_memory.db`（前端可观察，VM id 显示）
- [x] agent-browser docs 子页 + dze 子页截图验收通过
- [x] tsc --noEmit --strict 通过
- [x] 认知闭环: record VM-1791114783581 + verify confidence 0.3→0.4 贝叶斯升级

---

## 四、P3 详细 SPEC — 双向交互 + 用户经验沉淀

### 4.1 范围

| 模块 | 任务 |
|------|------|
| 前端 record 表单 | 用户填写 content + quality + tags → 写入新 VM |
| 前端 verify 按钮 | 每条 VM 旁加 verify 成功/失败按钮 |
| 用户笔记沉淀审批流 | user:note:* → 人工审批 → 迁移为 VM-* |

### 4.2 前端 record 表单

**组件**：`RecordExperienceForm.tsx`
- 字段：content（textarea） + quality_level（select S/A/B/C/D） + tags（input 逗号分隔）
- 提交：调 `useMemoryStore.recordExperience(content, quality, tags)`
- 提交后：自动 fetchRecall 刷新列表
- FAIL-OPEN：失败显示降级 banner + 错误信息

### 4.3 前端 verify 按钮

**改造 MemoryTimeline.tsx**：每条 VM 记录旁加两个按钮：
- ✅ verify success（绿）→ `verifyMemory(id, true)`
- ❌ verify failure（红）→ `verifyMemory(id, false)`
- 点击后：显示 loading + 自动 fetchStats 反映置信度变化

### 4.4 用户笔记沉淀审批流

**流程**：
1. 用户在 `/dashboard/memory/user` 选择笔记
2. 点击"沉淀为平台经验"按钮 → 弹出审批表单（填质量等级 + 标签）
3. 提交到 `/api/user-memory/notes/[id]/promote`（新端点）
4. 后端调用 cognitive record 写入 VM-*
5. 成功后将 user:note:* 标记为 `promoted_to: VM-xxx`
6. 前端刷新 + 显示"已沉淀"徽章

**硬约束**：
- 必须人工审批，禁止自动迁移
- promote 操作必须用户主动点击，禁止定时任务
- 沉淀后原 user:note:* 保留（标记 promoted_to），不删除

### 4.5 P3 验收清单

- [ ] `/dashboard/memory` 出现 record 表单
- [ ] 填表提交后新 VM 出现在列表
- [ ] 每条 VM 旁有 verify 成功/失败按钮
- [ ] 点击 verify 后 stats 中的 confidence 变化可见
- [ ] 用户笔记可点"沉淀为平台经验"
- [ ] 沉淀成功后笔记显示"已沉淀 VM-xxx"徽章

---

## 五、推进顺序与依赖图

```
P0 (✅ 已完成)
   │
   ├─ M1 认知 HTTP 网关 [✅]
   └─ M2 store 改造 [✅]
            │
            ▼
P1 — 用户层 + Skill 索引接入
   │
   ├─ M3 用户层独立 ──── 独立 SQLite, 与 P0 解耦
   ├─ M5a Skill 索引 ──── 复用 P0 spawn 模式
   └─ M4 dashboard 子页 ─ 依赖 M3 + M5a
            │
            ▼
P2 — 文档索引 + 概念对齐
   │
   ├─ M5b 文档索引 ──── 复用 P0 spawn 模式
   └─ 概念对齐 ─────── 依赖 P0 stats 数据
            │
            ▼
P3 — 双向交互 + 用户沉淀
   │
   ├─ record 表单 ───── 依赖 P0 record API
   ├─ verify 按钮 ───── 依赖 P0 verify API
   └─ 用户笔记沉淀 ──── 依赖 P1 M3 + P0 record API
```

**推进策略**：
1. **P1 优先 M3 → M5a → M4**（M3/M5a 独立可并行，M4 依赖前两者）
2. **P2 单独推进**（与 P1 解耦）
3. **P3 最后**（依赖 P1 用户层）

---

## 六、技术决策（基于 P0 经验）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 用户层 DB | SQLite + WAL 模式 | 复用 P0 经验，零新依赖 |
| Skill 索引 adapter | Python 单次 spawn | 复刻 P0 cognitive_adapter.py 模式 |
| 文档索引 adapter | Python 单次 spawn | 同上 |
| Store FAIL-OPEN | degraded 状态 + banner | 复刻 P0 MemoryTimeline 降级模式 |
| dashboard 子页 | tab 切换（非嵌套路由） | 减少路由复杂度，复用 layout |
| record/verify UI | 内联表单 + 按钮（非 modal） | 操作流短，FAIL-OPEN 直观 |

---

## 七、不在范围

- ❌ 改 4-MEMORY 后端任何代码
- ❌ 改 cognitive_mcp_server.py MCP 协议
- ❌ 改 skill_indexer.py / doc_sync_trigger.py 后端逻辑
- ❌ 引入新数据库引擎（PostgreSQL/MySQL）
- ❌ 多用户认证（P3 接入 auth，P1/P2 默认 user_id="default"）
- ❌ 自动化用户笔记沉淀（必须人工审批）

---

## 八、文档落盘说明

- **本 SPEC 落盘**：`1-ARCHITECTURE/specs/COGNITIVE_SYSTEM_INTEGRATION_P1_P3_SPEC.md`
- **状态机分类**：Hold（待评审，未闭环）
- **后续动作**：
  1. 用户评审 → 通过则进入 P1 实施
  2. P1 实施完成后 → 补 docs/ 五件套 + 登记 INDEX.md
  3. 同步登记到 `0-系统文档管理/INDEX.md` §8 快速导航
