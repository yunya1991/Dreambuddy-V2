# SPEC-53 DSH 插件生态接入总规范

- **版本**: v0.2 ｜ **日期**: 2026-11-12 ｜ **状态**: 🟢 已评审（评审结论与问题清单见 §十）
- **归属**: 53-DSH插件模块（DSH Cordis 插件生态接入唯一事实源）
- **上游约束**: 46-DSH架构 v0.2 升级路径、47-MCP管理系统 SSoT、49-交易框架协议 v0.14.2
- **下游影响**: DSH Worker 工具面、.dsh-home 配置、L0 能力域封装形态

---

## §0 Executive Summary

### 0.1 一句话定位

**消费社区插件 → 封装 L0 为 DSH 插件 → 规划插件治理层**，三级递进，完全对齐 DSH v0.2 Super-agent 架构升级方向，边际成本极低（层级 1 近乎零代码）。

### 0.2 七条决策 (ADR)

| # | 决策 | 依据 |
|---|------|------|
| ADR-1 | **三维递进**: 先消费（P0）→ 再封装（P1）→ 后治理（P2+），不跨越阶段 | 层级 1 成本 ≈ 0，可立即验证价值 |
| ADR-2 | **不替代 MCP**: DSH 插件封装是"Worker 原生工具面"，MCP 仍是跨端标准出口 | 47 SPEC 已确立 MCP = L0 对外统一出口，插件 = DSH 内部增强 |
| ADR-3 | **认知 + 检索优先封装**: 首批 DSH 插件只做这两域 | Worker 刚需最高、已 MCP 化、契约最稳定 |
| ADR-4 | **社区插件白名单 + sandbox profile**: 只装验证过的插件，隔离 profile 运行 | 社区插件 23,000+ 已索引 / 6,000+ 已验证（npm `dsh-plugin` 市场，2026-11-12），质量参差，FAIL-OPEN 是硬约束 |
| ADR-5 | **42 协调层不改造**: DSH 插件治理独立于 42 插件总线 | 42 服务交易域信号归一化，53 服务 DSH Worker 工具面，职责正交 |
| ADR-6 | **安全边界 FAIL-OPEN**: 任何社区插件执行失败/超时/异常 → Worker 拿到 degraded 结果而非 crash | 对齐 46 DESIGN v0.2 §5 红线 |
| ADR-7 | **Creator mode 产出临时插件进入白名单流程**: 对话生成的插件不直接载入生产 profile | 安全审计最小集 |

### 0.3 不做什么

| 禁止 | 原因 |
|---|---|
| 不把 DSH 插件当 MCP 替代 | MCP 是跨端契约，插件是 DSH 内部原生增强，职责不同 |
| 不让社区插件直接访问执行层 (paper MCP / live 执行器) | 执行层权限只给 L0 签名 MCP 和 11 交易执行器 |
| 不一次性封装所有 L0 域为 DSH 插件 | REA/评测/金融语义先保留 MCP 形态，按需再封装 |
| 不修改 42 registry.yaml | 42 是交易域信号总线，53 是 DSH Worker 工具面，互不侵入 |
| 不在生产 profile 运行未验证的社区插件 | 安全隔离硬约束 |

---

## §一、背景与动机

### 1.1 现状核实

| 项 | 事实 | 来源 |
|---|---|---|
| DSH 版本 | v0.1.5-rc.2，底层 Cordis「一切皆插件」架构 | 46-DSH架构/README.md |
| 我们的 MCP 面 | 认知 (7 工具) + REA (adapter) + 金融语义 (4 工具) | 47 SPEC |
| Cordis 插件形态 | 命名导出 `apply(ctx, config)` 函数 + 可选 `name`/`inject`/`Config` | 官方教程第 1-3 章 |
| 社区插件规模 | 23,000+ 已索引 / 6,000+ 已验证（npm `dsh-plugin` 市场）；sandbase-harness 643★（GitHub，非 npm） | 2026-11-12 npm/GitHub 实测 |
| 我们的 DSH 升级方向 | Router/Worker 多 agent + 事件驱动 + 能力集限流 | DESIGN-DSH-ARCH-UPGRADE v0.2 七层架构 |

### 1.2 为什么现在做

1. **DSH v0.2 升级要求 Worker 具备工具面** —— 插件生态是最高效的工具面供给渠道
2. **Cordis 架构天然支持"插拔"** —— 不侵入内核，`cordis.patch.yml` 声明即用
3. **社区生态已成熟** —— 25,000+ 插件可立即消费，Creator mode 可对话开发
4. **反向赋能** —— 把我们的 L0 能力封装为 DSH 插件后，Worker 可原生调用，延迟低于 MCP

### 1.3 三层接入模型（核心概念）

```
┌─────────────────────────────────────────────────────────┐
│  层级 3: 插件治理层 (P2+)                                │
│  ┌─────────────────────────────────────────────────┐    │
│  │  插件注册表 · 沙盒运行时 · 版本兼容 · 安全扫描    │    │
│  │  ← 按需引入，等接入量 > 5 再规划                 │    │
│  └─────────────────────────────────────────────────┘    │
│  ▲ 封装的插件 + 社区插件                                 │
│  │                                                      │
│  层级 2: 自有 L0 能力封装 (P1)                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │  dsh-plugin-dreamos-cognitive    ← 认知 (P1a)   │    │
│  │  dsh-plugin-dreamos-retrieval   ← 检索 (P1a)   │    │
│  │  dsh-plugin-dreamos-rea         ← REA (P2, 延后)│    │
│  │  dsh-plugin-dreamos-finance     ← 金融语义 (P2) │    │
│  └─────────────────────────────────────────────────┘    │
│  ▲ 消费                                                 │
│  │                                                      │
│  层级 1: 社区插件消费 (P0)                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │  cordis.patch.yml 声明 + npm/GitHub 安装         │    │
│  │  sandbox profile 隔离运行                        │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## §二、Cordis 插件技术规范

> 基于 [官方教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/) 第 1-7 章整理，作为本域所有插件开发的事实规范。

### 2.1 插件入口契约（MUST）

```js
// lib/index.js — 插件入口文件（ESM，无需构建步骤）
// 注意：参数用 JSON Schema 子集，不是 Zod（见 §9.2 踩坑 #1）；Config 用 Schemastery。

// ① 必需: apply 函数 — Cordis 加载时挂载到 ctx
export function apply(ctx, config) {
  ctx.tools.register({
    name: config.name,
    description: config.description,
    parameters: {              // JSON Schema 子集（properties/required/type/enum/items）
      type: "object",
      properties: { context: { type: "string" } },
      required: ["context"],
    },
    output: {                  // 必填：缺失即抛 must declare output
      schema: { type: "object" },
      render: (args, value) => [{ type: "text", text: JSON.stringify(value) }],
    },
    execute: async (params) => {
      try {
        return { ok: true, result: await doWork(params) };
      } catch (err) {
        return { ok: false, degraded: true, reason: String(err) }; // FAIL-OPEN
      }
    },
  });
}

// ② 可选: name — 诊断标签
export const name = 'dreamos-cognitive-plugin'

// ③ 可选: inject — 声明依赖的其他 Cordis 服务
// export const inject = ['tools']

// ④ 可选: Config — Schemastery schema（仅 z.object/z.string/z.boolean/z.number/z.any）
// import z from '@deepseek-ai/schemastery'
// export const Config = z.object({ enabled: z.boolean().default(false) })

