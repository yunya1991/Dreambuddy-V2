# PROP-20260814 DreamOS 交易系统四层闭环诊断与完善优化方案

- 日期: 2026-08-14
- 类别: 交易系统升级（代码/架构）
- 状态: 已批准（P0 已实施，P1/P2 待排期）
- 触发: 用户指令「仔细分析升级后的 DreamOS 交易系统，检查闭环现状，进行完善优化」
- 调研方式: 全量代码走读（6 新模块 + 调度器 + 实盘守护进程）+ 52 项测试回归 + 交易所账户实况查询
- 审批: 飞书实例 8B8B2AA6-A3E8-4B6F-A578-C08B9E4FEFE4（2026-08-14 已批准）

## 〇、P0 执行记录（2026-08-14 23:2x 已实施）

| 项 | 动作 | 验证 |
|---|---|---|
| P0-1 | screen_executor.py 3 处 Mac 硬编码路径 → /home/ubuntu/Dreambuddy-V2-main/12-三屏趋势系统 | engine 导入实测通过；00:10 巡检自动生效 |
| P0-2 | DreamOS 旧调度器重启（watchdog 静默失效期间持仓无管家 ~9h） | 进程 ALIVE，exit_check/scan 恢复运行 |
| P0-3 | V15Executor 增加 dry_run 门禁（默认 True，env DREAMOS_TRADING_DRY_RUN，真单须显式 False+审批） | 实测默认不触真单通道；52/52 测试全绿 |

遗留（P0.5，明日首办）: 调度器 exit_check 报 0 持仓 vs 交易所实况 3 空单（ETH/SOL/ARB，均有 reduceOnly TP/SL 保护单在交易所侧）——ClassicExitSystem 账本与交易所对账重建。

---

## 一、闭环现状总览

升级后的四层（五段）流水线 A选币 → B易经信号 → C V15执行 → D路由 → E认知，由 F层 OrchestratorV2 编排。

| 层 | 组件 | 代码 | 节点注册 | 被驱动 | 实状 |
|---|---|---|---|---|---|
| A | CoinSelector | ✅ 333行 | ✅ COIN_SELECTOR | ❌ | **mock 模式**，Hermes 接入是 TODO（coin_selector.py:65） |
| B | YijingSignalGenerator | ✅ 614行 | ✅ YIJING_SIGNAL | ❌ | 纯计算无外部依赖，可用 |
| C | V15Executor | ✅ 415行 | ✅ V15_EXECUTOR | ❌ | ⚠️ **无 dry-run 开关，直连真单** |
| D | SignalRouter | ✅ 235行 | ✅ SIGNAL_ROUTER | ❌ | Orchestrator 构造了它但 run_cycle **从不调用**（死接线） |
| E | CognitiveReviewer | ✅ 404行 | ✅ COGNITIVE_REVIEW | ❌ | lessons 不持久化；注入 API 无人调用（认知闭环断开） |
| F | OrchestratorV2 | ✅ 362行 | ✅ ORCHESTRATOR_V2 | ❌ **无任何调度器/graph 驱动它** | 状态纯内存，重启即失忆 |

**结论：四层闭环"装配完成、未通电、未接线"。** 52/52 单元测试全绿只证明零件合格，闭环整体从未运转过一次。当前实际运转的实盘是另一套旧管线（见第三节）。

## 二、发现的问题（按严重度）

### 🔴 致命
1. **V15Executor 无 dry-run，真单通道裸露**（v15_executor.py:170-201）
   - execute_signal() 无条件尝试通过 HyperliquidClient('c') 下真市价单（AGENT_C 密钥已配置在 .env）。
   - 更危险：真单失败时仅记录 `real_order={"error":...}`，仓位仍标记 OPEN → 账实不一致。
   - SIGNAL_ROUTER 节点内部也调用 execute_signal。一旦任何 graph/cron 接入这些节点，真金白银下单且**无审批门禁**。
2. **实盘巡检循环已崩溃 N 小时**：screen_executor.py:1082 硬编码 Mac 路径
   `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统` → 腾讯云服务器上不存在 → `from engine import ...` ImportError → 每小时巡检必崩（今日 07:10/09:10/11:10/13:10/14:10 UTC 全部退出码 1）。迁移残留。
3. **3 个真实空单处于"无管家"状态**：Hyperliquid Agent C 账户实况（本次实时查询）：
   - 权益 51.62 USDT，可用 18.57 USDT
   - ETH SHORT -0.0359 @1880.6（浮盈 +0.47）
   - SOL SHORT -0.71 @75.85（浮盈 +0.43）
   - ARB SHORT -602.7 @0.07465（浮盈 +0.23），均 5x
   - 管理这些持仓的 DreamOS 调度器已于今日 12:30 后死亡（最后日志：3 持仓 TP/SL 修改成功）。交易所侧 TP/SL 挂单仍在保护，但超时离场/加仓管理已停摆 ~9 小时。
   - ⚠️ 与记忆记录冲突：8/14 12:35 平仓维护记录称已平 BTC/ETH/SOL 并创建暂停标记，但 ETH/SOL 仍在仓、暂停标记文件不存在。需用户澄清当时维护的实际作用对象。

### 🟠 严重
4. **认知闭环断开**：get_cognitive_context()（E→B 注入接口）无任何调用方；OrchestratorV2 每轮用 pnl=0 的**伪造交易结果**喂给 reviewer（orchestrator_v2.py:165-181），认知层在"自我欺骗"，学不到任何东西。
5. **无持久化**：OrchestratorV2 的连败计数/贝叶斯状态、CognitiveReviewer 的 lessons 全在内存，进程重启全部丢失。
6. **贝叶斯触发器空转**：check_bayesian_trigger() 只置标志位，不对接任何优化器（self_evolution_engine 未接入）。
7. **D 层死代码**：run_cycle() 第 151-163 行手工拼 dict 冒充"路由结果"，self._router 从未被调用。

