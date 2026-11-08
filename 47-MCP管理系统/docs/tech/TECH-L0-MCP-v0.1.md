# TECH:L0 六域 MCP 封装 — 实现手册 v0.1

> **版本**: v0.1.5 ｜ **更新日期**: 2026-11-08 ｜ **状态**: ✅ M1-M4 全部落地 + D1/D2 已落 + **P0 控制面** + **P1 角色网关** + **P2 运行时/install/new-shell** + **P3 协议协商 / Agent Card / Docker 包**；2026-11-08 复核：9 壳真实拉起、漂移 0、`doctor --deep` 全通过、6 张 Agent Card 与 registry 一致
> **上游**: [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（契约）· [PLAN-L0-MCP-P0-P3 v0.1](./PLAN-L0-MCP-P0-P3-v0.1.md)（路线）· [ALIGNMENT-46-47 v1.0](./ALIGNMENT-46-47-v1.0.md)（决议）
> **读者**: M2/M3/M4 壳开发者 · 云端运维 · DSH Worker 消费方 · 壳后域内 agent 化 SPEC 作者
> **边界**: 本手册覆盖 **M1-M4 全部落地**（注册表 v1 / 信封映射层 / 基线脚本 / 校验器 / 认知壳 6 工具 / 39 壳 4 工具 / 数据壳 / 评测壳 / REA 壳 / 库管壳）。M2/M3/M4 壳实现细节见各壳 server.py 与契约测试。

---

## §0 本手册回答什么

SPEC 回答"**为什么这样设计、契约长什么样**"，PLAN 回答"**M1→M2→M3→M4 依次做什么**"。

本 TECH 回答：

1. **已落地的东西怎么用**（直接测试方法、四联门禁命令、基线怎么跑）
2. **扩壳时怎么不踩坑**（import 规约、信封兼容、注册表 schema、跨 domain 特例）
3. **常见反模式清单**（sys.path hack、信封 source 覆盖、三检索边界混淆、DB_BACKEND 漂移）
4. **壳后 agent 化 SPEC 的技术地基**（agent 与壳的边界、壳零感知原则）

---

## §1 概念总览

### 1.1 两层模型（SPEC §3.1 核心）

```
┌─────────────────────────────────────────────────┐
│ 外层 壳（mcp_shells/ 及存量三壳）                │
│   协议解析 → port/域入口调用 → 信封映射          │
│   零业务逻辑 · 不计 L0-P port 上限 6 · FAIL-OPEN 旁路 │
└──────────────────────┬──────────────────────────┘
                       │ 直接函数调用
┌──────────────────────▼──────────────────────────┐
│ 内层 L0-P ports（dreambuddy_l0/ports/）         │
│   六 port Protocol 不动（memory/collector/search/│
│   store/analysis/event）· 业务体零删零改         │
└─────────────────────────────────────────────────┘
```

**关键区分**：

| 概念 | 是什么 | 不是什么 |
|---|---|---|
| **port** | 进程内 Python Protocol 接口（`dreambuddy_l0/ports/` 六枚） | 不暴露协议、不跨进程 |
| **壳** | 纯协议转换层（stdin/stdout JSON-RPC → port 函数调用） | 不含业务逻辑、不训练模型、不新建 port |
| **adapter** | 壳内的三段之一：把 port 返回包信封、把 MCP 入参解包成 port 入参 | 不是独立模块、不做持久化 |
| **域内 agent** | 门后自治推理（壳上线之外的私有可迭代层） | 壳零感知、壳不路由到 agent |

> **D1 补充（2026-11-04）**：六 port Protocol 之外新增 [principal.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy_l0/ports/principal.py)（75 行）——`PrincipalMissingError` + `require_principal` 装饰器，对写类 port 方法做 fail-closed 身份硬门禁。它是**写门禁装饰器，不是第 7 个 Protocol**，不计入六 port 上限。

### 1.2 壳不算 port 上限

SPEC-L0 六 port 上限 **6** 是对 L0-P ports 的约束。壳是对外协议面，一个壳内部可以包多个 port 的工具（例：认知壳含 memory + search 两类 port 的工具）。

### 1.3 壳后域内 agent 的位置

agent 化路线不推进的原因：壳的协议面还没跑稳。壳跑稳后（M2/M3/M4 完成 + shadow 双跑一窗口），agent 会**在 port 实现体内生长**——壳完全零感知 agent 存在。详见 [§9](#9-壳后域内-agent-化的技术地基)。

---

## §2 目录结构与代码骨架

### 2.1 全局目录树

```
dreambuddy-v2/
├── mcp_shells/                      # 新增顶层目录（SPEC §3.1）
│   └── _shared/                     # 壳间共享模块
│       └── envelope_wrap.py         # M1③ L0 信封映射层 ✅
├── 4-MEMORY/9-工具与接口/
│   └── cognitive_mcp_server.py      # 存量壳①：认知+检索 6 工具 ✅
├── 39-金融语义蒸馏系统/scripts/
│   └── mcp_server.py                # 存量壳②：语义蒸馏 4 工具 ✅
├── dreambuddy_l0/ports/             # 内层六 port，本 P0 不动
├── 47-MCP管理系统/
│   ├── registry/
│   │   ├── mcp_capabilities.yaml    # 注册表 Schema 1.0-mcp ✅
│   │   └── scripts/
│   │       ├── validate_mcp_registry.py   # 8 项校验 ✅
│   │       └── measure_baseline.py        # 延迟基线 ✅
│   └── docs/tech/
│       ├── SPEC-L0-MCP-PACKAGING-v0.3.md
│       ├── PLAN-L0-MCP-P0-P3-v0.1.md
│       ├── ALIGNMENT-46-47-v1.0.md
│       ├── SPEC-L0-DOMAIN-AGENTS-v0.1.md
│       └── TECH-L0-MCP-v0.1.md      # 本文件
```

**新壳落地清单**（PLAN M2⑤/M2⑥/M3⑦/M4⑩ 已创建目录）：
```
mcp_shells/
├── l0_data/server.py           # M2⑤ 数据壳（只读 + 写面 Ban）
├── l0_eval/server.py           # M2⑥ 评测壳（薄包 45）
├── l0_rea/server.py            # M3⑦ REA 壳（6 两段式工具 + JSONL 作业持久层）
└── l0_store_admin/server.py    # M4⑩ 库管壳（只读）
```

### 2.2 壳三段式结构（所有存量/规划壳必须遵循）

```python
# 伪代码模板 —— 新壳骨架
def _handle_tool_x(args: dict) -> dict:
    # 第一段：协议解析（MCP 入参 → port 入参解包）
    port_args = _convert_mcp_to_port(args)

    # 第二段：port/域入口调用（零业务逻辑，直接透传）
    try:
        result = some_port.do_something(**port_args)
    except Exception as e:
        return envelope_wrap.wrap(
            data=None,
            source="l0.data.mcp",
            degraded=True,
            error_code="unavailable",
            meta={"error": str(e)},
        )

    # 第三段：信封映射（port 业务体原样透传到 envelope.data）
    return envelope_wrap.wrap(
        data=result,
        source="l0.data.mcp",
    )
```

### 2.3 import 规约（治 sys.path hack，SPEC §3.4）

- **新壳禁止新增 `sys.path.insert`**：统一由宿主 `mcp.json` 的 `env.PYTHONPATH=<repo root>` 注入，或以 `python3 -m mcp_shells.<domain>` 包方式拉起
- **存量 4 处 hack 白名单**（随各壳规范化逐步清零）：
  1. `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` L38-43（`parents[2]/mcp_shells/_shared` 双 import，每个行独立 `# noqa: E402`）
  2. `dreambuddy_l0/facade.py` L51-57
  3. `45-评测系统/api/server.py` L18-20
  4. `21-数据源客户端` 测试直插 18/20

---

## §3 注册表机制

### 3.1 Schema 1.0-mcp 完整字段表

注册表 = `47-MCP管理系统/registry/mcp_capabilities.yaml`（单一事实源，B4 定稿）。**不加载进运行时注册表**（进程内存态与多进程现实冲突，SPEC §3.7）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | str | 固定 `"1.0-mcp"` |
| `registry_version` | str | 注册表版本号 |
| `last_updated` | date | 最后更新日期 |
| `single_source_of_truth` | bool | 固定 `true` |
| `shells[]` | list | 已上线壳数组 |
| `shells[].shell_id` | kebab-case | 全局唯一（`l0.cognition.mcp` 格式） |
| `shells[].capability_id` | str | 对齐 C6 capabilities.yaml 的 capability_id |
| `shells[].transport` | enum | `stdio` / `ssh-stdio` / `http` / `in-process` |
| `shells[].shell_path` | path | 相对 repo root |
| `shells[].shell_cmd` | str | `python3 {path}` 占位模板 |
| `shells[].envelope_version` | enum | `0.1`（P0 信封）/ `0.2`（P1+信封迭代） |
| `shells[].status` | enum | `available` / `degraded` / `planned` / `deprecated` |
| `shells[].tools[].name` | str | 工具名，MCP tools/call 用 |
| `shells[].tools[].port` | enum | 六 port 枚举（memory/collector/search/store/analysis/event） |
| `shells[].tools[].domain` | enum | 七域语义枚举（cognition/search/semantic/data/eval/rea/store-admin） |
| `shells[].tools[].read_write` | enum | `read` / `write` / `read-write` |
| `shells[].tools[].requires_mandate` | bool | 写工具是否需宿主 Mandate 授权（SPEC §3.3） |
| `shells[].tools[].annotations` | dict | MCP tool annotations：`readOnlyHint` + `destructiveHint` |
| `planned_shells[]` | list | 规划壳占位（schema 已完整，落地时只填 path/cmd/version） |
| `enums` | dict | 校验器参照的所有枚举值 + 门禁阈值 |

### 3.2 门禁阈值

| 阈值 | 值 | 含义 |
|---|---|---|
| `max_tools_per_shell` | 10 | Worker 角色→工具集矩阵，每角色 ≤10 工具（SPEC B2） |
| `max_total_tools` | 80 | 全局**软上限**（G1-b，2026-11-08 确认）；主约束是每壳/每角色 ≤10 |

### 3.3 存量 vs 规划壳的 status 语义

| status | 含义 | CI 行为 |
|---|---|---|
| `available` | 已上线运行，注册表全字段填齐 | 校验器全量校验 |
| `planned` | schema 已存在、落地时只填 path/cmd/version | 校验器只校验 schema |
| `degraded` | 壳在线但 FAIL-OPEN 旁路 | 校验器全量 + 警告 |
| `deprecated` | 壳下线，注册表保留历史 | 校验器跳过 |

### 3.4 跨 domain 同承载特例

**认知壳 = cognition（recall/record/verify/stats/health）+ search（unified_search）**。

边界说明：
- `recall` = 认知域**内部**向量检索（Memory port，三后端之三）
- `unified_search` = Search 域**跨源门面**（三后端：41 SearchAPI `/home/ubuntu/fis-p0` + Chroma RAG + recall）
- 同 server 承载的原因：unified_search 第三后端必须**同进程调 recall**，C7 决策同壳承载、零 IPC 开销

**39 独立壳** = Search 域**独立第三面**（实体解析/别名蒸馏），质不同源，独立 stdio 壳避免污染检索门面。

---

## §4 信封映射层详解

### 4.1 两个函数

```python
# mcp_shells/_shared/envelope_wrap.py

def wrap(data, source, *, degraded=False, error_code="", meta=None,
         trace_id="", idempotency_key="") -> dict:
    """通用信封包装。业务体 data 透传到 envelope.data，零删零改。"""

def wrap_merge_partial(partial, source, *, data_key="result",
                       partial_ok_key="ok", partial_degraded_key="degraded") -> dict:
    """对已半信封（自带 ok/source/degraded）的返回体做 merge。
    保留内部结构（如 health.l0 聚合、unified_search.sources 明细），
    外层补全缺失的信封字段。
    source 参数为权威（调用方声明的壳级 source），
    partial 自带的旧 source 字段忽略。"""
```

### 4.2 10 字段完整说明

SPEC v0.3 §3.1 定义，版本 `0.1`。

| # | 字段 | 类型 | 说明 | 默认值 |
|---|---|---|---|---|
| 1 | `ok` | bool | 反向映射 MCP `isError`；`ok=true` 且 `data=None`（源可达无数据）≠ 错误 | `not degraded` |
| 2 | `data` | Any | **业务体原样透传，零删零改** | `data` 参数值 |
| 3 | `source` | str | 壳级 source（如 `"l0.cognition.mcp"`），**权威字段**，忽略 partial 自带 | 调用方传入 |
| 4 | `timestamp` | float | `time.time()` | 当前时间 |
| 5 | `degraded` | bool | FAIL-OPEN 增强型旁路标记（主功能禁止 FAIL-OPEN，见 SPEC B1） | 调用方传入 |
| 6 | `meta` | dict | 扩展元数据（trace_origin、error_detail、job_id 等） | `{}` |
| 7 | `version` | str | 信封语义版本，与壳 `envelope_version` 一致 | `"0.1"` |
| 8 | `trace_id` | str | 从 MCP envelope 传入，缺失时壳生成 | `os.environ.get("MCP_TRACE_ID", "")` |
| 9 | `idempotency_key` | str | 幂等键，壳层幂等由宿主 Mandate 或调用方保证 | `""` |
| 10 | `error_code` | enum | 六值：`not_found` / `unavailable` / `conflict` / `invalid` / `timeout` / `degraded` / `all_sources_unavailable` | 调用方传入（仅 degraded 时非空） |

### 4.3 与 MCP schema 的映射（SPEC §3.2 实现视角重述）

| 信封 | MCP | 映射规则 |
|---|---|---|
| `ok=false` | `isError=true` | 反向映射 |
| `ok=true, data=None` | `isError=false` | 源可达无数据 ≠ 错误 |
| `data` | content JSON text block | `json.dumps(data)` |
| `source/timestamp/degraded/meta/version/trace_id/idempotency_key/error_code` | content 内嵌 envelope 对象 | 原样透传到 content 内 |
| `degraded=true + ok=true` | `isError=false, meta.envelope.degraded=true` | FAIL-OPEN 增强型旁路，必须显式标记 |
| 异步 `submit_*` | `ok=true, meta.job_id=<str>` | 两段式入口 |
| 异步 `poll_*` | `state=running/success/failed` + 结果信封 | 状态从持久层读（评测落 45 PG / REA 落 JSONL） |

### 4.4 信封半 merge 坑（已修复，易复发）

`wrap_merge_partial` 的 `partial` 参数可能自带旧的 `source` 字段（如 unified_search 自身可能返回过一次信封）。修复前用 `partial.get("source", source)` 让旧值覆盖权威值，**修复后 `source` 参数无条件胜出**。

测试信封兼容写法（C12 契约测试用）：
```python
out = srv._handle_recall({"context": "test", "top_k": 3})
out = out.get("data", out)  # 信封兼容：带信封取 data，不带信封原样返回
assert out.get("ok") == True
```

---

## §5 已落地工具面直接测试方法

### 5.1 认知壳 6 工具

```python
# 直接 import 壳脚本，调 _handle_* 私有函数（黑盒测试）
import sys, json
sys.path.insert(0, "4-MEMORY/9-工具与接口")
import cognitive_mcp_server as srv

# 先 warmup（避免第一次调用含 import 开销）
_ = srv._handle_stats({})

# 调用
result = srv._handle_recall({"context": "基本面数据链路问题", "top_k": 5})
result = json.loads(result) if isinstance(result, str) else result
result = result.get("data", result)  # 信封兼容

assert result.get("ok") == True
```

6 个工具签名（与注册表一致）：

| 工具 | 入参 | read_write | requires_mandate |
|---|---|---|---|
| `recall` | `context, top_k, min_quality` | read | false |
| `unified_search` | `query, top_k, source_preference?` | read | false |
| `record` | `content, quality_level, tags` | write | **true** |
| `verify` | `memory_id, success` | write | **true** |
| `stats` | （无） | read | false |
| `health` | （无） | read | false |

### 5.2 39 语义蒸馏壳 4 工具

```python
sys.path.insert(0, "39-金融语义蒸馏系统/scripts")
import mcp_server as srv

result = srv._handle_query_entity({"entity": "腾讯控股"})
result = json.loads(result) if isinstance(result, str) else result
```

| 工具 | read_write | requires_mandate |
|---|---|---|
| `query_entity` | read | false |
| `semantic_lookup` | read | false |
| `distill_aliases` | write | **true** |
| `training_feed` | write | **true** |

### 5.3 写工具 Mandate 行为（本地 vs 云端）

| 场景 | record / verify / distill_aliases / training_feed |
|---|---|
| **本地 profile**（cognitive-local） | 写工具**禁用**，返回 `ok=false, error_code=conflict, meta.reason` 含 `local readonly mode (D5)`，stderr 审计 `write_denied` |
| **云端 ssh profile** | 需宿主 mcp.json 声明 Mandate scope，未声明返回 `ok=false, error_code=conflict, meta.reason=missing-mandate` |

双模开关是环境变量 **`COGNITIVE_MCP_MODE`**（实现：[cognitive_mcp_server.py](../../../4-MEMORY/9-工具与接口/cognitive_mcp_server.py#L56)）：
`local` = 本地只读降级，`ssh`（默认）= 云端单一事实源。变量名与实现必须一致（V7）。

本地 profile 配置示例（可直接从模板 [mcp_profiles.json](../../registry/mcp_profiles.json) 复制 `profiles.cognitive-local`）：
```json
{
  "mcpServers": {
    "cognitive-local": {
      "command": "python3",
      "args": ["<REPO_ROOT>/4-MEMORY/9-工具与接口/cognitive_mcp_server.py"],
      "env": {
        "COGNITIVE_MCP_MODE": "local",
        "PYTHONPATH": "<REPO_ROOT>"
      }
    }
  }
}
```

---

## §6 校验器与本地四联门禁

### 6.1 命令链（每次提交前必须跑）

```bash
# ① 注册表 schema + 交叉引用（validate_mcp_registry.py 8 项校验）
python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py

# ② 能力集单一载体（validate_capability_set.py 5 项校验 + 核心交叉引用）
python3 0-系统文档管理/scripts/validate_capability_set.py

# ③ C6 capabilities.yaml 校验（宿主契约）
python3 scripts/validate_capabilities.py

# ④ C10 DAL 直连白名单 ratchet（拦截新直连）
python3 scripts/check_db_direct_imports.py --ratchet

# ⑤ 注册表 ↔ 壳代码 tools/list 漂移（P0）
python3 "47-MCP管理系统/registry/scripts/check_mcp_tool_drift.py"
```

**顺序约束**：①⑤ 是 MCP 域门禁，必须先过；③④ 是全局门禁，放后面。任何一步 exit 非零 = 阻断提交。

### 6.2 validate_mcp_registry.py 8 项校验

| # | 校验项 | 失败条件 |
|---|---|---|
| 1 | Schema 版本匹配 | `schema_version != "1.0-mcp"` |
| 2 | shell_id 全局唯一 | 重复 kebab-case shell_id |
| 3 | transport 枚举合法 | 不在 `[stdio, ssh-stdio, http, in-process]` |
| 4 | tools[].port 枚举合法 | 不在六 port |
| 5 | tools[].domain 枚举合法 | 不在七域 |
| 6 | tools[].requires_mandate + read_write 一致性 | `write + false` 或 `read + true`（read 工具不该要 mandate） |
| 7 | 每壳工具数 ≤ 10 | 触发 `max_tools_per_shell` 门禁 |
| 8 | 全量聚合工具数 ≤ 80（软上限） | 触发 `max_total_tools` 门禁 |

### 6.3 CI 阻断点

`l0-contracts.yml` 新增 step：
```yaml
- name: Validate MCP registry
  run: python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py
- name: Validate capability set single source
  run: python3 0-系统文档管理/scripts/validate_capability_set.py
```

---

### 6.4 mcpctl — 角色接入控制面（P0）

> 对应 [ASSESSMENT-L0-MCP-GENERALITY-v0.1](./ASSESSMENT-L0-MCP-GENERALITY-v0.1.md) §七 P0。

| 命令 | 作用 |
|---|---|
| `python3 "47-MCP管理系统/registry/scripts/mcpctl.py" doctor --deep` | 环境体检 + 逐壳真实握手 |
| `... profile --role research --out .mcp.json` | 按角色生成宿主配置 |
| `... profile --role verifier --host claude-project --install` | 合并写入宿主配置（自动备份） |
| `... profile --role research --gateway --out .mcp.json` | 生成**单条**角色网关配置（P1，工具级最小权限） |
| `... install --role research --gateway --host all` | 一键写入全部宿主（自动备份），P2 |
| `... new-shell --name quant --domain data --port analysis --tools a:read,b:write` | 生成壳骨架 + 测试 + registry 片段；`--register` 自动登记 |
| `... cards` / `... cards --check` | 生成 / 校验全部角色 Agent Card（P3b） |
| `... card --role research` | 输出单角色 Agent Card |
| `... verify` | 注册表 ↔ 代码漂移门禁（同 §6.1 ⑤） |
| `... list-roles` / `list-shells` | 查看角色 / 壳工具面 |

**P0 边界**：角色包是**壳级**的——MCP 配置只能按 server 粒度挂载，工具级最小权限待 P1 `l0-gateway --role` 落地后由网关注入；`profile` 会在 stderr 明确列出"随壳额外暴露"的工具。

### 6.5 角色能力网关（P1）

> 完整契约见 [SPEC-L0-MCP-GATEWAY v0.1](./SPEC-L0-MCP-GATEWAY-v0.1.md)。

- 入口：`python3 mcp_shells/l0_gateway/server.py --role <role>`
- `tools/list` 精确等于 `worker_roles[role].tools`（≤10），不是整壳工具面；
- 角色外 / 写工具 → `ok=false, error_code=forbidden`；
- 壳不可用 → `unavailable + degraded`；传输失败 → 重试一次 → `shell_degraded`；
- 复用 `34/core/ShellHandleManager`（单壳复用 / 健康检查 / 重拉）；
- 本地 stdio 统一使用网关自身解释器 + `PYTHONIOENCODING=utf-8`。

**壳运行时（P1/P2）**：[shell_runtime.py](../../../mcp_shells/_shared/shell_runtime.py) 提供统一的 `initialize / tools/list / tools/call` 循环，`tools/list` 从 registry 派生。P2 已迁移 8 壳：cognition / semantic-39 / rea / data / eval / store-admin / trade-exec / debate；代码有 handler 但 registry 未登记的工具不再暴露（结构性消除漂移）。`l1.trading.mcp` 属未提交新壳，待其分支合入后迁移。

**自定义注册表**：`DREAMBUDDY_MCP_REGISTRY` 环境变量可覆盖默认 registry 路径（`shell_runtime` / `mcpctl` / 漂移门禁均生效），便于非默认部署。

### 6.6 能力发现与协议协商（P3）

> 完整契约见 [SPEC-L0-MCP-DISCOVERY v0.1](./SPEC-L0-MCP-DISCOVERY-v0.1.md)。

- **协议版本**：`shell_runtime` 支持 `2024-11-05 / 2025-03-26 / 2025-06-18 / 2025-11-25`，按客户端请求回显，未知回退 `2024-11-05`。
- **静态索引**：`47-MCP管理系统/registry/agent_cards.json`（由 `mcpctl cards` 生成，CI `--check` 阻断漂移）。
- **运行时卡片**：网关 `initialize.serverInfo._meta.agent_card`，含角色、工具面、只读边界、启动命令。
- 外部 Agent / 注册表可直接抓取卡片，无需人工读 SPEC。

### 6.7 Docker 分发包（P3a）

- 文件：[deploy/mcp/Dockerfile](../../../deploy/mcp/Dockerfile) + [deploy/mcp/README.md](../../../deploy/mcp/README.md)
- 构建：`docker build -f deploy/mcp/Dockerfile -t l0-mcp .`
- 运行：`docker run -i --rm l0-mcp --role verifier`
- CI：`.github/workflows/l0-contracts.yml` 的 `mcp-docker` job 实跑构建 + `initialize` + `tools/list` 断言。
- **边界**：官方 MCP SDK 未迁移（`mcp` 包未引入，需独立全量回归）；wheel 分发因中文目录/域内私有依赖暂不做。

---

## §7 基线测量

### 7.1 measure_baseline.py 参数

```bash
python3 47-MCP管理系统/registry/scripts/measure_baseline.py
# 默认 N=100，6 工具各 100 次 in-process + 100 次 stdio 冷启动
# 产出: 47-MCP管理系统/registry/latency_baseline.md
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `N` | 100 | 每工具迭代次数 |
| 工具集 | recall/record/verify/stats/health/unified_search | 认知壳 6 工具 |
| in-process 方法 | 直接调 `_handle_*` 私有函数 | 宿主进程 pre-fork，无冷启动 |
| stdio 方法 | `subprocess.Popen` 每次新进程拉起 | 含 Python 解释器 import + CognitiveLoopEntry 初始化 |

### 7.2 产出 latency_baseline.md 格式

```markdown
# L0 MCP 壳延迟基线（M1④）
- 测量日期：YYYY-MM-DD
- 宿主：python3.12 ｜ 每工具 N=100
- SPEC §3.8 验收：壳 P50 ≤ 基线 + 45ms（D4）

| Tool | In-Process P50 | In-Process P95 | stdio 冷启动 P50 | stdio P95 | ΔP50 | stdio/in-proc P50比 |
|---|---|---|---|---|---|---|
| recall | ~5ms | ~15ms | ~80ms | ~120ms | +75ms | ~16× |
```

### 7.3 云端跑注意事项

**腾讯云 QR 扫码超时断连（exit 255）**：拆开跑长命令，单次控制在 30 秒内。

```bash
# 拆分为两步（约 20 秒 each）
sudo -u luke env PYTHONPATH=/home/luke/dreambuddy \
  /home/luke/venv-trading/bin/python3 \
  47-MCP管理系统/registry/scripts/measure_baseline.py
```

**云端环境变量**：
- Python = `/home/luke/venv-trading/bin/python3` 3.12.3
- PYTHONPATH = `/home/luke/dreambuddy`（壳 import 依赖）
- PG 16.15（缺 pg_trgm/vector 扩展，认知库走 SQLite 遗留路径）

---

## §8 常见坑与反模式

### 8.1 sys.path hack 白名单（随壳规范化清零）

存量 4 处已登记，**新壳禁止新增**。清零触发点 = 对应壳落地 M2/M3/M4 时改造为 `PYTHONPATH` 注入或 `python3 -m` 包方式。

### 8.2 信封兼容：source 权威覆盖 partial 旧值

`wrap_merge_partial(partial, source)` — **source 参数为壳级权威**，partial 自带的旧 `source` 字段必须忽略。修复前 bug：`partial.get("source", source)` 让旧值覆盖新值 → 调用方声明的壳标识丢失。

已在 cognitive_mcp_server L400+ 附近所有 `_handle_*` 函数 return 行验证为正确调用。

### 8.3 三检索边界混淆

容易把 recall / unified_search / 39 混为一谈。正确边界：

| 组件 | port | domain | 定位 |
|---|---|---|---|
| `recall` | memory | cognition | 认知域**内部**向量检索（三后端之三） |
| `unified_search` | search | search | Search 域**跨源门面**（三后端聚合） |
| `39 mcp_server` | search | semantic | Search 域**独立第三面**（实体解析/别名蒸馏） |

**统一检索门面（unified_search）不加 agent 的技术依据**（SPEC-L0-DOMAIN-AGENTS v0.1 的🚫 Forbidden 档）：实时系统最怕延迟抖动+结果不确定，agent 路由让检索路径变不可预测。

### 8.4 DB_BACKEND env 漂移

19-DAL 用全局 `DB_BACKEND` 选后端（`json_legacy`/`dual_write`/`sqlite_unified`）。**壳内禁止改写此变量**（SPEC §3.5），需要多后端验证时走宿主层 profile 切换。

### 8.5 冷启动 stdio P50 5-20× 慢于 in-process

这是正常的——含 Python 解释器 import + CognitiveLoopEntry 初始化开销。**真正跑 MCP 壳时宿主进程 pre-fork 可省**，实际增量会显著降低。基线只是参考，SPEC §3.8 判据是壳 P50 ≤ in-process P50 + 45ms。

### 8.6 异步 job 状态无持久层的壳禁止暴露异步工具

SPEC DA1：壳进程按需拉起即退，job 状态必须落持久层——评测落 45 PG 八表、REA 落 JSONL 状态文件。**无持久层的域不得暴露异步工具**。

### 8.7 实盘风控红线永不暴露 MCP

11-易经推理 / yijing-polling-trader / 止损 — 这些热路径模块**任何壳不得包装**，任何工具注册表不得登记。写入硬约束记忆库（P0 级），CI 扫描。

---

## §9 壳后域内 agent 化的技术地基

本手册为 [SPEC-L0-DOMAIN-AGENTS v0.1](./SPEC-L0-DOMAIN-AGENTS-v0.2.md) 提供以下前置地基：

| SPEC-L0-DOMAIN-AGENTS 章节 | 依赖本手册的哪部分 | 依赖原因 |
|---|---|---|
| §2 四档定级 | §1.1 两层模型 / §8.3 三检索边界 | agent 在 port 实现体内生长，壳零感知；检索门面不加 agent 因实时延迟约束 |
| §3 Phase A/B/C/D/E 路线 | §5 工具面签名 / §4 信封字段 / §3 注册表 | agent 参数外部化需壳信封 meta 承载；agent 写路径必须过壳 Mandate |
| §4 壳零感知原则 | §2.2 壳三段式结构 | 壳纯协议转换，agent 在第二段 port 实现体内部，壳无路由逻辑 |

**壳后 agent 化的推进时机**：
- 壳落地完成（M2/M3/M4 全部 ✅）
- shadow 双跑一窗口（M3⑨ REA_MCP_SHADOW=1）
- 基线报告产出、延迟 SLO 达标
- **bcrm2 切流后**（不同日原则）

---

## §10 三端同步规范

| 端 | 路径 | 同步规则 |
|---|---|---|
| 本地 macOS M3 | `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2` | push 到 GitHub |
| GitHub main | `yunya1991/Dreambuddy-V2.git` | 单一源 |
| 云端 Ubuntu 24.04 4C16G 180G | `/home/luke/dreambuddy` | `sudo -u luke git -C /home/luke/dreambuddy pull --ff-only` |

**硬约束**：
- 禁止本地 scp/rsync 推云端
- commit 信息用常规 git commit（不用 spec-completion hook）
- 云端 venv = `/home/luke/venv-trading/bin/python3` 3.12.3
- PYTHONPATH = `/home/luke/dreambuddy`（壳 import 依赖）

### 10.1 云端现状审计（2026-11-04 审计快照）

**HEAD 对齐**：本地 / GitHub `yunya1991/Dreambuddy-V2` / 云端 VM-0-5-ubuntu → `789f26e4b5` 三端严格一致（2026-11-04 完成双端分叉对齐：云端 `24f9564a`（D1/D2 port Principal 硬门禁）+ `045abbfb9a`（文档标注）已 rebase 进本地主线）

**四联门禁**（云端实测）：
```
✅ 注册表 OK — 7 存量壳 + 0 规划壳 / 24 active 工具 / 上限 40
✅ 能力集 OK — 3 角色 / 25 引用 / 14 唯一工具 / 交叉引用已对齐 47 registry
OK: 能力声明与实现一致（五能力 / port / provides.impl 无漂移）
OK: 白名单外无新增直连（C10 门禁）
```

**云端运行日志**（2026-11-04 实采）：
```
shadow-driver.timer   每 10min（20:06 / 20:16 / 20:26 三轮，4 壳 9 调用，degraded=1: data_store_read=unavailable）
ablation-loop.timer   每 6h（18:11:51→18:12:37，18981 条轨迹，f2_pass=true / f1_pass=false，n=4455）
PROMOTION_STATE       stage=S1_READY（skipped: ablation_not_passed）
L0 测试               pytest mcp_shells dreambuddy_l0 → EXIT=0 全绿
```

**注册表 vs 代码落地**（md5 全一致，本地↔云端逐文件比对）：

| shell_id | registry status | 本地代码 | 云端代码 | 行数 | md5 |
|---|---|---|---|---|---|
| l0.cognition.mcp（recall/record/verify/stats/health/unified_search） | available | ✅ `4-MEMORY/.../cognitive_mcp_server.py` | ✅ 同路径 | 897 | f2185e1f |
| l0.semantic-39.mcp（query_entity/semantic_lookup/distill_aliases/training_feed） | available | ✅ `39-.../scripts/mcp_server.py` | ✅ 同路径 | 278 | — |
| l0.rea.mcp（submit/poll × analyze/trace/compare） | available | ✅ `mcp_shells/l0_rea/server.py` | ✅ 同路径 | 292 | 789490d2 |
| l0.rea-client.mcp（npm 133 工具占位） | **deprecated** | ❌ 已废弃 | ❌ 已废弃 | — | — |
| l0.data.mcp（data_fetch/collect_once/store_read/store_write） | available | ✅ `mcp_shells/l0_data/server.py` | ✅ 同路径 | 318 | 88f21820 |
| l0.eval.mcp（eval_analyze/eval_report） | available | ✅ `mcp_shells/l0_eval/server.py` | ✅ 同路径 | 196 | bd68ed17 |
| l0.store-admin.mcp（store_admin_status/store_admin_query） | available | ✅ `mcp_shells/l0_store_admin/server.py` | ✅ 同路径 | 233 | 8c9f3b93 |
| dreambuddy_l0/ports/principal.py（D1 写门禁，非 Protocol） | — | ✅ | ✅ | 75 | 116a82f5 |
| _shared/envelope_wrap.py | — | ✅ | ✅ | 109 | 503de28f |
| mcp_capabilities.yaml schema 1.1-mcp | — | ✅ | ✅ | 296 | 95b77777 |

**M1④ 基线报告**：`latency_baseline.md` 已落地（2026-11-02 云端跑过，N=100 冷启动）
- recall in-proc P50 18.4ms → stdio 冷启动 P50 399.56ms（21.7×）
- verify in-proc P50 197.35ms → stdio 冷启动 P50 700.81ms（3.6×）
- stdio 冷启动含 Python 解释器 import 开销，真正跑 MCP 壳时宿主 pre-fork 可省

**云端 NeuralSDE 模型资产**：
- ✅ `neural_sde_v1.pt`（~1.2GB，100 epoch，final_loss 0.0119）
- ❌ **缺口**：`neural_sde_v1_dim64.pt` + `neural_sde_v1_path_sig.pt`（本地有，云端无 → TRAIN-BASE Phase B DomainCouplingHead 增量训练 backbone 缺失，B2 阻塞项）

**云端正在运行的关键服务**：
| service | status | 说明 |
|---|---|---|
| cognitive-daemon.service | running | file-change watcher → cognitive loop |
| dreambuddy-continual-training.service | running | 每 30min 主动持续训练（exit_policy 等） |
| trailing-stop-runner.service | running | 16-control trailing stop runner（OKX real） |
| yijing-data-server.service | running | port 8765 |
| eval-api.service | running | port 8790 |
| datacenter-scheduler.service | running | 18 collection pipeline |
| fis-continual-training.service | running | 34 continual training (v0.5) |
| signal-scanner.service | running | 12-trend 每 300s |
| product-hub.service | running | Next.js 14 port 3456 |
| dreambuddy-frontend.service | running | Next.js 15 |

**硬约束**：MCP 壳本身**不是**独立 systemd 服务——stdio 模式由上层按需拉起，ssh-stdio 模式通过 `dreambuddy-remote` SSH 连接直接执行。

**腾讯云 SSH 连接注意**：
- 别名 `dreambuddy-remote` = `43.160.201.117`（旧 IP `43.136.205.155` 已失效，kex_exchange_identification 被远端主动关闭）
- 首次连接需要微信扫码安全登录（exit 255 不是 QR 拦截，是高频 subprocess spawn 被 rate limit）
- 基线脚本后台跑：`nohup sudo -u luke env PYTHONPATH=/home/luke/dreambuddy /home/luke/venv-trading/bin/python3 ... > /tmp/baseline.log 2>&1 &`

---

## 附录 A：版本演进

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-02 | 首版，覆盖 P0/M1 已落地模块 |
| v0.1.1 | 2026-11-03 | 新增 §10.1 云端现状审计快照 + M1④ 基线报告引用 + L1/DOMAIN-DISCOVERY/TRAIN-BASE/COMM-SHADOW/Roadmap 交叉引用 |
| v0.1.2 | 2026-11-08 | P0 通用化：§6.1 增漂移门禁 ⑤、§6.4 `mcpctl` CLI；补登 `l4_status`；trade-exec 壳 Windows `msvcrt` 兼容 |
| v0.1.3 | 2026-11-08 | P1：§6.5 角色网关 + `shell_runtime.py`；`l0_data` / `l0_eval` 迁移；`StdioShell` 改跨平台读线程 + `list_tools()`；G1-b 全局软上限 40→80 |
| v0.1.4 | 2026-11-08 | P2：壳运行时迁移至 8 壳；`mcpctl install --host all`；`mcpctl new-shell`（骨架+测试+登记）；`DREAMBUDDY_MCP_REGISTRY` 覆盖 |
| v0.1.5 | 2026-11-08 | P3：协议版本协商；Agent Card 静态索引 + 运行时 `_meta`；Docker 分发 + CI `mcp-docker`；SDK/wheel 明确后置 |
| （待更新） | M2 完成后 | 增补数据壳/评测壳实现细节 |
| （待更新） | M3 完成后 | 增补 REA 壳/认知壳双模 |
| （待更新） | M4 完成后 | 增补库管壳只读 + 45 契约评测 |



---

## §9 收尾验证记录（2026-11-03）

### 9.1 真实拉起冒烟（6 壳 24 工具）

以 luke 用户 stdio 真实拉起全部壳，initialize → tools/list → tools/call 全链路通过：

| 壳 | 工具数 | 工具面 |
|---|---|---|
| 认知（cognitive） | 6 | recall / record / verify / stats / health / unified_search |
| 语义（l0.semantic-39） | 4 | query_entity / semantic_lookup / distill_aliases / training_feed |
| REA（l0.rea） | 6 | submit/poll × analyze/trace/compare（两段式） |
| 数据（l0.data） | 4 | data_fetch / data_collect_once / data_store_read / data_store_write |
| 评测（l0.eval） | 2 | eval_analyze / eval_report |
| 库管（l0.store-admin） | 2 | store_admin_status / store_admin_query |

### 9.2 统一信封校验

6/6 壳真实工具调用返回完整 10 字段信封（ok/data/source/timestamp/degraded/meta/version/trace_id/idempotency_key/error_code）。

**修复记录**：39 语义壳此前返回裸业务体（注册表登记 envelope_version 0.1 与实现不一致），已在 tools/call 响应构造处接入统一信封映射层，业务体原样透传到 envelope.data（零删零改）；独立拉起时按文件路径加载映射层，未新增 sys.path hack（SPEC §3.4 红线）。

### 9.3 契约测试与门禁

- 全量壳测试 22/22 全绿（以 luke 用户运行；REA 壳 job 持久层目录属主为 luke，ubuntu 用户运行会因写权限失败，属环境问题非代码缺陷）
- 注册表校验通过：4 存量壳 + 3 规划壳 / 24 active 工具 / 上限 40
- REA 影子双跑：三工具规范化比对 SHA-256 指纹一致（SHADOW-REPORT-L0-REA-M3.md）

### 9.4 生产运行规约

- 壳进程须以 **luke 用户**拉起（job 持久层 / 认知库数据目录属主为 luke）
- PYTHONPATH=/home/luke/dreambuddy 由宿主 mcp.json env 注入
- 云端 Python：/home/luke/venv-trading/bin/python3（3.12.3）
