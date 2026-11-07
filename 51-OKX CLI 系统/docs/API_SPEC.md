# API SPEC — 51-OKX CLI 系统

> 版本：v0.1.0
> 日期：2026-11-07
> 类型：Python Port API（非 MCP 工具面）

---

## 1. 公开符号

```python
from okx_venue import (
    VenueConfig,
    OkxCliVenue,
    CliRunner,
    AuditLogger,
    build_adapter,
    build_order_adapter,
    ORDER_ADAPTER_ENV,
)
```

---

## 2. VenueConfig

```python
@dataclass(frozen=True)
class VenueConfig:
    cli_path: str = "okx"
    profile: str = "demo"
    mode: str = "demo"          # demo | live
    auth: str = "api_key"       # api_key | oauth
    timeout_s: float = 30.0
    audit_path: Path = .../runtime/audit/venue_calls.jsonl
    allow_live_read: bool = False
```

方法：

| 方法/属性 | 返回 | 说明 |
|---|---|---|
| `from_env()` | `VenueConfig` | 从环境变量构造 |
| `read_allowed` | `bool` | demo 或显式 live 读开关 |
| `write_allowed` | `bool` | 仅 demo |
| `mode_flags()` | `list[str]` | `--profile <p>` / `--demo` / `[]` |
| `describe()` | `dict` | 可观测快照（不含密钥） |

---

## 3. OkxCliVenue

### 3.1 构造

```python
OkxCliVenue(
    config: VenueConfig | None = None,
    runner: CliRunner | None = None,
)
```

- `config=None` → `VenueConfig.from_env()`
- `runner=None` → `CliRunner(config)`

### 3.2 MarketPort

#### `get_ticker(inst_id) -> dict`

```json
{
  "ok": true,
  "inst_id": "BTC-USDT-SWAP",
  "last": 70000.0,
  "bid": 69999.0,
  "ask": 70001.0,
  "bid_px": 69999.0,
  "ask_px": 70001.0,
  "open24h": 69000.0,
  "high24h": 71000.0,
  "low24h": 68500.0,
  "vol24h": 12345.0,
  "ts": "1700000000000",
  "raw": {}
}
```

CLI：`okx <flags> market ticker <instId> --json`

#### `get_candles(inst_id, bar="1H", limit=100) -> dict`

```json
{"ok": true, "candles": [[ts, o, h, l, c, vol, ...]], "raw": []}
```

CLI：`okx <flags> market candles <instId> --bar <bar> --limit <n> --json`

### 3.3 AccountPort

#### `get_balance(ccy=None) -> dict`

```json
{
  "ok": true,
  "balance": 1000.0,
  "total_eq": 1234.5,
  "ccy": "USDT",
  "details": [],
  "raw": {}
}
```

- `balance` 取值顺序：`availBal` → `availEq` → `cashBal` → `totalEq`。
- CLI：`okx <flags> account balance [<ccy>] --json`

#### `get_positions(inst_id=None) -> dict`

```json
{
  "ok": true,
  "positions": [
    {
      "inst_id": "BTC-USDT-SWAP",
      "coin": "BTC",
      "pos_side": "long",
      "side": "long",
      "pos": 2.0,
      "avg_px": 70000.0,
      "mark_px": 70100.0,
      "upl": 200.0,
      "raw": {}
    }
  ],
  "count": 1
}
```

- CLI：`okx <flags> account positions [--instId <id>] --json`

### 3.4 OrderPort（demo only）

#### `place_order(inst_id, side, size, *, order_type="market", price=None, td_mode=None, pos_side=None) -> dict`

```json
{
  "ok": true,
  "order_id": "123456",
  "cl_ord_id": "c-1",
  "s_code": "0",
  "s_msg": "",
  "raw": {}
}
```

规则：

| 参数 | 规则 |
|---|---|
| `side` | `buy` / `sell` |
| `size` | `> 0` |
| `order_type` | `market` / `limit` |
| `price` | 限价单必填 |
| `td_mode` | spot 默认 `cash`；swap 默认 `cross` |
| `pos_side` | swap 可选 `long` / `short`；spot 忽略 |