### 🟡 中等
8. **F 层无驱动**：旧调度器（scheduler_jobs.json: scan_main/exit_check/backtest/optimize，均 dry_run=true）只跑旧 BCRM 管线；新 ORCHESTRATOR_V2 节点不在任何调度计划或 graph 链中。
9. **调度器守护不可靠**：crontab watchdog（每小时 :05 pgrep 拉起）自 8/10 后未成功拉起过任何进程（scheduler_cron.log 无新输出），8/10 启动的进程死了 ~9 小时无人拉起。且 start_dreamos_scheduler.sh 指向 macOS launchd（已废弃但残留）。
10. **数据源风险**：OKX/Binance API 被墙（实测 000），Hyperliquid 可达（405=需POST，网络通）。新闭环的 market_data 没有定义真实数据来源（谁填 state.market？）。
11. **迁移残留**：14-V15经典马丁策略/ 下仍有 com.dreambuddy.v15_trader.plist 等 macOS launchd 文件；screen_executor Mac 路径（同 #2）。

## 三、当前真正运转的实盘系统（勿混淆）

| 系统 | 进程/调度 | 状态 |
|---|---|---|
| 14-V15经典马丁 trader | PID 297383 `run.py trader`，每小时轮询 8 币种 | ✅ 健康（自报持仓 0） |
| ab-trading orchestrator | PID 296328 `orchestrator.py --daemon` | ✅ 存活 |
| screen 三屏巡检 | crontab :10 → screen_orchestrator → screen_executor | ❌ **每小时崩溃**（#2） |
| DreamOS 旧调度器 | crontab :05 watchdog → start_scheduler.py | ❌ **进程死亡 ~9h**，watchdog 未拉起（#3/#9） |
| 易经数据服务 | PID 742971 data_server_fixed.py | ✅ 存活 |
| A系列 graph | cycle trade_20260814041340（A9→A6→C_MARTIN_V15） | ✅ 今日 04:15 有执行（用旧节点，未用新 A-E 层） |

## 四、优化方案（分级）

### P0 — 止血（实盘安全，建议立即批准）
- **P0-1** 修复 screen_executor.py Mac 硬编码路径 → `/home/ubuntu/Dreambuddy-V2-main/12-三屏趋势系统`，恢复巡检循环。
- **P0-2** 决策点：DreamOS 旧调度器是否立即重启以恢复对 ETH/SOL/ARB 三空单的管家（exit_check 每 30 分钟）？或维持现状靠交易所侧 TP/SL？**建议重启**（重启现有进程，不改代码）。
- **P0-3** V15Executor 增加 `dry_run` 参数，默认 True；真单必须显式 dry_run=False + 审批门禁双保险。SIGNAL_ROUTER/ORCHESTRATOR_V2 节点默认 dry_run。

### P1 — 闭环接线（让四层真正转起来）
- **P1-1** E→B 认知注入：run_cycle 开始时调用 reviewer.get_cognitive_context(symbol)，将 confidence_adjustment 注入信号置信度。
- **P1-2** 持久化：lessons → data/cognitive_lessons.json（每轮 persist）；orchestrator 状态 → data/orchestrator_state.json（连败/贝叶斯/累计PnL，启动时加载）。
- **P1-3** 真实反馈回路：接入真实平仓结果（从 exit_check/持仓对账获取 pnl）→ record_trade_result() + reviewer.review(真实结果)，替换伪造 pnl=0 审查。
- **P1-4** D 层接线：run_cycle 实际调用 self._router.route()，或明确删除 router 依赖（二选一，消除死代码）。
- **P1-5** F 层驱动：scheduler_jobs.json 新增 `orchestrator_v2_cycle` 任务（每小时、**dry_run=true**、先跑 7 天影子模式对比旧管线信号质量）。

### P2 — 强化
- **P2-1** CoinSelector 接入真实 Hermes SKILL（资产研究+注意力雷达），保留 mock 回退。
- **P2-2** 贝叶斯触发对接 11-易经 self_evolution_engine（连败≥3 → 参数再优化提案，走 trading 审批）。
- **P2-3** 统一行情数据 provider：以 Hyperliquid API 为主源（实测可达），OKX/Binance 降级备用；新闭环 market_data 由它供给。
- **P2-4** 调度可靠性：start_scheduler.py 改为 systemd 用户服务（Restart=always），替换 crontab watchdog；清理 macOS launchd 残留文件。

### 验证标准
- 每阶段完成后 52+ 项测试全绿；P0 后观察 1 个巡检周期日志无 traceback；P1 后影子模式运行 7 天，闭环状态文件每日有增量。
- 红线：V9 参数（8%×vol_mult 加仓间隔 / 4%×vol_mult 止盈 / 无固定止损 / 最多3次加仓）不动；P1/P2 任何真单行为必须先经 trading 审批。

## 五、影响面与风险
- 改动文件: screen_executor.py（1行路径）、v15_executor.py、orchestrator_v2.py、signal_router.py、cognitive_reviewer.py、scheduler_jobs.json、新增 systemd unit。
- 不动: 14-V15 策略代码、A系列 cron、V9 红线参数、旧管线回测基线。
- 风险: P0-2 重启调度器会恢复自动 TP/SL 管理（对当前持仓是保护而非风险）；P1-5 影子模式 dry_run 不产生真单。

---
请审批。批准顺序建议：P0 整批 → P1 分批 → P2 逐项。
