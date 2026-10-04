# 事件驱动策略系统 — 技术设计

> **版本**：v1.0 | **更新日期**：2026-10-04
> **关联 SPEC**：SPEC-事件驱动策略独立化-共享事件层与弹性约束.md v1.2

## 1. 设计定位

事件驱动策略 = **离散单点事件的冲击响应**（脉冲，小时-天尺度），与趋势策略（连续价格序列方向性判断，天-周尺度）形成互补。

**初期定位**：独立子交易系统（与 BCRM2.0、BDSM 平级），独立运行、归因清晰。
**成熟后定位**：开放接口，EventSignal 可被其他子系统消费。

## 2. 核心逻辑：买预期，卖事实

| 阶段 | 市场行为 | 策略偏向 |
|------|---------|---------|
| 预期积累 | 提前消化利空，价格先跌 | 空头 |
| 事件落地 | 利空出尽，资金反手 | 多头 |
| 重定价 | relief rally 验证 | 多头验证 |

**关键驱动**：实际利率 = 名义利率 - 通胀预期
- 通胀涨幅 > 加息速度 → 实际利率下行 → 金价上涨

## 3. 5 维评分体系

| 维度 | 权重 | 说明 |
|------|------|------|
| ① surprise_score | 25% | `(actual-expected)/σ` 标准化惊喜度 |
| ② priced_in_score | 20% | 定价充分度（ratio=预期涨跌/历史平均反应） |
| ③ real_rate_score | 20% | 实际利率方向（水平60% + 变化率40%） |
| ④ resilience_score | 15% | 价格在利空下的抗跌性（通用化） |
| ⑤ cross_asset_score | 20% | 跨资产同步验证（tanh 标准化） |

## 4. 单点脉冲算法

```
impulse(t) = strength × exp(-t / τ)
```

- τ 按事件类型：FOMC=3.0天, CPI=2.0天, NFP=1.5天, PPI=1.0天
- t > 3τ → 脉冲趋于 0
- 弹性修正：顺势（elasticity>0）同向增强，逆势（elasticity<0）反向

## 5. 阶段动态阈值

| 阶段 | long 阈值 | short 阈值 |
|------|----------|-----------|
| pre_event | 0.70 | 0.30 |
| expectation_jump | 0.65 | 0.32 |
| event | 0.55 | 0.40 |
| repricing | 0.60 | 0.35 |

## 6. EventDrivenTrader 独立子交易系统

### 6.1 核心职责

| 环节 | 逻辑 |
|------|------|
| 开仓 | signal != neutral + strength ≥ 阶段阈值 + 无持仓 |
| 仓位 | base × strength × phase_mult × elasticity_mult |
| SL/TP | ATR 自适应（SL=4-6×ATR, TP=3×SL）+ 事件窗口约束 |
| 离场 | 脉冲衰减（t>3τ）/ 事件窗口结束 / SL / TP / 信号反转 |

### 6.2 FAIL-OPEN 策略

| 异常场景 | 处理 |
|----------|------|
| EventDrivenStrategy.evaluate() 抛异常 | 返回 neutral，不影响主链路 |
| 数据缺失 | 各评分维度返回 0.5 中性 |
| ATR=0 | SL/TP 硬编码下限 4%/12% |
| 仓位上限 | ≤250 USDT 名义（与 BDSM 单币预算一致） |

## 7. ConvictionScorer 6 因子置信度

| 因子 | 权重 | 说明 |
|------|------|------|
| primary_contradiction | 25% | 主要矛盾清晰度 |
| cross_asset | 20% | 跨资产验证一致性 |
| technical | 15% | 技术面信号强度 |
| capital_flow | 15% | 资金流方向 |
| data_quality | 10% | 数据完整度 |
| fundamental_verification | 15% | 基本面验证 |

**过滤档位**：
- ≥ 0.85 → hard（覆盖其他子系统）
- 0.70-0.85 → soft（加权增强 ±0.10）
- < 0.70 → none（不过滤）

## 8. EventDominanceController 安全机制

- 双层门控：`enable_contradiction_driven_layer` + `enable_event_dominance`
- 连续 3 笔亏损自动降档（hard→soft→pass_through）
- 1 小时置信度漂移 >0.15 立即降档
- 降档单调（只能向下，不自动恢复；`reset_downgrade()` 人工重置）
- FAIL-OPEN：异常返回 False（安全默认）

## 9. 弹性约束关系

事件冲击方向 × 趋势方向 = 4 种弹性组合：

| 事件方向 | 趋势方向 | 弹性 | 策略含义 |
|---------|---------|------|---------|
| 利多 | 上升 | +1.0 | 顺势强化，趋势跟随加仓 |
| 利多 | 下降 | -0.7 | 逆势反弹，做空机会 |
| 利空 | 上升 | -0.7 | 逆势回调，做多机会 |
| 利空 | 下降 | +1.0 | 顺势强化 |

## 10. 与其他子系统边界

| 子系统 | 关系 |
|--------|------|
| 23-自进化 | 初期独立；成熟后 SubSystemBridge.get_event_signal() 消费 |
| 11-BCRM2.0 | 初期独立；Phase 4 作为反向风险闸门 |
| 11-战略层 | 不修改 enable_five_domain（保持 False） |
| 14-V15 | 完全独立，本系统不涉及 |