CLI：

```text
# swap
okx <flags> swap place --instId <id> --side <buy|sell> --ordType <market|limit> --sz <n> --tdMode <cross|isolated> [--posSide <long|short>] [--px <price>] --json

# spot
okx <flags> spot place --instId <id> --side <buy|sell> --ordType <market|limit> --sz <n> --tdMode cash [--px <price>] --json
```

#### `cancel_order(inst_id, *, ord_id=None, cl_ord_id=None) -> dict`

CLI：

```text
okx <flags> swap cancel <instId> [--ordId <id>] [--clOrdId <id>] --json
okx <flags> spot cancel <instId> [--ordId <id>] [--clOrdId <id>] --json
```

#### `get_order(inst_id, *, ord_id=None, cl_ord_id=None) -> dict`

```json
{"ok": true, "order": {}, "raw": {}}
```

CLI：

```text
okx <flags> swap get --instId <id> [--ordId <id>] [--clOrdId <id>] --json
okx <flags> spot get --instId <id> [--ordId <id>] [--clOrdId <id>] --json
```

---

## 4. CliRunner

```python
CliRunner(
    config: VenueConfig,
    *,
    audit: AuditLogger | None = None,
    run: Callable | None = None,   # 测试注入
)
```

### `run(argv, *, operation, write=False, expect_json=True, timeout_s=None, trace_id=None) -> Any`

行为：

1. `validate_argv(argv, write=...)`
2. 写操作 + 非 demo → `LiveTradingForbidden`
3. 读操作 + live 未开开关 → `LiveReadForbidden`
4. 构造 argv：`[cli_path, *mode_flags, *argv, --json]`
5. `subprocess.run(..., shell=False, timeout=...)`
6. 非零退出 → 分类异常
7. JSON 解析失败 → `CliInvalidResponse`
8. 写审计
9. 返回解析结果

---

## 5. 选择器（P2）

```python
build_order_adapter(
    value: str | None = None,
    *,
    config: VenueConfig | None = None,
    runner: CliRunner | None = None,
) -> OkxCliVenue | None
```

| 输入 | 结果 |
|---|---|
| `paper` / 空 | `None`（使用 OKXPaperLedger） |
| `okx-cli-demo` | `OkxCliVenue`（要求 config.mode=demo） |
| `okx-cli-live` / `live` / 未知 | `VenueConfigError` |

环境变量：`TRADE_EXEC_ORDER_ADAPTER`。

---

## 6. 错误码

| code | 语义 |
|---|---|
| `venue_config_error` | 配置矛盾 |
| `command_not_allowed` | 非白名单命令 |
| `live_trading_forbidden` | live 写 |
| `live_read_forbidden` | live 读未开开关 |
| `cli_not_installed` | CLI 不存在 |
| `cli_timeout` | 超时 |
| `cli_auth_error` | 401 / session expired |
| `cli_rate_limit` | 429 |
| `cli_nonzero_exit` | 其他非零退出 |
| `cli_invalid_json` | JSON 解析失败 |
| `invalid_argument` | Port 参数非法 |

---

## 7. 使用示例

```python
from okx_venue import OkxCliVenue, VenueConfig

config = VenueConfig(
    cli_path="okx",
    profile="demo",
    mode="demo",
    timeout_s=15,
)
venue = OkxCliVenue(config)

ticker = venue.get_ticker("BTC-USDT-SWAP")
balance = venue.get_balance("USDT")
positions = venue.get_positions("BTC-USDT-SWAP")

if balance["balance"] > 100:
    result = venue.place_order(
        "BTC-USDT-SWAP",
        "buy",
        1,
        order_type="market",
        td_mode="cross",
    )
    print(result["order_id"])
```

**禁止：**

```python
# 不要构造 live 写；代码路径会直接抛 LiveTradingForbidden
venue = OkxCliVenue(VenueConfig(profile="okx-live", mode="live"))
venue.place_order(...)  # LiveTradingForbidden
```