// ⑤ 必需: package.json — peerDependencies 的 @deepseek-ai/* 必须为 "*"（见 §9.2 踩坑 #4）
```

### 2.2 四种常见插件类型

| 类型 | 注册方式 | 示例 |
|---|---|---|
| **工具插件** | `ctx.tools.register({...})` | 文档问答、代码审查、外部 API 调用 |
| **服务插件** | `ctx.service('name', () => implementation)` | 数据库连接池、缓存层 |
| **事件插件** | `ctx.on('event-name', handler)` | 监听文件变更、定时触发 |
| **技能插件** | 在插件内引用 Skill 路径 | 加载 dream-bugfix-workflow SKILL |

### 2.3 配置层（cordis.yml / cordis.patch.yml）

```yaml
# .dsh-home/profiles/<name>/package.json — 依赖声明（file: 链接本地包）
# "dreambuddy-dreamos-cognitive": "file:../../../packages/cordis-plugin-dreamos-cognitive"

# .dsh-home/profiles/<name>/cordis.patch.yml — 顶层数组，新增插件用 insert
- insert:
    # 层级 2: 自有插件 (P1) — 包名 = package.json 的 name
    - id: dreambuddy-dreamos-cognitive
      name: dreambuddy-dreamos-cognitive
      config:
        enabled: true
        enableWrites: false          # 写工具默认不注册（HC-2）
        defaultTopK: 5
        defaultMinQuality: "C"

    # 层级 1: 社区插件 (P0) — 真实包名以 npm 实测为准（见 §3.1.2）
    - id: dsh-plugin-code-review
      name: dsh-plugin-code-review

# 注意: `cordis.patch.yml` 里 `- id:` 独立条目只能 patch 已存在 entry；
# 新增插件必须放进 `- insert:` 数组（§9.1）。
```

### 2.4 生命周期与 Effect（用于安全审计）

| 阶段 | 钩子 | 用途 |
|---|---|---|
| 挂载 | `ctx.effect(() => {...})` | 在插件卸载时自动清理注册（工具/服务/事件监听） |
| 启动 | `apply()` 同步执行 | 注册所有能力 |
| 卸载 | `effect` 返回函数被调用 | 撤销所有注册 |
| 热重载 | Cordis HMR | 开发态无需重启即可更新 |

### 2.5 安全要点

1. **所有工具注册必须在 `apply` 内完成** — 保证可撤销
2. **`inject` 声明依赖必须精确** — 防止隐式依赖（如直接访问 `ctx.db` 而不声明）
3. **schema 校验必须覆盖所有外部输入** — 参数、配置、返回值
4. **FAIL-OPEN 硬约束** — 任何工具执行异常必须返回 `{ ok: false, degraded: true, error: message }`，不可 crash Worker
5. **FAIL-OPEN 只覆盖「工具执行层」，不覆盖「插件激活层」**（P0-1d 实测，2026-11-12）：插件 `apply()` 抛异常 → `dsh-app-boot` 的 `assertEntriesActivated` 判定 `1 entry did not activate`，**整个 profile 拒绝启动**（fail-closed）。因此插件必须先在 sandbox 验证可加载，再进生产 profile。

---

## §三、三层接入实施方案

### 3.1 层级 1：社区插件消费（P0，零代码侵入）

#### 3.1.1 操作步骤

```bash
# Step 1: 在 sandbox profile 里装社区插件，不碰生产 profile
cd ~/.dsh-home/
mkdir -p profiles/sandbox  # 隔离的测试 profile
cp profiles/web/cordis.yml profiles/sandbox/

# Step 2: 向 sandbox 的 cordis.yml 添加社区插件
# (先查 dsh.so 或 GitHub topics/dsh-plugin 挑 5-10 个高质量)

# Step 3: 在 sandbox profile 里验证
DSH_PROFILE=sandbox npx @deepseek-ai/dsh web

# Step 4: 通过 Creator mode 或 DSH 内置 plugin_manager 审计
# plugin_manager · install_bundle  # Creator mode 可一键验证临时插件
```

#### 3.1.2 推荐首批插件清单（按 DreamOS 价值排序）

> ⚠️ 以下为建议清单，安装前必须在 sandbox profile 验证并通过白名单审计。

| 优先级 | 插件（真实包名） | 实测版本/来源 | DreamOS 场景价值 |
|---|---|---|---|
| P0-1 | `@puwenhui/dsh-rag-kb`（备选 `@kai232/dsh-rag`） | npm 0.3.1 / 0.1.2 | 对工作区 40+ SPEC 做问答检索（中文混合检索 + reranker + 引用） |
| P0-2 | `dsh-plugin-code-review` | npm 0.1.1 ✅ | 代码变更自动审查 |
| P0-3 | `dsh-plugin-debugging`（备选 `dsh-plugin-ops-bundle`） | npm 0.8.1 / 0.20.9 | 运行时诊断 + 就地修复（替代原假名 terminal-ops） |
| P0-4 | `awesome-dsh-plugin` + `awesome-dsh-plugin-feed` | npm 0.1.0 / 0.20261112.0 | 引入社区精选生态（feed 可走 npmmirror） |
| P0-5 | `sandbase-harness` | GitHub 643★（**非 npm**） | 自托管 agent runtime 参考实现 |

> **包名核实（2026-11-12 npm 实测）**：原清单中的 `dsh-plugin-document-qa`、`dsh-plugin-terminal-ops` 均 **404 不存在**，已替换为上表真实包名，并在白名单中将假名标记为 `forbidden` 防误装。`sandbase-harness` 非 npm 包，只能走 GitHub 安装。

#### 3.1.3 白名单治理（已落地）

白名单事实源：[plugin_whitelist.yaml](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/53-DSH插件模块/plugin_whitelist.yaml)；
校验器：[check_whitelist.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/53-DSH插件模块/check_whitelist.py)。

```yaml
# 条目字段（v1）
- id: "dsh-plugin-xxx"
  source: "npm"                    # npm / github / local / creator-mode
  version: ">=1.0.0 <2.0.0"
  status: "candidate"              # candidate / approved / forbidden
  risk_level: "low"                # low / medium / high / forbidden（支持 * 通配，如 *trading*）
  security_scanned: false
  sandbox_verified: false          # 必须 sandbox 实测后才能进生产 profile
  fail_open_verified: false
  permitted_profiles: ["sandbox"]  # 空数组 = 任何 profile 都禁止
  notes: "用途与验证结论"
```

```bash
# 校验（deny-by-default，退出码 0 通过 / 1 违规 / 2 配置错误）
python3 53-DSH插件模块/check_whitelist.py --profile sandbox
python3 53-DSH插件模块/check_whitelist.py --profile headless --json

