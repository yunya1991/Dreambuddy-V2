# 执行引擎中心 — 变更记录

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
