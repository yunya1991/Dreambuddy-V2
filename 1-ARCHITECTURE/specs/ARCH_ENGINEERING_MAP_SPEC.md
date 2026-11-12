# ARCH-ENGINEERING-MAP — 架构驾驶舱 SPEC（A+）

- **版本**：v0.1.3（M0/M1/M2 已落地）
- **日期**：2026-11-12
- **定位**：开发阶段专用的「架构工程地图」——把 SACG 架构节点与能力在前端可视化，运行时点亮，并按「每轮架构推进结束」留快照复盘，用于发现**架构完整性缺口**、**数据流断点**与**大模型实现漂移**。
- **上游约束**：[DREAM_ARCH_LANDING_SPEC](./DREAM_ARCH_LANDING_SPEC.md)（不重复造轮子）、《SYSTEM_ARCHITECTURE_OVERVIEW.md v4.2》（只有 SACG）
- **硬约束**：仅 dev 使用；不新建事件总线/图数据库；不手写拓扑；埋点只在 3 个边界。

---

## 0. 结论（可行性）

**可行，地基已有 4/5，不需要新建基础设施。**

| 层 | 已有资产（实测） | 复用方式 |
|---|---|---|
| 静态拓扑 | [`build_d2_architecture_graph.py`](../../48-涌现架构/baselines/build_d2_architecture_graph.py) → `artifacts/d2_architecture_graph/architecture_graph.json`：7859 节点（py 4110 / md 3303 / external 446）、53959 边（call 27563 / import 24640 / doc_ref 1756），`dangling=0`，可重生成 | 只加「投影」步骤，不改 builder |
| 运行时通道 | [`monitor-bus.ts`](../../3.1-FRONTEND/src/lib/monitor-bus.ts)（RingBuffer 500；`trace_id/layer/phase/status/duration_ms/extra`）+ `/api/monitor/stream` SSE + `/api/monitor/events` | 直接订阅，零改动 |
| 前端渲染 | [`DAGGraphView.tsx`](../../3.1-FRONTEND/src/components/features/monitor/DAGGraphView.tsx)（自绘 SVG，S/A/C/G 上色 + `active` 高亮）、`HistoryPlayer` | 复用配色与 SVG 画法，新建独立视图组件 |
| 能力注册 | [`mcp_capabilities.yaml`](../../47-MCP管理系统/registry/mcp_capabilities.yaml)（10 壳 + 5 角色） | 作为 C 层节点的补充标注 |
| 公共键 | 图是 file-level，事件是 `layer+phase`，**无 `cap_id`** | 缺口，用规则表补齐 |

三个缺口：**口径断层**（文件节点 ↔ 事件 phase）、**图过重**（9.5MB 不可下发）、**Python 盲区**（DSH/C-Drive 不发 monitor 事件，只能先在 IPC 边界观测）。

---

## 1. 目标与非目标

### 1.1 目标

| 编号 | 目标 | 验收信号 |
|---|---|---|
| G-M0 | 一张自动生成的 SACG 能力地图 | `project_arch_map.py` 输出 ≥60 个能力节点、边已聚合；`/dev/arch-map` 可打开；生产环境 404 |
| G-M1 | 能力被调用时点亮 | 发一次任务，S→A→C→G 顺序点亮；失败红、完成绿、30s 衰减 |
| G-M2 | 每轮架构推进后可复盘 | `arch_map_review.py --run-id <id>` 产出快照 + `review.md`；列出新增/删除/孤立/未接线能力 |
| G-M3 | 防大模型漂移 | 复盘报告能指出「SPEC 声称已有但图中无」「图中已有但从未点亮」「本轮新增但未接线」三类偏差 |

### 1.2 非目标

- 不做生产监控/告警（生产监控已有 `/dashboard/monitor`）。
- 不引入 Graph 库（reactflow/cytoscape/d3）、不引入 OTel/Jaeger/Grafana。
- 不逐文件埋点（7859 个），不追求 100% 覆盖。
- 不替代 REA（REA 是事实源，地图是聚合视图）。
- 不写数据库；快照落本地文件，不入库。

