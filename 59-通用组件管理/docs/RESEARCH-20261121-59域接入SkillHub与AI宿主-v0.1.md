# RESEARCH-20261121 · 59 域组件 × SkillHub × AI 宿主接入调研 v0.1

> **日期**: 2026-11-21 ｜ **状态**: 调研结论，未改代码 ｜ **范围**: 只回答"怎么接"，不含实现
> **上游**: [INDEX.md §3](../INDEX.md) 组件登记 ｜ [SPEC-通用组件管理-架构重构-v0.1.md](./SPEC-通用组件管理-架构重构-v0.1.md)
> **调研对象**: `tools/dreambuddy.py`（新增统一编排壳）、SkillHub CLI（本机 `~/.skillhub/skills_store_cli.py`）、Trae MCP 配置、`47-MCP管理系统` 注册表与壳范式

---

## 0. 结论（先看这里）

1. **现状不是"接不上"，而是"接在了最弱的一层"**：59 域的新能力是一个本地 CLI（`dreambuddy`）+ 一个全局 Skill 说明书。对 AI 宿主而言，它只是"一段需要 Bash 的脚本"，不是原生工具——这跟"Claude 嵌入 VSCode"的体验差一个协议层。
2. **最短路径是 MCP 投影，不是重写 CLI**：仓库已有零依赖 stdio MCP 壳范式（`mcp_shells/_shared/shell_runtime.py`），且 Trae 已通过 `.trae/mcp.json` 挂了两个 MCP server。把 `component.yaml` 的 26 个 actions 自动投影成 MCP tools，即可获得工具卡、参数 schema、错误码、读写权限注解——这就是"嵌入 IDE"的等价物。
3. **"AI 间底层直接交互"有两条现成通道**：
   - 本地/内网：MCP（stdio，零依赖；或 streamable HTTP 供远端 Agent）。
   - 云端：SkillHub 的 `skillhub run --skill <slug>`，走 `/api/v1/sandbox/sessions` + `/api/v1/sandbox/runs` 的 **SSE 托管的沙箱会话**，属于零安装的 Agent-to-Agent 调用。
4. **真正的阻塞点在契约，不在传输**：`component.yaml.actions` 只有 `name/script/args/safety`，**没有入参 schema**，也不声明强制 JSON 输出；脚本虽普遍支持 `--json`，但动作层没登记。MCP 工具无法生成稳定的 `inputSchema`，跨 Agent 调用会退化成"猜命令行"。这项必须先补。
5. **建议形态**：一份 `component.yaml` → 四种产物（CLI / Skill 包 / MCP 工具 / SkillHub 分发与在线运行），单一源、生成式、`make check` 防漂移。SkillHub 只做"分发 + 在线执行"，不做能力编排中枢。

---

## 1. 现状取证

### 1.1 统一编排壳（本次新增能力）

[dreambuddy.py](../../tools/dreambuddy.py) 的设计是"子进程编排、不 import 组件代码"：

