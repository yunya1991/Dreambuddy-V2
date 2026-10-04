# 大认知系统接入路径 SPEC (SPEC-COG-INT)

> **版本**: v0.1 (草案)
> **日期**: 2026-10-04
> **状态**: 🟡 评估草案 · 待用户评审 · 不含实现代码
> **作者**: dreambuddy-v2 架构盘点（基于 2026-10-04 dashboard/memory 现场检查 + 后端 4-MEMORY 审计 + 市场 AGI 对标）
> **定位**: 将已成熟的 4-MEMORY 认知核心（VM 记忆 / Skill / 文档 / 索引）以"平台级 + 用户级"两层架构接入前端 dashboard，形成完整大认知系统
> **调研方法**: recall 认知记忆（命中 5 条）+ agent-browser 页面实测 + Glob/Grep 代码审计 + 市场 AGI 对标
>
> **与既有文档关系**:
> | 既有文档 | 维度 | 关系 |
> |----------|------|------|
> | [FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md](./FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md) | 三层 OS 架构 + 11 缺口 | **互补**：前者架构层，本 SPEC 聚焦认知子系统接入面 |
> | [4-MEMORY/MEMORY_SYSTEM_ARCHITECTURE.md](../../4-MEMORY/MEMORY_SYSTEM_ARCHITECTURE.md) | 4-MEMORY 体系结构 | **本 SPEC §一引用**，不改后端 |
> | [4-MEMORY/9-工具与接口/cognitive_mcp_server.py](../../4-MEMORY/9-工具与接口/cognitive_mcp_server.py) | MCP stdio 5 工具 | **本 SPEC §四 M1 包裹为 HTTP 网关** |
> | [dream-harness-bridge IPC 模式 (VM-1789618914215)](../../1-ARCHITECTURE/dream-harness-bridge/) | Python handler + TS caller + FAIL-OPEN | **本 SPEC §四 M1/M2 直接复刻该模式** |
> | 三大系统协同记忆 (VM-1790871681293) | 认知↔Skill↔文档四条自动化链路 | **本 SPEC §三引用**作为底层已闭合证据 |
>
> **后续**: 用户评审通过后 → 进入 P0 实施（仅本 SPEC §五 P0 范围）

---

## 一、现状与缺口

### 1.1 现状快照（2026-10-04 实测）

**前端 dashboard/memory**：页面可访问、组件渲染正常，但**记忆数据全为空**。
- 压缩统计 Blueprint/Architecture/Chronicle = 0 / 0 / 0，压缩率 0%
- 记忆记录区显示"暂无记忆记录"
- DZE 三链（D1-D4 / Z1-Z4 / E1-E3）状态均 idle（0/4 / 0/4 / 0/3）

**后端 4-MEMORY**：体系完整可用，但**仅对接 IDE/MCP，前端完全无感知**。
- `cognitive_mcp_server.py` 暴露 5 个 MCP 工具（recall/record/verify/stats/health），仅走 stdio JSON-RPC，**无 HTTP API**
- 已有 7 类记忆目录、`cognitive_memory.db`、Skill 索引、doc-sync trigger
- 三大系统协同四条自动化链路已落地（VM-1790871681293）

### 1.2 五大缺口

| # | 缺口 | 证据 | 影响 |
|---|------|------|------|
| G1 | 后端 HTTP 化缺失 | `cognitive_mcp_server.py` 仅 stdio，前端 fetch 不可达 | 前端无法读 VM 记忆 |
| G2 | 前端 store 空壳 | `memory-store.ts` 纯 Zustand 静态初始化，零 fetch 调用 | dashboard 永远显示 0 |
| G3 | 概念不对齐 | 前端 DZE/BAC 工程链压缩 vs 后端 7 类 VM 记忆 + 5 级质量 | 数据即便接入也无法对齐展示 |
| G4 | 用户层缺失 | `user_profile.md` 在 Trae 平台侧（`~/.trae-cn/memory/`），仓库内 0 实现 | 无用户专属记忆 |
| G5 | Skill/Doc 索引无前端出口 | `skill_indexer.py` / `doc_sync_trigger.py` 存在但无 HTTP 暴露 | 用户无法浏览 Skill/文档索引 |

### 1.3 市场 AGI 对标（论证优势）