---

## 2. 总体设计

```
┌───────────────────────────────────────────────────────────────┐
│ 生成层（Python，仓库根）                                        │
│  architecture_graph.json ──project──▶ arch-map.json / cap-map.json │
│         ▲                                  │                    │
│         └── build_d2_architecture_graph.py  │                    │
│  arch_map_rules.yaml（唯一人工维护：层归属 + phase→cap 映射）        │
├───────────────────────────────────────────────────────────────┤
│ 运行时层（Next.js，零新增后端）                                  │
│  monitor-bus ──SSE /api/monitor/stream──▶ useArchMapLive        │
│     ▲ 生产者：task-manager / intent / router / DSH IPC 边界      │
├───────────────────────────────────────────────────────────────┤
│ 展示层 /dev/arch-map（仅 dev）                                   │
│  ArchMapView：SACG 四泳道 + 能力节点 + 聚合边 + 健康度着色         │
├───────────────────────────────────────────────────────────────┤
│ 复盘层（Python CLI）                                             │
│  arch_map_review.py ──▶ .arch-map/history/<ts>_<run_id>.json     │
│                     └─▶ .arch-map/history/<ts>_<run_id>.md       │
└───────────────────────────────────────────────────────────────┘
```

### 2.1 三条硬设计

1. **拓扑不手写**：能力节点来自目录聚合 + 规则文件；规则文件只声明「层归属 / 展示名 / phase 映射」，不声明边。
2. **运行时零 schema 变更**：点亮信息走 `MonitorEvent.extra.cap_id`（字段已存在）；旧事件按 `phase_map` 兜底。
3. **dev-only**：`/dev/arch-map` 在 `NODE_ENV === 'production'` 且未设 `NEXT_PUBLIC_ARCH_MAP=1` 时 `notFound()`；数据随 dev chunk 打包，不落 `public/`。

---

## 3. 数据契约

### 3.1 `arch_map_rules.yaml`（唯一人工维护文件）

```yaml
layers:
  - { id: S, label: 认知规划 }
  - { id: A, label: 节点验收 }
  - { id: C, label: 执行驱动 }
  - { id: G, label: 压缩沉淀 }
  - { id: X, label: 支撑/外部 }

# 能力节点：id + 展示名 + 层 + 路径前缀（聚合到这些前缀）
capabilities:
  - { id: S.intent,        label: 意图识别,   layer: S, paths: ["3.1-FRONTEND/src/lib/intent/", "1-ARCHITECTURE/dreamos/core/sense/"] }
  - { id: S.recall,        label: 经验召回,   layer: S, paths: ["4-MEMORY/"] }
  - { id: S.plan,          label: 计划编排,   layer: S, paths: ["1-ARCHITECTURE/dreamos/core/arrange/"] }
  - { id: A.skills,        label: SKILL 注册, layer: A, paths: ["1-ARCHITECTURE/skills/", "1-ARCHITECTURE/工作索引/"] }
  - { id: A.selector,      label: 技能选择,   layer: A, paths: ["3.1-FRONTEND/src/lib/skill-selector", "24-图结构上下文压缩/planner/"] }
  - { id: C.dsh,           label: DSH 执行,   layer: C, paths: ["1-ARCHITECTURE/dream-harness-bridge/", "46-DSH架构/"] }
  - { id: C.cdrive,        label: C-Drive,    layer: C, paths: ["1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py", "3.1-FRONTEND/src/lib/c-drive.ts"] }
  - { id: C.rea,           label: REA 逆向,   layer: C, paths: ["33-REA逆向解析工程/"] }
  - { id: C.mcp,           label: MCP 壳,     layer: C, paths: ["47-MCP管理系统/"] }
  - { id: C.trade,         label: 交易执行,   layer: C, paths: ["6-TRADING/", "10-经典指标系统/", "18-数据获取中心/", "19-数据访问层/"] }
  - { id: G.knowledge,     label: 知识库,     layer: G, paths: ["2-KNOWLEDGE/"] }
  - { id: G.docs,          label: 文档索引,   layer: G, paths: ["0-系统文档管理/", "41-文件索引系统/"] }
  - { id: G.emergence,     label: 涌现实验,   layer: G, paths: ["48-涌现架构/"] }
  - { id: X.frontend,      label: 前端应用,   layer: X, paths: ["3.1-FRONTEND/src/app/", "3.1-FRONTEND/src/components/", "3.1-FRONTEND/src/stores/"] }

# 未命中任何 paths 的目录 → 归 X.other（自动聚合）
# 运行时 phase → cap（M1 点亮兜底，按优先级 match）
phase_map:
  user_input: [S.intent]
  intent_recognized: [S.intent]
  recognized: [S.intent]
  rule_follow_up: [S.intent]
  chain_started: [S.plan, A.selector]
  routed: [A.selector]
  task_created: [C.dsh]
  inline_exec_start: [C.dsh]
  inline_exec_done: [C.dsh]
  async_spawned: [C.dsh]
  artifact_synced: [G.knowledge, G.docs]
  index_updated: [G.docs]
  feed_ready: [G.knowledge]
  result_displayed: [X.frontend]
  jev_evaluated: [C.cdrive]

# layer 级兜底（phase 未命中时）
layer_default:
  frontend: [X.frontend]
  gateway: [C.dsh]
  intent: [S.intent]
  router: [A.selector]
  workbuddy: [C.dsh]
  artifact_hub: [G.docs]
```

