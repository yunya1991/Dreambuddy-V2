# SPEC:L0 MCP 能力发现（Agent Card）— 契约与协议协商

> **版本**: v0.1 ｜ **更新日期**: 2026-11-08 ｜ **状态**: ✅ P3b 已落地
> **上游**: [ASSESSMENT-L0-MCP-GENERALITY v0.1](./ASSESSMENT-L0-MCP-GENERALITY-v0.1.md) §七 P3b
> **依赖**: [SPEC-L0-MCP-GATEWAY v0.1](./SPEC-L0-MCP-GATEWAY-v0.1.md)（角色投影）· [mcp_capabilities.yaml](../../registry/mcp_capabilities.yaml)（唯一事实源）
> **定位**: 让外部 Agent / 运维工具**机器可读**地发现"这个 L0 能提供什么、怎么连、权限边界是什么"，不再依赖人工读文档。

---

## 1. 两层发现

| 层 | 载体 | 消费者 | 生命周期 |
|---|---|---|---|
| **静态索引** | `47-MCP管理系统/registry/agent_cards.json` | 运维 / CI / 外部注册表抓取 | 随 registry 版本生成 |
| **运行时卡片** | `initialize.result.serverInfo._meta.agent_card` | MCP 宿主（连接时自描述） | 每次连接 |

两者内容同源（registry `worker_roles`），静态索引多一层 `generated_by` 与 `registry` 版本戳。

## 2. Agent Card Schema `1.0-agent-card`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | str | 固定 `"1.0-agent-card"` |
| `name` | str | `l0-<role>`（与 mcp.json 条目名一致） |
| `display_name` | str | 人类可读名称 |
| `description` | str | 角色描述（来自 `worker_roles[role].description`） |
| `version` | str | 卡片版本 |
| `protocol.name` | str | 固定 `"mcp"` |
| `protocol.versions` | list[str] | 支持的协议版本（与 `shell_runtime.SUPPORTED_PROTOCOL_VERSIONS` 同源） |
| `protocol.transport` | str | `stdio` |
| `server.command` / `server.args` / `server.env` | — | 启动信息。**静态索引**使用 `<PYTHON>` / `<REPO_ROOT>` 占位符以保证跨机器/CI 可校验；`mcpctl card` 单角色输出真实绝对路径 |
| `capabilities.tools[]` | list | `{name, read_only}`，顺序 = 角色工具顺序 |
| `capabilities.tool_count` | int | 工具数（≤10） |
| `capabilities.read_only` | bool | Worker 角色恒为 `true` |
| `registry.schema_version` / `registry.registry_version` | str | 来源注册表版本 |
| `security.worker_read_only` | bool | ADR-9/H7 |
| `security.write_tools_require_mandate` | bool | 写工具仍需宿主 Mandate |

### 2.1 索引文件 `agent_cards.json`

```json
{
  "schema_version": "1.0-agent-card-index",
  "generated_by": "mcpctl cards",
  "registry": {"schema_version": "1.1-mcp", "registry_version": "0.4"},
  "cards": {"research": {"...": "..."}}
}
```

> 该文件是**派生产物**，不得手改。CI 用 `mcpctl cards --check` 阻断漂移。

## 3. 生成与校验

```bash
# 全部角色 → registry/agent_cards.json
python3 "47-MCP管理系统/registry/scripts/mcpctl.py" cards

# 只校验（CI）
python3 .../mcpctl.py cards --check

# 单角色输出 / 指定文件
python3 .../mcpctl.py card --role research
python3 .../mcpctl.py card --role research --out /tmp/research.card.json
```

## 4. 运行时发现

网关 `initialize` 返回：

```json
{
  "protocolVersion": "2025-06-18",
  "capabilities": {"tools": {}},
  "serverInfo": {
    "name": "l0-gateway-research",
    "version": "0.3",
    "_meta": {
      "agent_card": {
        "schema_version": "1.0-agent-card",
        "name": "l0-gateway-research",
        "role": "research",
        "protocol": {"name": "mcp", "transport": "stdio"},
        "capabilities": {
          "tools": [{"name": "recall", "read_only": true}],
          "tool_count": 8,
          "read_only": true
        }
      }
    }
  }
}
```

> `_meta` 是 MCP 允许的扩展位；不识别它的宿主会安全忽略。

## 5. 协议版本协商

- 支持版本：`2024-11-05` / `2025-03-26` / `2025-06-18` / `2025-11-25`。
- 客户端请求版本在支持列表内 → **回显**；未知或缺失 → 回退 `2024-11-05`（保守默认）。
- 实现位置：`mcp_shells/_shared/shell_runtime.negotiate_protocol_version`；网关与全部迁移壳共用。
- 目的：消除原"硬编码 2024-11-05"的漂移（ASSESSMENT D3），不引入 SDK 依赖。

## 6. 验收

| # | 判据 | 实测 |
|---|---|---|
| V1 | 全部角色卡片工具面精确匹配 `worker_roles` | ✅ 6 cards |
| V2 | `cards --check` 能拦截手改/漂移 | ✅ 单测覆盖 |
| V3 | 网关 `initialize` 回显客户端协议版本 | ✅ 单测 + 真实端到端 |
| V4 | 未知版本回退默认 | ✅ 单测覆盖 |
| V5 | 卡片可由外部工具直接解析为 mcp.json 启动信息 | ✅ `server.command/args/env` 字段 |

## 7. 未做（明确边界）

- **官方 MCP SDK 迁移**：当前 `mcp` 包未引入；迁移需全量回归 9 壳，作为独立任务。
- **MCP 官方 Registry 自动注册**：需要外部网络与账号；当前只产出标准 Agent Card，供任何注册表/发现服务抓取。
- **HTTP 发现端点**：当前为 stdio + 静态文件；如需 `/.well-known/agent-card.json`，在 P3 后续加薄 HTTP 服务。