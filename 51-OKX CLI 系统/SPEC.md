# SPEC: 51-OKX CLI 系统（OKX Venue Adapter）

> 版本：v0.1.0（首版，按 2026-11-07 用户三项决策）
> 日期：2026-11-07
> 状态：🟢 P1 骨架已落地（Port 契约 + CLI 适配器 + 审计 + 单元测试）；P2 trade-exec MCP 接线待评审
> 归属：51-OKX CLI 系统（执行层 EXEC/L1.5 的**场所适配层**）
> 上游：49 交易框架协议（执行层契约）、47-MCP 管理系统（MCP 边界与硬约束）
> 下游：trade-exec MCP（paper 主出口）、11 交易执行器 / okx_client 旁路（live 唯一出口）
> 迁移来源：6-TRADING `okx_cli.py` / `okx_unified_toolkit.py`（DEC-25 / R-L0-03）
> 外部依赖：`@okx_ai/okx-trade-cli`（锁定版本）、Python ≥3.10（仅标准库）

---

## §0 定位与决策

### 0.1 一句话定位

**51 把 OKX CLI 的“命令面”收束为受治理的 Port；执行治理仍由 trade-exec MCP / 11 旁路负责。**

51 **不是**交易系统、**不是**策略层、**不是**第二个执行出口、**不是** MCP 壳。

### 0.2 用户决策（2026-11-07，已确认）

| 编号 | 决策 | 对 51 的约束 |
|---|---|---|
| D1 | 51 定位 = **场所适配层** | 不新建独立执行出口；不新增 MCP shell；不新增 MCP 工具 |
| D2 | **live 暂不交给 51**，保持 11 旁路 | v0.1 仅允许 demo 写；live 读需显式开关；**live 写恒拒绝** |
| D3 | 6-TRADING 的 OKX CLI 封装**迁入 51**，退休直连路径 | 落地 DEC-25 / R-L0-03；legacy live 路径 fail-closed |

### 0.3 不做什么

| 禁止 | 原因 |
|---|---|
| 不做策略判断 / 信号生成 | 归 23 / 42 / 40 / 43 / 50 |
| 不做风控 / 定容 | 归 13 / 16；51 只提供场所能力 |
| 不承载 live 下单 | D2：live 唯一出口仍是 11 旁路 |
| 不新增 MCP shell / MCP 工具 | D1：MCP 面保持 trade-exec 10 工具 |
| 首期不纳入 bot / earn / event / 期权 / 交割 | 风险类别与验收标准不同，后续单独立项 |
| 不把 API Key / OAuth token 写入代码或日志 | 凭证只由 `okx` CLI 自己管理（`~/.okx/config.toml` / `okx-auth`） |

---

## §1 在现有架构中的位置

```text
23 / 42 / 40 / 43 / 50 ──信号──▶ trade-exec MCP（exec.trade.mcp，paper 主出口）
                                    │
                                    ├─ ExecutionRights（标的级单出口）
                                    ├─ RiskBridge（13 域，fail-closed）
                                    ├─ 定容钳位（13 PositionSizer）
                                    ├─ OrderPort ──▶ OKXPaperLedger（默认，现有）
                                    └─ OrderPort ──▶ 51 OkxCliVenue（demo，P2 可选）
                                                         │
                                                         └─ okx CLI（demo profile）

11 polling_trader ──live 旁路──▶ okx_client（不经 MCP，不变）
```

**关键边界：**

- 51 只实现 Port，不实现 MCP；trade-exec MCP 的 10 工具面保持不变。
- 51 的 demo 适配器只作为 `OrderPort` 的一个可选实现；默认仍是 `OKXPaperLedger`。
- 11 域 live 旁路完全不动；51 不持有 live 凭证、不接受 live 写命令。

---

## §2 Port 契约

### 2.1 MarketPort（只读）

```text
get_ticker(inst_id) -> {ok, inst_id, last, bid, ask, bid_px, ask_px, open24h, high24h, low24h, vol24h, ts, raw}
get_candles(inst_id, bar="1H", limit=100) -> {ok, candles, raw}
```

### 2.2 AccountPort（只读）

```text
get_balance(ccy=None) -> {ok, balance, total_eq, details, raw}
get_positions(inst_id=None) -> {ok, positions: [Position], count}
Position = {inst_id, coin, pos_side, side, pos, avg_px, mark_px, upl}
```