# 试装（在 sandbox profile，不碰生产）
dsh plugin --profile sandbox add <package>
dsh --profile sandbox --dump-config          # 校验插件树
dsh --profile sandbox "run the tests"        # 实跑
```

**2026-11-12 实测结论**：
1. sandbox profile 已建在 `<bridge>/.dsh-home/profiles/sandbox/`，`--dump-config` 显示 **dreambuddy 条目 0 个**（headless 为 35 个），隔离成立。
2. `npm view dsh-plugin-document-qa` → **404**：原候选包名来自调研推测。**2026-11-12 已完成核实**：假名 `document-qa` / `terminal-ops` 均 404，已替换为 `@puwenhui/dsh-rag-kb@0.3.1` / `dsh-plugin-debugging@0.8.1`，假名标记 `forbidden`（详见 §3.1.2 与白名单）。
3. `dsh plugin --profile sandbox list` 可正常转发 pnpm，试装通道可用。
4. 校验器负例已验证：未登记 / 越 profile 权限 / `*trading*` 禁止通配 三类违规均能拦截。
5. 白名单已覆盖 12 个自有插件（含 P1-1 `dreambuddy-dreamos-cognitive`）：`check_whitelist.py --profile headless` → 12 个第三方插件全部通过（补齐前该插件会被 `default_deny` 判违规）。

**R10 实装结论（2026-11-12，DSH 0.1.5-rc.3 + pnpm 11.1.1）**：

| 插件 | 加载 | 运行 | 结论 |
|---|---|---|---|
| `@puwenhui/dsh-rag-kb@0.3.1` | ✅ | ✅ 注册 3 工具，实调 `knowledge_status` → `{ok:true,…,documents:[]}` | `sandbox_verified: true` |
| `dsh-plugin-code-review@0.1.1` | ✅ | ❌ 启用即崩 `text.indexOf is not a function` | 保持 `false`，profile 内 `disabled: true` |

1. **`dsh plugin add` 只安装、不激活**，但**不等于需要手写 insert**：插件包自带的 `dsh.bundle.patch`（`cordis.patch.yml`）在安装后会自动进入组合树。再用 `- insert:` 重复添加会导致同一插件挂两遍（重复注册）。
2. **profile 的 `pnpm-workspace.yaml` 必须写 `nodeLinker: hoisted` + `autoInstallPeers: false`**（对齐 headless）。pnpm 11 默认 isolated 布局会让 DSH loader 的裸包名解析失败（`@deepseek-ai/dsh-sandbox-local could not be resolved`）。`allowBuilds` 必须显式给 `true/false`，否则安装以 `ERR_PNPM_IGNORED_BUILDS` 失败。副作用：`dsh plugin add` 会把 sandbox 的 `dsh-base`/`dsh-headless` 从 `0.1.5-rc.2` 抬到 `^` 允许的最新 `rc.3`，与 headless profile 暂时不一致（不影响 boot，但跨 profile 对比结论时需注意版本差异）。
3. **code-review 的根因**：它的 `systemPrompt.section({text: async () => …})` 返回 Promise，而 `@deepseek-ai/dsh-system-prompt` 的 `assemble()` 对函数型 `text` **不 await**（`lib/index.js:339`），随后的 `interpolate()` 执行 `text.indexOf` 即抛错。对照组 `enableSkill:false` 可正常跑到 LLM 请求 → 定位为 section text 形态不兼容，非插件加载问题。该插件不注册任何 tool，验收标准应是 prompt 注入而非工具调用。
4. **rag-kb 虽标 `dsh.client.platform: "web"`，headless 下可正常加载**：`settings` 服务由 `@deepseek-ai/dsh-settings-file` 提供；`ctx.inject(["webServer"])` 因服务缺失不触发，仅影响 SSE 索引进度通道。原生构建 `onnxruntime-node`/`sharp` 在 `allowBuilds` 中关闭，向量化与 rerank 未验证（`knowledge_search` 空库可用，`knowledge_status` 完整）。
5. 实跑验证方式：用临时探针插件（`ctx.inject(["tools"])` → `ctx.tools.schemas()` + 直接 `ctx.tools.get('knowledge_status').execute({})`）在真实 profile 内取证，避免依赖 LLM 配额；探针用完即删。当前宿主 DeepSeek 账户余额不足（`QUOTA: Insufficient Balance`），端到端自然语言触发未验证。

**R10 FAIL-OPEN 实测（P0-1d，2026-11-12）**：三个临时插件（`apply` 抛错 / 工具 execute 抛错 / 规范返回 degraded）+ 探针，均在 sandbox 实跑。

| 场景 | 实测结果 | 判定 |
|---|---|---|
| 插件 `apply()` 抛 `BOOM` | `dsh: 1 entry did not activate` + `assertEntriesActivated` 失败 → **RC=1，整个 profile 不启动** | ❌ fail-closed（激活层无兜底） |
| 工具 `execute()` 抛错（走 registry 真实调度：`prepareScheduledExecution` → `dispatchToolBody`） | 兜底为 `{isError:true, content:[{type:'text',text:'Error: BOOM: …'}]}`，进程继续 | ✅ FAIL-OPEN 成立 |
| 工具自行 catch 返回 `{ok:false,degraded:true,reason}` | 原样返回 degraded 结构 | ✅ 规范写法可用 |
| 崩溃插件存在时其他插件 | rag-kb 三工具仍全部注册（探针确认 `knowledge_status` 在册） | 仅当崩溃发生在激活阶段之外 |

结论：**Worker 不会因工具异常 crash（harness 兜底），但会因插件激活失败导致整个 profile 起不来**。因此 ADR-6 的「FAIL-OPEN」必须限定作用域，配套约束是「插件必须先过 sandbox 加载验证」——这也解释了 code-review 崩溃为何是致命的（它在 prompt assembly 阶段抛错）。


### 3.2 层级 2：自有 L0 能力封装（P1）

> ⚠️ **实施偏差（2026-11-12）**：下方 §3.2.2 模板中的「spawn `cognitive_mcp_server.py` MCP 进程」形态**未采用**；实际落地为**共享 IPC 进程内桥**（`cognitive_bridge.py`，由主组 `server.py` 承载），差异与理由见 §3.2.2.1。

#### 3.2.1 首批封装范围（ADR-3 决策）

| DSH 插件名 | 对应 L0 域 | MCP 现状 | 封装优先级 | 预计工时 |
|---|---|---|---|---|
| `dsh-plugin-dreamos-cognitive` | 认知系统 (4-MEMORY) | ✅ `cognitive_mcp_server.py` 已在运行 | P1a | 2-3 天 |
| `dsh-plugin-dreamos-retrieval` | 检索 (41+Chroma+recall) | ✅ `unified_search` 已在认知 MCP 内 | P1a | 1-2 天 |
| `dsh-plugin-dreamos-rea` | REA 逆向解析 (33) | ⚠️ 是 MCP client，非 server | P2 | 待定 |
| `dsh-plugin-dreamos-finance` | 金融语义蒸馏 (39) | ✅ 有第 3 个 MCP server (4 工具) | P2 | 待定 |
| `dsh-plugin-dreamos-eval` | 评测系统 (45) | ❌ FastAPI，非 MCP | P3 | 待定 |

> **决策依据**：认知 + 检索 = Worker 高频刚需，已 MCP 化且契约最稳定。REA 是长任务、金融语义是写类工具，后置。

#### 3.2.2 插件实现模板（dsh-plugin-dreamos-cognitive）

```ts
// packages/dsh-plugin-dreamos-cognitive/src/index.ts
import type { Context } from '@deepseek-ai/cordis'
import { z } from 'zod'

export const name = 'dreamos-cognitive-plugin'
export const version = '0.1.0'
export const inject = ['tools']  // 依赖 Cordis tools 服务

// Schema 校验
const RecallSchema = z.object({
  context: z.string().describe('检索上下文关键词'),
  top_k: z.number().int().min(1).max(20).default(5),
  min_quality: z.enum(['S', 'A', 'B', 'C', 'D']).default('C'),
})

const RecordSchema = z.object({
  content: z.string().max(3000),
  quality_level: z.enum(['S', 'A', 'B', 'C']),
  tags: z.string(),
})

