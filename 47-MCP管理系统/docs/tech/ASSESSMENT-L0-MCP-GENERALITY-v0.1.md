# ASSESSMENT:L0 MCP 通用性评估 — 面向"任意 Agent 即插即用"的差距与路线

> **版本**: v0.1 ｜ **更新日期**: 2026-11-08 ｜ **状态**: 🟡 评估完成，结论待评审（未开工）
> **上游**: [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（契约基线）· [TECH-L0-MCP v0.1](./TECH-L0-MCP-v0.1.md)（实现手册）· [PLAN-L0-MCP-P0-P3 v0.1](./PLAN-L0-MCP-P0-P3-v0.1.md)（路线基线）
> **关联**: [SPEC-DSH-P5 Transport v1.0](../../../46-DSH架构/docs/tech/SPEC-DSH-P5-TRANSPORT-HEALTHCHECK-v1.0.md)（壳生命周期）· [SPEC-L0-three-layer-architecture](../../../44-三端协作架构系统/docs/tech/SPEC-L0-three-layer-architecture.md)（六 port + 信封）
> **定位**: 评估报告。回答"现有 L0 MCP 能否让后续接入的任何 Agent 直接获得架构优势"，并给出通用化改造的最小路径。
> **评测口径**: 以仓库当前代码与注册表**实测**为准（2026-11-08），不以文档描述为准；凡文档与代码不一致处，在 §2.3 单列。

---

## 一、结论摘要

**L0 MCP 的"契约内核"通用性高（约 7.5/10），"接入外壳"通用性低（约 3/10）。**

- 内核已具备可复用的架构资产：统一信封、契约注册表单一事实源、写工具 Mandate、角色能力集、壳生命周期自愈、trace/shadow 观测。这些**与 Agent 类型无关**，是真正的通用底座。
- 接入面尚未产品化：新增一个 Agent 仍需人工读文档、逐壳拼 `mcp.json`、手工注入 `PYTHONPATH`；角色最小权限只在 DSH 内部 Python 调用链生效，**MCP 协议面上没有等价物**。
- 三个杠杆点（按收益排序）：
  1. **角色能力网关**（`l0-gateway --role`）——让外部 Agent 一条配置接入，且 `tools/list` 精确等于角色白名单；
  2. **注册表驱动的配置生成器**（`mcpctl profile/install/doctor`）——把已有的 `shells` + `worker_roles` 数据变成可直接落盘的宿主配置；
  3. **壳运行时抽取**（`shell_runtime.py`）——消除 8 份重复的 JSON-RPC 模板，新域接入从"写一个 server"变成"填一张 HANDLERS 表"。

**推荐路线**：先做生成器（S），再做角色网关 + 运行时抽取（M），最后是可选的 **P3a 分包 / P3b 发现**。**P4 共享沉淀仅登记草案，暂不开发**（用户 2026-11-08 决策：开发先到 P3）。

---

## 二、现状实测盘点

### 2.1 壳与工具面

| shell_id | status | transport | 工具数 | 工具 |
|---|---|---|---|---|
| `l0.cognition.mcp` | available | ssh-stdio（双模） | 7 | recall / unified_search / record / verify / stats / health / l4_status |
| `l0.semantic-39.mcp` | available | stdio | 4 | query_entity / semantic_lookup / distill_aliases / training_feed |
| `l0.rea.mcp` | available | stdio | 6 | submit/poll × analyze/trace/compare |
| `l0.data.mcp` | available | stdio | 4 | data_fetch / data_collect_once / data_store_read / data_store_write |
| `l0.eval.mcp` | available | stdio | 2 | eval_analyze / eval_report |
| `l0.store-admin.mcp` | available | stdio | 2 | store_admin_status / store_admin_query |
| `l0.trade-exec.mcp` | available | stdio | 10 | place_order / cancel_order / get_positions / get_balance / pre_trade_check / check_exit / get_account_mode / reconcile / read_signals / ingest_signal |
| `l0.rea-client.mcp` | deprecated | http | 3 | rea_analyze / rea_trace / rea_compare（npm 存量面，保留登记） |

**门禁余量**：活跃工具合计 **35 个，全局软上限 80**（[mcp_capabilities.yaml](../../registry/mcp_capabilities.yaml) `enums.max_total_tools`；G1-b 于 2026-11-08 用户确认，原硬顶 40 已上调；P0 漂移门禁补登 `l4_status` 后由 34 升至 35）。
**角色面**：`research` 8 / `engineer` 7 / `verifier` 5 / `executor` 7 / `l2_analysis` 7，均 ≤10 符合 ADR-4。

### 2.2 已具备的通用资产（应保留、不重构）

| 资产 | 载体 | 为什么是"通用优势" |
|---|---|---|
| 统一信封 10 字段 | [envelope_wrap.py](../../../mcp_shells/_shared/envelope_wrap.py) | 任何 Agent 拿到的返回结构一致；`ok/data/degraded/error_code` 可机器判定，不依赖自然语言 |
| 契约注册表 SSoT | [mcp_capabilities.yaml](../../registry/mcp_capabilities.yaml) | 工具面、读写属性、Mandate、角色映射集中在唯一文件，CI 可校验 |
| 写工具默认禁 + Mandate | [mandate_gate.py](../../../34-前端应用训练系统/core/mandate_gate.py) | 接入新 Agent 时默认只读，写能力需显式授权，安全边界与 Agent 实现无关 |
| 壳零业务逻辑 | `mcp_shells/*/server.py` | 协议面与业务实现解耦，业务可在 port 实现体内独立进化，壳无需随 Agent 变化 |
| 壳生命周期自愈 | [shell_handles.py](../../../34-前端应用训练系统/core/shell_handles.py) | 单壳复用、健康检查、重拉上限、try-retry-degrade 三态，对调用方透明 |
| 多传输 launcher | [stdio_shell_launcher.py](../../../34-前端应用训练系统/core/stdio_shell_launcher.py) / [ssh_shell_launcher.py](../../../34-前端应用训练系统/core/ssh_shell_launcher.py) | stdio / ssh-stdio / in-process 已实现，本地与云端可切换 |
| 观测与进化钩子 | `envelope.meta.trace_id` / `shadow_hook` / registry `capabilities` | 接入即可获得调用链追踪与轨迹采集能力，无需 Agent 侧改造 |

### 2.3 文档与代码的偏差（须先修正认知）

| # | 文档口径 | 代码实测 | 影响 |
|---|---|---|---|
| D1 | SPEC §3.4：壳统一由宿主注入 `PYTHONPATH`，禁止新增 `sys.path.insert` | 全部壳仍在运行时插入仓库根（如 [l0_data/server.py](../../../mcp_shells/l0_data/server.py) L28-30），且中文目录名无法以包方式 import | 新宿主必须精确复制路径，接入成本与出错率上升 |
| D2 | 注册表为工具面唯一事实源（§3.7 漂移比对） | `tools/list` 仍以字面量写在每个 `server.py`；[validate_mcp_registry.py](../../registry/scripts/validate_mcp_registry.py) 只校验注册表自身与文件存在，**不比对代码工具面** | 注册表与实现对漂移无门禁，是通用化的隐性腐蚀点 |
| D3 | 全壳统一协议版本 | ✅ **P3 已消除**：`shell_runtime` 版本协商（2024-11-05 / 2025-03-26 / 2025-06-18 / 2025-11-25），按请求回显、未知回退 | 已改为协商，不再硬编码 |
| D4 | 全壳统一走 JSON-RPC 壳 | 无任何官方 MCP SDK 依赖，`initialize/tools/list/tools/call/main` 在 8 个文件中重复实现 | 单壳 ~80 行协议样板，扩展成本与一致性风险高 |
| D5 | 角色能力集约束所有 Worker | `worker_roles` 仅被 [worker_tool_call.py](../../../34-前端应用训练系统/core/worker_tool_call.py) 读取，**外部 MCP 宿主不经此链路** | 外部 Agent 接入即获得整壳工具面，最小权限在协议面失效 |
| D6 | `mcp_profiles.json` 提供可复制 profile | 仅有 2 个手写 profile（cognitive-local / cognitive-cloud-ssh），无生成器 | 7 壳 × N 宿主需人工组合，无法一键 |

---

## 三、通用性八维评分

| 维度 | 评分 | 判断依据 | 结论 |
|---|---|---|---|
| 契约一致性 | **8/10** | 注册表 + 9 项 CI 校验 + 统一信封；扣分在 D2 漂移无门禁 | 接近可复用 |
| 权限治理 | **7/10** | 写工具默认禁、Mandate、Worker 只读矩阵完整；身份仍靠环境变量，无 per-agent 凭证 | 语义完备，载体待补 |
| 运行保障 | **7/10** | 单壳复用、被动健康检查、重拉上限、三态降级均已落地 | 可直接复用 |
| 观测 | **7/10** | trace_id、shadow 旁路、训练钩子字段齐备 | 可直接复用 |
| 协议兼容 | **3/10** | 手写 JSON-RPC、版本硬编码、无 resources/prompts/sampling | 需抽取或迁移 |
| 接入便捷性 | **3/10** | 无角色包生成器、无根 `.mcp.json`、无 `doctor` | 主要缺口 |
| 扩展成本 | **5/10**（G1-b 后） | 新域仍需新建 server.py + 注册表 + 测试，但全局软上限 80 已解除容量天花板；壳运行时抽取后可再降成本 | 容量已解锁，模板待铺开 |
| 分发通用性 | **2/10** | 依赖仓库检出 + venv + `python3` 假设；无 wheel/Docker/entry-point；Windows 原生不可用 | 需产品化 |
| **综合** | **内核 ~7.5 / 接入 ~3** | | **底座可用，入口不通** |

---

## 四、通向"任意 Agent 即插即用"的六个硬障碍

### H1 无角色化 MCP 入口（最高优先级）

外部 Agent 只能整壳接入：需要 `recall` 就必须同时暴露 `record/verify` 等写工具。当前最小权限只存在于 DSH 内部 `call_worker_tool(role, tool, args)`，**MCP 协议层没有 `role` 概念**。后果：接入即越权面暴露，安全阀只能靠壳内事后拒绝。

### H2 无配置生成器

`shells` 与 `worker_roles` 已包含生成宿主配置所需的全部信息，但从未被消费。现有 [install_cognitive_mcp.py](../../../4-MEMORY/9-工具与接口/deploy/install_cognitive_mcp.py) 只处理 cognition 一个壳，且路径、解释器、验证工具名均为硬编码。

### H3 壳协议模板未抽取

8 个 `server.py` 各自实现 `initialize / tools/list / tools/call / main`，合计约 4,000 行中约 600-800 行为重复样板。新壳开发必须复制粘贴并按壳名改写，是扩展成本的主要来源。

### H4 全局工具上限曾成天花板（G1-b 已解决）

原 `max_total_tools = 40` 按"全局注册工具数"计，34 个已近触顶。**2026-11-08 用户确认 G1-b**：主约束改为「每壳 / 每角色 ≤10」，全局 40 → **软上限 80**，新增域不再被容量直接卡死。

### H5 注册表↔代码漂移无校验

D2 所述。缺少 `tools/list` 与注册表的比对门禁，注册表的"SSoT"地位在实现层是名义上的。

### H6 跨平台/跨环境假设

`python3`、`<REPO_ROOT>` 占位、POSIX 路径、中文目录名，使 Windows 原生宿主（当前开发环境即 Windows）无法直接接入；远程模式需手工拼 SSH 命令。

---

## 五、建议目标形态：一个网关 + 一个生成器 + 一套运行时

```
任意 Agent（Claude Code / Cursor / Trae / Windsurf / 自研）
        │  一条 mcp.json 条目（唯一接入点）
        ▼
┌──────────────────────────────────────────┐
│  l0-gateway --role <role>                │  ← 新增：角色网守（MCP server）
│  tools/list = 角色白名单（≤10）           │
│  集中：Mandate / trace_id / 审计 / 限流    │
└──────────────────┬───────────────────────┘
                   │ 复用 ShellHandleManager（不改）
     ┌─────────────┼─────────────┬──────────────┐
  cognition       data          eval        trade-exec …
```

### 5.1 三件套

| 组件 | 职责 | 复用基础 | 新增量 |
|---|---|---|---|
| **`mcpctl` CLI** | `doctor` 环境体检 / `profile --role --host` 生成配置 / `install` 写入宿主 / `verify` 冒烟 / `new-shell` 脚手架 | 泛化现有 installer 的检测、备份、合并、验证逻辑 | 中 |
| **`l0-gateway`** | 单条配置接入；按角色裁剪 `tools/list`；集中执行 Mandate、trace、审计、限流 | `ShellHandleManager` + `mandate_gate` + 注册表 | 中 |
| **`shell_runtime.py`** | 统一 JSON-RPC 循环；`tools/list` 从注册表派生；分发到 HANDLERS；信封与 shadow 内置 | 抽取 7 壳公共段 | 小 |

### 5.2 为什么网关优于"继续直连整壳"

| 维度 | 直连整壳（现状） | 角色网关 |
|---|---|---|
| Agent 配置条目 | 每个相关壳一条，N 壳 = N 条 | 1 条 |
| 最小权限 | 壳级（只能整壳给或整壳不给） | 工具级（精确等于角色白名单） |
| 治理落点 | 壳内分散 | 网关集中（Mandate/trace/审计/限流） |
| 工具上限 | 受全局软上限 80 约束 | 按角色暴露面计算，注册表可扩容 |
| 进程数 | 随 Agent 数线性增长 | 随角色数增长，壳可复用 |
| 延迟 | 一跳 | 两跳（本地 stdio 增量可忽略，需 P0 基线复测） |

### 5.3 需要一并决策的治理口径

| # | 议题 | 现状 | 建议 |
|---|---|---|---|
| G1 | 工具上限语义 | ✅ **已确认 G1-b（2026-11-08）**：每壳/每角色 ≤10 + 全局软上限 80 | 注册表 `max_total_tools` 已改 80；校验器/TECH/SPEC 同步 |
| G2 | 漂移门禁 | 无 | CI 增 `tools/list` ↔ 注册表比对；不一致即 ERR |
| G3 | 协议版本 | 硬编码 2024-11-05 | 壳运行时做 `initialize` 协商，最低支持版本写入门禁 |
| G4 | 身份载体 | 环境变量 | 网关层预留 per-agent principal（可先用 env，后续接 token） |

> 以上 G1-G2 涉及既有硬约束数值，**须用户确认后**再落入 SPEC 与注册表。

---

## 六、路线对比

| 路线 | 内容 | 成本 | 收益 | 风险 |
|---|---|---|---|---|
| **A. 轻量生成器** | 仅 `mcpctl profile/doctor`，不改运行时 | S | 接入从"小时级"降到"分钟级" | 不解决整壳暴露与工具上限 |
| **B. 角色网关（推荐）** | A + `l0-gateway` + 壳运行时抽取 + 漂移门禁 | M | 真正"一条配置接入任意 Agent"；治理集中；可扩容 | 多一跳延迟；网关本身需纳入契约测试 |
| **C. 平台化** | B + P3a 分包（SDK / wheel / Docker）+ P3b 发现（Agent Card） | L | 协议演进红利、跨机分发 | 改动面大，需全量回归 |

**推荐 A → B，C 作为可选项后置。** 理由：B 已能覆盖"通用、便捷、快速"的主要诉求，且完全复用现有 `ShellHandleManager` 与注册表，不改动 L0 port 层，符合"零回归"硬约束。

---

## 七、分期建议

| 期 | 内容 | 验收标准 |
|---|---|---|
| **P0（S）✅ 已落地（2026-11-08）** | ① 注册表↔代码漂移校验；② `mcpctl doctor`；③ `mcpctl profile --role --host` 生成 `.mcp.json` | 任一角色一条命令产出可用配置；漂移可被 CI 拦截 |
| **P1（M）🟡 主体已落地（2026-11-08；G1 待确认）** | ① ✅ `l0-gateway --role`；② ⏸ 治理口径 G1 待用户确认；③ ✅ 壳运行时抽取 + `l0_data`/`l0_eval` 迁移 | 外部 Agent 单条接入；`tools/list` 精确等于角色白名单 |
| **P2（M）✅ 已落地（2026-11-08）** | ① 壳运行时迁移 7 壳；② `mcpctl install --host all`；③ `new-shell` 脚手架；④ `DREAMBUDDY_MCP_REGISTRY` 覆盖 | 新域从 0 到可调用 ≤30 分钟；`agent.debate` / `l1.trading` 属其他在途分支 |
| **P3a（L）🟡 部分落地（2026-11-08）** | ✅ 协议版本协商 + ✅ Docker 分发包；⏸ 官方 MCP SDK / wheel 后置（依赖与全量回归成本） | 干净机器单命令安装；协议版本协商通过；三端 `doctor` 一致 |
| **P3b（L）✅ 已落地（2026-11-08）** | Agent Card 静态索引 + 运行时 `serverInfo._meta.agent_card` | 外部 Agent 可机器发现角色与能力，不需人工读文档 |
| **P4（XL，⏸ 暂不开发）** | 共享沉淀协议：tenant 命名空间、provenance 血缘、trust tier、合并/蒸馏 | 不排期；仅草案登记，见 §八 |

**P0 落地记录（2026-11-08）**

| 交付 | 载体 |
|---|---|
| 漂移门禁 | [check_mcp_tool_drift.py](../../registry/scripts/check_mcp_tool_drift.py)：7 壳真实 stdio 探测，`extra` / `missing` / `readOnlyHint` 三类漂移；CI 已接线（`.github/workflows/l0-contracts.yml`） |
| 控制面 CLI | [mcpctl.py](../../registry/scripts/mcpctl.py)：`doctor --deep` / `profile --role` / `verify` / `list-roles` / `list-shells` |
| 角色配置生成 | `profile` 输出 `mcpServers`，支持 `json / claude-project / trae / claude / cursor / windsurf / continue`，`--install` 自动备份合并 |
| 测试 | [test_mcpctl.py](../../registry/scripts/test_mcpctl.py)：8 项（profile 全角色覆盖 / SSH 分支 / 漂移比对 / 真实壳零漂移） |
| 首轮实测 | 发现并修复 2 处存量问题：① 认知壳 `l4_status` 未登记 → 已补注册表（现 35/80）；② `l0_trade_exec` 依赖 POSIX `fcntl` → 已加 Windows `msvcrt` 兼容 |

> P0 验收口径：`check_mcp_tool_drift.py` 退出 0；`mcpctl doctor --deep` 7/7 壳握手通过；`mcpctl profile --role <任一角色>` 产出可解析的 `mcpServers`。

**P1 落地记录（2026-11-08）**

| 交付 | 载体 |
|---|---|
| 角色网关 | [l0_gateway/server.py](../../../mcp_shells/l0_gateway/server.py)：`tools/list` 精确等于角色白名单；角色外/写工具 `forbidden`；壳不可用 `unavailable`；传输失败重试→`shell_degraded` |
| 网关契约 | [SPEC-L0-MCP-GATEWAY-v0.1.md](./SPEC-L0-MCP-GATEWAY-v0.1.md) |
| 壳运行时 | [shell_runtime.py](../../../mcp_shells/_shared/shell_runtime.py)：统一 JSON-RPC 循环，`tools/list` 从 registry 派生 |
| 迁移验证 | `l0_data`（4 工具）、`l0_eval`（2 工具）已迁移；`pytest mcp_shells/` 全绿、漂移 0 |
| 单条接入 | `mcpctl profile --role <role> --gateway --out .mcp.json` 产出 1 条 `l0-<role>` 配置 |
| 跨平台传输 | `StdioShell` 由 `select` 改为后台读线程（Windows 管道不可 select）；本地 stdio 统一网关解释器 + UTF-8 |
| 测试 | [test_l0_gateway_server.py](../../../mcp_shells/l0_gateway/test_l0_gateway_server.py) 7 项（含真实 verifier 端到端） |

**P1 G1 已定**：用户 2026-11-08 确认 **G1-b**——主约束为每壳/每角色 ≤10，全局上限由 40 改为**软上限 80**；`mcp_capabilities.yaml`、校验器、TECH、SPEC 已同步。

**P2 落地记录（2026-11-08）**

| 交付 | 载体 / 结果 |
|---|---|
| 壳运行时全量迁移 | 7 壳：cognition / semantic-39 / rea / data / eval / store-admin / trade-exec；`agent.debate` / `l1.trading` 属其他在途分支 |
| 一键安装 | `mcpctl install --role <role> [--gateway] --host all`：自动备份并合并到全部可写宿主 |
| 新壳脚手架 | `mcpctl new-shell`：生成 `server.py` + 契约测试 + registry 片段；`--register` 自动插入并校验（失败回滚） |
| 自定义注册表 | `DREAMBUDDY_MCP_REGISTRY` 环境变量覆盖，`shell_runtime` / `mcpctl` / 漂移门禁均生效 |
| 跨平台 | 迁移后的壳统一 UTF-8 stdio；`StdioShell` 读线程 + Windows 命令拆分 |
| 测试 | `pytest mcp_shells/ + test_mcpctl.py` 全绿；漂移 0；`doctor --deep` 8 壳通过（7 active + 1 deprecated） |
| 脚手架实测 | `new-shell` 生成临时壳 + 临时注册表：`tools/list = [demo_read]`，调用返回 `not_found` 信封，验证后已清理 |

**P3 落地记录（2026-11-08）**

| 交付 | 载体 / 结果 |
|---|---|
| 协议版本协商 | `shell_runtime.negotiate_protocol_version`：支持 2024-11-05 / 2025-03-26 / 2025-06-18 / 2025-11-25，按请求回显、未知回退；网关与全部迁移壳共用 |
| Agent Card（P3b） | [SPEC-L0-MCP-DISCOVERY-v0.1.md](./SPEC-L0-MCP-DISCOVERY-v0.1.md)；`mcpctl cards` 生成 [agent_cards.json](../../registry/agent_cards.json)；网关 `initialize._meta.agent_card` |
| Docker 分发（P3a） | [deploy/mcp/Dockerfile](../../../deploy/mcp/Dockerfile) + [README](../../../deploy/mcp/README.md)；CI `mcp-docker` job 实跑构建 + 协议协商 + verifier 工具面断言 |
| CI 防漂移 | `mcpctl cards --check` 加入 l0-contracts |
| 后置 | 官方 MCP SDK 迁移（`mcp` 包未引入，需独立全量回归）；wheel 分发（中文目录/域内私有依赖） |

---

## 八、共享沉淀前提与 P4 草案（⏸ 暂不开发）

> **决策（2026-11-08）**：开发范围先到 P3（P3a / P3b）。本节仅登记"若要共享沉淀还缺什么"，**不排期、不预留实现工作**，避免过早引入租户与联邦复杂度。

### 8.1 为什么 P3 不等于"协议级共享沉淀"

P3 的三项能力分别解决"能连"（SDK）、"能装"（wheel/Docker）、"能找到"（Agent Card），都属于**分发与兼容**。它们让"别人用得上"，但不产生"别人的经验回流并让所有人变强"。共享沉淀是更上面一层的问题，MCP 协议本身不提供。

### 8.2 "协议级"的三层含义

| 层级 | 含义 | 现状 | P3 能到吗 |
|---|---|---|---|
| 协议兼容级 | 任意 MCP 宿主能连、能握手、能调用 | 手写 JSON-RPC，版本硬编码（D3/D4） | ✅ 能 |
| 契约级 | 别人按统一信封、错误码、角色能力集、Mandate 语义写 Agent | **已具备**，是本系统的真实资产 | ✅ 能，且已有 |
| 生态级 | 别人注册能力、贡献验证过的经验、共同变强 | 不存在 | ❌ 不能，需 P4 |

### 8.3 沉淀资产的可共享性

| 沉淀层 | 载体 | 默认可共享 | 前提 |
|---|---|---|---|
| 代码 / 契约 | wheel、registry、envelope | ✅ 是 | 打包分发（P3a） |
| 模型 / 基因 | 权重、`bayesian_memories.json` | ⚠️ 有条件 | 版本化 + 授权 + 体积治理 |
| 记忆 / 轨迹 | `cognitive_memory.db`、trajectories | ❌ 否 | 多租户 + 血缘 + 隔离 |
| 经验结论 | record/verify 后的高质量记忆 | ❌ 否 | 质量门禁 + 信任分层 + 责任边界 |

### 8.4 与单一事实源的硬冲突

当前认知库刻意保持**单一事实源**（D5：云端 ssh 默认，本地只读降级；F2 修正明确禁止本地写分叉）。多用户 / 多机器同时写入会直接破坏该不变量——这不是打包或镜像能解决的，必须显式设计隔离与合并规则。

### 8.5 三种共享模式

| 模式 | 形态 | 适用 | 代价 |
|---|---|---|---|
| **A. 单租户产品** | 每人/每机一套，沉淀私有 | 对外分发 | 无网络效应 |
| **B. 中央大脑** | 多客户端共用一个云端权威库 | 单所有者多机 / 多 Agent | 需认证与租户隔离；**最贴合现状** |
| **C. 联邦沉淀** | 各端本地沉淀 → 蒸馏合并到公共库 | 生态化 | 需 provenance + 合并协议 + 质量门禁，成本最高 |

**当前架构天然落在 B**；若未来要走 C，必须先完成 8.6 的最小协议面。

### 8.6 P4 最小协议面（草案，不实现）

| # | 能力 | 内容 |
|---|---|---|
| P4-1 | 租户命名空间 | `tenant_id` / namespace 贯穿记忆、轨迹、任务状态；默认单租户，保持向后兼容 |
| P4-2 | 来源血缘 | `provenance = {principal, machine_id, agent_id, run_id, evidence_ref, ts}`，每条记忆可追溯 |
| P4-3 | 信任分层 | 与现有 S/A/B/C/D 质量等级**正交**的 trust tier，区分"谁验证的、在哪验证的" |
| P4-4 | 合并与蒸馏 | 联邦模式下的去重、冲突消解、质量衰减、跨租户提升规则 |
| P4-5 | 隐私与责任 | 脱敏、可见性、撤回（forget）传播、责任归属 |
| P4-6 | 未来验收 | U7 跨租户隔离 · U8 血缘可追溯 · U9 低质量记忆不跨租户扩散 |

### 8.7 现在唯一值得记住的"留缝"（待定，未实施）

若未来启动 P4，最低成本路径是给 `record` / `verify` 的请求与信封增加**可选** `tenant_id` + `provenance` 字段（缺省单租户、旧调用不受影响）。**本次不实施**，仅在 P4 启动时作为首选切入点。

---

## 九、验收标准（通用性达成判据）

- **U1** 任意角色接入新宿主：`mcpctl bootstrap --role <role> --host <host>` 单命令完成，且 `tools/list` 与注册表角色白名单完全一致。
- **U2** 最小权限：外部宿主调用角色外工具时，网关返回 `ok=false, error_code=forbidden`（而非壳内静默降级）。
- **U3** 零漂移：CI 中注册表与代码工具面不一致即阻断。
- **U4** 可扩展：新增一个域（≤10 工具）不触发现有工具上限，注册表校验仍通过。
- **U5** 跨平台：Windows / macOS / Linux 三端 `doctor` 与 `profile` 输出一致（路径分隔符除外）。
- **U6** 零回归：现有 7 壳 35 工具契约测试全绿；热路径延迟不劣化（壳 P50 ≤ 基线 + 45ms）。

---

## 十、附：实测方法

| 项 | 方法 |
|---|---|
| 壳/工具清单 | 读取 `47-MCP管理系统/registry/mcp_capabilities.yaml` 的 `shells[].tools[]` 逐项统计 |
| 代码漂移 | 比对各 `server.py` 内 `tools/list` 字面量与注册表 `tools[].name` |
| 协议实现 | `grep` 全仓 `from mcp import` / `FastMCP` / `mcp.server`，结果为空；统计 8 个壳的 `protocolVersion` 常量 |
| 客户端能力 | 阅读 `34-前端应用训练系统/core/{shell_handles,stdio_shell_launcher,ssh_shell_launcher,worker_tool_call,mandate_gate}.py` |
| 部署能力 | 阅读 `4-MEMORY/9-工具与接口/deploy/install_cognitive_mcp.py` + `registry/mcp_profiles.json`；确认仓库根无 `.mcp.json` |
| 分发能力 | 检查根 `pyproject.toml`（无 packages / entry-points / package-data 声明） |

---

## 十一、后续动作

1. 本评估评审通过后，按 §5.3 G1-G4 逐项确认治理口径；
2. 若确认，落 `SPEC-L0-MCP-GENERALITY-v0.1.md`（协议与组件契约），并在 [PLAN-L0-MCP-P0-P3](./PLAN-L0-MCP-P0-P3-v0.1.md) 追加 P0-P3 的通用化里程碑；
3. P0 先行实施漂移门禁 + `mcpctl profile`，可在不改变运行时行为的前提下立即验证价值；
4. **P4 不排期**：本次开发范围到 P3（P3a / P3b）为止，§八 仅作决策留档，待出现真实的多用户 / 多机共享需求时再启动。