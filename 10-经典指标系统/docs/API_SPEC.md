# 接口规格文档 — 经典指标系统

> **定位：** 全部公开 HTTP 接口与 Python API 的签名、参数、返回值、调用示例
> **版本：** v1.1 | **更新：** 2026-07-25

---

## 目录

- [1. 接口概览](#1-接口概览)
- [2. 认证方式](#2-认证方式)
- [3. 经典离场系统 HTTP API（classic_exit_system.py，端口 8095）](#3-经典离场系统-http-apiclassic_exit_systempy端口-8095)
- [4. ml_trade_service HTTP API（端口 8092）](#4-ml_trade_service-http-api端口-8092)
- [5. carry_service HTTP API（注册到 ml_trade_service，端口 8092）](#5-carry_service-http-api注册到-ml_trade_service端口-8092)
- [6. Python API（classic_exit_system.py）](#6-python-apiclassic_exit_systempy)
- [7. 错误码](#7-错误码)
- [8. 版本管理](#8-版本管理)

---

## 1. 接口概览

经典指标系统由三个 Flask 服务/模块组成，统一通过 HTTP/JSON 暴露能力。

### 1.1 经典离场系统（classic_exit_system.py）

独立可运行服务，默认监听 `0.0.0.0:8095`，提供持仓离场决策。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET  | `/health` | 健康检查，返回 L1 模式与杠杆口径状态 |
| POST | `/exit/evaluate` | 单笔持仓离场决策评估 |
| POST | `/exit/batch_evaluate` | 批量持仓离场评估 |
| POST | `/exit/features` | 仅计算离场特征（不决策） |
| GET  | `/exit/config` | 读取当前离场系统配置 |
| POST | `/exit/state/reset` | 重置运行时状态（风险闸门 / L2 滞回 / 冷却） |

### 1.2 ml_trade_service（端口 8092）

主交易服务，作为信号生成、Webhook 接收与执行下单的中枢。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET  | `/fundamental/flows/brief/latest` | **已退役**（410 module_retired） |
| GET  | `/fundamental/flows/regime/latest` | **已退役**（410 module_retired） |
| GET  | `/fundamental/narrative/brief/latest` | **已退役**（410 module_retired） |
| GET  | `/fundamental/narrative/registry/latest` | **已退役**（410 module_retired） |
| GET  | `/fundamental/narrative/history` | **已退役**（410 module_retired） |
| GET  | `/fundamental/narrative/automation` | **已退役**（410 module_retired） |
| POST | `/fundamental/narrative/automation/config` | **已退役**（410 module_retired） |
| POST | `/fundamental/narrative/automation/run` | **已退役**（410 module_retired） |
| GET  | `/fundamental/trading/latest` | **已退役**（410 module_retired） |
| GET  | `/fundamental/trading/automation` | **已退役**（410 module_retired） |
| POST | `/fundamental/trading/automation/config` | **已退役**（410 module_retired） |
| POST | `/fundamental/trading/automation/run` | **已退役**（410 module_retired） |
| GET  | `/fundamental/overview/latest` | **已退役**（410 module_retired） |
| POST | `/webhook/freqtrade` | 接收 Freqtrade 实例信号并按策略分配资金 |
| POST | `/webhook/tradingview` | 接收 TradingView 告警信号（含去重） |
| GET  | `/exit/features/latest` | 查询持仓离场特征快照（被 classic_exit_system 调用） |
| GET  | `/execution/hyperliquid/ping` | Hyperliquid 执行通道连通性探测 |
| POST | `/execution/hyperliquid/market_open` | Hyperliquid 永续市价开仓 |
| POST | `/execution/hyperliquid/market_close` | Hyperliquid 永续市价平仓 |
| POST | `/execution/hyperliquid/spot/market_open` | Hyperliquid 现货市价买入 |
| POST | `/execution/hyperliquid/spot/market_close` | Hyperliquid 现货市价卖出 |
| GET  | `/execution/hyperliquid/open_orders` | 查询 Hyperliquid 当前挂单 |
| GET  | `/execution/hyperliquid/user_state` | 查询 Hyperliquid 用户状态 |
| POST | `/execution/hyperliquid/set_leverage` | **已禁用**（403 hyperliquid_disabled） |
| POST | `/execution/hyperliquid/cancel` | **已禁用**（403 hyperliquid_disabled） |
| POST | `/execution/hyperliquid/cancel_all` | **已禁用**（403 hyperliquid_disabled） |
| POST | `/execution/hyperliquid/sync` | **已禁用**（403 hyperliquid_disabled） |
| GET  | `/execution/aster/ping` | Aster 执行通道连通性探测 |
| GET  | `/execution/aster/account_summary` | Aster 账户摘要 |
| POST | `/execution/aster/market_open` | Aster 永续市价开仓 |
| POST | `/execution/aster/market_close` | Aster 永续市价平仓 |
| POST | `/execution/aster/preflight` | Aster 开仓前置预检 |
| POST | `/execution/aster/spot/market_open` | Aster 现货市价买入 |
| POST | `/execution/aster/spot/market_close` | Aster 现货市价卖出 |
| POST | `/execution/aster/bulk_setup_margin_leverage` | Aster 批量设置保证金/杠杆 |
| POST | `/execution/aster/sync` | Aster 持仓同步 |
| POST | `/execution/pairs/btceth/market_open` | BTC/ETH 配对开仓 |
| POST | `/execution/pairs/btceth/market_close` | BTC/ETH 配对平仓 |
| POST | `/execution/pairs/btcalt/market_open` | BTC/山寨 配对开仓 |
| POST | `/execution/pairs/btcalt/market_close` | BTC/山寨 配对平仓 |
| GET  | `/three_screen/5m/research` | 5m 三屏研究数据 |

### 1.3 carry_service（注册到 ml_trade_service，端口 8092）

套利与资金费率路由模块，通过 `register_routes(app, svc)` 注入主服务；同时提供 `create_standalone_app()` 用于独立最小化部署（仅 `/health`）。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET  | `/carry/status` | 套利引擎整体状态（含资金时钟、PnL、配置、引擎快照） |
| GET  | `/carry/candidates` | 候选币种列表（Top-N，含缓存/刷新） |
| GET  | `/carry/acceptance` | 套利验收报告（按 venue 与 lookback_days） |
| GET  | `/carry/universe` | 套利币种宇宙（含强制刷新） |
| POST | `/carry/config` | 写入套利配置（需治理写权限） |
| POST | `/carry/hyperliquid/sync_open` | Hyperliquid 永续+现货同步开仓（套利对冲） |
| GET  | `/funding/schedule` | 资金费率时刻表（仅 Hyperliquid） |
| GET  | `/funding/rates` | 资金费率详情（含 APR、基差） |
| GET  | `/health` | 独立模式健康检查（standalone app） |

---

## 2. 认证方式

经典指标系统采用分层鉴权，不同接口适用不同策略：

| 鉴权方式 | 适用接口 | 说明 |
|----------|----------|------|
| 本地回环直通 | 大多数只读 GET | `_is_local_request()` 判定（127.0.0.1 / localhost），本地访问免鉴权 |
| 配置口令鉴权 | 受保护 GET（如 `/execution/hyperliquid/open_orders`） | 通过 `_config_auth_ok()` 校验请求头中的配置口令；本地回环自动通过 |
| 治理写权限 | `POST /carry/config`、`POST /carry/hyperliquid/sync_open`（execute=true） | `_governance_write_auth_ok()` 校验，未授权返回 `403 config_forbidden` |
| 执行守卫 | 所有 `execute=true` 的写入/下单接口 | `_check_execute_guard(data)` 校验幂等键、冷却、白名单等，失败返回 400/403 |
| TradingView Webhook Token | `POST /webhook/tradingview` | 环境变量 `TRADINGVIEW_WEBHOOK_TOKEN` 配置后，校验 `X-Webhook-Token` 请求头或 body 中的 `token` 字段 |
| 幂等性预检 | `POST /carry/hyperliquid/sync_open` | `_execute_idempotency_precheck(data)` 通过幂等键去重 |

> **说明：** classic_exit_system.py 的 `/exit/*` 接口默认不鉴权，建议仅在内网/本地暴露；如需远程访问应通过反向代理加层。

---

## 3. 经典离场系统 HTTP API（classic_exit_system.py，端口 8095）

启动方式：`python classic_exit_system.py serve --host 0.0.0.0 --port 8095 --api-base http://127.0.0.1:8092`

### 3.1 GET /health

健康检查。

**响应：**

```json
{
  "ok": true,
  "service": "classic_exit_system",
  "l1_mode": "heuristic",
  "leverage_applied": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| ok | bool | 固定 true |
| service | str | 固定 `"classic_exit_system"` |
| l1_mode | str | L1 评估模式：`heuristic` / `mrd` / `ml` |
| leverage_applied | bool | 阈值是否含杠杆口径 |

---

### 3.2 POST /exit/evaluate

单笔持仓离场决策评估。

**请求体：**

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| coin / symbol | str | "" | 币种标识 |
| side | str | "long" | 持仓方向（`long`/`short`） |
| entry_price | float | 0 | 开仓均价 |
| current_price | float | 0 | 当前价 |
| position_age_sec / age_sec | float | 0 | 持仓时长（秒） |
| unrealized_pnl_pct | float | 0 | 未实现收益率（不含杠杆） |
| leverage | float | 1.0 | 杠杆倍数 |
| atr_pct | float | 0.02 | ATR 占价比率 |
| mfe_pnl_pct | float | 0 | 最大有利偏移 |
| max_dd_pct | float | 0 | 最大回撤 |
| entry_ts / entry_time | int | 0 | 开仓时间戳（秒或毫秒） |
| trailing_armed | bool | false | 跟踪止损是否已 armed |
| trailing_stop_price | float | 0 | 当前跟踪止损价 |
| liq_price | float | 0 | 强平价 |
| candles_1h / candles | list | [] | 1H K线数据（[{c,h,l,o,v,ts}, ...]） |
| regime | str | "trend" | 市场状态（`trend`/`chop`） |
| now_ts | float | 当前时间 | 评估时间戳 |
| metadata | object | {} | 附加元数据 |

**响应（成功）：**

```json
{
  "ok": true,
  "decision": {
    "action": "hold",
    "priority": "p3",
    "reason": "",
    "confidence": 0.0,
    "reduce_frac": 0.0,
    "suggested_price": 100.0,
    "l0_triggered": false,
    "l0_reason": "",
    "l1_hold_risk": 0.5,
    "l1_hold_value": 0.5,
    "tb_sl_hit": false,
    "tb_tp_hit": false,
    "tb_time_hit": false,
    "trailing_triggered": false,
    "trailing_stop_price": 0.0,
    "new_trailing_stop": 0.0,
    "tstp_triggered": false,
    "tstp_stage": 0,
    "new_tp_price": 0.0,
    "new_tp_pct": 0.0,
    "gate_passed": true,
    "gate_reason": "",
    "source": "local",
    "features": {
      "hold_risk": 0.5,
      "hold_value": 0.5,
      "mrd_score": 0.0,
      "p_mrd": 0.5,
      "dd": 0.0,
      "rsi": 50.0,
      "adx": 25.0,
      "atr_pct": 0.02,
      "trend_shape": "chop",
      "trend_w_dir": 0,
      "trend_d_dir": 0,
      "mom_dir": 0,
      "vol_dir": 0,
      "pot_dir": 0,
      "flow_dir": 0,
      "risk_budget_penalty": 0.0
    }
  }
}
```

**响应（失败）：** HTTP 400，`{"ok": false, "error": "<异常信息>"}`

**action 取值：** `close` | `reduce` | `hold` | `raise_tp`

---

### 3.3 POST /exit/batch_evaluate

批量持仓评估。对每条持仓自动选择 `evaluate_full`（含 entry_price）或 `evaluate`（API 优先）路径。

**请求体：**

```json
{
  "positions": [
    {"coin": "BTC", "side": "long", "entry_price": 60000, "current_price": 67000,
     "position_age_sec": 3600, "unrealized_pnl_pct": 0.10, "leverage": 2.0, "regime": "trend"}
  ],
  "candles_map": {"BTC": [{"c": 67000, "h": 67500, "l": 66500, "o": 67200, "v": 100, "ts": "..."}]}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| positions | list[dict] | 持仓列表，字段同 `/exit/evaluate` 请求体 |
| candles_map | dict[str, list] | 可选，币种 → K线列表 |

**响应：**

```json
{
  "ok": true,
  "results": {
    "BTC": { "action": "hold", "priority": "p3", "reason": "", ... }
  }
}
```

`results` 的值为 `/exit/evaluate` 中 `decision` 对象的映射。

---

### 3.4 POST /exit/features

仅计算离场特征，不做决策。请求体字段同 `/exit/evaluate`。

**响应（成功）：**

```json
{
  "ok": true,
  "features": {
    "hold_risk": 0.5,
    "hold_value": 0.5,
    "mrd_score": 0.0,
    "p_mrd": 0.5,
    "dd": 0.0,
    "rsi": 50.0,
    "adx": 25.0,
    "atr_pct": 0.02,
    "trend_shape": "chop",
    "trend_w_dir": 0,
    "trend_d_dir": 0,
    "mom_dir": 0,
    "vol_dir": 0,
    "pot_dir": 0,
    "flow_dir": 0,
    "risk_budget_penalty": 0.0
  }
}
```

**响应（失败）：** HTTP 400，`{"ok": false, "error": "<异常信息>"}`

---

### 3.5 GET /exit/config

读取当前离场系统配置（关键字段子集）。

**响应：**

```json
{
  "ok": true,
  "config": {
    "l1_mode": "heuristic",
    "apply_leverage_to_thresholds": true,
    "l0_max_hold_sec": 86400,
    "l0_max_loss_pct": -0.05,
    "l2_close_threshold": 0.75,
    "l2_reduce_threshold": 0.55,
    "tb_enabled": true,
    "tstp_enabled": true,
    "trailing_enabled": true,
    "gate_enabled": false,
    "risk_budget_enabled": true
  }
}
```

---

### 3.6 POST /exit/state/reset

重置运行时状态（风险闸门 / L2 滞回 / 冷却 / 快照历史）。

**请求体：**

| 字段 | 类型 | 说明 |
|------|------|------|
| coin | str | 可选；指定币种则只重置该币种，省略则重置全部 |

**响应：**

```json
{"ok": true, "message": "State reset for BTC"}
```

省略 `coin` 时 `message` 为 `"State reset for all"`。

---

## 4. ml_trade_service HTTP API（端口 8092）

启动方式：`python ml_trade_service.py`，监听地址由 `LISTEN_HOST`（默认 127.0.0.1）、`PORT` / `ML_TRADE_SERVICE_PORT`（默认 8092）控制。

### 4.1 基本面模块（已退役）

下列路径统一返回 HTTP 410：

```
GET  /fundamental/flows/brief/latest
GET  /fundamental/flows/regime/latest
GET  /fundamental/narrative/brief/latest
GET  /fundamental/narrative/registry/latest
GET  /fundamental/narrative/history
GET  /fundamental/narrative/automation
POST /fundamental/narrative/automation/config
POST /fundamental/narrative/automation/run
GET  /fundamental/trading/latest
GET  /fundamental/trading/automation
POST /fundamental/trading/automation/config
POST /fundamental/trading/automation/run
GET  /fundamental/overview/latest
```

**响应体：**

```json
{
  "ok": false,
  "error": "module_retired",
  "module": "fundamental_non_news",
  "path": "/fundamental/flows/brief/latest",
  "ts": 1721900000000
}
```

> 注：`/fundamental/news/*` 不在退役列表中，仍按各自定义返回。

---

### 4.2 POST /webhook/freqtrade

聚合 Webhook 接口：接收所有 Freqtrade 实例的信号，按策略分配资金。

**请求体：**

| 字段 | 类型 | 说明 |
|------|------|------|
| strategy | str | 策略名（必填） |
| pair | str | 交易对（必填，如 `BTC/USDT`） |
| type | str | 信号类型（`entry` / `exit` 等） |
| side | str | 方向（`long`/`short`，默认 `long`） |
| notional_usdc / notional_usdt / notional / size_usdc / size | float | 名义本金（按顺序优先取，缺省用 `entry_fixed_notional_usdc`） |
| execute | bool | 是否真实下单（默认 false） |
| 其他 | any | 透传给策略执行器 |

**资金分配：** `notional = base_notional × STRATEGY_ALLOCATION[strategy] / 100`（未配置时取 base_notional）。

**响应：** 返回策略执行结果，缺失 strategy/pair 时返回 `400 {"ok": false, "error": "missing_strategy_or_pair"}`；`execute=true` 时先经 `_check_execute_guard` 守卫校验。

**调用示例：**

```bash
curl -X POST http://127.0.0.1:8092/webhook/freqtrade \
  -H "Content-Type: application/json" \
  -d '{"strategy":"V15_CLASSIC","pair":"BTC/USDT","type":"entry","side":"long","notional_usdc":200,"execute":false}'
```

---

### 4.3 POST /webhook/tradingview

接收 TradingView 告警信号，含去重与方向归一化。

**请求体：**

| 字段 | 类型 | 说明 |
|------|------|------|
| symbol / ticker / pair | str | 标的（自动 upper） |
| dir / direction / side / signal | str | 方向原始值，归一化为 `long`/`short`/`flat` |
| sig_id / id / alert_id / alertId | str | 信号 ID（用于去重，命中上次 ID 返回 `dedup: true`） |
| ts / time | int | 信号时间戳（秒或毫秒，自动适配） |
| token | str | Webhook 令牌（与请求头 `X-Webhook-Token` 二选一） |

**鉴权：** 若环境变量 `TRADINGVIEW_WEBHOOK_TOKEN` 非空，则必须匹配请求头 `X-Webhook-Token` 或 body 中 `token`，否则返回 `403 {"ok": false, "error": "webhook_token_invalid"}`。

**响应：**

```json
{"ok": true, "stored": true, "dedup": false, "sig_id": "...", "state": {"sig_id": "...", "symbol": "BTCUSDT", "dir": "long", "ts": 1721900000000, "recv_ms": 1721900000000}}
```

重复信号返回 `{"ok": true, "stored": false, "dedup": true, "sig_id": "...", "state": {...}}`。

---

### 4.4 GET /exit/features/latest

查询持仓离场特征快照。被 `ClassicExitSystem.evaluate_api()` 调用，也可独立使用。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| pairs | str | 当前所有 open positions | 逗号分隔的交易对列表（如 `BTC-PERP,ETH-PERP`） |
| include_macro | bool | false | 是否附带宏观资金流/趋势/能量快照 |

**响应：**

```json
{
  "ok": true,
  "ts": 1721900000000,
  "items": [
    {
      "pair": "BTC-PERP",
      "hold_risk_score": 0.42,
      "hold_value_score": 0.61,
      "mrd_score": 0.0,
      "macro_mrd_score": 0.0,
      "p_mrd": 0.5,
      "macro_p_mrd": 0.5,
      "dd": 0.05,
      "pos_max_drawdown_since_entry": 0.05,
      "rsi": 52.3,
      "rsi_d": 52.3,
      "adx": 22.0,
      "adx_h": 22.0,
      "ema_short_dist": 0.01
    }
  ]
}
```

`include_macro=true` 时额外返回 `macro_flow_snap`、`macro_btc_trend_snap`、`macro_eth_trend_snap`、`macro_btc_energy_snap`、`macro_eth_energy_snap` 字段。

---

### 4.5 执行接口（/execution/*）

执行接口统一遵循：

- **执行守卫：** 所有 `execute=true` 的接口先经 `_check_execute_guard(data)`，校验幂等键、冷却、白名单等。
- **幂等：** 通过 `idempotency_key` 字段去重。
- **沙箱：** 沙箱模式下 `execute=true` 仅模拟，不真实下单。

#### 4.5.1 Hyperliquid 通道

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/execution/hyperliquid/ping` | 连通性探测，返回 `_hl_ping_payload()` |
| POST | `/execution/hyperliquid/market_open` | 永续市价开仓 |
| POST | `/execution/hyperliquid/market_close` | 永续市价平仓 |
| POST | `/execution/hyperliquid/spot/market_open` | 现货市价买入 |
| POST | `/execution/hyperliquid/spot/market_close` | 现货市价卖出 |
| GET  | `/execution/hyperliquid/open_orders` | 当前挂单（需本地或配置鉴权） |
| GET  | `/execution/hyperliquid/user_state` | 用户状态（需本地或配置鉴权） |
| POST | `/execution/hyperliquid/set_leverage` | **已禁用** → `403 {"ok": false, "error": "hyperliquid_disabled"}` |
| POST | `/execution/hyperliquid/cancel` | **已禁用** → 403 |
| POST | `/execution/hyperliquid/cancel_all` | **已禁用** → 403 |
| POST | `/execution/hyperliquid/sync` | **已禁用** → 403 |

#### 4.5.2 Aster 通道

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/execution/aster/ping` | 连通性探测，返回 `_aster_ping_payload()` |
| GET  | `/execution/aster/account_summary` | 账户摘要，查询参数 `owner` 可选 |
| POST | `/execution/aster/market_open` | 永续市价开仓 |
| POST | `/execution/aster/market_close` | 永续市价平仓 |
| POST | `/execution/aster/preflight` | 开仓前置预检 |
| POST | `/execution/aster/spot/market_open` | 现货市价买入 |
| POST | `/execution/aster/spot/market_close` | 现货市价卖出 |
| POST | `/execution/aster/bulk_setup_margin_leverage` | 批量设置保证金模式与杠杆 |
| POST | `/execution/aster/sync` | 持仓同步 |

`/execution/aster/bulk_setup_margin_leverage` 请求体关键字段：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| execute | bool | false | 是否真实执行 |
| owner | str | "quant" | `quant`/`strategy`/`carry` |
| isolated | bool | true | 逐仓模式 |
| leverage | int | 5 | 杠杆倍数 |

#### 4.5.3 配对执行

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/execution/pairs/btceth/market_open` | BTC/ETH 配对开仓 |
| POST | `/execution/pairs/btceth/market_close` | BTC/ETH 配对平仓 |
| POST | `/execution/pairs/btcalt/market_open` | BTC/山寨 配对开仓 |
| POST | `/execution/pairs/btcalt/market_close` | BTC/山寨 配对平仓 |

---

## 5. carry_service HTTP API（注册到 ml_trade_service，端口 8092）

`carry_service.py` 通过 `register_routes(app, svc)` 将下列路由注入 ml_trade_service 的 Flask app，由主服务统一暴露在 8092 端口。`create_standalone_app()` 仅提供 `/health` 用于独立最小化部署。

### 5.1 GET /carry/status

套利引擎整体状态。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| include_positions | bool | false | 是否返回当前持仓明细 |
| include_events | bool | false | 是否返回最近事件流 |
| events_n | int | 50 | 事件流条数（1-200） |

**响应（节选）：**

```json
{
  "ok": true,
  "ts": 1721900000000,
  "venue": "hyperliquid",
  "enabled": true,
  "enabled_effective": true,
  "live_enabled": false,
  "sandbox": true,
  "execute_allowed": true,
  "execute_effective": false,
  "next_funding_ts": 1721900800000,
  "minutes_to_funding": 13.33,
  "window_state": "OPEN",
  "base_ts": 1721900800000,
  "minutes_to_base": 13.33,
  "funding_pnl": 1.23,
  "price_move_pnl": -0.45,
  "costs": 0.12,
  "pnl": { "...": "..." },
  "funding_income": {"ok": true},
  "profile": "default",
  "profiles": {},
  "regime": {},
  "gate": {"enabled_effective": true},
  "cfg_base": {"carry_trade_enabled": true},
  "cfg_effective": {"carry_trade_mode": "perp"},
  "status": {"step_raw": "idle", "step": "idle", "step_ts": 1721900000000, "last_error": null},
  "engine": {"tick_ts": 1721900000000, "pool_ts": 1721900000000, "pool_n": 12, "pool_refreshing": false, "positions_count": 0, "open_window": true},
  "carry_universe": {"ts": 1721900000000, "venue": "hyperliquid", "n": 30, "last_error": null},
  "active_position": null,
  "positions": [],
  "events": {"n": 0, "items": []}
}
```

---

### 5.2 GET /carry/candidates

候选币种列表（Top-N）。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| n | int | `carry_trade_candidates_top_n` 或 10 | 返回数量（1-200） |
| refresh | bool | false | 是否触发候选池刷新 |

**响应（节选）：**

```json
{
  "ok": true,
  "ts": 1721900000000,
  "venue": "hyperliquid",
  "n": 10,
  "minutes_to_funding": 13.33,
  "window_state": "OPEN",
  "profile": "default",
  "regime": {},
  "gate": {},
  "cfg_effective": {},
  "recommended_open_top_k": 3,
  "candidates": [{"coin": "BTC", "funding_rate": 0.0001, "...": "..."}],
  "cache": {"ok": true, "venue": "hyperliquid", "pool_ts": 1721900000000, "age_ms": 1200, "pool_n": 30},
  "pool": {"ok": true, "venue": "hyperliquid", "pool_ts": 1721900000000, "pool_n": 30, "refreshing": false},
  "universe": {"ok": true, "ts": 1721900000000, "venue": "hyperliquid", "n": 30, "last_error": null}
}
```

> 当 `window_state == "WAIT"` 时，`n` 会被自动限制到 8 以内。

---

### 5.3 GET /carry/acceptance

套利验收报告。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| venue | str | hyperliquid | 仅支持 `hyperliquid`/`hl`，其他返回 `400 venue_hl_only` |
| lookback_days | int | 90 | 回看天数（7-3650） |

**响应：** 直接透传 `svc._carry_acceptance_report()` 返回值。

---

### 5.4 GET /carry/universe

套利币种宇宙。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| refresh | bool | false | 是否强制刷新宇宙 |

**响应（节选）：**

```json
{
  "ok": true,
  "ts": 1721900000000,
  "venue": "hyperliquid",
  "state": {
    "ts": 1721900000000,
    "venue": "hyperliquid",
    "n": 30,
    "coins": ["BTC", "ETH", "..."],
    "metadata": {},
    "last_error": null
  },
  "cfg_effective": {"carry_universe_min_vol": 1000000},
  "refresh": {"ok": true}
}
```

---

### 5.5 POST /carry/config

写入套利配置（仅接受 `carry_trade_*` / `carry_universe_*` 前缀且已存在于 CONFIG 的键）。

**鉴权：** 需治理写权限，未授权返回 `403 {"ok": false, "error": "config_forbidden"}`。

**请求体示例：**

```json
{"carry_trade_enabled": true, "carry_trade_mode": "perp", "carry_trade_venue": "hyperliquid"}
```

**响应：**

```json
{
  "ok": true,
  "changed": {"carry_trade_enabled": true},
  "config": {"carry_trade_enabled": true, "carry_trade_mode": "perp", "...": "..."}
}
```

`carry_trade_venue` 仅接受 `hyperliquid`/`hl`，其他返回 `400 {"ok": false, "error": "carry_trade_venue_hl_only", "got": "<value>"}`。

---

### 5.6 POST /carry/hyperliquid/sync_open

Hyperliquid 永续+现货同步开仓（套利对冲）。

**请求体：**

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| coin / pair | str | "BTC" | 币种或交易对 |
| perp_notional_usdc / notional_perp_usdc | float | 100.0 | 永续名义本金（必须 > 0） |
| spot_notional_usdc / notional_spot_usdc | float | 100.0 | 现货名义本金（必须 > 0） |
| leverage | int | `hl_default_leverage` 或 3 | 杠杆（1-100） |
| execute | bool | false | 是否真实执行；`true` 时需治理写权限 |
| idempotency_key | str | — | 幂等键 |

**响应：** 包含 `leverage`、`perp`、`spot` 三个子对象，结构由 `svc` 内部执行器决定。失败时返回 `400 invalid_perp_notional` / `400 invalid_spot_notional` / `403 config_forbidden` 等。

---

### 5.7 GET /funding/schedule

资金费率时刻表（仅 Hyperliquid）。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| venue | str | hyperliquid | 仅支持 `hyperliquid`/`hl` |
| n | int | 8 | 返回时刻数（1-48） |

**响应：**

```json
{
  "ok": true,
  "ts": 1721900000000,
  "venue": "hyperliquid",
  "period_ms": 28800000,
  "schedule": [1721900800000, 1721929600000, 1721958400000]
}
```

---

### 5.8 GET /funding/rates

资金费率详情。

**查询参数：**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| venue | str | hyperliquid | 仅支持 `hyperliquid`/`hl` |
| limit | int | 0 | 限制返回数量（0-500；0=不限） |
| key | str | "pair" | 返回字典键模式：`pair` / `coin` |

**响应（节选）：**

```json
{
  "ok": true,
  "ts": 1721900000000,
  "venue": "hyperliquid",
  "next_funding_ts": 1721900800000,
  "minutes_to_funding": 13.33,
  "period_ms": 28800000,
  "key": "pair",
  "coins_order": ["BTC", "ETH"],
  "rates_by_coin": {
    "BTC": {
      "funding_rate": 0.0001,
      "funding_period_ms": 28800000,
      "funding_rate_1h": 0.0000125,
      "funding_rate_apr": 0.1095,
      "next_funding_ts": 1721900800000,
      "minutes_to_funding": 13.33,
      "mark_price": 67000.0,
      "index_price": 66950.0,
      "basis_bps": 7.47,
      "ts": 1721900000000
    }
  },
  "rates_by_pair": {"BTC-PERP": {"...": "同上"}}
}
```

---

### 5.9 GET /health（standalone）

独立模式健康检查（仅 `create_standalone_app()` 创建的 app 提供）。

**响应：**

```json
{"ok": true, "ts": 1721900000000}
```

---

## 6. Python API（classic_exit_system.py）

### 6.1 类型与枚举

```python
class ExitAction(str, Enum):
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"   # 提高止盈价（强反弹时让利润奔跑）

class ExitPriority(str, Enum):
    P0_L0_HARD = "p0_l0"
    P1_VALUE_RISK = "p1"
    P2_TRIPLE_BARRIER = "p2"
    P3_BEHAVIORAL = "p3"

class TrendShape(str, Enum):
    UP_STRONG = "up_strong"
    UP_REVERSAL = "up_reversal"
    DOWN_STRONG = "down_strong"
    DOWN_REVERSAL = "down_reversal"
    CHOP = "chop"

class L1Mode(str, Enum):
    HEURISTIC = "heuristic"
    MRD = "mrd"
    ML = "ml"
```

### 6.2 PositionState（输入）

```python
@dataclass
class PositionState:
    coin: str = ""
    side: str = "long"               # "long" / "short"
    entry_price: float = 0.0
    current_price: float = 0.0
    position_age_sec: float = 0.0
    unrealized_pnl_pct: float = 0.0  # 不含杠杆
    leverage: float = 1.0
    atr_pct: float = 0.02
    mfe_pnl_pct: float = 0.0
    max_dd_pct: float = 0.0
    entry_ts: int = 0
    trailing_armed: bool = False
    trailing_stop_price: float = 0.0
    liq_price: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def pnl_eff(self) -> float: ...      # 含杠杆收益率 = unrealized_pnl_pct × leverage

    @property
    def is_long(self) -> bool: ...
```

### 6.3 ExitDecision（输出）

```python
@dataclass
class ExitDecision:
    action: ExitAction = ExitAction.HOLD
    priority: ExitPriority = ExitPriority.P3_BEHAVIORAL
    reason: str = ""
    confidence: float = 0.0
    reduce_frac: float = 0.0
    suggested_price: float = 0.0

    l0_triggered: bool = False
    l0_reason: str = ""

    l1_hold_risk: float = 0.5
    l1_hold_value: float = 0.5

    tb_sl_hit: bool = False
    tb_tp_hit: bool = False
    tb_time_hit: bool = False

    trailing_triggered: bool = False
    trailing_stop_price: float = 0.0
    new_trailing_stop: float = 0.0

    tstp_triggered: bool = False
    tstp_stage: int = 0

    # RAISE_TP 相关
    new_tp_price: float = 0.0
    new_tp_pct: float = 0.0

    gate_passed: bool = True
    gate_reason: str = ""

    features: Optional[ExitFeatureSet] = None
    source: str = "local"
```

### 6.4 ExitConfig

```python
@dataclass
class ExitConfig:
    apply_leverage_to_thresholds: bool = True
    l1_mode: L1Mode = L1Mode.HEURISTIC

    # L0 硬退出
    l0_max_hold_sec: int = 86400
    l0_max_loss_pct: float = -0.05
    l0_liq_buffer_enabled: bool = True
    l0_liq_buffer_pct: float = 0.005
    l0_weekly_reversal_enabled: bool = True
    l0_weekly_reversal_confirm_weeks: int = 2
    l0_weekly_reversal_adx_min: float = 20.0
    l0_risk_gate_enabled: bool = True
    l0_risk_gate_cooldown_min: float = 30.0
    l0_risk_gate_long_thr: float = 0.50
    l0_risk_gate_short_thr: float = 0.40
    l0_risk_gate_confirm_n: int = 2
    l0_risk_gate_reduce_frac: float = 0.5

    # L1/L2 价值风险
    l1_enabled: bool = True
    l2_close_threshold: float = 0.75
    l2_reduce_threshold: float = 0.55
    l2_deadband: float = 0.03
    l2_confirm_n: int = 1

    # Triple Barrier
    tb_enabled: bool = True
    tb_sl_atr_mult: float = 1.5
    tb_tp_atr_mult: float = 3.0
    tb_sl_min_pct: float = 0.02
    tb_tp_min_pct: float = 0.04
    tb_time_barrier_sec: int = 28800

    # TSTP 时间止盈
    tstp_enabled: bool = True
    tstp_trend_plan: Dict[int, Tuple[float, float, str]] = field(default_factory=...)
    tstp_chop_plan: Dict[int, Tuple[float, float, str]] = field(default_factory=...)

    # RAISE_TP
    tstp_raise_tp_enabled: bool = True
    tstp_raise_tp_value_thr: float = 0.65
    tstp_raise_tp_atr_mult: float = 4.0
    l2_raise_tp_enabled: bool = True
    l2_raise_tp_value_thr: float = 0.65
    l2_raise_tp_risk_thr: float = 0.30
    l2_raise_tp_atr_mult: float = 4.0

    # 跟踪止损
    trailing_enabled: bool = True
    trailing_arm_profit_pct: float = 0.06
    trailing_retrace_pct: float = 0.03

    # 冷却/滞回
    inflight_cooldown_sec: int = 90
    cooldown_after_close_sec: int = 3600
    cooldown_after_reduce_sec: int = 1800
    post_close_freeze_hours: float = 2.0

    # 成本缓冲
    fee_roundtrip_pct: float = 0.001
    slippage_pct: float = 0.001
    safety_margin_pct: float = 0.0005
    funding_buffer_enabled: bool = True

    @classmethod
    def from_env(cls) -> "ExitConfig": ...
```

环境变量映射（节选）：`EXIT_L0_MAX_HOLD_SEC`、`EXIT_L0_MAX_LOSS_PCT`、`EXIT_L0_WEEKLY_REVERSAL`、`EXIT_L0_RISK_GATE_ENABLED`、`EXIT_L1_ENABLED`、`EXIT_L2_CLOSE_THR`、`EXIT_L2_REDUCE_THR`、`EXIT_TB_ENABLED`、`EXIT_TB_SL_ATR_MULT`、`EXIT_TB_TP_ATR_MULT`、`EXIT_TSTP_ENABLED`、`EXIT_TRAILING_ENABLED`、`EXIT_TRAILING_ARM_PCT`、`EXIT_TRAILING_RETRACE_PCT`、`EXIT_GATE_ENABLED`、`EXIT_INFLIGHT_COOLDOWN_SEC`、`EXIT_APPLY_LEVERAGE`、`EXIT_RISK_BUDGET_ENABLED`、`EXIT_L1_MODE`。

### 6.5 ClassicExitSystem 类

```python
class ClassicExitSystem:
    def __init__(
        self,
        config: Optional[ExitConfig] = None,
        api_base: str = "http://127.0.0.1:8092",
        api_timeout: float = 5.0,
    ): ...
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| config | ExitConfig \| None | None | 配置对象；None 时调用 `ExitConfig.from_env()` |
| api_base | str | `http://127.0.0.1:8092` | ml_trade_service API 地址（用于 evaluate_api 模式） |
| api_timeout | float | 5.0 | API 调用超时（秒） |

#### 6.5.1 evaluate_full

```python
def evaluate_full(
    self,
    pos: PositionState,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",
    now_ts: Optional[float] = None,
) -> ExitDecision
```

完整离场评估，按 P0 → P2 → P3 → P1 顺序逐级检查。

#### 6.5.2 evaluate

```python
def evaluate(
    self,
    coin: str,
    current_price: float,
    position_action: str,
    candles_1h: Optional[List[Dict]] = None,
) -> ExitDecision
```

便捷接口（优先 API，失败回退本地）。`position_action` 取 `LONG`/`BUY` 视为 long，其他视为 short。

#### 6.5.3 batch_evaluate

```python
def batch_evaluate(
    self,
    positions: List[Dict],
    candles_map: Optional[Dict[str, List[Dict]]] = None,
) -> Dict[str, ExitDecision]
```

批量评估。当 pos_info 含 `entry_price` 且 > 0 时走 `evaluate_full`，否则回退到 `evaluate`。

#### 6.5.4 其他方法

```python
def is_api_available(self) -> bool             # 检查 ml_trade_service /health 可达
def reset_state(self, coin: Optional[str] = None) -> None  # 重置运行时状态
```

### 6.6 模块级便捷函数

```python
def get_default_system() -> ClassicExitSystem

def evaluate_exit(
    coin: str,
    current_price: float,
    position_action: str,
    candles_1h: Optional[List[Dict]] = None,
) -> ExitDecision

def evaluate_exit_full(
    pos: PositionState,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",
) -> ExitDecision

def batch_evaluate_exit(
    positions: List[Dict],
    candles_map: Optional[Dict[str, List[Dict]]] = None,
) -> Dict[str, ExitDecision]

def create_app(system: Optional[ClassicExitSystem] = None) -> Flask
```

**调用示例：**

```python
from classic_exit_system import (
    ClassicExitSystem, PositionState, evaluate_exit_full, get_default_system
)

# 1) 直接使用默认实例
pos = PositionState(
    coin="SOL", side="long",
    entry_price=100.0, current_price=110.0,
    position_age_sec=3600,
    unrealized_pnl_pct=0.10, leverage=2.0, atr_pct=0.03,
)
decision = evaluate_exit_full(pos, candles_1h=[{"c": 110, "h": 112, "l": 109, "o": 109, "v": 100}], regime="trend")
print(decision.action.value, decision.reason)

# 2) 自定义配置 + API 模式
system = ClassicExitSystem(api_base="http://127.0.0.1:8092")
d = system.evaluate("BTC", 67000.0, "LONG")

# 3) 启动 HTTP 服务
app = create_app(get_default_system())
app.run(host="0.0.0.0", port=8095)
```

---

## 7. 错误码

HTTP 状态码与业务错误码统一定义如下：

| HTTP | error 字段 | 触发场景 | 说明 |
|------|-----------|----------|------|
| 200 | — | 正常 | 业务成功 |
| 400 | `<异常信息>` | `/exit/evaluate`、`/exit/features` 解析失败 | 请求参数异常或计算异常 |
| 400 | `missing_strategy_or_pair` | `/webhook/freqtrade` | 缺失 strategy 或 pair |
| 400 | `bad_payload` | `/carry/config`、`/carry/hyperliquid/sync_open` | 请求体非对象 |
| 400 | `venue_hl_only` | `/carry/acceptance`、`/funding/*` | venue 非 hyperliquid |
| 400 | `carry_trade_venue_hl_only` | `/carry/config` | carry_trade_venue 非 hyperliquid |
| 400 | `invalid_perp_notional` | `/carry/hyperliquid/sync_open` | 永续名义本金 ≤ 0 或非有限 |
| 400 | `invalid_spot_notional` | `/carry/hyperliquid/sync_open` | 现货名义本金 ≤ 0 或非有限 |
| 403 | `webhook_token_invalid` | `/webhook/tradingview` | TradingView Webhook 令牌不匹配 |
| 403 | `config_forbidden` | `/carry/config`、`/carry/hyperliquid/sync_open`（execute=true） | 治理写权限校验失败 |
| 403 | `hyperliquid_disabled` | `/execution/hyperliquid/{set_leverage,cancel,cancel_all,sync}` | Hyperliquid 写入类接口已禁用 |
| 410 | `module_retired` | `/fundamental/{flows,narrative,trading,overview}/*`（非 news） | 基本面非新闻模块整体退役 |

> 执行类接口（`/execution/*`、`/carry/hyperliquid/sync_open`）在 `execute=true` 时还会经 `_check_execute_guard` 返回的守卫响应（含幂等、冷却、白名单等业务错误码），具体由守卫实现决定。

---

## 8. 版本管理

### 8.1 版本策略

- **接口版本：** 当前为 **v1.1**（2026-07-25），与 `docs/ENGINEERING_INDEX.md` 文档版本对齐。
- **变更来源：** 任何 HTTP 路由或 Python API 签名的变更（新增/修改/删除/退役）必须在 `docs/CHANGELOG.md` 追加一条记录，并同步更新本文档的「接口概览」与「接口详情」。
- **兼容性：**
  - 新增字段不视为破坏性变更，旧客户端可忽略。
  - 删除字段、改变字段语义、改变 HTTP 方法/路径、改变默认值视为破坏性变更，需升主版本号并在 CHANGELOG 中标注「影响范围」。
  - 退役接口保留路由并返回 410 `module_retired`，至少保留一个版本周期后再移除路由。
- **环境变量覆盖：** `ExitConfig.from_env()` 支持的环境变量在「6.4 ExitConfig」中列出；新增环境变量必须同步更新该章节。

### 8.2 路由注册约定

- `ml_trade_service.py` 为主入口，所有 `/execution/*`、`/webhook/*`、`/fundamental/*`、`/exit/features/latest`、`/three_screen/*` 路由直接定义于该文件。
- `carry_service.py` 通过 `register_routes(app, svc)` 将 `/carry/*`、`/funding/*` 路由注入主 app；`create_standalone_app()` 仅用于独立最小化部署。
- `classic_exit_system.py` 通过 `create_app(system)` 工厂独立暴露 `/health`、`/exit/*` 路由，默认端口 8095。

### 8.3 端口约定

| 服务 | 默认端口 | 监听地址 | 环境变量 |
|------|----------|----------|----------|
| ml_trade_service | 8092 | `LISTEN_HOST`（默认 127.0.0.1） | `PORT` / `ML_TRADE_SERVICE_PORT` |
| classic_exit_system | 8095 | 0.0.0.0 | `--port` CLI 参数 |
| frontend | 5173 | — | Vite 默认 |

---

_最后更新：2026-07-25 | 来源：10-经典指标系统（classic_exit_system.py / ml_trade_service.py / carry_service.py）_
