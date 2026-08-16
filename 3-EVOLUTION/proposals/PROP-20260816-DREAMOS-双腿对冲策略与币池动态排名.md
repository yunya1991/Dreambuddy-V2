# PROP-20260816: DreamOS 双腿对冲策略 + 币池动态排名

**状态**: 待审批（飞书审批实例 `09949909-A303-487C-B15F-D3BE8BCAEFF0`，模板 096DC318 交易进化审批，2026-08-16 创建）
**日期**: 2026-08-16
**系统**: DreamOS（1-ARCHITECTURE/dreamos）
**前置**: 四闭环已导通（FOUR_LOOP_VERIFICATION_20260815）、30币新池已上线消费（18:30 实测）

---

## 一、背景与目标

新币池（多15/空15）上线后发现两个结构性问题，用户给出设计方向：

1. **`ordered[:6]` 覆盖缺口**：编排每周期固定消费 long_pool 前6币，24币（含全部空头）永不被消费
2. **V15 马丁策略本质做多为主**：无固定止损的马丁在空头方向风险无限，不应消费空头池
3. **新增双腿对冲策略**：做多多币池最强币 × 做空空币池最强币，~1:1 名义，按**合并盈利**制定离场

**已确认参数**（用户 2026-08-16 确认，按默认）：

| 参数 | 值 |
|---|---|
| 动态排名信号源 | 每周期 B层 conf + scan 信号强度 → 动态分，写运行时层（不覆盖周报初始分）|
| 对冲入场门槛 | 双腿 conf 均 ≥0.62 |
| 仓位 | 每腿 ≤150 USDT 名义，1:1 |
| 离场 | 合并 PnL ≥ +4% 双腿同平；合并回撤 ≤ -6% 熔断双腿同平 |
| 适用 regime | 仅 RANGE_BOUND 激活 |

**硬约束**：V9 基线（8%加仓间隔/4%止盈/无固定止损/3次加仓）不动 —— 对冲是与 V15 并列的新策略，不是修改。

## 二、现状调研结论（D链）

| 接线点 | 位置 | 结论 |
|---|---|---|
| 币池加载 | `coin_selector.py:65 _load_persisted_pools()` | 读 coin_pool.json，8天新鲜度，返回 long/short_pool |
| 编排选币 | `scheduler.py:423-441` orchestrate job | `ordered[:6]` 无轮询 ← 缺口所在 |
| 信号路由 | `signal_router.py:51 route()` | B易经→C执行→D路由一体，共享 V15Executor 账本 |
| V15执行 | `v15_executor.py:188 execute_signal(signal)` | 契约 {symbol,direction,confidence,entry_price}；min_confidence/max_concurrent/dry_run 门禁 |
| 离场管理 | `cli/auto_trader.py:2211 run_exit_check_all()` | 从交易所拉真实持仓逐币查 TP/SL/移动止损 ← 对冲离场扩展点 |
| 下单客户端 | `execution.aster_spot.HyperliquidClient` | 真单冒烟已验证 open_long/open_short/close（PROP-20260816 五项验收通过）|
| regime 源 | coin_pool.json `regime` 字段 | 周度写入，当前="RANGE_BOUND底部修复…" |

## 三、设计（Z链）

### 模块1：动态排名（pool_dynamic_scores）

新增运行时文件 `scheduler_data/pool_dynamic_scores.json`：

```json
{"updated_at": "...", "scores": {
  "HEMI": {"dyn_score": 0.27, "last_dir": "LONG", "last_conf": 0.27, "cycles_seen": 3, "updated_at": "..."}
}}
```

- **写方**：orchestration_cycle 每周期把已评估币的 B层 conf upsert 回写
- **读方**：编排选币按合并分排序：`merged = 0.7×weekly_score + 0.3×dyn_score`（dyn_score 冷启动默认 0.5 中性）
- **不修改 coin_pool.json**（周报 SSoT 只读，动态分独立存储）

### 模块2：V15 纯多门禁

- 编排选币**仅从 long_pool** 取（按合并分 top6）
- 防御性门禁：`execute_signal` 增加 `long_only` 开关，SHORT 信号拒单 reason=`v15_long_only`
- 存量 ACE 空头 paper 仓：不并入对冲对，由现有离场逻辑自然管理

