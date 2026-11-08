# TECHNICAL DESIGN — 51-OKX CLI 系统

> 版本：v0.1.0
> 日期：2026-11-07
> 范围：P1 骨架；P2 trade-exec MCP 接线为设计态

---

## 1. 运行时模型

```text
caller (trade-exec MCP / test / script)
        │
        ▼
OkxCliVenue (adapter.py)
        │  逻辑操作：get_ticker / get_balance / place_order ...
        ▼
CliRunner (runner.py)
        │  1. 白名单校验
        │  2. demo/live 门禁
        │  3. 注入 --profile / --demo / --json
        │  4. subprocess.run(shell=False, timeout)
        │  5. JSON 解析 + 错误分类
        │  6. 审计 JSONL
        ▼
okx CLI (Node, @okx_ai/okx-trade-cli)
        │
        ▼
OKX demo account（v0.1 唯一可达账户类型）
```

**进程边界：** 51 与 OKX CLI 之间是 subprocess；与 trade-exec MCP 之间是 Python 进程内调用（P2）。不引入网络代理或额外守护进程。

---

## 2. 配置解析

优先级：显式 `VenueConfig(...)` > 环境变量 > 默认值。

```text
OKX_VENUE_CLI              默认 okx
OKX_VENUE_PROFILE          默认 demo
OKX_VENUE_MODE             默认 demo
OKX_VENUE_AUTH             默认 api_key
OKX_VENUE_TIMEOUT_S        默认 30
OKX_VENUE_ALLOW_LIVE_READ  默认 0
OKX_VENUE_AUDIT_PATH       默认 runtime/audit/venue_calls.jsonl
```

`VenueConfig.__post_init__` 做强校验：

- mode ∈ {demo, live}
- auth ∈ {api_key, oauth}
- profile 与 mode 不得矛盾（见 SPEC §3.3）
- timeout > 0

---

## 3. 命令构造

最终 argv：

```text
[cli_path]
  + mode_flags()          # api_key: --profile <p>；oauth+demo: --demo；oauth+live: 无
  + operation_argv        # 由 adapter 构造的白名单命令
  + --json                # expect_json 时追加
```

示例：

```text
okx --profile demo market ticker BTC-USDT-SWAP --json
okx --profile demo account balance USDT --json
okx --profile demo swap place --instId BTC-USDT-SWAP --side buy --ordType market --sz 1 --tdMode cross --json
```

**调用方不能传** `--profile` / `--demo` / 凭证 flag；catalog 在构造前拒绝。

---

## 4. 错误模型

| 异常 | code | 触发 |
|---|---|---|
| `VenueConfigError` | `venue_config_error` | 配置矛盾 / 非法值 |
| `CommandNotAllowed` | `command_not_allowed` | 命中黑名单 / 非白名单动作 |
| `LiveTradingForbidden` | `live_trading_forbidden` | live 模式调用写方法 |
| `LiveReadForbidden` | `live_read_forbidden` | live 读未开开关 |
| `CliNotInstalled` | `cli_not_installed` | `FileNotFoundError` |
| `CliTimeout` | `cli_timeout` | `TimeoutExpired` |
| `CliAuthError` | `cli_auth_error` | 输出含 401 / session expired |
| `CliRateLimit` | `cli_rate_limit` | 输出含 429 / rate limit |
| `CliNonZeroExit` | `cli_nonzero_exit` | 其他非零退出 |
| `CliInvalidResponse` | `cli_invalid_json` | `--json` 输出无法解析 |

**失败语义：** 所有错误向上抛出；P2 MCP 层转换为 `degraded=true` + `error_code`，**不自动回退 paper**。

---

## 5. 结果归一化

### 5.1 Ticker

OKX CLI `--json` 返回列表；取第一条，映射：

```text
last / bidPx / askPx / open24h / high24h / low24h / vol24h / ts
→ last / bid / ask / bid_px / ask_px / open24h / high24h / low24h / vol24h / ts
```

同时保留 `raw`。

### 5.2 Balance

```text
account.totalEq
account.details[] → ccy == USDT
balance = availBal || availEq || cashBal || totalEq
```

返回 `{ok, balance, total_eq, ccy, details, raw}`。

### 5.3 Positions

```text
posSide == net → 按 pos 符号推导 long/short
posSide == long/short → 直接使用
pos = abs(raw pos)
```