| 维度 | OpenAI Memory | Claude Projects | Cursor | Claude Code | **dreambuddy-v2** |
|------|---------------|-----------------|--------|-------------|-------------------|
| 存储模型 | 平铺 KV / 向量 | 项目级 context | 项目内 .md | CLAUDE.md + skills | **分类轴 × 层级轴 7 类 + 贝叶斯置信度** |
| 置信度 | ❌ | ❌ | ❌ | ❌ | ✅ S/A/B/C/D 五级 + verify 升级 |
| 闭环 | 单向写 | 单向写 | 手动 | 手动 | **recall→record→verify→distill 四阶段** |
| Skill 系统 | 函数调用 | 无 | 无 | skills（无生命周期） | **Skill 索引 + 生命周期（shadow→active）+ TAG_HOOKS 自动桥** |
| 文档管理 | 无 | 无 | 无 | 无 | **doc-sync 自动 record + INDEX 索引** |
| 蒸馏/压缩 | 无 | 无 | 无 | 无 | **dynamic_distill_engine.py + BAC 三层压缩** |
| 跨会话回放 | 部分 | 部分 | ❌ | ❌ | **cognitive_backtest.py A/B 会话重放** |
| 元认知 | ❌ | ❌ | ❌ | ❌ | **0-元记忆/ + constitution.py 宪法层** |

**核心结论**：本系统在"贝叶斯置信度进化 + Skill↔记忆↔文档自动双向桥 + 元认知层"维度具备市场稀缺优势；瓶颈在"接入面"（前端），不在"能力面"（后端）。

---

## 二、设计原则与硬约束

### 2.1 设计原则（硬约束）

| 原则 | 含义 | 反例 |
|------|------|------|
| **P1 不改后端** | 4-MEMORY 后端代码冻结，仅在 3.1-FRONTEND 新增接入层 | ✗ 改 `cognitive_mcp_server.py` 协议 |
| **P2 接入面优先** | 瓶颈在接入不在能力，先打通数据流再优化展示 | ✗ 等后端重构完再做前端 |
| **P3 两层架构** | 平台级（VM/Skill/Doc）+ 用户级（user:*）物理隔离 | ✗ 用户偏好写入 VM-xxx |
| **P4 FAIL-OPEN** | 前端降级不影响后端，认知系统不可达时 UI 显示降级提示而非崩溃 | ✗ 后端不可用时整页 500 |
| **P5 复刻现有 IPC 模式** | 直接借鉴 dream-harness-bridge P0-5（VM-1789618914215）成熟模式 | ✗ 自创新 IPC 协议 |

### 2.2 不在范围（硬约束）

- ❌ 改 `4-MEMORY/` 任何 Python 后端代码
- ❌ 改 `cognitive_mcp_server.py` 的 MCP stdio 协议
- ❌ 引入新数据库（用户层用 SQLite 即可，复用现有 sqlite3 标准库）
- ❌ 重写 `cognitive_loop_entry.py`（CognitiveLoopEntry）
- ❌ 改 `1-ARCHITECTURE/skills/` 已有 Skill 定义

---

## 三、目标架构

### 3.1 三层接入架构