- `balance` 为 USDT 可用余额（`availBal` → `availEq` → `cashBal` → `totalEq` 兜底）。
- `Position` 字段与 trade-exec MCP `get_positions` 现有形状对齐，便于 P2 直接替换。

### 2.3 OrderPort（写，仅 demo）

```text
place_order(inst_id, side, size, order_type="market", price=None, td_mode=None, pos_side=None) -> {ok, order_id, cl_ord_id, s_code, s_msg, raw}
cancel_order(inst_id, ord_id=None, cl_ord_id=None) -> {ok, order_id, cl_ord_id, s_code, s_msg, raw}
get_order(inst_id, ord_id=None, cl_ord_id=None) -> {ok, order, raw}
```

- `inst_id` 以 `-SWAP` 结尾 → `swap` 模块；否则 → `spot`。
- spot 默认 `td_mode=cash`；swap 默认 `td_mode=cross`。
- `side` ∈ `{buy, sell}`；`size > 0`；限价单必须给 `price`。
- **live 模式调用写方法 → `LiveTradingForbidden`，不执行任何 CLI 命令。**

### 2.4 未来 Port（v0.1 不实现）

| Port | 内容 | 前置条件 |
|---|---|---|
| BotPort | 网格 / DCA | 独立风险评审 + demo 验收 |
| EarnPort | Simple Earn / 双币赢 | 独立风险评审 + 合规确认 |
| EventPort | 事件合约 / 预测市场 | 合规确认 + 单独立项 |

---

## §3 模式与凭证隔离

### 3.1 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `OKX_VENUE_CLI` | `okx` | CLI 可执行文件路径 |
| `OKX_VENUE_PROFILE` | `demo` | `~/.okx/config.toml` 中的 profile 名 |
| `OKX_VENUE_MODE` | `demo` | `demo` / `live` |
| `OKX_VENUE_AUTH` | `api_key` | `api_key` / `oauth` |
| `OKX_VENUE_TIMEOUT_S` | `30` | 单条 CLI 超时 |
| `OKX_VENUE_ALLOW_LIVE_READ` | `0` | 允许 live 只读（写仍拒绝） |
| `OKX_VENUE_AUDIT_PATH` | `runtime/audit/venue_calls.jsonl` | 审计日志路径 |
| `OKX_VENUE_LEGACY_LIVE` | `0` | 6-TRADING legacy live 路径总开关（迁移期临时） |

### 3.2 模式规则

| 场景 | 读 | 写 |
|---|---|---|
| `mode=demo` | ✅ | ✅（demo 账户） |
| `mode=live` + `ALLOW_LIVE_READ=0` | ❌ `LiveReadForbidden` | ❌ `LiveTradingForbidden` |
| `mode=live` + `ALLOW_LIVE_READ=1` | ✅ | ❌ `LiveTradingForbidden` |

**ADR 修订（2026-11-13，SPEC-52 F2/F3）— 用户 venue 的受限 live 写**

- 新增 `credential_source=env`：前端配置的用户 API 以环境变量**仅注入本次子进程**，
  不写 `~/.okx/config.toml`，不进入后端 22 配置。
- 新增 `allow_live_write`（默认 `False`，D2 不变）。仅用户 venue 的 `LiveGate`
  解锁窗口内为 `True`；解锁需人工短语 `UNLOCK LIVE TRADING`，TTL 60s–8h，进程重启即失效。
- 范围仅限「51 用户 venue HTTP Bridge」；trade-exec MCP 选择器仍无 live 分支，
  11 旁路（后端自有链路）完全不变。
- 隔离边界：独立凭证目录 `runtime/user_venue/`、独立审计 `user_venue_calls.jsonl`、
  独立 BFF `/api/venue/*`；后端 22 不读取上述任何内容。

> `mode_flags()` 现在显式下传 `--demo` / `--live`，避免「以为在 demo、实际打到 live」的反向风险。

### 3.3 Profile 自洽校验

- `mode=demo` 但 profile 名含 `live/prod/real/main` → 配置错误（fail-closed）。
- `mode=live` 但 profile 名含 `demo/paper/test/sim` → 配置错误（fail-closed）。
- API Key 模式必须显式给 profile；OAuth 模式 demo 用 `--demo`，live 不加 flag。
- **profile / mode flag 由 51 注入，调用方不可传入**（catalog 拒绝 `--profile` / `--demo`）。

---