### 3.2 `arch-map.json`（投影产物）

```json
{
  "schema": "ArchMap/v1",
  "generated_at": "2026-11-12T...",
  "source": { "graph_sha256": "...", "node_count": 7859, "edge_count": 53959 },
  "layers": [{ "id": "S", "label": "认知规划" }],
  "nodes": [{
    "id": "C.dsh", "label": "DSH 执行", "layer": "C",
    "files": 421, "loc": 120345,
    "hit": true, "orphan": false,
    "owner_paths": ["1-ARCHITECTURE/dream-harness-bridge/"]
  }],
  "edges": [{ "src": "A.selector", "dst": "C.dsh", "kind": "import", "weight": 42 }],
  "unmapped": { "dirs": ["37-一键启动脚本/"], "files": 812 }
}
```

- 节点粒度：`capabilities[].paths` 聚合；未命中的顶层目录 → `X.other.<dir>`；`external:*` → `X.external`。
- 边：file-level 边两端映射到 cap 后聚合，`weight` = 原始边数；自环丢弃。
- `hit`：是否有至少一条入/出边（静态连通性）。
- `orphan`：`files > 0` 但 `hit == false`。
- 目标体积：≤ 300KB（未压缩）。规模基线（v0.1.1 实测）：**能力节点 ≥40、聚合边 ≥500**。

> **覆盖面说明（v0.1.1 修正）**：`architecture_graph.json` 只扫描 `.py/.md`，因此纯 TS 能力（`X.frontend`、`A.selector`、`A.router`、`C.cdrive`）`files=0`，界面显示「未入图」。这是**预期口径**，不是 bug；它们的运行时点亮由 M1 事件补齐，`files=0` 也用于识别「声明了但没有任何后端落点」的能力。原 v0.1.0 的「节点 ≥60」按能力粒度不可达，改为 ≥40 并按真实能力拆分（不靠碎片化凑数）。

### 3.3 `cap-map.json`（运行时映射产物）

```json
{ "schema": "CapMap/v1", "generated_at": "...", "phase_map": {}, "layer_default": {}, "cap_ids": ["S.intent", "..."] }
```

### 3.4 点亮事件（不新增 schema）