```
┌──────────────────────────────────────────────────────────────────────┐
│  前端层 — 3.1-FRONTEND (Next.js port 3001)                            │
│  /dashboard/memory                                                   │
│  ├─ DZEChainView (保留: 工程链压缩概念, 独立子页)                     │
│  ├─ CognitiveExplorer (新增: VM 记忆浏览 + recall 检索)               │
│  ├─ SkillIndexView   (新增: Skill 列表 + 生命周期)                    │
│  ├─ DocIndexView     (新增: 文档索引 + doc-sync 状态)                 │
│  └─ UserMemoryView   (新增: 用户偏好 / 会话 / 笔记)                   │
│                                                                      │
│  Stores (Zustand):                                                   │
│  ├─ memoryStore     (改造: fetch 真实 VM 数据, 替代静态壳)            │
│  ├─ cognitiveStore  (新增: recall/record/verify 操作)                │
│  └─ userMemoryStore (新增: user:* 命名空间)                           │
└────────────────────────────┬──────────────────────────────────────────┘
                             │ HTTP fetch / SWR
┌────────────────────────────┴──────────────────────────────────────────┐
│  接入层 — Next.js API Routes (3.1-FRONTEND/src/app/api/)               │
│  ├─ /api/cognitive/recall    GET  (包裹 MCP stdio recall)             │
│  ├─ /api/cognitive/record   POST  (包裹 MCP stdio record)             │
│  ├─ /api/cognitive/verify   POST  (包裹 MCP stdio verify)             │
│  ├─ /api/cognitive/stats    GET   (包裹 MCP stdio stats)              │
│  ├─ /api/cognitive/health   GET   (包裹 MCP stdio health)             │
│  ├─ /api/skills/index       GET   (包裹 skill_indexer.list_skills)     │
│  ├─ /api/docs/index        GET   (包裹 doc_sync_trigger.doc_index)    │
│  └─ /api/user-memory/*      CRUD  (独立 SQLite, 不进 VM-xxx)           │
└────────────────────────────┬──────────────────────────────────────────┘
                             │ subprocess JSON-RPC over stdio
                             │ (复刻 dream-harness-bridge P0-5 模式)
┌────────────────────────────┴──────────────────────────────────────────┐
│  后端层 — 4-MEMORY (冻结, 不改一行代码)                                │
│  ├─ cognitive_mcp_server.py (stdio MCP, 5 工具)                       │
│  ├─ CognitiveLoopEntry (cle)                                         │
│  ├─ cognitive_memory.db (VM-xxx 记忆)                                 │
│  ├─ 1-ARCHITECTURE/skills/ (Skill 索引, skill_indexer.py)             │
│  └─ 1-ARCHITECTURE/dreamos/core/compute/doc_sync_trigger.py           │
└──────────────────────────────────────────────────────────────────────┘

         ┌─────────────────────────────────────────────┐
         │  平台级 vs 用户级 隔离                       │
         │  ─────────────────────────────────           │
         │  平台级: VM-xxx / SKILL:xxx / DOC:xxx       │
         │           (cognitive_memory.db, 只读用户视角)│
         │  用户级: user:pref:* / user:sess:* / user:note:*│
         │           (user_memory.db, 独立 SQLite)      │
         │  原则: 用户层数据不污染平台 VM-xxx           │
         └─────────────────────────────────────────────┘
```

### 3.2 平台级 vs 用户级 职责矩阵

| 维度 | 平台级（底层） | 用户级 |
|------|---------------|--------|
| 数据库 | `cognitive_memory.db`（已有） | `user_memory.db`（新增，SQLite） |
| 命名空间 | `VM-*` / `SKILL:*` / `DOC:*` | `user:pref:*` / `user:sess:*` / `user:note:*` |
| 写入源 | 系统/Agent/IDE 自动 record | 用户表单 / 前端交互 |
| 读取权限 | 全局共享，所有用户可见 | 仅当前用户可见 |
| 验证机制 | verify 贝叶斯升级 | 无（用户输入即真相） |
| 蒸馏机制 | dynamic_distill_engine | 无（用户数据不蒸馏） |
| 备份策略 | 随仓库 git | 随用户 profile（如需多用户则独立表） |
| UI 入口 | `/dashboard/memory/cognitive` | `/dashboard/memory/user` |

---

## 四、模块分解

### M1. 认知 HTTP 网关（P0 必做）

**目标**：把 `cognitive_mcp_server.py` 的 5 个 stdio MCP 工具包裹为 HTTP 端点。

**复刻模式**：dream-harness-bridge P0-5（VM-1789618914215）
- Python handler 模式：同目录 import + `try/except ImportError fallback lambda`
- TS caller 模式：`createProtocolClient` + 按行过滤 stdout（因 import 会污染 stdout）+ 10s 超时
- FAIL-OPEN：`try/except + traceback.format_exc() + _send_stderr('WARN',...) + 返回 degraded=True 兜底`

**端点契约**：

| 端点 | 方法 | 入参 | 出参 | 后端调用 |
|------|------|------|------|---------|
| `/api/cognitive/recall` | GET | `context`, `top_k?=5`, `min_quality?="C"` | `{memories: [...], count, processes}` | MCP recall |
| `/api/cognitive/record` | POST | `{content, quality_level, tags}` | `{memory_id, success}` | MCP record |
| `/api/cognitive/verify` | POST | `{memory_id, success}` | `{new_quality, confidence}` | MCP verify |
| `/api/cognitive/stats` | GET | — | `{total, by_quality, by_tag}` | MCP stats |
| `/api/cognitive/health` | GET | — | `{db_ok, mcp_ok, latency_ms}` | MCP health |

**实现路径**（两种候选，P0 选 A）：