// 插件主函数
export function apply(ctx: Context, config: CognitivePluginConfig) {
  const mcpServerName = config.mcp_server ?? 'mcp_cognitive'

  // P1a-1: recall 工具 — Worker 高频刚需
  ctx.tools.register({
    name: 'dreamos_recall',
    description: '从 DreamOS 认知记忆库检索相关经验，避免重复踩坑',
    parameters: RecallSchema,
    execute: async (params) => {
      try {
        // 调本地 MCP server (跨进程)
        const result = await callLocalMCP(mcpServerName, 'recall', params)
        return { ok: true, data: result.data?.memories ?? [], source: 'dreamos-cognitive' }
      } catch (err) {
        // FAIL-OPEN 硬约束
        return { ok: false, degraded: true, data: [], error: String(err) }
      }
    }
  })

  // P1a-2: unified_search 工具 (同时覆盖检索域)
  ctx.tools.register({
    name: 'dreamos_search',
    description: '跨 Chroma 向量库 + 认知库 + 41 索引的统一检索',
    parameters: z.object({
      query: z.string(),
      top_k: z.number().default(10),
      sources: z.array(z.enum(['chroma', 'cognitive', 'filesystem'])).default(['chroma', 'cognitive']),
    }),
    execute: async (params) => {
      // 调我们的 unified_search (已在认知 MCP 内)
      try {
        const result = await callLocalMCP(mcpServerName, 'unified_search', params)
        return { ok: true, data: result.data, source: 'dreamos-retrieval' }
      } catch (err) {
        return { ok: false, degraded: true, data: [], error: String(err) }
      }
    }
  })

  // P1a-3: record 工具 (写类，需 scope 化)
  // 注: 47 SPEC 已确立写工具需 COGNITIVE_MCP_WRITE_ENABLED=true
  // 插件层只暴露只读工具；写工具需另行权限声明
}

interface CognitivePluginConfig {
  mcp_server: string          // 'mcp_cognitive' 或 ssh 远端
  default_top_k?: number
  enable_write?: boolean      // 默认 false，47 SPEC 硬约束
}
```

#### 3.2.2.1 实施记录（2026-11-12，P1-1 完成）

实际落地与上方模板的偏差（模板为 MCP 跨进程调用，实施改为**复用 D3-b 共享 IPC 的进程内桥**，避免第二个常驻进程）：

| 层 | 文件 | 内容 |
|---|---|---|
| Python 桥 | `packages/python-server/cognitive_bridge.py` | `cognitive_recall` / `cognitive_search` / `cognitive_record` / `cognitive_verify` 4 方法，直接调 `CognitiveLoopEntry`；写门禁对齐 §5.2 C6（`COGNITIVE_MCP_MODE=local` / `COGNITIVE_MCP_WRITE_ENABLED` / principal ∈ {orchestrator,verifier,admin}）；verify 复用 `OutcomeLedger` + `validate_outcome`（SPEC-33-G T-G1，默认 enforce）；FAIL-OPEN 全部返回 `{ok:false,degraded:true,reason}` |
| IPC 分派 | `packages/python-server/server.py` | `_COGNITIVE_METHOD_NAMES` 白名单 + `_load_cognitive_bridge()` 惰性加载，失败降级 `cognitive_bridge_unavailable` |
| 插件 | `packages/cordis-plugin-dreamos-cognitive/` | `inject:["tools"]`；`dreamos_recall` / `dreamos_search` 常注册；`dreamos_record` / `dreamos_verify` 仅在 `enableWrites=true` 注册；`enabled=false`（HC-2 默认）不注册任何工具；`getSharedIPC()` 不带 env → 并入主组 server.py（与 10 个插件共享进程） |
| Profile | `.dsh-home/profiles/headless/cordis.patch.yml` + `package.json` | 第 12 个 insert 条目；`enableWrites: false`；依赖 `file:` 链接 + node_modules 符号链接 |

验证证据：
- `node --check` 通过；`py_compile` 通过。
- 直调 `cognitive_bridge.handle("cognitive_recall", …)`：读真实 660MB DB，`count=2`，首条命中 DSH 插件域硬约束记忆（冷启动约 4.8s，numpy fallback 路径）。
- `server.py` NDJSON 冒烟（handshake → `cognitive_recall`）：`ok=true`、`count=2`，退出码 0。
- stub ctx 冒烟：注册 `dreamos_recall,dreamos_search` 两个只读工具；真实 IPC 调用 `ok=true count=2`；进程退出后 `server.py` 残留 0（共享 IPC 统一回收）。
- 实盘 Router pass（`shadow=false`）：PASS1 物化 `TK-LIVE-P11-1` + 分派 `w-live-1` + 投递 inbox，`committed=1`；PASS2 `skipped=already_live`、`committed=0`（幂等成立）；测试产物已清理。

遗留与开关：
- `enableWrites=false` → 运行时 record/verify 不注册；开启需插件 `enableWrites: true` **且** 宿主 env `COGNITIVE_MCP_WRITE_ENABLED=true` + `COGNITIVE_MCP_DEFAULT_PRINCIPAL` 注入（纵深防御，Worker 默认只读）。
- `cognitive_*` 方法并入主组 server.py（无 `DSH_ENABLE_UPGRADE`）；`router_pass` 在 p0 组（带 `DSH_ENABLE_UPGRADE=true`），两组进程隔离，互不影响。

#### 3.2.3 与 MCP 的关系（ADR-2 详细展开）

```
         Worker 工具调用
               │
        ┌──────┴──────┐
        ▼              ▼
   DSH 插件         MCP server
   (Cordis 原生)    (跨进程 JSON-RPC)
        │              │
  ┌─────┴─────┐   ┌───┴────┐
  │ 直接调     │   │ 进程间  │
  │ L0 函数    │   │ 通信    │
  └───────────┘   └────────┘
  延迟 ≈ 1ms      延迟 ≈ 50ms (本地) / 200ms (远端)

策略:
┌────────────────────────────────────────────┐
│ DSH 插件 = Worker 原生工具面 (低延迟)       │
│ MCP      = 跨端标准出口 (Trae/云端/其他宿主) │
│ 同一 L0 能力，两种暴露形态，互不替代         │
└────────────────────────────────────────────┘
```

### 3.3 层级 3：插件治理层（P2+，等接入量 > 5 再规划）

当 P1 自有插件 ≥ 3 个 + 社区插件 ≥ 5 个时，引入治理层。以下为预定义架构草案，不进入 P0/P1 实施。

```
┌ 53-插件治理层 ──────────────────────────────────────────┐
│                                                         │
│  plugin_registry.yaml                                   │
│  ├─ id / name / source / version / risk_level           │
│  ├─ security_scanned / sandbox_verified                 │
│  └─ permitted_profiles / dependencies                  │
│                                                         │
│  plugin_sandbox.shim                                    │
│  ├─ 进程隔离 (unshare / bubblewrap)                     │
│  ├─ 网络白名单                                          │
│  └─ 文件系统只读挂载 (except ~/tmp)                     │
│                                                         │
│  plugin_health_monitor                                  │
│  ├─ 执行超时检测 (>5s → degraded)                       │
│  ├─ crash 频率追踪 (>3/分钟 → 自动 disable)              │
│  └─ 版本兼容性校验 (与 Cordis 运行时版本比对)            │
│                                                         │
│  creator_mode_review_flow                               │
│  ├─ 对话生成临时插件 → 自动安全扫描                      │
│  ├─ sandbox profile 试运行                              │
│  └─ 人工 review → 合入白名单                            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## §四、架构对齐

### 4.1 与 DSH v0.2 升级路径的关系