优先级：`event.extra.cap_id`（string | string[]）→ `phase_map[event.phase]` → `layer_default[event.layer]` → 忽略。
节点运行态：`idle | warm(<5min) | active(<30s) | failed(<30s)`；累计 `hits/completed/failed/last_duration_ms`。

运行态导出（`/dev/arch-map` →「导出本次点亮」，`arch_map_review.py --runtime` 读取）：

```json
{
  "schema": "ArchMapRuntime/v1",
  "exported_at": "2026-11-12T05:30:00Z",
  "since": "2026-11-12T05:00:00Z",
  "caps": { "C.dsh": { "hits": 3, "completed": 2, "failed": 1, "last_at": "...", "last_duration_ms": 820 } },
  "ghosts": { "Ghost.cap": 1 }
}
```

`ghosts` = 运行态出现但 `cap-map.cap_ids` 中不存在的 cap（规则表过期信号），由前端直接随导出带走。

### 3.5 复盘快照（`.arch-map/history/`）

```json
{
  "schema": "ArchMapSnapshot/v1",
  "run_id": "ARCH-20261112-01",
  "ts": "...",
  "graph_sha256": "...",
  "nodes": 46, "edges": 772,
  "file_nodes": 7859,
  "orphans": ["X.other.37-一键启动脚本"],
  "unmapped": { "dirs": ["1-ARCHITECTURE"], "files": 302 },
  "cap_index": { "C.dsh": { "label": "DSH 执行", "layer": "C", "files": 244, "in": 12, "out": 9, "orphan": false } },
  "runtime": { "source": "export|none", "hits": { "C.dsh": 3 }, "failed": {}, "ghosts": {} },
  "analysis": { "signals": {}, "drift": false, "reasons": [], "warnings": [] }
}
```

`.arch-map/history/index.json` 存快照顺序；`.gitignore` 忽略 `.arch-map/history/`（不入库）。

---

## 4. 分期与任务

### M0 静态地图（先落地）

| 任务 | 内容 | 文件 | 验收 |
|---|---|---|---|
| T-M0-1 | 规则文件（层/能力/phase 映射） | `48-涌现架构/baselines/arch_map_rules.yaml`（新） | YAML 可解析，cap id 唯一 |
| T-M0-2 | 投影脚本 | `48-涌现架构/baselines/project_arch_map.py`（新） | 读 graph → 输出两个 JSON；打印节点/边/unmapped 统计 |
| T-M0-3 | 生成产物 | `3.1-FRONTEND/src/data/arch-map/{arch-map,cap-map}.json` | 体积 ≤300KB；节点 ≥60 |
| T-M0-4 | dev 路由 + 视图 | `3.1-FRONTEND/src/app/dev/arch-map/page.tsx`、`src/components/features/arch-map/ArchMapView.tsx`、`src/lib/arch-map/types.ts` | 四泳道可读；生产 404 |

### M1 运行时点亮

| 任务 | 内容 | 文件 | 验收 |
|---|---|---|---|
| T-M1-1 | 订阅 SSE + 映射 + 衰减 | `src/components/features/arch-map/useArchMapLive.ts` | 一次任务按 S→A→C→G 点亮；30s 衰减 |
| T-M1-2 | 节点态渲染 | `ArchMapView.tsx` | active 发光、failed 红、warm 半亮 |
| T-M1-3 | 边界补 `cap_id`（可选，不改 schema） | `task-manager.ts`、`smart-router.ts`、`dsh-execution-engine.ts` 的 `emitMonitorEvent({... extra})` | 有 `cap_id` 时优先使用 |

### M2 复盘与漂移检测