- **方案 A（推荐）**：Next.js API Route + `child_process.spawn('python3', ['cognitive_mcp_server.py'])` + stdin 写 JSON-RPC + stdout 按行过滤 + 10s 超时 + FAIL-OPEN
- 方案 B：直接 `import { CognitiveLoopEntry } from python`(via python-shell)，耦合更紧但延迟低

**FAIL-OPEN 兜底**：后端不可达时返回 `{degraded: true, memories: [], reason: 'cognitive_mcp_unreachable'}`，UI 显示降级提示。

### M2. 前端 Store 重构（P0 必做）

**目标**：把 `memory-store.ts` 从静态 Zustand 改为 fetch 真实 VM 数据。

**改造点**：

| 当前 | 目标 |
|------|------|
| `dzeChains` 写死三链 | 保留（作为工程链压缩独立概念，独立子页） |
| `records: []` 永远空 | `fetchRecords()` 调 `/api/cognitive/recall?context=recent&top_k=50` |
| `compressionStats` 全 0 | `fetchStats()` 调 `/api/cognitive/stats` |
| 无 fetch / SWR | 引入 SWR（项目已有 `lib/v3/api/client.ts`） |
| 无错误处理 | FAIL-OPEN：fetch 失败显示降级 banner |

**新增 store**：`cognitive-store.ts`
- `recall(context, top_k, min_quality)` → 返回 VM 列表
- `record(content, quality, tags)` → 写入新经验
- `verify(memory_id, success)` → 触发贝叶斯升级
- 缓存：SWR + 5 分钟 dedup

### M3. 用户层独立（P1）

**目标**：新增 `user_memory.db` + 命名空间 `user:*`，与平台 VM-xxx 物理隔离。

**数据模型**（SQLite schema）：

```sql
-- 用户偏好（key-value, 单值覆盖）
CREATE TABLE user_preferences (
  user_id TEXT NOT NULL,
  pref_key TEXT NOT NULL,
  pref_value TEXT,
  updated_at INTEGER,
  PRIMARY KEY (user_id, pref_key)
);

-- 用户会话历史（追加写入）
CREATE TABLE user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  topic TEXT,
  summary TEXT,
  created_at INTEGER
);

-- 用户笔记（CRUD）
CREATE TABLE user_notes (
  id TEXT PRIMARY KEY,  -- user:note:xxx
  user_id TEXT NOT NULL,
  title TEXT,
  content TEXT,
  tags TEXT,  -- 逗号分隔
  created_at INTEGER,
  updated_at INTEGER
);
```

**API 端点**：`/api/user-memory/*`（CRUD），不进 `cognitive_memory.db`。

**命名空间硬约束**：用户层 record **禁止写入** `cognitive_memory.db`；如需将用户经验沉淀为平台 VM，需经 `verify` 人工审批后才迁移（P3 阶段）。

### M4. dashboard 接入（P1）

**路由改造**：`/dashboard/memory` 改为统一入口 + 5 个子页（tab 切换）：

| 子路由 | 内容 | 数据源 |
|--------|------|--------|
| `/dashboard/memory` (默认) | 概览：stats + 最近记忆 + 三链状态 | 综合 |
| `/dashboard/memory/cognitive` | VM 记忆浏览 + recall 检索 | M1 网关 |
| `/dashboard/memory/skills` | Skill 列表 + 生命周期 | M5 skill_indexer |
| `/dashboard/memory/docs` | 文档索引 + doc-sync 状态 | M5 doc_sync_trigger |
| `/dashboard/memory/user` | 用户偏好 / 会话 / 笔记 | M3 user_memory.db |
| `/dashboard/memory/dze` | 工程链压缩（保留原 DZEChainView） | 静态 + 工程链 record |

### M5. Skill / Doc 索引接入（P1-P2）

**Skill 索引**：包裹 `1-ARCHITECTURE/skills/dream-skill-index-governance/skill_indexer.py`
- 端点：`GET /api/skills/index` → `{skills: [{id, name, lifecycle, last_verified}]}`

**文档索引**：包裹 `1-ARCHITECTURE/dreamos/core/compute/doc_sync_trigger.py`
- 端点：`GET /api/docs/index` → `{docs: [{path, last_synced, cognitive_linked}]}`
- 端点：`POST /api/docs/sync` → 手动触发 doc-sync（写入 VM 记忆）

---

## 五、阶段路线图

### P0 · 最小接入（核心打通）

**范围**：M1（认知 HTTP 网关）+ M2（前端 store 改造为 fetch）

