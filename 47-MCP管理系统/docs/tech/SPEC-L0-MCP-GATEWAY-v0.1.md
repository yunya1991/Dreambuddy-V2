# SPEC:L0 角色能力网关（l0-gateway）— 协议与契约

> **版本**: v0.1 ｜ **更新日期**: 2026-11-08 ｜ **状态**: ✅ P1 已落地（`mcp_shells/l0_gateway/server.py`）
> **上游**: [ASSESSMENT-L0-MCP-GENERALITY v0.1](./ASSESSMENT-L0-MCP-GENERALITY-v0.1.md) §五 / §七 P1
> **依赖**: [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（信封 / Mandate / registry）· [SPEC-DSH-P5 Transport v1.0](../../../46-DSH架构/docs/tech/SPEC-DSH-P5-TRANSPORT-HEALTHCHECK-v1.0.md)（壳生命周期）
> **定位**: 新增一个**协议入口层**，把 registry 的 `worker_roles` 投影成 MCP `tools/list`，让外部 Agent 用**一条配置**获得精确到工具的最小权限。

---

## 1. 定位与边界

```
外部 Agent（Claude Code / Cursor / Trae / …）
        │  一条 mcp.json 条目：l0-<role>
        ▼
┌──────────────────────────────────────┐
│ l0-gateway --role <role>             │
│ tools/list = worker_roles[role].tools│
│ 治理：forbidden / 只读 / trace / 重试 │
└──────────────────┬───────────────────┘
                   │ 复用 ShellHandleManager
     ┌─────────────┼─────────────┬──────────────┐
  cognition       data          eval        trade-exec …
```

| 边界 | 口径 |
|---|---|
| 网关**不是**壳 | 不新增 port、不新增工具、不占用 `shells` 注册项、不进入工具总数上限 |
| 网关**不是** Router | 不做意图理解/任务规划；只做角色投影 + 壳路由 |
| 网关**不写业务** | 不改写信封业务字段；只补 `meta.gateway_role/shell_id/trace_id` |
| 网关**不常驻** | stdio 按需拉起；由宿主进程管理 |

## 2. 角色投影契约

### 2.1 工具面来源

`tools/list` **唯一来源** = registry `worker_roles[role].tools`。

- 工具顺序 = 角色 `shells` 顺序 × 各壳注册表工具顺序（确定性，便于测试比对）。
- 工具描述 / `inputSchema` 优先从所属壳实时 `tools/list` 获取；壳不可用则使用 registry 注解 + 空 schema 降级。
- 代码中存在但 registry 未登记的工具**永不暴露**（registry 为 SSoT）。
- 角色工具总数必须 ≤ `max_tools_per_shell`（10，ADR-4）。

### 2.2 启动校验（fail-fast）

以下任一条件成立时，网关**拒绝启动**（退出码 2）：

1. `role` 不在 `worker_roles`；
2. 角色引用的 shell 未在 `shells` 登记；
3. 角色工具无法映射到任一已引用壳；
4. 角色工具含 `requires_mandate=true` 写工具（违反 ADR-9/H7 Worker 只读）。

### 2.3 壳级 vs 工具级

| 模式 | 配置条目 | `tools/list` |
|---|---|---|
| 直连壳（P0） | 每壳一条 | 壳的全部工具（可能含写工具，靠壳内拒绝） |
| 角色网关（P1） | **一条** | 精确等于角色白名单 |

## 3. 请求处理契约

| 方法 | 行为 |
|---|---|
| `initialize` | 返回 `protocolVersion`（当前 `2024-11-05`）+ `capabilities.tools` + `serverInfo.name = l0-gateway-<role>` |
| `notifications/initialized` | 无响应 |
| `ping` | 返回空 result |
| `tools/list` | 角色白名单工具定义 |
| `tools/call` | 见 §3.1 |
| 其他 | JSON-RPC `-32601` |

### 3.1 tools/call 判定顺序

1. `name` 不在角色白名单 → `ok=false, error_code=forbidden`（**优先于一切**）
2. `name` 属写工具 → `ok=false, error_code=forbidden`（Worker 只读纵深防御）
3. 解析 `tool → shell_id`；壳不可用 → `ok=false, error_code=unavailable, degraded=true`
4. 调壳；传输层异常 → `get_handle(force_new=True)` 重试一次（HC-6）
5. 重试仍失败 → `ok=false, error_code=shell_degraded, degraded=true`（HC-7）
6. 成功 → 原样透传壳信封，补 `meta.gateway_role` / `meta.shell_id` / `meta.trace_id`

> 主功能禁止 FAIL-OPEN：壳不可用与「无结果」必须可区分（B1）。

### 3.2 trace_id

- 入参：`params._meta.trace_id`（可选）
- 出参：信封 `meta.trace_id`；缺失时不伪造，保持空串
- 网关不覆盖壳已写入的 `trace_id`

## 4. 失败语义汇总

| 场景 | ok | error_code | degraded |
|---|---|---|---|
| 角色外工具 | false | `forbidden` | true |
| 写工具 | false | `forbidden` | true |
| 壳不可用 | false | `unavailable` | true |
| 壳调用传输失败（重试后） | false | `shell_degraded` | true |
| 壳业务失败 | 透传 | 透传 | 透传 |

## 5. 壳生命周期

- 复用 `34-前端应用训练系统/core/ShellHandleManager`：同 `shell_id` 单壳复用、被动健康检查、重拉上限 3 次。
- 本地 stdio 统一使用**网关自身解释器**（覆盖 registry 的 `python3`），避免多解释器/Windows 环境漂移。
- `transport=ssh-stdio` 且提供 `--ssh-host` 时走 `ssh_launcher`；未提供时按本地 stdio 拉起。
- 子壳 stdio 统一 `PYTHONIOENCODING=utf-8`（MCP 协议面）。

## 6. 接入方式

### 6.1 直接拉起

```bash
python3 mcp_shells/l0_gateway/server.py --role research
python3 mcp_shells/l0_gateway/server.py --role research --ssh-host dreambuddy-remote
```

### 6.2 生成宿主配置（推荐）

```bash
python3 "47-MCP管理系统/registry/scripts/mcpctl.py" profile --role research --gateway --out .mcp.json
```

产物（单条）：

```json
{
  "mcpServers": {
    "l0-research": {
      "command": "<python>",
      "args": ["<repo>/mcp_shells/l0_gateway/server.py", "--role", "research"],
      "env": {"PYTHONPATH": "<repo>", "PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

## 7. 与既有契约的关系

- **不改** 44 六 port、统一信封、Mandate、FAIL-OPEN 分型。
- **不改** registry schema；网关只读 `worker_roles` 与 `shells`。
- **不新增** 工具总数；角色暴露面 ≤10，注册表全局为软上限 80（G1-b，见 §8）。
- 45 契约评测后续应增加「网关角色投影」用例：`tools/list` 与角色白名单逐项一致、越权 `forbidden`。

## 8. G1 工具上限语义（✅ 已决）

**2026-11-08 用户确认 G1-b**：主约束 = 每壳 / 每角色 ≤10；全局 `max_total_tools` 由 40 改为**软上限 80**。

| 选项 | 内容 | 状态 |
|---|---|---|
| G1-a | 保持 40 硬顶，靠聚合/下线存量工具扩容 | 未采纳 |
| G1-b | 每壳/每角色 ≤10 + 全局软上限 80 | ✅ **已采纳** |
| G1-c | 移除全局上限，仅保留每壳/每角色 ≤10 | 未采纳 |

> 落点：`mcp_capabilities.yaml` `enums.max_total_tools=80`；`validate_mcp_registry.py` 默认值与错误语义同步；TECH §3.2 阈值表同步。网关按角色暴露（≤10）不受全局软上限影响。

## 9. 验收

| # | 判据 | 实测 |
|---|---|---|
| V1 | `tools/list` 精确等于角色白名单 | ✅ research 8 / verifier 5 / executor 7 |
| V2 | 角色外工具返回 `forbidden` | ✅ `record`（research） |
| V3 | 写工具进入角色 → 启动拒绝 | ✅ 单测覆盖 |
| V4 | 壳不可用 → `unavailable + degraded` | ✅ 单测覆盖 |
| V5 | 壳传输失败 → 重试 → `shell_degraded` | ✅ 复用 HC-6/HC-7 |
| V6 | 真实网关端到端 | ✅ verifier：`eval_analyze` 缺参 → `invalid` |
| V7 | 不改变既有壳契约测试 | ✅ `pytest mcp_shells/` 全绿 |