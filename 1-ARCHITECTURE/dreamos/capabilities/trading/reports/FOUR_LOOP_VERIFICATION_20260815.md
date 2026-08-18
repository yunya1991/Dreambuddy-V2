# DreamOS 四大闭环真实实盘验证报告

- 日期: 2026-08-15 22:50 (UTC+8)
- 方式: 手动触发一次完整生产编排周期（与 :30 定时任务同一代码路径）+ 交易所实况查询 + 生产日志取证
- 模式: 影子模式（dry_run=True 安全门禁生效，零真单）；SOL 真实持仓由 exit_check 实盘管理
- 产物: `four_loop_verification_20260815.json`（本报告同目录）

## 结论

**四大闭环（A选币 → B易经信号 → C V15执行 → E认知复盘，F编排/D路由驱动）物理接线全部导通，真实运转；但发现 2 个数据链路缺口（见"发现"），修复前 B 层信号与平仓反馈为降级状态。**

## 逐层证据

### A 选币层 ✅ 真实数据
- 币池来源 `persisted:hermes-weekly`（每周选币 cron 产出 coin_pool.json）
- 多头池: LINK 0.82 / BTC 0.74 / HYPE 0.71 / ETH 0.66 / NEAR 0.60；空头池: UNI 0.66 / KAITO 0.62 / PUMP 0.55
- 生产 F 层实际消费前 6 币种（生产日志 22:30 `F层编排启动: 6币种 ['LINK','BTC','HYPE','ETH','NEAR','UNI'] | 来源=persisted:hermes-weekly`）
- 新鲜度在 8 天容差内（今日 11:11 产出）

### B 易经信号层 ⚠️ 导通但数据饥饿（发现 F-1）
- 引擎运转正常：卦象生成（生产输入下 Dui_58 → Tong_Ren_13，moving_yaos=[0,1,3]，phase=leaping-dragon）
- 但生产 F 层 job 仅注入 `{symbol, entry_price, close_price}`，12 个指标字段全部落默认值 → 所有币种输出相同：HOLD conf=0.1312（20:30/21:30/22:30 三个生产周期 + 本次验证周期全部一致）
- 对照实验：喂入真实指标后引擎输出 LONG conf=0.1858，卦象 Lin_19 → Gu_18 —— **引擎有判别力，缺的是指标数据**

### C V15执行层 ✅ 门禁有效 + 实盘持仓管理中
- dry_run 门禁生效（job 级配置直接落到 executor，不依赖环境变量）：本次 6 周期全部 HOLD/REJECTED，账本零新增
- 真实持仓实盘管理（交易所实况查询确认）: **SOL SHORT size=-2.15 entry=75.4246 lev=5.0**（Hyperliquid）
- exit_check 每 30 分钟实盘更新条件单：22:30 `TP/SL 已更新: SOL | SL=76.5107 TP=73.2524 | action=modify`（今日 33+ 次）

### E 认知复盘层 ✅ 接线导通，等待首次真实平仓
- P1-1 注入：每个周期信号均携带 `cognitive_adjustment` 字段（当前 0.0 = 无历史教训，中性正确）
- P1-2 持久化：lessons 文件路径就绪，首次真实审查后自动创建（当前不存在 = 正确，W/L=0/0）
- P1-3 回填：`auto_trader._feed_cognitive_loop → record_real_exit` 已接线，本次验证加上 real_fill 守卫（commit 01109a2）
- 缺口 F-2：交易所条件单触发的平仓无对账检测（见下）

### F 编排 / D 路由层 ✅ 稳定运转
- 状态机：cycles 126 → 132（本次验证 +6），state 每周期落盘，跨重启恢复（22:26 重启后 cycles=114→120→126 连续）
- 调度：orchestration_cycle 每小时 :30 准点（生产日志 20:30/21:30/22:30 全部 COMPLETED），HEARTBEAT 累计错误=0
- D 路由：SignalRouter.route() 单实例单 PRNG 流，B+C+D 单次调用完成

## 本次验证顺带修复（commit 01109a2）

1. **P1-3 real_fill 守卫**：发现平仓回填对 dry_run/估算平仓也无条件喂认知层 → 模拟 pnl 会污染 W/L/lessons。已加守卫：仅 `px_source=='real_fill'` 进认知层。+3 测试（dry_run不喂/估算不喂/real_fill必喂），55/55 全绿
2. **清理测试污染**：冒烟测试残留的假 BTC@100000 持仓从 v15_positions.json 移除（备份保留）

## 发现（未修复，待提案审批）

- **F-1 B 层指标数据饥饿**：F 层 job 需拉 K 线计算指标（MA5/10/20、趋势强度、量能比等）注入 market_data，否则 B 层恒输出 HOLD 0.1312。修复前影子模式的信号质量对比无意义
- **F-2 交易所侧平仓无对账**：SOL 若被交易所 TP/SL 条件单平仓，本地 fetch 只看到持仓消失，无 exit 事件 → 真实 pnl 永不进认知。需持仓快照 diff + 成交历史查询对账

## 监控

- dreamos-loop-watchdog（每30分钟，含状态污染守卫 + 币池新鲜度检查）
- 下一观察点：8/17 周一 10:00 A层每周选币 cron 更新币池；F-1/F-2 修复前，B 层信号与 E 层反馈维持降级状态