```
DESIGN-DSH-ARCH-UPGRADE v0.2 七层架构:
┌ ④ 执行层: Worker ─────────────────────────┐
│  按角色分池 (研究/工程/交易分析/验收)        │
│  每 Worker 只见自己的能力集 (≤10 工具)       │
│    │          │          │                  │
│    ▼          ▼          ▼                  │
│  [P0 社区] [P1 自有] [MCP 跨端]            │
│  工具插件  工具插件  标准出口                │
└───────────────────────────────────────────┘
        ▲
        │ 插件生态提供 Worker 工具面供给
        │ 对齐 Router → Worker 分派模型
```

**53 域价值**：直接为 v0.2 的 Worker 能力集限流提供工具面来源，避免 Router 需要在海量工具中选择 → 每个 Worker profile 只需加载 3-5 个 DSH 插件，自然满足"≤10 工具"约束。

### 4.2 与 42 协调层的关系

| 维度 | 42 协调层 | 53 DSH 插件模块 |
|---|---|---|
| 职责 | 交易域信号归一化 + 参数治理 | DSH Worker 工具面 |
| 注册面 | `registry.yaml` (adapters/) | `cordis.yml` + `cordis.patch.yml` |
| 运行时 | in-process port (热路径) | Cordis Context (DSH 插件架构) |
| 典型消费者 | 23 矛盾裁决器 | DSH Worker (研究/工程/分析) |
| 写入 42？ | ❌ 不修改 42 registry.yaml (ADR-5) |

### 4.3 与 MCP 的关系

| 维度 | MCP server (47) | DSH 插件 (53) |
|---|---|---|
| 协议 | JSON-RPC 跨进程 | Cordis Context 原生 |
| 消费者 | Trae / 云端 / 其他宿主 | DSH Worker |
| 延迟 | ~50ms (本地) / ~200ms (远端) | ~1ms (直接调 ctx) |
| 契约标准 | 47 SPEC SSoT | Cordis 官方规范 |
| 替代？ | ❌ 不替代，互补形态 (ADR-2) |

---

## §五、安全与边界

### 5.1 三级安全等级

| 等级 | 适用 | 隔离要求 | 验证要求 |
|---|---|---|---|
| **L1 自有只读插件** | P1 认知/检索插件 | 进程级（Worker profile 隔离） | schema 校验 + FAIL-OPEN 测试 |
| **L2 自有写插件** | `dreamos_record` / `dreamos_verify`（P1-1 已实现，默认不注册） | 进程级 + 写权限 token | 插件 `enableWrites=true` + `COGNITIVE_MCP_WRITE_ENABLED=true` + principal 授权 |
| **L3 社区插件** | 层级 1 消费的第三方 | sandbox profile + 文件只读 + 网络白名单 | 安全扫描 + sandbox 实测 + 白名单审批 |

### 5.2 FAIL-OPEN 硬约束（所有插件 MUST）

```
规则: 任何插件工具执行必须返回以下之一，禁止 crash Worker:
  ✓ { ok: true, result: ... }
  ✓ { ok: false, degraded: true, reason: "..." }
  ✗ throw Error / process.exit / 未捕获异常

实现: 所有 DSH 插件的 ctx.tools.register({...}) 中:
  execute: async (params) => {
    try {
      // 正常逻辑
      return { ok: true, result: await doWork(params) }
    } catch (err) {
      return { ok: false, degraded: true, reason: String(err) }
    }
  }
```

### 5.3 执行层权限隔离（ADR 补充）

- **禁止** 社区插件通过任何路径触达执行层（paper MCP / okx_client / 11 交易执行器）
- 执行层权限仅授予：L0 签名 MCP server + 11 域内部执行器 + Mandate 授权的 Worker
- 社区插件若声明需要交易数据访问 → 必须经过 42 的 `SignalSchema` 归一化接口，不走 DSH 插件通道

---

## §六、分阶段路线图

> **进度以 §九 / §3.2.2.1 为准**：P0 的 1a/1c/1b/1d 已完成（sandbox profile + 白名单 v1 + rag-kb 实装 + FAIL-OPEN 实测，见 §3.1.3）；P1 的 2a-2d 已由 P1-1 完成（认知插件，无 build 步骤、纯 ESM）。

### P0: 社区插件消费（立即启动，预计 1 周）

| 周 | 任务 | 产出 | 验收 |
|---|---|---|---|
| 1a | sandbox profile 创建 + cordis.patch.yml 初始化 | `~/.dsh-home/profiles/sandbox/` | sandbox profile 可启动 |
| 1b | 首批 5 个社区插件安装 + 功能验证 | sandbox profile 插件面 | 每个插件工具调用 ≥ 1 次成功 |
| 1c | 白名单 v1 创建 | `53/plugin_whitelist.yaml` | 含 5 个插件 + 风险分级 + 审计结论 |
| 1d | FAIL-OPEN 验证 | 崩溃插件测试脚本 | 故意 crash 的插件 → Worker 拿到 degraded 结果 |

### P1: L0 能力封装（P0 验收后进，预计 2-3 周）

| 周 | 任务 | 产出 | 验收 |
|---|---|---|---|
| 2a | `dsh-plugin-dreamos-cognitive` 骨架搭建 | `packages/dsh-plugin-dreamos-cognitive/` | `npm run build` 通过 + Cordis 加载测试 |
| 2b | recall 工具实现 + MCP 桥接 | `dreamos_recall` 工具可用 | Worker 对话中成功调 recall 并拿到记忆 |
| 2c | unified_search 工具实现 | `dreamos_search` 工具可用 | Worker 对话中成功检索 Chroma + 认知库 |
| 2d | 安装到 web profile + 多 Worker 验证 | web profile 原生工具面 | Router → Worker → 插件端到端链路可用 |

### P2: REA + 金融语义封装（按需，预计接入量 > 3 后启动）

### P3: 插件治理层规划（按需，等接入量 > 5 后启动）

---

## §七、代码组织建议

> **实际落地位置**：自有插件源码在 `1-ARCHITECTURE/dream-harness-bridge/packages/cordis-plugin-*/`（与 DSH bridge 同仓、便于共享 IPC 与符号链接），**不在** `53-DSH插件模块/packages/`。本节目录树为早期规划，保留作参考。

```
53-DSH插件模块/
├── README.md
├── SPEC-53-DSH插件生态接入总规范.md
├── plugin_whitelist.yaml                    # P0 产出 (社区插件白名单)
└── plugin_audit_template.md                 # 社区插件安全审计模板

1-ARCHITECTURE/dream-harness-bridge/packages/ # P1 实际产出
├── cordis-plugin-dreamos-cognitive/         # 已落地（P1-1）
│   ├── package.json                         # name: dreambuddy-dreamos-cognitive
│   └── lib/index.js                         # 纯 ESM，无 build 步骤
└── python-server/cognitive_bridge.py        # 认知桥（进程内，共享 IPC）

# 安装方式：profile package.json 用 file: 链接 + node_modules 符号链接
# 无 pnpm build；发布时才 npm pack（可选）
```

---

## §八、与现有 SPEC 冲突矩阵