## §4 命令白名单

### 4.1 允许的读命令

| 模块 | 子命令 |
|---|---|
| `market` | `ticker`, `tickers`, `candles`, `instruments`, `orderbook`, `funding-rate`, `open-interest`, `indicator`, `list-indicators` |
| `account` | `balance`, `positions`, `config`, `fees` |
| `spot` | `get`, `orders` |
| `swap` | `get`, `positions`, `orders` |

### 4.2 允许的写命令（仅 demo）

| 模块 | 子命令 |
|---|---|
| `spot` | `place`, `cancel` |
| `swap` | `place`, `cancel` |

### 4.3 明确禁止（v0.1）

`config` / `auth` / `login` / `logout` / `skills` / `upgrade` / `pilot` / `diagnose` / `mcp` / `bot` / `earn` / `event` / `futures` / `option` / `transfer` / `set-position-mode` / `max-withdrawal` / 任何 `close` / 任何 `batch`。

禁止原因：凭证与安装面、资金划转、不同风险类别、批量操作放大误单风险。

---

## §5 审计与可观测

- 每次 CLI 调用追加一行 JSONL：`ts / trace_id / operation / argv（脱敏）/ profile / mode / ok / error_code / duration_ms / returncode`。
- 脱敏：`--api-key` / `--secret` / `--secret-key` / `--passphrase` 的值替换为 `***`。
- 不支持把 raw stdout/stderr 全量落盘（避免误记敏感信息）；错误只记 `stderr` 前 500 字符。
- P2 接入 trade-exec 后，审计同时进入 MCP 信封 `meta.venue = {adapter, profile, mode, trace_id}`。

---

## §6 trade-exec MCP 接线（P2，待评审）

### 6.1 选择器

```text
TRADE_EXEC_ORDER_ADAPTER = paper（默认） | okx-cli-demo
```

- 默认 `paper`：行为与现状完全一致（`OKXPaperLedger`）。
- `okx-cli-demo`：`OrderPort` 走 51；`get_balance` / `get_positions` 同步走 51，保证风控看到同一账户视图。
- 选择器 **拒绝** `okx-cli-live` / `live` / 任何不在枚举内的值（fail-closed）。

### 6.2 不变量

| 不变量 | 说明 |
|---|---|
| 10 工具面不变 | 不新增 `okx_*` 工具；不把 OKX 103 个 MCP 工具塞进 trade-exec |
| ExecutionRights 优先 | 51 适配器在 `place_order` 内层，仍受标的级单出口闸门 |
| RiskBridge fail-closed | 13 风控不可用 → 拒绝下单（与 paper 路径一致） |
| 定容钳位 | 13 PositionSizer 建议仍作为上限，只收紧不放大 |
| 信封统一 | 仍由 `_wrap_paper` 产出；新增 `meta.adapter` / `meta.venue` |
| live 不可达 | 选择器无 live 分支；51 写方法在 live 模式直接拒绝 |

### 6.3 失败语义

- `okx` CLI 未安装 / 超时 / 401 / 429 / JSON 解析失败 → MCP 返回 `degraded=true` + `error_code=venue_*`，**不自动回退到 paper**（避免“以为在 demo，实际没成交”）。
- 只有启动时显式选择 `paper` 才使用本地账本；运行中不切换。

---

## §7 6-TRADING 迁移（D3：DEC-25 / R-L0-03）

### 7.1 迁移映射

| 6-TRADING 资产 | 现状 | 迁移后 |
|---|---|---|
| `scripts/okx_cli.py` | 自建 CLI 封装；`profile` 参数未真正注入（隐患） | 保留为**弃用兼容 shim**；内部委托 51；live 写 fail-closed |
| `scripts/okx_unified_toolkit.py` | spot/swap/option/grid/DCA 全能包 | 停止新增功能；spot/swap 能力由 51 承接；option/bot 单独立项 |
| `scripts/dream_trade_exec.py` | 直连 OKX `/api/v5/trade/order`，自带生产凭证 | **降为调试/回放**；默认退出，需 `OKX_VENUE_LEGACY_LIVE=1` 才运行 |
| `bridge/api/trade_exec_api.py` | paper/live 双路径 | 仅 demo；live 只读余额保留，live 写禁用 |
| `scripts/dream_strategy_pipeline.py` | 自建 REST 签名客户端（含 `place_order` / `place_algo_order`） | 读保留；live 写默认拒绝，需 legacy 开关 |

