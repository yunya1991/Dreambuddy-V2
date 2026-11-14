# 执行引擎中心 — 变更记录

## v1.6（2026-11-14）— 多资产 live：注册表单一事实源 + 动态 allowlist

### 新增
- `config/live_symbols.json`：live 可交易标的单一事实源（32 标的：crypto_usdt 20 / precious_metal 2 / us_stock 10），含 `max_positions_default`
- `tests/test_live_order_bridge_moved.py::test_registry_drives_allowed_symbols_and_max_positions`：白名单与并发上限来自注册表，`22_MAX_POSITIONS` 可覆盖

### 修改
- `x1_live_executor.py` / `executors/live_order_bridge.py`：`ALLOWED_SYMBOLS` 改读注册表（缺失 fail-closed 仅 BTC）；并发上限默认 6（注册表 → 环境变量覆盖）
- `50/tools/run_live.py`：allowlist 改为总线 `confidence≥0.8` 的 long/short 动态选取 + 资产类别共振传导；默认 Mandate 改 `mandate-20261114-50-live-multi`
- `47/registry/execution_rights.json` v0.4：`fifty_nn_domain` 32 标的 `live:50-bypass`，Mandate 不匹配回落 paper

## v1.5（2026-11-14）— Plan A：OKX 凭据收口到 22 域

### 新增
- `executors/credentials.py`：交易所凭据唯一存放地（AES-256-GCM，`runtime/venue`，密钥 0600），CLI 支持 `status` / `import-env`
- `executors/okx_client.py`：OKX 客户端唯一实现（自 11 `okx_simulated.py` 迁入），凭据优先级 = 环境变量 > 22 加密库 > 默认值，禁止回落 `.env`
- `executors/live_order_bridge.py`：真实下单唯一出口（原 11 同名脚本迁入），kill-switch `22_LIVE_KILL_SWITCH`、审计 `runtime/live_order_audit.jsonl`
- `tests/test_executor_credentials.py` / `test_okx_client_moved.py` / `test_live_order_bridge_moved.py`：共 18 项契约测试

### 修改
- `x1_live_executor.py`：`_BRIDGE` 指向 22 `executors/live_order_bridge.py`
- 11 `scripts/memory_l4/okx_simulated.py`：降为转发 shim（11→22 单向依赖）
- 11 `data_server_fixed.py`：账户查询改读 22 加密凭据库
- `11/.env`：移除全部 `OKX_*` 明文凭据（迁移前备份于 /tmp，权限 0600）

## v1.4（2026-11-14）— 13/16/22 整合：域路由执行器迁入 + 13 门禁 fail-closed

### 新增
- `executors/domain_clients.py`：自 11 迁入的域路由执行器唯一实现
  - `DomainTaggedOkxClient`：raw client + evo23 标签 + 13 只读影子校验
  - `DomainRoutedOkxClient`：23 自进化域 → evo client，其余 → 22 RiskGatedOkxClient
  - `tag_reason()` / `shadow_decision()` / `EVOLUTION_DOMAIN_TAG` / `EVOLUTION_OKX_TAG` / `NN_OKX_TAG`
  - 仅依赖传入 client/gateway，不 import 11
- `tests/test_domain_clients_moved.py` 9 项：独立 import / 无 11 引用 / 行为等价 / 11 与 22 同一对象断言

### 修改
- `trade_execution_gateway.py`：裸 `PreTradeGate()` → `core.factory.create_gate()`
  - 13 门禁真正生效（7 条规则全量加载，规则数=0 fail-closed）
  - `ExecutionResult` 新增 `rules_evaluated` / `rule_name` 审计字段
  - `_create_gate()` 用 sys.path 隔离 + sys.modules 保存/恢复避免顶层包冲突

### 兼容
- 11 `polling_trader.py` 改为同对象别名导入（`_DomainTaggedOkxClient` 等旧符号保留）
- `live_order_bridge.py` 因 11 独占真实密钥，长期留在 11（22 通过子进程调用）

### 验证
- 22 全量 160 项测试通过
- 云端 `tag_reason('x')` → `[23域]x`，`create_gate()` 加载 7 条规则

## v1.3（2026-11-14）— NN live 链路接入 13 风控、去重、持仓守卫与冷静期

### 新增
- `risk_bridge.py`：13 `PreTradeGate` 判定 + `risk_capital` 真实权益 + PACA 定容，
  名义金额 10~100 USDT、杠杆 3，任一环节异常 fail-closed（`RISK_MODULE_LOAD_FAILED` / `RISK_BLOCKED` / `SIZING_BELOW_MIN`）。
