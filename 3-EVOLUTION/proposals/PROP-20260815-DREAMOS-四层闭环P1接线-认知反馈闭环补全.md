# PROP-20260815 DreamOS 四层闭环 P1 接线：认知反馈闭环补全 + 真单解锁路径

- 日期: 2026-08-15
- 类别: 交易系统升级（代码/架构）
- 状态: 待审批
- 触发: 用户指令「检查 DreamOS 交易系统的四闭环是否运行正常」+「重点放在闭环上线，然后监控」
- 前置: PROP-20260814（已批准，P0 已实施）；今日 11:09 commit a277445 已完成 A层币池接线 + D层路由接线
- 调研方式: 逐层代码核实 + 调度器日志 + orchestrator_v2_state.json + 交易所实况查询（18:34-18:50）

## 一、现状核实（2026-08-15 18:50）

四层闭环 A选币 → B易经信号 → C V15执行 → E认知复盘（F编排/D路由），逐层验证结果：

| 层 | 状态 | 证据 |
|---|---|---|
| A 选币 | ✅ 已接线有真数据 | 每周选币 cron 今日 11:11 产出 coin_pool.json（多头池 LINK 0.82 / 空头池 UNI 0.66，source=hermes-weekly），F层实际消费（日志 source=persisted:hermes-weekly） |
| B 易经信号 | ✅ 可用 | 纯计算无外部依赖 |
| C V15执行 | 🔒 dry_run=True 安全门禁 | env DREAMOS_TRADING_DRY_RUN 未设置=默认模拟（PROP-20260814 P0-3 成果） |
| D 路由 | ✅ 已接线 | orchestrator_v2.py:201 实际调用 router.route()（a277445） |
| E 认知 | ⚠️ 两端断开 | ① E→B 注入接口 get_cognitive_context() 无调用方；② run_cycle 仍喂 pnl=0 占位（orchestrator_v2.py:221/237），state 显示 cycles=79 W/L=0/0 pnl=0.0；③ lessons 无持久化文件 |
| F 编排 | ✅ 已驱动 | orchestration_cycle 每小时 :30 运行，状态持久化 orchestrator_v2_state.json |

**结论：闭环已"部分通电"，以影子模式运转；E 认知层进化空转，是唯一断点。**

## 二、本提案实施项（均为影子模式内改动，零真单）

### P1-1 E→B 认知注入接线
run_cycle 开始时调用 `reviewer.get_cognitive_context(symbol)`，将 `confidence_adjustment` 注入 B层信号置信度（PROP-20260814 原 P1-1，方案不变）。

### P1-2 lessons 持久化
CognitiveReviewer lessons → `data/cognitive_lessons.json`，每轮 persist、启动时加载（原 P1-2）。

### P1-3 真实盈亏反馈回路
`update_exit_feedback` 对接真实平仓结果：从 exit_check/持仓对账获取真实 pnl → `record_trade_result()` + `reviewer.review(真实结果)`，替换 pnl=0 占位审查（原 P1-3）。数据来源：旧调度器 exit_check 已实盘管理持仓（今日 33 次运行，TP/SL 实盘更新验证通过），平仓回填路径已存在（auto_trader P0-2 修复），本项只做接线。

### C层真单解锁路径（本次不实施，仅定义门禁）
影子模式达标标准：连续 7 天 orchestration_cycle 状态文件每日有增量 + 信号质量对比旧管线记录在案。达标后**单独提 trading 审批**，批准后设置 `DREAMOS_TRADING_DRY_RUN=false`。本提案不触碰该开关。

## 三、验证标准与红线

- 每项完成后现有测试全绿（52+ 项）；E层接线后观察 24h：orchestrator_v2_state.json 出现非零 pnl/W-L 变化或 lessons 文件有增量
- 红线：V9 参数（8%×vol_mult 加仓间隔 / 4%×vol_mult 止盈 / 无固定止损 / 最多3次加仓）不动；不改 14-V15 策略代码、A系列 cron；本提案零真单行为

## 四、影响面

- 改动文件: capabilities/trading/orchestrator_v2.py、capabilities/trading/cognitive_reviewer.py、新增 data/cognitive_lessons.json
- 不动: v15_executor.py、coin_selector.py、scheduler_jobs.json 的 dry_run 配置、旧管线
- 风险: 全部改动在影子模式（dry_run）内，无实盘风险；认知注入仅影响信号置信度数值，不下单

---
请审批。批准后按 P1-1 → P1-2 → P1-3 顺序实施，每项完成即验证。