**交付物**：
- 5 个 `/api/cognitive/*` 端点可独立 curl
- `/dashboard/memory` 显示真实 stats + 非空记录列表
- FAIL-OPEN：后端关停时 UI 不崩

**验收命令**：
```bash
# 1. 端点冒烟
curl 'http://localhost:3001/api/cognitive/stats' | jq .
curl 'http://localhost:3001/api/cognitive/recall?context=test&top_k=3&min_quality=C' | jq .

# 2. 页面验证
agent-browser open http://localhost:3001/dashboard/memory
agent-browser snapshot -i  # 压缩统计应非 0，记录列表应非空
```

### P1 · 用户层 + Skill 索引接入

**范围**：M3（用户层独立）+ M4（dashboard 子页）+ M5 部分（Skill 索引）

**交付物**：
- `/dashboard/memory/user` 可读写用户偏好 / 笔记
- `/dashboard/memory/skills` 展示 Skill 列表 + 生命周期徽章
- `user_memory.db` 独立 SQLite，与 `cognitive_memory.db` 物理隔离

**验收**：
```bash
curl 'http://localhost:3001/api/user-memory/preferences' -X POST -d '{"key":"risk_tolerance","value":"low"}'
curl 'http://localhost:3001/api/skills/index' | jq '.skills | length'
```

### P2 · 文档索引 + 概念对齐

**范围**：M5 文档索引 + DZE/BAC 概念与 4-MEMORY 7 类记忆对齐

**交付物**：
- `/dashboard/memory/docs` 展示文档索引 + doc-sync 状态
- 文档变更触发 doc-sync record 入认知系统（前端可见）
- DZE 三链映射到 4-MEMORY 7 类记忆分类轴（D=设计→3-架构记忆 / Z=工程→5-通用经验 / E=评估→0-元记忆）

### P3 · 双向交互（用户经验沉淀为平台 VM）

**范围**：前端 record/verify 操作 + 用户笔记 → 平台 VM 沉淀审批流

**交付物**：
- 前端表单 → `/api/cognitive/record` 写入新 VM 记忆
- 前端 verify 按钮 → `/api/cognitive/verify` 触发贝叶斯升级
- 用户笔记"沉淀为平台经验"按钮 → 人工审批后从 `user:note:*` 迁移到 `VM-*`

---

## 六、数据流

### 6.1 recall 路径（读）
```
前端 cognitiveStore.recall()
  → SWR fetch GET /api/cognitive/recall?context=...
  → Next API Route
  → child_process.spawn('python3', ['cognitive_mcp_server.py'])
  → stdin: JSON-RPC {"method":"tools/call","params":{"name":"recall","arguments":{...}}}
  → stdout: 按行过滤（仅 schema_version+message_type='response' 的 JSON 行）
  → 解析返回 {memories, count, processes}
  → UI 渲染 VM 列表（含 quality_level 徽章 + tags + score）
```

### 6.2 record 路径（写）
```
前端表单 → POST /api/cognitive/record
  → 同 spawn 模式调 MCP record
  → cognitive_memory.db 写入 VM-xxx
  → TAG_HOOKS 触发（doc-sync / wiki-compile / SKILL 等下游）
  → 返回 {memory_id, success}
  → SWR mutate 刷新列表
```

### 6.3 用户层路径（隔离）
```
前端 userMemoryStore
  → fetch /api/user-memory/preferences
  → user_memory.db（独立 SQLite, 路径: 3.1-FRONTEND/data/user_memory.db）
  → 不进 cognitive_memory.db
  → 不触发 TAG_HOOKS
```

### 6.4 verify 路径（升级）
```
前端 verify 按钮 → POST /api/cognitive/verify
  → MCP verify → 贝叶斯置信度更新
  → 触发 dynamic_distill_engine 蒸馏（如达到阈值）
  → 返回 {new_quality, confidence}
  → UI 更新徽章（如 B → A）
```

---

## 七、命名空间与隔离

### 7.1 命名空间约定（硬约束）