| 任务 | 内容 | 文件 | 验收 |
|---|---|---|---|
| T-M2-1 | 快照脚本 | `48-涌现架构/baselines/arch_map_review.py`（新，含 `--run-id/--base/--fail-on-drift`） | 产出 `history/<ts>_<run>.json|.md`；退出码可控 |
| T-M2-2 | 漂移分类 | 同上 | 报告含：`topology_delta`、`orphan`、`never_lit`、`ghost`（运行时 id 不在图） |
| T-M2-3 | 接进收尾流程 | `dream-completion-evolution-workflow` SKILL 增加一步 | 收尾时自动跑复盘并贴结论 |
| T-M2-4 | 前端导出/导入运行态 | `/dev/arch-map` 增加「导出本次点亮」/「载入历史」 | 导出 JSON 可供 `arch_map_review.py --runtime` 读取 |

**依赖顺序**：T-M0-1 → T-M0-2 → T-M0-3 → T-M0-4 → T-M1-1/T-M1-2 → T-M2-1/T-M2-2 → T-M2-3/T-M2-4。

### 4.1 交付状态（v0.1.1）

| 任务 | 状态 | 实际落点 |
|---|---|---|
| T-M0-1/2/3 | ✅ | `48-涌现架构/baselines/arch_map_rules.yaml`、`project_arch_map.py`、`3.1-FRONTEND/src/data/arch-map/{arch-map,cap-map}.json`（46 能力 / 772 边 / 78.1KB） |
| T-M0-4 | ✅ | `src/app/dev/arch-map/page.tsx`、`src/components/features/arch-map/ArchMapView.tsx`、`src/lib/arch-map/types.ts` |
| T-M1-1/2 | ✅ | `src/components/features/arch-map/useArchMapLive.ts`（SSE 订阅 + 200ms 批量 + 30s 衰减 + ghost 记录） |
| T-M1-3 | ⏳ 可选 | 未改任何生产者；当前完全依赖 `phase_map`/`layer_default` 兜底 |
| T-M2-1/2 | ✅ | `48-涌现架构/baselines/arch_map_review.py`（`--run-id/--base/--runtime/--rebuild/--fail-on-drift`） |
| T-M2-3 | ✅ | `dream-completion-evolution-workflow` SKILL 步骤 5.6（`.trae/skills` 与 `1-ARCHITECTURE/skills` 双副本同步） |
| T-M2-4 | ✅ | `/dev/arch-map` 顶部「导出本次点亮 / 载入历史运行态 / 重置」 |

---

## 5. 每轮架构推进后的复盘（防漂移闭环）

固定四步，接在「收尾」阶段：

1. **重生成**：`python3 48-涌现架构/baselines/build_d2_architecture_graph.py`（或在 review 脚本内 `--rebuild`）。
2. **投影 + 快照**：`python3 48-涌现架构/baselines/project_arch_map.py && python3 48-涌现架构/baselines/arch_map_review.py --run-id <本轮ID> --runtime <可选导出>`
3. **读结论**：`review.md` 四类信号
   - `topology_delta`：新增/删除能力或边显著变化 → 对照本轮 SPEC 范围，判断是否越界。
   - `orphan`：有文件但无任何边 → 疑似未接线/死代码。
   - `never_lit`：本轮运行态从未点亮的能力 → 数据流未覆盖或事件映射缺失。
   - `ghost`：运行态出现图中不存在的 cap → 规则表过期，图与代码漂移。
4. **回写**：结论进 `.runs/<run_id>/review.md`；发现架构问题 → 写回 DREAM 落地 SPEC §4 或本轮 SPEC。

**漂移判据（默认，可调）**
- 节点增删 > 5% 或边增删 > 10% → 必须人工确认是否在 SPEC 范围内。
- 出现 `ghost` → 视为规则表失效，必须补 `arch_map_rules.yaml`。
- `never_lit` 覆盖本轮宣称改动的能力 → 视为「接线未完成」，不得宣称完成。

---

## 6. 验收

### 6.1 自动