### 模块3：HedgeExecutor（双腿对冲，新文件）

`dreamos/capabilities/trading/hedge_executor.py`

**入场**（每 orchestration_cycle 评估一次）：
1. regime 门禁：coin_pool.json regime 含 "RANGE_BOUND" 才激活
2. 候选：多池合并分 top1 × 空池合并分 top1
3. B层信号双向验证：长腿须 dir=LONG、短腿须 dir=SHORT，**双腿 conf 均 ≥0.62**
4. 开仓：每腿 150U 名义、杠杆与 V15 一致（5x）、1:1 市场中性
5. **孤儿腿保护**：第二腿开仓失败 → 立即平掉第一腿
6. 并发上限：同时最多 1 个对冲对

**离场**（run_exit_check_all 增加 hedge 分支）：
- `combined_pnl = 长腿浮盈 + 短腿浮盈`（交易所 unrealized）
- `combined_pnl_pct = combined_pnl / (2×单腿名义)`
- ≥ +4% → 双腿同平（reason=hedge_tp_combined）
- ≤ -6% → 熔断双腿同平（reason=hedge_sl_combined）
- 单腿无独立 TP/SL、无马丁加仓

**账本** `scheduler_data/hedge_positions.json`：

```json
{"pairs": {"HP-20260816-001": {
  "long_symbol": "...", "long_entry": 0.0, "long_size": 0.0,
  "short_symbol": "...", "short_entry": 0.0, "short_size": 0.0,
  "notional_per_leg": 150.0, "opened_at": "...", "status": "OPEN", "close_reason": null
}}}
```

**dry_run 门禁**：复用 `DREAMOS_TRADING_DRY_RUN` 环境变量，默认 paper。

### 模块4：编排集成（scheduler.py orchestrate job 改造）

```
加载币池 → 合并动态分排序
  ├─ V15路径: long_pool top6（纯多）→ route() 逐币
  ├─ 对冲路径: 管理存量对离场 → 评估新对入场
  └─ 回写 pool_dynamic_scores.json
```

## 四、文件变更清单

| 文件 | 变更 | 规模 |
|---|---|---|
| `capabilities/trading/hedge_executor.py` | 新增 | ~200行 |
| `cli/scheduler.py` orchestrate job | 选币改造+对冲调用+分数回写 | ~40行 |
| `capabilities/trading/coin_selector.py` | 新增 merge_dynamic_scores() | ~30行 |
| `capabilities/trading/v15_executor.py` | long_only 门禁 | ~10行 |
| `cli/auto_trader.py` run_exit_check_all | hedge 对离场分支 | ~40行 |
| `tests/test_hedge_strategy.py` | 新增测试 | ~150行 |

## 五、风险与缓解

| 风险 | 缓解 |
|---|---|
| 单腿成交另一腿失败（孤儿腿）| 失败即平第一腿，不保留裸敞口 |
| 价差/基差风险 | 合并回撤 -6% 熔断兜底 |
| funding 双向收付侵蚀净利 | P1：账本记录 funding，观察后再优化 |
| 空头池 conf 普遍偏低（当前 0.23-0.39）| 宁缺毋滥：门槛不满足则跳过，不降标准 |
| 动态分冷启动 | 默认 0.5 中性，退化回周报排名 |

## 六、测试与验收（paper 先行）

1. **确定性单元**：合并 PnL 计算 / regime 门禁 / 单腿不达标→无仓 / 孤儿腿保护
2. **集成全链**：合成强信号→双腿开仓→合并+4%→双腿同平→账本闭环
3. **回归**：现有套件全绿，V15 路径行为不变
4. **生产完整性核验**（dreamos-testing §3）测试前后各一次
5. **paper 运行观察** 1-2 天 → 实盘另行提交审批（dreamos-testing §10）

## 七、实施顺序（批准后）

1. hedge_executor.py + 测试（隔离，不碰生产状态）
2. coin_selector 动态分合并 + scheduler 选币改造
3. v15 long_only 门禁 + exit_check hedge 分支
4. 全套回归 + 生产完整性核验
5. 重启调度器（pgrep 防双进程 + mtime 验证）→ paper 观察