| 能力 | 实现位置 | 事实 |
|---|---|---|
| 组件发现 | [load_components L37-43](../../tools/dreambuddy.py#L37-L43) | 扫 `components/*/component.yaml`，当前 6 个组件 / 26 个动作 |
| 动作解析 | [resolve_target L57-74](../../tools/dreambuddy.py#L57-L74) | 动作 = 固定前置参数 + 透传 `rest`；**无参数类型、无必填、无枚举** |
| 只读门禁 | [cmd_run L124-135](../../tools/dreambuddy.py#L124-L135) | `safety: write` 必须 `--allow-write` |
| 参数兜底 | [normalize_args L269-280](../../tools/dreambuddy.py#L269-L280) | 用硬编码 `ARG_FLAG` 给裸值补 `--symbols/--chain`，说明契约层缺 schema |
| 自然语言路由 | [L364-390](../../tools/dreambuddy.py#L364-L390) | Qwen 优先，关键词兜底；模型只输出 `component/action/args` |

全局 Skill [~/.agents/skills/dreambuddy/SKILL.md](../../../../.agents/skills/dreambuddy/SKILL.md) 只是"教模型去跑 CLI"，不提供任何结构化调用面。

### 1.2 组件契约与输出

- [component.schema.json L63-94](../../contracts/component.schema.json#L63-L94)：`actions[]` 仅 `name/description/script/args/safety`，**没有 `params`**。
- [output.schema.json L1-18](../../contracts/output.schema.json#L1-L18)：已有 `data.v1` 等统一外壳（`skill/version/generated_at/rows/missing/method_ids/sources/limits`），但只约束"脚本输出"，不约束"动作调用"。
- 各组件脚本普遍支持 `--json`（`market-data`、`event-context`、`market-facts-daily`、`mra`、`ra` 均已具备），但 `component.yaml` 的动作没声明默认 JSON，导致 `dreambuddy run` 默认给人读文本。

### 1.3 分发侧现状

- [build_product.py L1-15](../../tools/build_product.py#L1-L15)：只产 **Skill 包**（`dist/<product>/<variant>/`），叠加 variants、内联 kernel。
- [INDEX.md §3.1 L84-L91](../INDEX.md#L84-L91)：已有 4 族多个商品在 SkillHub/SkillPay 上架。
- 结论：SkillHub 目前只被当作**发布渠道**，未使用它的搜索、技能集、在线运行、验签能力。

### 1.4 宿主侧现状（为什么说"已具备嵌入条件"）

- [.trae/mcp.json](../../../.trae/mcp.json) 已挂 `cognitive` 与 `rea` 两个 MCP server，说明 Trae/该工作区**原生支持 MCP 工具卡**。
- [shell_runtime.py L98-107](../../../mcp_shells/_shared/shell_runtime.py#L98-L107) 提供 `build_tool_list`（registry 决定工具集合）；[L248-260](../../../mcp_shells/_shared/shell_runtime.py#L248-L260) 提供 `run_stdio` 阻塞式 JSON-RPC 主循环，**纯标准库、零外部依赖**。
- [l0_gateway/server.py L1-18](../../../mcp_shells/l0_gateway/server.py#L1-L18) 是现成的"角色裁剪网关"：按 role 只暴露 ≤10 个工具、越权返回 `forbidden`、写工具在 Worker 角色一律拒绝。
- [mcp_capabilities.yaml L5-L12](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L5-L12) 已有 `shell_id/shell_path/tools[]` 注册范式，新增一个 `l0.components.mcp` 即可纳入治理。

### 1.5 SkillHub CLI 实际能力（本机实测）

`skillhub --help` 暴露的子命令：

| 子命令 | 能力 | 对 59 的价值 |
|---|---|---|
| `search` / `install` / `upgrade` / `list` | 发现、安装、（按 config.json 的 update URL）升级、列本地技能 | 分发通道；`--dir` 可指定安装到 `~/.agents/skills` |
| `publish` | 目录/zip 发布，`--dry-run` 预检，返回 `skillId/status` | 现有发布链路 |
| `pack install` | 安装 **SkillSet**（技能集） | 可把"59 域全量"打包成一次安装 |
| `verify` | 校验本机技能与平台签名（或 `--zip`） | 供应链安全，可纳入 `make check` |
| `run --skill <slug>` | 在线调用，**仅支持服务化 skill**，SSE 流式，按 host+skills 复用会话 | A2A / 云端 Agent 零安装调用 |
| `soul` / `comment` | 人格包、评论区 | 与本议题弱相关 |

在线运行的实现证据（[skills_store_cli.py](../../../../.skillhub/skills_store_cli.py)）：`POST /api/v1/sandbox/sessions` 建会话（L4983 起）、`POST /api/v1/sandbox/runs` 读 SSE（L5084 起）、`cmd_run` 组装 body 并复用 session（L5174 起）。

> 注意：`run` 在服务端沙箱里执行 skill，**不是**把你的本地脚本原样搬上去。它要求 skill 被平台认定为"服务化"，且沙箱的出网、依赖安装、密钥注入能力均未验证——这是 P3 的未决项，不是 P0 阻塞。

---

## 2. 四层接入面对比

| 层 | 形态 | 宿主体验 | 结构化程度 | 成本 | 适用 |
|---|---|---|---|---|---|
| L1 CLI（现状） | `dreambuddy run ...` | 模型需 Bash，无工具卡 | 低（文本） | 已付 | 运维、调试、脚本 |
| L2 Skill 包 | `SKILL.md` + scripts | 安装后可读说明书并执行 | 中（靠文档约束） | 低 | SkillHub 分发、非 MCP 宿主 |
| **L3 MCP（推荐主路径）** | stdio / HTTP JSON-RPC | **原生工具卡、参数表单、权限注解** | 高（JSON Schema + 结构化结果） | 中（生成器 + 壳） | IDE/桌面 Agent（Claude Code、Trae、Cursor、VS Code） |
| L4 SkillHub `run` | 云端沙箱 SSE | 无需安装，跨设备 | 中高（事件流） | 高（平台准入未知） | 云端 Agent、非本机用户、A2A |

**推荐组合**：L3 为主（本机/内网原生调用）+ L2 为分发与兜底 + L4 为云端在线执行 + L1 为运维面。四者共用同一份 `component.yaml`，不允许各自定义版本。

---

## 3. 目标架构：一份源，四种产物

```
components/<name>/component.yaml  ──┐
                                   ├─→ L1 CLI        tools/dreambuddy.py（已存在）
                                   ├─→ L2 Skill      tools/gen_skill.py  → components/*/skill/SKILL.md + pack 清单
                                   ├─→ L3 MCP        tools/gen_mcp.py    → mcp_shells/l0_components/server.py
                                   └─→ L4 分发       tools/build_product.py → dist/ + SkillHub frontmatter
```

### 3.1 契约补齐（P0，唯一必须先做的）

`component.yaml.actions[]` 增加：

```yaml
actions:
  - name: quotes
    script: scripts/quotes.py
    safety: read
    output: json            # 强制 --json，MCP/跨 Agent 调用唯一可解析形态
    params:
      - {name: symbols, flag: "--symbols", type: string, required: true,
         description: "逗号分隔 A 股代码，如 sh600519,sz000001"}
      - {name: format, flag: "--json", type: boolean, const: true}
```

要点：
- `params` 是**生成 MCP `inputSchema` 的唯一源**，也是 Skill 文档参数表的唯一源；
- 未声明 `params` 的动作只允许出现在 CLI，不投影成 MCP 工具（避免"猜参数"）；
- `safety: write` 自动映射为 MCP 注解 `readOnlyHint=false / destructiveHint=true` + `requires_mandate`；
- `output: json` 由壳统一追加，组件脚本无需改。

### 3.2 MCP 壳（P1）

- 新建 `mcp_shells/l0_components/server.py`，复用 [shell_runtime.run_stdio](../../../mcp_shells/_shared/shell_runtime.py#L248-L260)，工具表由 `gen_mcp.py` 生成。
- 工具命名：`<component>_<action>`，可再用 `mcp.name` 覆盖为意图词（如 `a_share_quote`）。26 个工具对上下文偏多，建议按族裁剪（复用 [l0_gateway 的 role 裁剪](../../../mcp_shells/l0_gateway/server.py#L1-L18)）：默认只挂 `*-hub` 6~8 个高频只读工具，其余按需展开。
- 执行路径：MCP handler → 解析 `params` → 复用 `dreambuddy.resolve_target/execute` 的子进程逻辑 → 强制 `--json` → 校验 `output_contract` → 返回 `content[0].text`（JSON）+ `structuredContent`。
- 权限：read 直接执行；write 要求调用方 principal + `--allow-write`，并写审计（who/when/action/参数摘要）。
- 接入：在 [.trae/mcp.json](../../../.trae/mcp.json) 增加一个 server 条目即可；Claude Code / Cursor / VS Code 各自 MCP 配置文件同理。**这就是"Claude 嵌入 VSCode"等价的落点**。
- 注册：在 [mcp_capabilities.yaml](../../../47-MCP管理系统/registry/mcp_capabilities.yaml) 增 `shell_id: l0.components.mcp`，纳入 `make check` 的 registry 校验；先独立跑通、后补注册也可（两阶段）。

### 3.3 Skill 与 SkillHub（P2/P3）

- `gen_skill.py` 从 `component.yaml` 生成各组件 `skill/SKILL.md` 的"动作参数表"段落，避免文档与实现漂移；现有 `build_product.py` 继续负责打包。
- 发布形态二选一或并存：
  - **单组件 Skill**（现状）：`market-data-hub`、`event-context`、`market-facts-daily`、`cogsteward-pro` 等；
  - **59 域 SkillSet**（新增）：把 6 个组件 + `dreambuddy` 编排说明打成一个 pack，`skillhub pack install` 一次装齐。
- `skillhub verify` 接入 `make check`，保证"本地装的就是平台上架的"。
- L4 `run`：先向平台确认"服务化 skill"准入与沙箱能力，再决定是否把只读动作（quotes/macro/filings/onchain）做成在线服务；写动作与预约类**不进云端沙箱**。

---

## 4. 分期建议与验收

| 阶段 | 内容 | 验收（可观测） |
|---|---|---|
| P0 | 补 `actions[].params/output`，schema 校验 + 单测；不改任何运行行为 | `make check` 通过；旧 CLI 输出逐字节不变 |
| P1 | 只读 MCP 投影（6 个高频工具）+ `.trae/mcp.json` 接入 | 在 IDE 里**不写 Bash**，模型直接 tool call 拿到 `data.v1` JSON；工具卡参数可填 |
| P2 | 全量动作 + 写动作权限/审计 + 角色裁剪 | 越权调用返回 `forbidden`；写动作无 mandate 必失败；审计可查 |
| P3 | SkillSet 打包发布、`verify` 进闸门、L4 在线运行试点 | `pack install` 一次装齐；`verify` 通过；在线只读动作端到端成功 |

---

## 5. 风险与未决问题

1. **SkillHub "服务化 skill" 准入未知**：需平台侧确认；若不可用，L4 降级为"自建 HTTP + OpenAPI"，不阻塞 P0–P2。
2. **沙箱能力未知**：出网、依赖、密钥、额度；预约/写类动作一律不进沙箱。
3. **工具数量与上下文预算**：26 个工具全挂会挤占上下文；默认裁剪、按需展开。
4. **多形态版本漂移**：唯一源 = `component.yaml`；所有生成物必须 `--check`，禁止手改。
5. **远端 MCP 鉴权**：stdio 本机可信，HTTP/SSE 必须带 token + principal，禁止裸奔。
6. **重复建设风险**：`47-MCP管理系统` 已有壳范式与注册表，59 只新增"投影器"，不新建第二套 MCP 基础设施。

---

## 6. 待拍板选项

| 选项 | 内容 | 代价 / 收益 |
|---|---|---|
| **A（推荐）** | 先做 P0 契约 + P1 只读 MCP，直接把 59 域变成 IDE 原生工具 | 小改动、立即见效；写动作暂不进 |
| B | 先做 SkillSet 分发（一个 pack 装齐 59 域） | 分发体验提升；仍是"脚本级"调用 |
| C | 直接做远端 MCP / HTTP 网关（A2A） | 适合云端 Agent；鉴权与部署成本最高 |

> 若目标是"我在 VSCode/Claude 里像用内置工具一样用 59 域"，选 A；若目标是"让别人一键安装我的技能集"，选 B；若目标是"云端 Agent 互调"，选 C。三者不冲突，A 是共同前置。

---

## 附：取证命令

```bash
# 组件与动作清单
python3 59-通用组件管理/tools/dreambuddy.py ls

# SkillHub CLI 能力面
skillhub --help
skillhub run --help
skillhub pack install --help

# 现有 MCP 接入形态
cat .trae/mcp.json
sed -n '1,60p' mcp_shells/l0_gateway/server.py
```

---

## 7. 落地记录（2026-11-21，按选项 A：P0 + P1）

### 7.1 已完成

| 项 | 位置 | 结果 |
|---|---|---|
| 动作契约扩展 | [component.schema.json L89-L158](../../contracts/component.schema.json#L89-L158) | 新增 `output` / `params[]` / `mcp{expose,tier,name}`；`additionalProperties: false` 保持严格 |
| 7 个动作补参数 | `market-data`（quotes/macro/filings/onchain/handoff）、`market-facts-daily`（facts）、`event-context`（events/context/handoff）、`mobile-reservation-assist`（ask/jobs）、`reservation-assist`（doctor/list/report） | `output: json` + 参数 schema 唯一源 |
| MCP 投影壳 | [mcp_shells/l0_components/server.py](../../../mcp_shells/l0_components/server.py) | 零外部依赖（仅 PyYAML），stdio JSON-RPC；hot 8 工具 / all 12 只读；`--allow-write` 再加 2 个写工具 |
| 宿主接入 | [.trae/mcp.json](../../../.trae/mcp.json) | 新增 `components` server（`--profile all`）；重启 IDE 后出现 12 个只读工具卡 |
| 单测 | [test_server.py](../../../mcp_shells/l0_components/test_server.py) | 7 项通过（工具集、schema 对齐、argv 拼装、必填/未知参数拒绝） |
| 治理闸门 | `59-通用组件管理 && make check` | 全绿（G1–G7、INDEX、规则、站点产物、93 项 Node 测试） |

默认 8 个工具：`a_share_quote` / `market_data_macro` / `sec_filing_reader` / `market_data_onchain` / `a_share_index_facts` / `official_fed_sec_event_search` / `ticket_reservation` / `reservation_job_list`；`--profile all` 追加 `event_context_context` / `ticket_monitor_{list,report}` / `reservation_assist_doctor`。结果统一包 L0 信封（`ok/data/source/timestamp/meta/version`）。端到端实测：MCP `tools/call a_share_quote` 返回 `isError=false`、`source=l0.components.mcp`、`data.rows` 非空；无 principal 调写工具返回 `E_MANDATE`。

### 7.2 P2 修正记录（2026-11-21）

1. **动作清单与真实 CLI 漂移（已修）**：`reservation-assist` 改为 `watch list` / `switch-status` / `inbox show`，删除不存在的 `show/check/lint`；`cogsteward.lint` 改为 `skill lint`。`ra` 三个只读动作（doctor/list/report）已纳入 MCP extended 档。
2. **输出契约未全覆盖（待修）**：`market-data quotes` 的 JSON 含 `module/generated_at/window/...`，缺 `data.v1` 要求的 `skill/version/data_date/limits`；G6 golden 未覆盖该动作，故闸门仍绿。
3. **写动作门禁与审计（已加）**：MCP 需 `--allow-write` 才投影写工具；调用必须同时满足 `principal`（`--principal` 或 `DREAMBUDDY_PRINCIPAL`）与 `confirm=true`，执行后写 JSONL 审计（`DREAMBUDDY_AUDIT_LOG`，默认 `~/.local/share/dreambuddy/audit/components-mcp.jsonl`）。
4. **注册表登记（已加）**：`l0.components.mcp` 已进入 [mcp_capabilities.yaml](../../../47-MCP管理系统/registry/mcp_capabilities.yaml)（L0 / stdio / 14 工具，含 2 个 mandate 写工具），`validate_mcp_registry.py` 通过（19 壳 / 95 工具 / 上限 120）。

### 7.3 下一步（P3）

- 修 `market-data quotes` 的 `data.v1` 输出契约（或在 G6 golden 中显式豁免并记录）；
- SkillHub：`pack` 技能集分发、`verify` 进 `make check`；确认"服务化 skill"准入后再做 L4 在线运行；
- 远端 MCP / HTTP 网关（A2A）与 token/principal 鉴权。

---

## 8. 可发现性路由基准（2026-11-21）

### 8.1 目的与形态

回答"用户装了一堆 skill，agent 为什么首选我们"。基准放在 `platform/bench/routing/`：

| 文件 | 作用 |
|---|---|
| `intents.yaml` | 30 条真实意图（22 条覆盖 + 8 条越界），每条声明期望工具/分类/难度 |
| `competitors.yaml` | 4 个竞品夹具（A股行情、全球资产、SEC 解读、票务监控） |
| `run_bench.py` | 同一 prompt 让模型从"我们 12 个只读工具 + 4 个竞品"中单选；输出命中率/首选率/误选率/时延 |
| `test_run_bench.py` | 夹具与计分单测 |

命令：`make bench-dry`（只校验夹具，已并入 `make check`）、`make bench`（真实调用，需 Qwen 配置）。

### 8.2 基线结果（Qwen，30 条）

| 指标 | 值 |
|---|---|
| 覆盖命中率 | **36.4%**（8/22） |
| 选中我们的比例 | 26.7%（8/30） |
| 选错我们的动作 | 0 |
| 越界误选率 | 0%（未出现"什么都答"） |
| 平均时延 | 8.0 s |

分类：macro 100%、onchain 100%、event 67%、facts 50%；**quote 0%、filings 0%、reservation 0%**。

### 8.3 三个可解释的失分点（描述问题，不是能力问题）

1. **quote 全败给 `a_share_market`**：我们写"行情快照"，竞品写"A股实时行情、历史 K 线、财务指标、龙虎榜"。能力上我们只做行情，但描述没有把"贵州茅台/宁德时代/A股现价"这些实体显式写出来。
2. **filings 全败给 `sec_reader`**：我们写"美股披露"，竞品写"美股 SEC 公告检索、10-K/10-Q 解读"。我们的"8-K/10-K/us-gaap 字段"没有出现在描述里。
3. **reservation 全败给 `ticket_monitor`**：我们写"查看作业清单/生成报告"，竞品写"演出与博物馆门票余票监控、开票提醒与预约辅助"。内部术语（作业、监控项）对 agent 不可读。

结论：当前工具名与描述是"内部视角"，agent 无法把用户原话映射过来。这正是下一次对照实验的输入。

### 8.4 对照实验结果（2026-11-21 已执行）

只改动作描述，不改能力、工具名与参数：

| 指标 | 基线 | 改后 | Δ |
|---|---|---|---|
| 覆盖命中率 | 36.4%（8/22） | **100.0%（22/22）** | +63.6% |
| 选中我们的比例 | 26.7%（8/30） | **73.3%（22/30）** | +46.7% |
| 选错我们的动作 | 0 | 0 | 0 |
| 越界误选率 | 0.0%（0/8） | 0.0%（0/8） | 0 |
| 平均时延 | 7996 ms | 8059 ms | +63 ms |

分类命中全部 100%：quote / macro / filings / onchain / facts / event / reservation。

结论：

1. 描述里写**用户原话的实体**（贵州茅台、8-K、国博）比内部术语（行情快照、美股披露、作业清单）决定性强得多；
2. 不新增工具、不改架构，单靠文案即可把首选率从 26.7% 提到 73.3%；
3. 越界误选保持 0，说明提升来自"匹配更准"而不是"什么都说自己能干"。

复跑：`make bench`；与历史对比：`python3 platform/bench/routing/run_bench.py --compare <旧报告.json>`。

### 8.5 R2 对照：工具名（2026-11-21 已执行，含纠错）

**R2a（full 模式）**：只改 3 个工具名（`a_share_quote` / `us_sec_filings` / `reservation_plan`），描述与参数不动，结果 100% → 100%。但 R1 已到 100% 天花板，**该对照无 headroom，不能据此判定名字无效果**。

**R2b（name-only 隔离）**：候选只给名字、不给描述，只跑被改名的 10 条意图：

| 组 | 工具名 | 覆盖命中 | filings | reservation |
|---|---|---|---|---|
| A | 旧名（`market_data_quotes` 等） | 60%（6/10） | 0/3 | 1/2 |
| B | 新名（`a_share_quote` 等） | **80%（8/10）** | 2/3 | 1/2 |

结论：**名字有独立信号，+20pp**；但在强描述下会被淹没（full 模式已无提升空间）。剩余未命中：`f02`（10-Q 财务字段）仍输给 `sec_reader`，`r01`（国博预约）选了 `none`。方法论教训：测变量前先检查 headroom，基线贴近 100% 时用 name-only 或加难例。

**R6（name-only 命名细化）**：

- 第一次尝试把 `reservation_plan` 改为 `museum_ticket_reservation`：r01（国博）修好，但 r02（演唱会）失败，净覆盖仍 80%。**绑定单一实体牺牲了同族泛化**。
- 第二次改为 `ticket_reservation` + `sec_filing_reader`：定向 5 条 5/5，全量 10 条 **100%**（80% → 100%，+20pp）。
- 命名规则：**动作 + 能力对象**（`ticket_reservation`、`sec_filing_reader`），不要绑定单一实体；改完难例必须复测同族其它意图。

**R8（全量命名补齐）**：补改 `a_share_index_facts`、`ticket_monitor_list`、`ticket_monitor_report` 与 event 名（最终 `official_fed_sec_event_search`）。全量 name-only **81.8% → 95.5%**，越界误选仍 0；facts / reservation 均到 100%。仅剩 `e02`（美联储声明）偶发输给 `market_data_macro`——属跨族歧义 + 模型随机性（定向 6/6、全量 2/3），不应靠加长名字硬压，交给描述或 `when_to_use` 消歧。

**R9（when_to_use / not_for）**：新增 `--catalog-fields guidance`（名字+边界，不含描述），8 个热工具成组补齐边界。第一次只给 event / macro 加，结果 95.5% → 86.4%（event 抢走 filings、facts 落选）；成组补齐并解决两处语义重叠（`reservation_job_list` vs `ticket_monitor_list`、facts 的"一页数字事实"措辞）后到 **100%（22/22）**，选错动作 0，越界 0。结论：边界必须成组加；语义重叠先改名划边，再写 `not_for`。

**R10（弱模型复测）**：换 `qwen3.6-flash`，同一套 30 条。name-only 95.5%、guidance（名字+边界）95.5%、full（描述+边界）**100%**。命名规律跨模型复现；guidance 单独不够（弱模型更字面，e01 被 `sec_filing_reader` 吸走），描述+边界才是稳定面。平均时延 3.5–5.5s，full prompt 约 2559 字符。

**R11（SkillHub 上架字段）**：4 个免费商品补齐 `description` / `tags`，`summary` 改为问题优先并写入实体词，`displayName` 补意图词；版本 patch 后重建 8 个变体。`make check` 通过，`skillhub publish dist/<p>/free --dry-run --json` 4/4 返回 slug + version。曝光/安装转化需平台侧数据，本地无法量化；另发现 `cogsteward` slug 无 `dreambuddy-` 前缀，暂不统一以免破坏已有链接。

**R12（稳定性复跑）**：full 模式、强模型同一配置连跑 3 次，覆盖 100% × 3、选错 0 × 3、越界 0 × 3，30 条选择跨轮**翻转 0 次**；时延 12818 / 9636 / 7457 ms，σ≈2201（约 22%）。结论：准确率指标稳定，时延是噪声最大项，单次 ±1s 的差异不可作结论。强模型 full 回归（原 R13）由本轮顺带完成。

**R14（压力集）**：新增 10 条超短意图 + 5 条看似相关越界。覆盖 9/10（90%），越界误选 0/5，选错动作 0。唯一失败 `国博还有票吗` 选了竞品——我们只解析预约计划、不查实时余票，属能力边界而非文案问题；不用描述硬抢。

### 8.6 下一轮可测变量（未执行）

- 实际上架后接平台曝光/安装数据，验证 listing 转化；
- 温度/采样参数敏感性（0.2 vs 0.7），评估稳定性边界；
- 若补齐实时余票查询，再把 p08 改回期望 `ticket_reservation`。