- `x1_live_executor.py`：真实下单前持仓守卫（同标的已有仓位 → `symbol_already_open`，查询失败 fail-closed）。
- `x1_live_executor.py`：开仓冷静期 8h（`COOLDOWN_HOURS`，`22_LIVE_COOLDOWN_HOURS` 可覆盖），
  状态持久化 `runtime/x1_live_processed.json` 的 `last_entry`，仅真实成功开仓写入。
- 云端 `dreambuddy-nn-live-chain.service/.timer`：每 5 分钟执行 50 live 决策 → 22 执行。

### 变更
- 50 `run_live.py` 的 `decision_id` 改为证据批次 sha1（`50-nn|<16hex>`），
  修复时间戳 id 导致 22 `processed` 幂等失效的问题。

### 修复
- 加载 13 时顶层 `core` 包与 12/14/16/50 冲突（pytest 下 `No module named 'core.context'`）：
  加载期间临时置顶 13 路径并隔离 `core.*`，退出恢复 `sys.path` 与模块缓存。

### 验证
- 22 全量 167 用例通过；云端真实首单 BTC-USDT-SWAP short 73 USDT / 3x / OCO 成功，
  复跑幂等跳过；冷静期末期新决策被拦（`remaining_sec` 约 7.7h）。

## v1.2（2026-11-13）— 23 自进化域下单链路隔离

### 背景
`13→16→22→11` 执行链路仅适用于神经网络系统（50-NN / 11-BCRM / BDSM 等）。
23-四层闭环自进化系统的实盘单**禁止**经 13 拦截 / 16 定容 / 22 执行，
需由 11-polling_trader 的 raw 通道直接下单，并携带可区分标签，
以与神经网络系统订单进行对照。

### 新增
- `TradeExecutionGateway(shadow_only=True)`：只读影子校验模式。
  仅运行 13 `PreTradeGate.check()` 并将判定写入 `audit/gateway.jsonl`
  （`source=23-evolution` / `executed=false` / `shadow_only=true` / `reason_code=SHADOW_*`），
  **不阻断**订单，也不调用任何交易所接口。
- 11 `_DomainTaggedOkxClient` / `_DomainRoutedOkxClient`：
  23 域订单走 raw client + OKX `tag=evo23` + reason 前缀 `[23域]`；
  神经网络订单仍走 13/16/22 链路，tag 保持 `yijingsim` 不变。
- `PositionTracker.open_position` / `TradeRecord` 新增 `domain_tag` 字段（`"23域"` 或 `""`）。

### 边界
- `shadow_only` 网关只承担审计职责，13 判定结果不影响 23 域订单是否成交；
  23 域订单的真实风控由其自身决策逻辑 + OKX 交易所风控承担。
- 神经网络链路（13/16/22）行为零变更。

## v1.1（2026-11-13）— DEC-BCL-07 执行层落位

### 新增
- `x1_paper_executor.py`：X1 纸面成交记录器。输入 40 X0 意图流（含 `decision_id`），经 13 PreTradeGate → 22 Gateway → 18 统一价格源纸面撮合，落盘 `audit/x1_paper_fills.jsonl`（`decision_id/order_id/fill_id/fill_px/exit_px/pnl/status/venue`）
- `x1_paper_config.json`：纸面场配置（notional 100 / 1x / 7 日持仓 / 滑点 5bps / 手续费 5bps / 并发 3）
- `FinalDecisionSignal.decision_id`：顶层优先、`payload.decision_id` 兜底；审计行同步落 `decision_id`

### 边界
- `venue` 恒为 `paper`，不调用任何交易所下单接口；取价只走 18 统一价格源
- 风控拒绝 / 取价失败如实记 `rejected` / `no_price`，不伪造 fill

## v1.0（2026-10-11）

### 新增
- 补建 docs/ 五件套文档（ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG）
- 核心引擎：engine / config / protocol / contract / router / kill_switch / failopen / auditor
- 适配器：OKX 实盘 / Paper 模拟盘 / Lark 通知
- 执行算法：DirectMarket / SmartPassive / SmartTWAP
- 滑点估计器
- V15 + 易经子系统集成
- Task 1-12 TDD 测试套件
- 影子对比与滑点对比脚本

### 架构
- 分层架构：core → adapters → algorithms → estimators → integrations
- FAIL-OPEN 降级优先
- 全链路审计不可绕过