| 可能冲突 | 实际判定 | 依据 |
|---|---|---|
| 53 插件 vs 42 插件总线 | **不冲突** — 42 服务交易域信号归一化，53 服务 DSH Worker 工具面 | ADR-5: 职责正交，互不侵入 |
| 53 插件 vs 47 MCP | **不冲突** — 插件 = DSH 内部原生工具面，MCP = 跨端标准出口 | ADR-2: 同一 L0 能力两种暴露形态 |
| 53 插件 vs 46 DSH v0.2 升级 | **加速升级** — 为 Worker 能力集限流提供工具面供给 | §4.1 架构对齐分析 |
| 53 写插件 vs 35 认知写治理 | **一致** — 写插件必须声明 COGNITIVE_MCP_WRITE_ENABLED + Mandate 授权 | 35 COLLABORATION-CONTRACT §5.4 |

---

## 附录 A：Cordis 插件 API 速查

```ts
// Context 关键能力 (from cordis-surface)
interface Context {
  // 工具注册
  tools: {
    register(def: ToolDefinition): void
    unregister(name: string): void
  }
  // 服务注入
  service: <T>(name: string, factory: () => T) => void
  // 事件系统
  on(event: string, handler: (...args: any[]) => any): void
  emit(event: string, ...args: any[]): any[]  // waterfall 模式
  // 生命周期
  effect(effect: () => void | (() => void)): void  // 返回函数即卸载清理
  // 配置读取
  config: ConfigObject
}

interface ToolDefinition {
  name: string
  description: string
  parameters: JsonSchemaObject       // 用 DSH 支持的 JSON Schema 子集，不是 Zod
  output: {
    schema: JsonSchemaObject         // 必填
    render: (args: any, value: any) => ContentPart[]   // 必填
    presentationMeta?: (args: any, value: any) => any
  }
  execute: (args: any, exec: any) => Promise<any> | any
  timeoutMs?: number
}
```

> 以上为 2026-11-12 在 dsh 0.1.5-rc.2 实测校准后的契约（`ctx.tools.register` 会校验
> `output { schema, render }`，缺失即抛 `must declare output`）。
> `system-prompt/assemble` 是 waterfall 事件，监听器签名 `(assembly, context, next)`，
> **必须 `await next()` 并返回组装结果**，否则上游读取 `transformed.contexts` 时崩溃。

## 附录 B：参考链接

| 资源 | URL | 复验（2026-11-12，curl 实测） |
|---|---|---|
| Cordis 官方教程 | https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/ | 200 |
| Cordis 核心 API | https://deepseek-harness.github.io/deepseek-harness/reference/cordis-api/context | 200 |
| DSH GitHub | https://github.com/deepseek-ai/deepseek-harness | 200，280k★ |
| 社区插件目录 | https://www.dsh.so/ | 200 |
| awesome-dsh-plugin | https://github.com/awesome-dsh-plugin/awesome-dsh-plugin | 200，24k★（原记 23,288，已更新） |
| sandbase-harness | https://github.com/sandbaseai/sandbase-harness | 200，643★（原记 604，已更新） |
| Cordis 论文 | https://arxiv.org/abs/2608.25512 | 200，标题 *A Programming Paradigm for Spatiotemporal Composability*，摘要含 Cordis |
| 首个 Harness 插件教程 | https://deepseek-harness.github.io/deepseek-harness/develop/basic/ | 200 |
| DSH 插件标准草案 | https://github.com/lanbaolu/dsh-plugin-standard | 200，**0★**（个人草案，非社区共识，引用时勿当权威标准） |

**季度复核（2026-11-12 执行）**：9/9 链接返回 200；star 数无漂移（deepseek-harness 280k / awesome-dsh-plugin 24k / sandbase-harness 643 / dsh-plugin-standard 0）；arXiv 2608.25512 标题与摘要仍与记录一致。下次复核：2027-02-12。

---

## §九、落地进展（2026-11-12 实测）

### 9.1 已完成：`dreambuddy-superagent-p0` 已在 headless runtime 正式启用

| 项 | 结论 |
|---|---|
| 插件位置 | `1-ARCHITECTURE/dream-harness-bridge/packages/cordis-plugin-superagent-p0/` |
| 运行 profile | `<bridge>/.dsh-home/profiles/headless/`（**不是仓库根的 .dsh-home**） |
| 挂载方式 | 顶层 `- insert:` 数组内新增 entry（`- id:` 独立条目只能 patch 已存在 entry） |
| 开关 | `enabled: true` + `enableUpgrade: true`（HC-2 总闸门已开） |
| 工具面 | 5 个工具全部注册成功：`dreamos_event_gateway_route` / `ticket_router_dispatch` / `ticket_bridge_translate` / `ticket_state_transition` / `dreamos_router_loop_stats` |
| Prompt 注入 | `system-prompt/assemble` waterfall 已生效（prepend 一段 P0 能力说明） |
| 运行验证 | `dsh --profile headless "say hi"` → 5 工具注册日志 + IntentGateway + GraphPlanner 正常执行 |

### 9.2 踩坑归档（后续插件开发直接复用）

1. **Schemastery ≠ Zod**：`@deepseek-ai/schemastery` 无 `.optional()` / `.nullable()` / `.enum()` / `.record()`，Config 里只能用 `z.any()` / `z.string()` / `z.boolean()`。
2. **`ctx.tools.register` 不用 `defineTool` 也能用**：直接传 `{ name, description, parameters(JSON Schema), output:{schema, render}, execute }` 即可，避免插件侧引入 `@deepseek-ai/dsh-tools` 依赖。
3. **水落事件必须返回**：`system-prompt/assemble` 监听器漏 `return`/`next()` → `Cannot read properties of undefined (reading 'contexts')`。
4. **peerDependencies 硬校验**：runtime 会 disable 所有 peerDeps 不匹配的插件。本地 12 个 dreambuddy 插件统一 `"*"`，并把全局 CLI 锁到与 profile bundle 一致的 `0.1.5-rc.2`。
5. **沙盒下需显式 `DSH_HOME`**：否则写 `~/.dsh/profiles/node_modules.lock` 被 EPERM 拒绝；`.credentials.yaml` 需 `chmod 600`。

### 9.3 待推进（P0-D / P1）

| 项 | 说明 | 状态 |
|---|---|---|
| P0-D1 | `event_intents.yaml` 与 INVENTORY 27 个事件源对齐（意图池 3 → 6） | ✅ 2026-11-12 完成（见 9.4） |
| P0-D2 | 常驻 Router 循环（当前是单轮无状态工具调用） | ✅ D2a-D2c 已实施（`router_loop.run_pass` + IPC `router_pass` + 插件 timer，15 单测/冒烟通过）；**2026-11-12 已切实盘**（`routerLoopShadow: false`，实盘 pass 冒烟：物化+分派+投递 inbox 通过、第二轮幂等已跳过）；花名册为空 → 运行时仅对账/唤醒。见 [DESIGN-P0-D2-ROUTER-LOOP-v0.1](../46-DSH架构/docs/tech/DESIGN-P0-D2-ROUTER-LOOP-v0.1.md) |
| P0-D3 | bridge 合并进 `python-server/server.py` 共享进程，减少常驻子进程 | ✅ 2026-11-12 完成（D3 代码合并 + D3-b 进程收敛 3 → 1，见 9.5/9.6） |
| P0-D3-b | 共享 IPC 单例：11 插件复用同一 `server.py` | ✅ 2026-11-12 完成（见 9.6） |
| P1-1 | L0 认知能力封装（`dsh-plugin-dreamos-cognitive`，见 §3.2.2） | ✅ 2026-11-12 完成（`cognitive_bridge.py` 4 方法进程内桥 + 插件 2 只读/2 写工具，复用共享 IPC 不另起 MCP 进程；见 §3.2.2 实施记录） |
| P1-2 | 社区插件白名单 `plugin_whitelist.yaml` 落地 + sandbox profile 试装 | ✅ 2026-11-12 完成：白名单+校验器+真实包名核实；sandbox 实装 `@puwenhui/dsh-rag-kb`（`sandbox_verified`/`fail_open_verified` 均 true）与 `dsh-plugin-code-review`（实测不兼容已 disabled）。见 §3.1.3 R10 |