### 7.2 迁移期开关

- `OKX_VENUE_LEGACY_LIVE=0`（默认）：所有 6-TRADING live 写路径拒绝。
- `OKX_VENUE_LEGACY_LIVE=1`：仅迁移期临时放行，且必须记录告警；P3 完成后删除该开关。
- **51 本身永远不读该开关**（避免 legacy 开关污染新适配器）。

### 7.3 验收

- `grep -R "OKX_API_KEY\|/api/v5/trade/order" 6-TRADING` 无默认启用的生产路径。
- `6-TRADING` 文档明确“仅调试/回放/demo”。
- 49 SPEC R-L0-03 状态更新为“已收口”。

---

## §8 实施阶段与验收

### P1（本次已落地）

- [x] `51-OKX CLI 系统/` 五文档 + SPEC
- [x] `okx_venue` 包：config / catalog / runner / adapter / errors
- [x] demo 写 / live 拒绝 / profile 自洽 / 命令白名单
- [x] JSONL 审计与脱敏
- [x] 单元测试（config / catalog / runner / adapter）
- [x] 6-TRADING legacy live fail-closed 守卫

**验收命令：**

```bash
python -m pytest "51-OKX CLI 系统/tests" -q
```

### P2（待评审）

- trade-exec MCP 选择器 + `okx-cli-demo` 适配器接线
- MCP 契约测试：默认 paper 无回归；demo 适配器路径 mock 测试
- 信封 `meta.adapter` / `meta.venue` 落地

### P3（待排期）

- 6-TRADING `okx_cli.py` 改为真正的 51 shim
- 清理 `okx_unified_toolkit.py` 的 spot/swap 重复实现
- 更新 49 SPEC R-L0-03 / DEC-25 状态

### P4（未批准）

- live 交给 51：**需单独 ADR 修订“实盘链路永不暴露 MCP”边界**；不在本 SPEC 范围。

---

## §9 硬约束兼容性

| 约束 | 51 的处理 |
|---|---|
| 实盘链路永不暴露 MCP（47） | 51 不进 MCP；live 写恒拒绝；11 旁路不变 |
| 标的级单出口（execution_rights） | 51 不是出口，只是 OrderPort 实现；闸门仍在 MCP |
| 23 唯一信号出口（49） | 51 不生成/不接收信号；只接受 MCP 传入的已裁决订单参数 |
| ADR-9/H7 Worker 只读 | 51 不暴露给 Worker；P2 只挂 trade-exec 编排侧 |
| 13 风控优先（49） | 51 在 RiskBridge 之后；风控拒绝时不调用 51 |
| DEC-25 / R-L0-03（49） | legacy live 路径默认 fail-closed；迁移映射见 §7 |
| FAIL-OPEN / FAIL-CLOSED | 信号侧 fail-open 不变；51 执行侧 fail-closed（不自动回退 paper） |

---

## §10 风险

| 风险 | 等级 | 对策 |
|---|---|---|
| `okx` CLI 供应链（postinstall 下载原生二进制） | 中 | 锁定版本；校验 SHA-256；限制可执行路径；生产环境预装并禁网安装 |
| 凭证泄露 | 高 | 专用子账户、关闭提币、IP 白名单；密钥不进仓库/对话/日志 |
| 模式误判（demo/live） | 高 | profile 自洽校验 + 调用方不可传 `--profile`/`--demo` + live 写恒拒绝 |
| CLI 输出格式漂移 | 中 | pin 版本；JSON 契约测试；解析失败 fail-closed |
| 重复访问路径 | 高 | 6-TRADING legacy 守卫；51 之外不得新增 OKX CLI 调用 |
| 误单放大（batch/close/bot） | 高 | v0.1 白名单排除；逐项评审后再开 |
| 合规（event/earn） | 高 | 首期不纳入；单独合规确认 |

---

## §11 待决问题

1. P2 是否允许 `okx-cli-demo` 作为 **默认** paper 实现（提升撮合保真度），还是保持 opt-in？
2. `okx` CLI 的安装方式：项目 devDependency、系统全局安装、还是容器内预装？
3. 6-TRADING `okx_unified_toolkit.py` 的 option/grid/DCA 能力是否单独立项（52？）还是永久退役？
4. `OKX_VENUE_LEGACY_LIVE` 的删除时间点（建议 P3 完成后 2 周）。