- `python3 48-涌现架构/baselines/project_arch_map.py` → 退出码 0，打印 `nodes/edges/unmapped`；产物 **节点 ≥40、边 ≥500、≤300KB**。
- `python3 48-涌现架构/baselines/arch_map_review.py --run-id smoke` → 退出码 0，生成两个文件。
- `cd 3.1-FRONTEND && npx tsc --noEmit` → 0 error（仅本 SPEC 新增文件）。
- `npm run lint` → 不新增 error（注：仓库缺 `eslint.config.js`，lint 为既有失败，与本 SPEC 无关）。

### 6.2 手工

| 编号 | 步骤 | 期望 |
|---|---|---|
| A1 | `npm run dev` 后访问 `/dev/arch-map` | 四泳道 + 能力节点 + 聚合边可读 |
| A2 | `NODE_ENV=production` 下访问 `/dev/arch-map` | 404 |
| A3 | 在 `/dashboard/trade` 发一次任务 | 地图按 S→A→C→G 依次点亮，30s 后转 warm |
| A4 | 构造一条失败事件 | 对应节点变红并保留 30s |
| A5 | 跑 `arch_map_review.py --run-id demo` | `review.md` 列出四类信号，退出码符合 `--fail-on-drift` |

---

## 7. 风险

| 编号 | 风险 | 缓解 |
|---|---|---|
| R1 | 图漂移（代码变了没重生成） | 收尾流程强制重生成；界面显示 `generated_at`，超 7 天标黄 |
| R2 | 规则表维护成本 | 只维护层归属与 phase 映射；未命中自动落 `X.other` |
| R3 | Python 侧盲区 | M1 明确「仅前端可观测」；DSH 在 IPC 边界记 `C.dsh`，不保证子 Agent 粒度 |
| R4 | 9.5MB 图不可下发 | 投影 + 自环/弱边裁剪 + 仅 dev chunk |
| R5 | 事件量大导致渲染抖动 | 节流 200ms；节点最多 150；边权重阈值裁剪 |
| R6 | 生产误开 | 双重门禁（env + `NEXT_PUBLIC_ARCH_MAP`） |
| R7 | 把地图当唯一事实源 | 地图是聚合视图；冲突以 REA/代码为准，地图只做「提示」 |

---

## 8. 不做清单

- 不引入任何图可视化库或监控栈。
- 不在 `route.ts` 新增 `fs/child_process`（守住 C-C8 边界门禁）。
- 不写数据库、不做时序存储、不接生产。
- 不自动改代码/自动修复漂移（只报告）。
- 不把 `.arch-map/history/` 入库。

---

## 9. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1.0 | 2026-11-12 | 初稿：A+ 三期（M0 静态地图 / M1 运行时点亮 / M2 复盘漂移检测）；确定复用 architecture_graph + monitor-bus + DAGGraphView；新增 `arch_map_rules.yaml` 单文件规则与四类漂移信号 |
| v0.1.1 | 2026-11-12 | M0/M1/M2 落地：新增 §4.1 交付状态；补齐运行态导出契约（`ArchMapRuntime/v1`）与快照实际字段；规模判据由「节点 ≥60」修正为「能力 ≥40 / 边 ≥500」（图仅含 .py/.md，纯 TS 能力 files=0 为预期口径）；lint 既有失败标注 |
| v0.1.2 | 2026-11-12 | 自噪音修复：builder `EXCLUDE_DIRS` 增加 `.arch-map`（复盘产物非架构节点，否则每轮复盘自造 orphan → 假漂移）；规则表新增 `S.devgate`（覆盖 `.trae/skills/dreamos-dev/`）。实测：能力 46→47，orphan=0，对 ARCH-20261112-01 基准 drift=PASS（见 `ARCH-20261112-04`） |
| v0.1.3 | 2026-11-12 | 同源修复：`EXCLUDE_DIRS` 再加 `.runs`（dreamos-dev run 工作目录，含 plan/acceptance 等 .md，入图会自造 orphan）。`S.devgate` files 3→6（新增 g1/g2/g5 门禁脚本）。实测：nodes=47 / edges=815 / orphan=0 / drift=False（见 `ARCH-20261112-06`） |