### 9.4 P0-D1 事件意图池扩展（对齐 INVENTORY §五）

`34-前端应用训练系统/core/event_intents.yaml` 由 3 意图扩到 6 意图（schema_version 0.1 → 0.2）：

| intent_id | kinds | executor | 来源事件源 |
|---|---|---|---|
| `alert_confirm` | alert_confirm | alert_card | signal-scanner / ab-monitor 阈值命中 |
| `event_triage` | event_triage, job_done, file_landed | data_reply | atomic_events.jsonl / file-drop |
| `health_alert` | health_alert, service_down, timer_missed | alert_card | dreambuddy-healthcheck.timer(5min JSON) |
| `job_failed`（新增） | job_failed, timer_failed, exit_nonzero | alert_card | 全部 29 timer 退出码非零（通用兜底） |
| `job_completed`（新增） | job_completed, backfill_done, training_done | data_reply | backfill / continual-training / orchestrator |
| `integrity_alert`（新增） | integrity_alert, dal_integrity_failed | alert_card | dal-integrity(6h) / job-runs-audit(1h) |

验证：`pytest tests/test_event_gateway.py`（41 passed）+ `tests/test_e2e_event_to_ticket.py`（2 passed）。

### 9.5 P0-D3 bridge 并入 server.py（单进程代码路径）

**改动**：

| 文件 | 改动 |
|---|---|
| `packages/python-server/superagent_p0.py` | 新增：P0 handlers 模块（原 `superagent_bridge.py` 的方法实现 + `_load_p0` 延迟加载 + `_degraded` FAIL-OPEN），只导出 `handle(method, params)`，不做 stdin/stdout |
| `packages/python-server/server.py` | 新增 `_P0_METHOD_NAMES` + `_load_p0_handlers()`，分派表加 `elif method in _P0_METHOD_NAMES:` 分支（加载失败降级 `p0_unavailable`） |
| `packages/python-server/superagent_bridge.py` | **删除**（不再有独立 Python 入口） |
| `cordis-plugin-superagent-p0/lib/index.js` | 默认路径改为 `server.py`；握手与请求改为 server.py 协议（每条消息带 `schema_version`，`message_type:"request"` + `method`）；启动探测改为 `"启动"`；`execute` 返回 `resp.result`，非 ok 转 degraded |
| `cordis.patch.yml` | `pythonBridgePath` 指向 `server.py` |

**验证**：
- `server.py` 冒烟（`DSH_ENABLE_UPGRADE=true`）：handshake `compatible:true`；`superagent_p0_health` → 4 组件全 `true`；`event_gateway_route` / `ticket_state_transition` 正常返回。
- 回归：既有 `intent_gateway` 方法仍正常（`intent=general, risk_level=low`）。
- `dsh --profile headless "say hi"`：4 工具全部注册、IntentGateway + GraphPlanner 正常；仍仅 LLM 侧 `QUOTA: Insufficient Balance`。

**关于"减少常驻子进程"的准确结论**：本次完成的是**代码路径合并**——P0 不再有独立 Python 入口，协议实现只剩 server.py 一套。但进程数**当前未下降**：每个 Cordis 插件各自 spawn 一个 `server.py`，superagent-p0 只是把原来的 bridge 进程替换成了 server.py 进程（1 → 1）。

真正的进程数下降需要 **D3-b：JS 侧共享 IPC 单例**——用一个按绝对路径导入的 `shared-ipc.mjs`（ESM 同 URL 模块缓存天然单例），让多个插件复用同一个 `server.py` 子进程，11 个插件收敛到 1 个进程。改动面涉及全部 11 个插件的客户端代码，回归面较大，单独立项。

### 9.6 P0-D3-b 共享 IPC 单例（真正的进程收敛，2026-11-12 完成）

**实现**：

| 文件 | 改动 |
|---|---|
| `packages/python-server/shared-ipc.mjs` | 新增共享客户端：`getSharedIPC({serverPath, executable, env})` 按 `executable + serverPath + env(C 排序)` 分组返回单例；registry 挂在 `globalThis[Symbol.for("dreambuddy.shared-ipc.registry")]`，即使插件目录是独立副本也能共享；`exit/SIGINT/SIGTERM` 钩子统一 `SIGKILL` 回收子进程 |
| 11 个 `cordis-plugin-*/lib/index.js` | 删除各自 90 行的 `PythonIPCClient` 类，改为 `getSharedIPC(...)`；删除 dispose 里的 `stop()`（共享进程不能被单个插件 kill）。共 -1400 行重复代码 |
| profile `node_modules/dreambuddy-*`（10 个） | 由**副本目录**改为**符号链接**指向 `packages/cordis-plugin-*`，与 superagent-p0 一致，消除「改了源码但运行的是旧副本」的漂移（本次已发现 c-chain 副本比源码多 `additionalProperties`） |
| `dream-harness-bridge/node_modules/@deepseek-ai/dsh-tools` | 新增符号链接到 profile 内的 dsh-tools（符号链接后 ESM 按真实路径解析裸模块，插件目录上溯找不到 profile 的 node_modules） |

**分组策略**（HC-2 隔离）：

- 普通插件组：`env` 为空 → 共用一个 `server.py`
- superagent-p0 组：`DSH_ENABLE_UPGRADE=true` → 单独一个（总闸门隔离，不影响普通组）

**实测结果**（同 workload `dsh --profile headless "say hi"`）：

| 指标 | D3 之前 | D3-b 之后 |
|---|---|---|
| 常驻 `server.py` 进程 | 3 | **1**（惰性启动，无 P0 工具调用时不启 upgrade 组） |
| 11 插件加载 | 11/11 | 11/11（无 resolve 失败） |
| 4 个 P0 工具注册 | 4/4 | 4/4 |
| SIGTERM 后子进程回收 | 残留 | **0 残留** |

**踩坑归档**：
1. 把 profile 里的插件副本改成符号链接后，`import "@deepseek-ai/dsh-tools"` 会按**真实路径**上溯，找不到 profile 的 node_modules → 5 个插件加载失败，但报错是 `cannot create effect on inactive context`（误导性），真实原因是模块解析失败。解法：在 bridge 根 `node_modules/@deepseek-ai/` 补 dsh-tools 符号链接。
2. Cordis 里**不要**在 `dispose` 里 stop 共享进程；否则先 dispose 的插件会杀掉仍在被其他插件使用的 server。
3. `process.once("exit")` 在 `kill -9` 下不触发；对 SIGINT/SIGTERM 需显式钩子，且 python 侧 SIGTERM 可能不立即退出，退出路径统一用 `SIGKILL`。

---

## §十、整体评审结论（2026-11-12）

### 10.1 评审范围与方法

- 对象：本 SPEC v0.2 全文（§0-§9）。
- 方法：文档 ↔ 实测交叉验证 —— npm/GitHub 包名实测、headless profile 实际配置（`cordis.patch.yml` / `package.json` / 符号链接）、`check_whitelist.py` 实跑、§9 落地记录逐条回查。

### 10.2 总体结论

