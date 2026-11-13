# T1–T14 交易链验收报告

## 基本信息

- 验收对象：T13 `13 PreTradeGate → 16 CapitalAllocator → 22 tee/raw` 唯一执行链，以及本轮 T1–T14 相关改造。
- 核心约束：22 tee 只由 Gateway 持有；tee 的底层 client 必须是 raw client；停用 T12 外层 monkeypatch；高层开仓、平仓、减仓不得绕过 13。
- 验收时间：2026-11-13 11:14:41 CST。
- 验收人：AI。
- 关联 commit：本报告在提交前生成，对应本次交易链提交。
- 验收范围：本地自动化测试与 paper 链路；不冒充实盘成交或云端部署验收。

## 验收目标与通过标准

1. 所有交易入口统一进入 Gateway，依次执行 13 风控、16 定容和 22 tee/raw 执行。
2. tee 不由 11/PollingTrader 持久持有，不使用 `RiskGatedOkxClient` 作为其底层 client，不保留 T12 外层 monkeypatch。
3. 13 拒绝高层开仓时 raw 下单次数为 0；平仓和减仓仍按各自风控语义经过 Gateway。
4. active 与 shadow 均不得递归、重复下单或吞单；shadow 必须留下审计并继续 raw 下单。
5. SPEC R-L0-02 要求的 paper `13→16→22`、订单对账和无直连旁路均有运行证据。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 判定 |
|---|---|---|---|
| 症状复测 | PASS | `repro_after.log:1-9`：Gateway 17 项测试 exit=0；`observed=TEE_RAW_CLIENT_OK sole_owner=Gateway`。`repro_after.log:55-67`：真实模块 paper 链路全部断言为 true，`CHAIN_OK`。 | 高层交易旁路、tee 持有权错误和递归风险已按原路径复测。 |
| 日志证据 | PASS | `repro_after.log:21-28`：`tee_ord_id=paper-tee-1`、`tee_engine=TEE`、`tee_state=filled`、`tee_filled_sz=0.02`；`repro_after.log:72-78`：shadow/active 均 `ok=true`，最终 `TEE_MODES_OK` 与 `observed=HIGH_LEVEL_ROUTE_AND_TEE_MODES_VERIFIED`。 | SPEC→代码→运行→输出追溯完整，订单字段非空且可对账。 |
| 回归测试 | PASS | `test.log:1-4`：22 执行引擎全套 137 项，exit=0；`test.log:5-9`：23/42 定向 59 项，exit=0；`repro_after.log:1-4`：Gateway 17 项，exit=0。 | 相关回归均为 0 退出，无 FAIL/ERROR。 |
| 影响面 | PASS | `fix.diff`：17 个代码/测试文件，1868 insertions、353 deletions；代码/测试 `git diff --cached --check` exit=0（验收补丁原样保留）；暂存 Python 文件均通过 `py_compile`。Black 格式化前后 7 个文件 AST strict 等价，格式化后 Gateway 17 项复测 exit=0。 | 提交范围限定于本轮交易链实现、测试与验收包；运行态 episodes/metrics、新闻归档和无关文件未纳入。 |
| 边界验证 | PASS | Gateway 测试覆盖 13 拒绝、16 定容失败降级、22 失败回退、raw `ok=False`、shadow 审计；`repro_after.log:72-74` 验证 active/shadow 均只产生 1 笔 raw 订单。 | 负面与降级场景符合预期，无重复执行、递归或 shadow 吞单。 |

## SPEC R-L0-02 追溯

- SPEC：`49-交易框架协议/SPEC.md` R-L0-02 要求 16 `capital_allocator` sizing、22 `tee_core` OrderPort、paper 管道 `13→16→22` 完整、订单可对账、无直连旁路。
- 代码：`trade_execution_gateway.py` 统一编排 13/16/22；`polling_trader.py` 保存 raw client，构造 tee 后立即注入 Gateway，并移除外层 monkeypatch 与自有 tee 持久字段。
- 运行：`repro_after.log` 中加载模块为 `core.pre_trade_gate`、`core.capital_allocator.component`、`tee_core.core.engine`。
- 结果：16 将调用方 `sz=1.0` 截断为 `0.02`；22 以 `tee_direct` 产生唯一 raw 订单；audit 记录 `risk_decision=allow`、`executed=true`、`reason_code=PASS`，订单 ID、成交状态、成交数量和引擎标识均可对账。

## 关键边界明细

| 场景 | 预期 | 实测结果 |
|---|---|---|
| 13 拒绝高层开仓 | 不得调用 raw 下单 | 返回 rejected，raw 下单次数为 0。 |
| 高层开空 | 必须经过 13，再到 22 | 事件顺序为 `13 → 22`，side/sz 与换算结果一致。 |
| 平多、平空、减仓 | 不得经 raw bound method 绕过 Gateway | 均经过 13，动作依次为 close、close、reduce，方向和数量正确。 |
| 16 定容超过上限 | 只截断，不放大 | paper 中 `1.0 → 0.02`；定容失败时使用调用方仓位并 FAIL-OPEN。 |
| tee active | tee 接管成交，只下一次单 | raw_order_count=1，state=live，无 shadow 审计文件。 |
| tee shadow | 记录审计且不得吞单 | raw_order_count=1，shadow_audit_files=1。 |
| tee/raw 失败 | 不得伪装为成功或风控拒绝 | 原始 `ok=False` 不被误报为 executed；tee 失败可回退 raw。 |
| tee 构造身份 | 必须持有 raw client，Gateway 独占 | `engine.client._raw is raw` 为 true，holder 无 `_tee_engine`。 |

## 排除项

以下运行态或无关变更不进入本次提交：

- `11-易经推理系统/.workbuddy/episodes/TC_*.json`。
- `42-神经网络交易协调层/runtime/metrics.json`。
- `1-ARCHITECTURE/dreamos/cli/ranking_backtest.py`。
- `1-ARCHITECTURE/specs/FRONTEND_INDUSTRIALIZATION_GOAL_SPEC.md`。
- 新闻归档与 `cleanup_news_local.py`。
- `/tmp` 下仅用于验收的临时脚本。

## 红旗清单

- 本地/paper 验收无红旗。
- 云端版本、服务健康和云端业务日志需在部署后单独核验；本报告不预先宣称云端通过。
- 本轮不执行真实实盘下单。

## 验收结论

- [x] 五维证据齐全，本地/paper 验收通过。
- [x] 四文件验收包齐全：`repro_after.log`、`fix.diff`、`test.log`、`acceptance_report.md`。
- [ ] 云端部署验收：待推送和部署后执行。

AI 验收：2026-11-13。