返回与 trade-exec MCP 现有 `get_positions` 相同的字段：
`{inst_id, coin, pos_side, side, pos, avg_px, mark_px, upl}`。

### 5.4 Order

```text
sCode == "0" → ok=True
order_id = ordId
cl_ord_id = clOrdId
```

---

## 6. 审计

路径：`runtime/audit/venue_calls.jsonl`（可配置）。

每条记录：

```json
{
  "ts": "2026-11-07T12:00:00+00:00",
  "trace_id": "…",
  "operation": "place_order",
  "argv": ["okx", "--profile", "demo", "swap", "place", "..."],
  "profile": "demo",
  "mode": "demo",
  "ok": true,
  "error_code": "",
  "duration_ms": 123.4,
  "returncode": 0
}
```

- `--api-key` / `--secret` / `--secret-key` / `--passphrase` 的值替换为 `***`。
- 错误时只记录 `stderr` 前 500 字符。
- 使用 `threading.Lock` 保证多线程追加完整行。

---

## 7. P2：trade-exec MCP 接线设计

### 7.1 选择器

```python
adapter = build_order_adapter()  # 读 TRADE_EXEC_ORDER_ADAPTER
# paper → None（使用 OKXPaperLedger）
# okx-cli-demo → OkxCliVenue
```

### 7.2 MCP 修改点（设计）

| 位置 | 修改 |
|---|---|
| 模块级 | `_order_adapter = build_order_adapter()`（启动时一次） |
| `_handle_place_order` | 风控/定容后，若 adapter 非空 → `adapter.place_order(...)`；否则走 `_ledger` |
| `_handle_cancel_order` | 若 adapter 非空 → `adapter.cancel_order(...)` |
| `_handle_get_balance` | 若 adapter 非空 → `adapter.get_balance()` |
| `_handle_get_positions` | 若 adapter 非空 → `adapter.get_positions()` |
| 风控快照 | 若 adapter 非空，用 adapter 的 balance/positions 作为 `RiskContext` |
| 信封 | `meta.adapter` + `meta.venue = {profile, mode, trace_id}` |

### 7.3 不变量测试

- 默认 `paper`：现有 10 契约测试全绿。
- `okx-cli-demo`：mock CLI 返回固定 JSON，断言：
  - 风控拒绝时 **不调用** adapter
  - ExecutionRights 冲突时 **不调用** adapter
  - 定容钳位仍生效
  - adapter 异常 → `degraded=true`，不回退 paper
  - 信封含 `meta.adapter`

---

## 8. 6-TRADING legacy 守卫

| 文件 | 守卫 |
|---|---|
| `scripts/okx_cli.py` | 注入 `--profile`（修复原实现忽略 profile 的隐患）；live 写需 `OKX_VENUE_LEGACY_LIVE=1` |
| `scripts/dream_trade_exec.py` | `main()` 默认退出；需 `OKX_VENUE_LEGACY_LIVE=1` |
| `scripts/dream_strategy_pipeline.py` | `place_order` / `place_algo_order` 默认拒绝；读操作保留 |
| `bridge/api/trade_exec_api.py` | 下单端点仅 demo；live 余额查询保留 |

守卫原则：**默认拒绝，显式开关放行，放行时打印告警。**

---

## 9. 安全边界

- 不读取、不打印、不持久化 API Key / secret / passphrase。
- 不把 `okx` CLI 的 `config` / `auth` / `skills` / `upgrade` 暴露给调用方。
- 不执行 shell，argv 为列表，`shell=False`。
- 拒绝 shell 元字符，即使 `shell=False` 也做纵深防御。
- live 写无开关（不是默认关闭，而是代码路径不存在）。

---

## 10. 测试策略

| 层 | 方法 |
|---|---|
| 配置 | 纯 dataclass 单测，覆盖矛盾/默认/开关 |
| 白名单 | 表驱动：允许/拒绝/危险 flag/元字符 |
| Runner | 注入 fake `subprocess.run`，覆盖成功/非零/超时/未安装/坏 JSON |
| Adapter | 注入 fake runner，断言 argv 与归一化结果 |
| 审计 | 读取 JSONL 断言字段与脱敏 |
| P2 | 在 MCP 测试中 monkeypatch 选择器 + fake adapter |