- **定位与边界正确**：三维递进（先消费→再封装→后治理）与 7 条 ADR 自洽；「不替代 MCP」「不动 42 registry」「FAIL-OPEN」三条红线明确，与 46/47/35 无冲突。
- **可作为 53 域唯一事实源**，但主要问题集中在「文档滞后于实现」和「早期模板与实测契约冲突」，本轮已修正 9 项（R1-R9）。
- **未完成项集中在层级 1**：社区插件尚无一个真实实装并跑通，P0 的 1b/1d 仍为空。

### 10.3 问题清单与处置

| # | 严重度 | 问题 | 处置 |
|---|---|---|---|
| R1 | P0 | §3.1.2 `dsh-plugin-document-qa` / `dsh-plugin-terminal-ops` 在 npm 均 404，照文档无法安装 | ✅ 已替换为 `@puwenhui/dsh-rag-kb@0.3.1` / `dsh-plugin-debugging@0.8.1`（含备选） |
| R2 | P0 | 白名单缺 P1-1 新插件 → headless 会被 `default_deny` 判违规 | ✅ 已补 `dreambuddy-dreamos-cognitive`，`--profile headless` 12/12 通过 |
| R3 | P1 | §2.1 模板用 Zod 且缺 `output`，与 §9.2/附录A 直接冲突 | ✅ 已改为 JSON Schema + `output{schema,render}` + Schemastery Config |
| R4 | P1 | §2.3 配置示例包名（`@awesome-dsh-plugin/...`）与挂载语法（`require:`）均错误 | ✅ 已改为 `insert` 结构 + 真实包名 |
| R5 | P1 | §3.2.2 模板为 MCP spawn 形态，与进程内桥实现不符 | ✅ 已加实施偏差指引 → §3.2.2.1 |
| R6 | P1 | §9.1 工具面写 4 个，实际已 5 个（含 `dreamos_router_loop_stats`） | ✅ 已修 |
| R7 | P2 | §1.1/ADR-4 社区规模与 star 数过期（25,000+ / 604★） | ✅ 已修（23,000+ 索引 / 6,000+ 验证；643★） |
| R8 | P2 | §六 路线图未标注完成度，易被误读为全部完成 | ✅ 已加进度指引 |
| R9 | P2 | §5.2 FAIL-OPEN 字段（`data`/`error`）与实际返回（`result`/`reason`）不一致 | ✅ 已统一 |
| R10 | P1 | 社区插件实装、sandbox 实测、FAIL-OPEN 实测（P0 1b/1d）未做 | ✅ 已完成：rag-kb 实装通过（`sandbox_verified: true`/`fail_open_verified: true`）；code-review 实测不兼容已禁用；FAIL-OPEN 实测完成并修正作用域（工具层 open / 激活层 closed） |
| R11 | P2 | 附录 B 外部链接（arXiv 编号、`dsh-plugin-standard`、★数）未复验 | ✅ 已复验（2026-11-12）：9 条链接全部 200；arXiv 2608.25512 标题/摘要核对通过；awesome-dsh-plugin 24k★、sandbase-harness 643★、`lanbaolu/dsh-plugin-standard` 0★ 已更正并标注 |
| R12 | P2 | `dsh plugin --profile sandbox add` 命令语法未实测 | ✅ 已实测（见 §3.1.3 R10 结论 1/2） |
| R13 | P2 | D2 循环把 plan 中所有 ticket 物化为 live（占 `external_ref`），若本轮**无可用 Worker**（`unassigned`）则下一轮按 `already_live` 跳过 → 该 ref 永久派不出去 | ✅ 已修复（幂等闸判据改为「live **且已绑 worker_id**」才算已派；live 无 worker 允许下轮补派），单测 `test_unassigned_ticket_redispatched_next_pass` + 265 项回归全绿 |
| R14 | P1 | `dsh_worker_inbox.jsonl` 无消费者、`completed_refs` 无可信来源 → 依赖闸永不解除，下游 Ticket 永久 `deferred` | ✅ 已修复（2026-11-12）：新增 `core/worker_receipts.py` 消费 `dsh_worker_receipts.jsonl`（`done→ended` 释放槽并解除依赖、`failed→paused+waiting_person`、坏行/未知状态 `ignored` FAIL-OPEN）；`run_pass` 步骤 ②b 消费回执（shadow 不写）；4 项单测 + 回归全绿 |
| R15 | P1 | 跨轮依赖闸失效：依赖票已派但未 `ended` 时被幂等闸移出本批，底层 `route_single_round` 把「不在本批」的依赖视同外部锚点 → 下游提前派单 | ✅ 已修复（2026-11-12，联通性测试发现）：`run_pass` 步骤⑥ 用 L0 快照补判 `unfinished_refs`（存在且未 ended 的依赖 → `dependency_unmet`）；单测 `test_dependency_held_across_rounds_until_receipt` |
| R16 | P1 | 回执重放非幂等：回执文件每轮重读，人工恢复后旧 `failed` 回执再次把 Ticket 打回 `paused` | ✅ 已修复（2026-11-12，联通性测试发现）：`worker_receipts` 在 Ticket 上记录 `last_receipt_key`（回执内容哈希），同内容只应用一次；单测 `test_receipt_replay_after_manual_resume_is_idempotent` |

### 10.4 后续建议（按优先级）

1. ~~**P0**：在 sandbox 实装 `@puwenhui/dsh-rag-kb` + `dsh-plugin-code-review`，各跑通 1 次工具调用后回填 `sandbox_verified: true`。~~ **已完成（2026-11-12）**：rag-kb 回填 `true`；code-review 实测不兼容（async section text）→ 保持 `false` 并在 sandbox 中 `disabled: true`，待上游修复后复验。详见 §3.1.3 R10 结论。
2. ~~**P0**：用故意 crash 的临时插件验证 FAIL-OPEN（P0-1d），补齐 L3 安全闭环。~~ **已完成（2026-11-12）**：工具执行层 FAIL-OPEN 成立（harness 兜底为 `isError`），插件激活层为 fail-closed → 已写入 §2.5 第 5 条硬约束。详见 §3.1.3「R10 FAIL-OPEN 实测」。
3. ~~**P1**：配置 D2 花名册并在宿主注入 `DSH_ENABLE_UPGRADE=true`，让实盘 Router 真正产生分派。~~ **已完成（2026-11-12）**：headless / superagent 两个 profile 的 superagent-p0 均配置 `enableUpgrade: true` + `enableRouterLoop: true` + `routerLoopShadow: false` + 8 角色花名册 + `routerLoopPlanPath`；插件新增 plan 文件读取（缺文件→只对账/唤醒）。实测：Python 层 2/3 派单（未知角色→`no_free_worker`）、幂等闸生效；插件层 4 轮 pass 从 plan 文件产出 2 条 assignment。遗留风险见 R13。
4. ~~**P1**：补上 inbox 消费闭环（回执 → Ticket 状态 → `completed_refs`），否则依赖闸永不解除。~~ **已完成（2026-11-12）**：`core/worker_receipts.py` + `run_pass` 步骤 ②b；契约：`{"ticket_id","status":"done|failed","evidence","at"}`，`done→ended`、`failed→paused+waiting_person`、坏行 `ignored`；shadow 不消费。
5. ~~**P2**：季度复核附录 B 链接与社区 star 数，避免再次出现「文档包名不可安装」。~~ **已完成（2026-11-12）**：9/9 链接 200；star 数无漂移（280k / 24k / 643 / 0）；下次复核 2027-02-12。详见附录 B。


