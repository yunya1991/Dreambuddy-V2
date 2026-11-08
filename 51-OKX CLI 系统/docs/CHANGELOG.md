# CHANGELOG — 51-OKX CLI 系统

## v0.1.0 — 2026-11-07

### 新增

- 建立 `51-OKX CLI 系统` 作为执行层（EXEC/L1.5）的 OKX 场所适配层。
- `VenueConfig`：demo/live 模式、profile 自洽校验、环境变量解析。
- `catalog`：OKX CLI 命令白名单（读 4 模块 / 写 2 模块 / 明确黑名单）。
- `CliRunner`：subprocess 执行、`--profile`/`--demo`/`--json` 注入、超时、错误分类、JSONL 审计与脱敏。
- `OkxCliVenue`：MarketPort（ticker/candles）、AccountPort（balance/positions）、OrderPort（place/cancel/get，demo only）。
- `selector`：`TRADE_EXEC_ORDER_ADAPTER` = `paper` | `okx-cli-demo`，无 live 分支。
- 35 个单元测试：配置、白名单、runner、adapter、选择器。

### 安全

- live 写恒拒绝（`LiveTradingForbidden`），无环境变量可放开。
- live 读默认拒绝，需 `OKX_VENUE_ALLOW_LIVE_READ=1`。
- 调用方不可传 `--profile` / `--demo` / 凭证 flag。
- 审计日志脱敏 `--api-key` / `--secret` / `--secret-key` / `--passphrase`。

### 迁移

- 6-TRADING legacy live 路径增加 fail-closed 守卫（默认拒绝，`OKX_VENUE_LEGACY_LIVE=1` 临时放行）：
  - `scripts/okx_cli.py`
  - `scripts/dream_trade_exec.py`
  - `scripts/dream_strategy_pipeline.py`
- 新增 `6-TRADING/docs/MIGRATION-51-OKX-VENUE.md`。

### 未完成

- P2：trade-exec MCP 选择器接线与契约测试。
- P3：6-TRADING 封装完全迁移、49 SPEC R-L0-03 状态更新。
- P4：live 交给 51（未批准，需 ADR）。