| 类型 | 前缀 | 数据库 | 写入源 | 示例 |
|------|------|--------|--------|------|
| 平台认知 | `VM-` | `cognitive_memory.db` | 系统/Agent/IDE 自动 | `VM-1790865488067-f1127123` |
| 平台 Skill | `SKILL:` | `cognitive_memory.db`（cognitive_links 表） | skill_indexer 自动 | `SKILL:dream-tdd-dev-workflow` |
| 平台文档 | `DOC:` | `cognitive_memory.db` | doc_sync_trigger 自动 | `DOC:0-系统文档管理/INDEX.md` |
| 用户偏好 | `user:pref:` | `user_memory.db` | 用户表单 | `user:pref:risk_tolerance` |
| 用户会话 | `user:sess:` | `user_memory.db` | 前端会话管理器 | `user:sess:abc123` |
| 用户笔记 | `user:note:` | `user_memory.db` | 用户 CRUD | `user:note:weekly_review` |

### 7.2 隔离原则

- ❌ 用户层 API 禁止直接写 `cognitive_memory.db`
- ❌ 用户笔记不可自动升级为 VM（必须经 P3 人工审批流）
- ✅ 平台 VM 可被用户层 recall（只读）
- ✅ 用户层数据可独立备份/导出（不影响平台）

---

## 八、风险与对策

| # | 风险 | 概率 | 影响 | 对策 |
|---|------|------|------|------|
| R1 | stdio MCP 子进程启动慢（每次 spawn ~200ms） | 高 | recall 延迟感 | P0 用短生命周期进程池 or 改方案 B（python-shell） |
| R2 | stdout 污染（Python import 输出混入 JSON-RPC） | 高 | 解析失败 | 复刻 P0-5 行过滤：仅 `schema_version + message_type='response'` 行 |
| R3 | 用户层数据污染平台 VM | 中 | 严重 | 独立 DB + 命名空间前缀 + API 层硬隔离 |
| R4 | DZE/BAC 概念与 7 类记忆难对齐 | 中 | 中 | P2 阶段单独处理，保留 DZE 独立子页降级方案 |
| R5 | recall 性能（DB 大后慢） | 中 | 中 | 网关层 5 分钟缓存 + top_k 上限 50 |
| R6 | 多用户场景下 user_memory.db 并发写 | 低 | 低 | SQLite WAL 模式 + user_id 索引 |
| R7 | 后端 cognitive_mcp_server.py 协议变更 | 低 | 中 | 接入层版本锁定 + FAIL-OPEN |

---

## 九、验收清单

### P0 验收
- [ ] `curl /api/cognitive/stats` 返回非空 JSON（total > 0）
- [ ] `curl '/api/cognitive/recall?context=test&top_k=3'` 返回 ≥1 条 VM 记忆
- [ ] `/dashboard/memory` 压缩统计区域显示非 0 数值
- [ ] `/dashboard/memory` 记录列表显示真实 VM 内容（非"暂无"）
- [ ] 后端关停时 UI 显示降级提示而非 500（FAIL-OPEN）
- [ ] `agent-browser snapshot` 页面元素含真实 VM id

### P1 验收
- [ ] `/dashboard/memory/user` 可读写用户偏好（POST + GET）
- [ ] `/dashboard/memory/skills` 显示 Skill 列表 + 生命周期徽章
- [ ] `user_memory.db` 与 `cognitive_memory.db` 物理隔离（不同文件）
- [ ] 用户层数据库无任何 `VM-` 前缀记录

### P2 验收
- [ ] `/dashboard/memory/docs` 显示文档索引
- [ ] 文档变更触发 doc-sync record 入 `cognitive_memory.db`（前端可观察）
- [ ] DZE 三链映射到 4-MEMORY 7 类记忆分类轴（独立子页保留）

### P3 验收
- [ ] 前端 record 表单 → 新 VM 记忆出现在列表
- [ ] 前端 verify 按钮 → quality_level 徽章变化（如 B → A）
- [ ] 用户笔记"沉淀为平台经验"按钮 → 审批通过后 `user:note:*` 迁移为 `VM-*`

---

## 十、文档落盘说明

- **本 SPEC 落盘路径**：`1-ARCHITECTURE/specs/COGNITIVE_SYSTEM_INTEGRATION_SPEC.md`
- **状态机分类**：Hold（待用户评审，未闭环）
- **后续动作**：
  1. 用户评审 → 通过则状态变 Active，进入 P0 实施
  2. P0 实施完成后 → 补 `docs/` 五件套（README + IDX + TD + API + CL）
  3. 同步登记到 `0-系统文档管理/INDEX.md` §8 快速导航

---

**附：本 SPEC 不写实现代码**（用户明确"只评估不改代码"），P0 启动时再按本 SPEC §四模块契约实施。
