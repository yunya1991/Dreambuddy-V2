# PROP-20260810-CMARTIN-NODE: C_MARTIN_V15 节点在 SACG 节点注册表中缺失

- **提案ID**: PROP-20260810-CMARTIN-NODE
- **类型**: trading（涉及 C链节点定义 → 场景编排路由 → 交易路径）
- **创建时间**: 2026-08-10 09:30 UTC
- **状态**: ✅ IMPLEMENTED_VERIFIED（2026-08-10 方案A；V9等价6/6 + 基线锚点+6.27%；13:25重启已激活，待NEUTRAL实弹确认）
- **提交方**: dreamos-daily-monitor cron（每日监控七步闭环 第2步 Bug修复 / 第3步 交易评估）

---

## 背景与问题

场景→策略路由表 `dreamos/core/arrange/types.py` 将 **全部 NEUTRAL_* 场景**
（NEUTRAL_LOW/NORMAL/HIGH × ACCELERATING/DECELERATING/EXHAUSTION，共 8+ 条）
映射到节点 `C_MARTIN_V15`（v15 经典马丁策略节点）。

但 `C_MARTIN_V15`：
1. **未在 `config/nodes.yaml`（22 个节点）中注册**
2. **无实现文件**：`capabilities/trading/nodes/` 存在 c1_tech_scan/c2_momentum/
   c3_volatility/c5_exit_system，但**没有 c_martin_v15 相关实现**

## 故障证据（scheduler.log）

- `节点 C_MARTIN_V15 REDO 次数超限 (3 > 2), 强制跳到下一节点` × **95 次**（仅 08-10 当日）
- 首次出现：2026-08-08 22:06:08（与 graph_store checkpoint 更新同期）
- 每个 NEUTRAL 场景扫描周期：尝试执行 → 节点不存在 → REDO×3 → 强制跳过 → 走默认路径
- 跳过后的降级行为：`Symbol XXX A5正常执行 | path=full_sacg`（交易仍在产生，但**未经过 v15 马丁策略节点**）

## 影响评估

- **基线锚点 `6-TRADING/baselines/v15-six-trading-20260601` 是 v15 经典马丁策略**，
  C_MARTIN_V15 本应承载该基线策略。节点缺失 = 基线策略在 SACG 编排图中**断路**。
- A层"回测学习→编排优化"闭环（PROP-20260810-SCHEDPATHS 修复对象）写回
  orchestration_memory 后，若 L0-L2 查询命中 NEUTRAL 场景，同样会打到不存在的节点。
- 当前交易输出实际由默认 full_sacg 路径产生，**与 v15 基线语义不一致**，
  导致"回测对比基线"的评估基准本身失真。

## 候选方案（需人工决策，不擅动 SACG 语义）

1. **方案A（推荐）**：从基线 `6-TRADING/baselines/v15-six-trading-20260601/backtest_strategy.py`
   实现 `c_martin_v15.py` 节点 + 在 nodes.yaml 注册（handler 指向新类）。
   工作量：中等；语义影响：恢复基线路由，不新增语义。
2. **方案B**：将 types.py 中 NEUTRAL_* 路由改指向现有节点。
   ⚠️ 改变场景→策略映射语义，违背"回测对比 v15 基线"的锚点设定，不建议。
3. **方案C**：保持现状，接受 NEUTRAL 场景降级为默认路径。
   ⚠️ 需显式承认基线锚点失效，并更新 SSoT 与基线定义。

## 硬门禁声明

- 方案A 实现后**必须回测对比 v15 基线**，不优于基线 → 回退。
- 任何方案落地前，本提案等人审批，永不自动。
- 本提案不改动 SACG 四层（Sense/Arrange/Compute/Graph）语义定义。


---

## 实施记录（2026-08-10 13:31）

实施记录: c_martin_v15.py（230行，V9红线完整: 8%×vol_mult加仓/4%×vol_mult止盈/无止损/≤3次等额加仓）+ nodes.yaml 注册 + register_all 自动发现验证。测试: 运行时4/4（牛/熊/震荡/无价格）+ V9数学等价6/6（BTC/ETH/SOL×多空 vs 基线 run_screen2 L880-898）+ 基线离线回测锚点（BTC 400天 2025-07→2026-08: +6.27%, 胜率79.31%, 回撤2.41%, 夏普0.72）。13:15日志拍到节点缺失期 REDO 风暴实况（NEUTRAL→降级c_chain L3），13:25重启后节点已进注册表。
