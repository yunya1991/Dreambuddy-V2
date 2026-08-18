# Dream-MultiSkill 工程架构基线（v1.0）

## 1. 文档定位

本文件是 Dream-MultiSkill 的工程架构基线，用于统一以下事项：

- 分层关系与职责边界
- 工作流通信与调用方向
- 经验沉淀到约束的闭环机制
- 版本治理、审计与回滚规则

适用范围：`constraints/`、`workflows/`、`artifacts/`、`skills/`、`docs/`。

## 2. 总体架构分层

```text
┌─────────────────────────────────────────────────┐
│ 底层约束层 (constraints/)                      │
│ - constitution/ - system-index/                │
│ - workflows-spec/ - faq/                       │
└─────────────────────────────────────────────────┘
                    ↓ 约束
┌─────────────────────────────────────────────────┐
│ 记忆工作流 (workflows/memory/) - 底座         │
│ - L1/L2/L3/L4 + review + distill + index + stats │
└─────────────────────────────────────────────────┘
                    ↓ 服务
┌─────────────────────────────────────────────────┐
│ 并联工作流 (四条线)                            │
│ - governance/ trading-decision/ knowledge/ evolution/ │
└─────────────────────────────────────────────────┘
```

核心原则：

- 约束层是唯一规则源（SSOT）。
- 记忆工作流是共享底座，不直接改写约束层。
- 并联工作流按职责分工协作，统一输出到 `artifacts/`。

## 3. 目录架构（当前标准）

```text
dream-multiskill-v2/
├── constraints/
│   ├── constitution/
│   ├── system-index/
│   ├── workflows-spec/
│   └── faq/
├── workflows/
│   ├── memory/
│   ├── trading-decision/
│   ├── governance/
│   ├── knowledge/
│   └── evolution/
├── skills/
├── artifacts/
│   ├── trading/
│   ├── memory/
│   ├── governance/
│   ├── knowledge/
│   └── evolution/
├── docs/
└── .github/workflows/
```

## 4. 三大初期迁移对象与职责

### 4.1 底层约束层（constraints）

- `constitution/`：系统最高约束与原则。
- `system-index/`：架构索引、组件边界、依赖地图。
- `workflows-spec/`：各工作流输入/输出契约、阶段责任、门禁规则。
- `faq/`：常见运行约束与外部系统问答（如 OKX API）。

### 4.2 记忆工作流（workflows/memory）

- 作为底座提供查询、回写、蒸馏、索引、统计服务。
- 维护 L1-L4 生命周期与可追溯证据链。
- 为交易决策和并联工作流提供经验支撑。

### 4.3 交易决策工作流（workflows/trading-decision）

- 承担 A0-A9 决策链编排与产物输出。
- 每阶段执行前后都必须带约束校验与记忆引用。
- 输出统一落地到 `artifacts/trading/`。

## 5. 通信与调用结构（必须遵守）

### 5.1 方向约束

- `constraints -> memory / trading-decision / governance / knowledge / evolution`
- `memory -> trading-decision`（服务调用）
- `trading-decision -> memory`（回写 episode/case）
- `memory -> evolution`（提交约束候选）
- `evolution -> constraints`（唯一允许的约束升级通道）

### 5.2 禁止项

- 禁止 `memory` 直接修改 `constraints`。
- 禁止 `trading-decision` 绕过约束校验直接执行关键动作。
- 禁止无 `trace_id` 和无证据引用的产物进入主链。

## 6. 记忆沉淀到约束的闭环（关键机制）

```text
memory 经验沉淀
  -> 形成 constraint_candidate
  -> evolution/feedback 接收
  -> evolution/audit 评估
  -> evolution/sandbox 回放与压测
  -> (通过) 写入 constraints 新版本
  -> (失败) 驳回并记录原因
  -> evolution/rollback 持续监控与回滚
```

闭环规则：

- 经验升格为制度必须经过 `workflows/evolution/`。
- 每条约束变更都要绑定来源证据：`episode_id/case_id/distill_id`。
- 所有约束发布必须可回放、可审计、可回滚。

## 7. 统一数据契约（v1）

建议所有关键产物统一包含：

- `trace_id`：一次完整决策链唯一 ID
- `stage_id`：A0-A9 或 memory 子阶段标识
- `constraint_version`：执行时使用的约束版本
- `memory_refs[]`：引用的记忆实体 ID
- `evidence_refs[]`：证据文件路径或证据 ID
- `timestamp`：UTC 时间戳
- `decision_summary`：阶段结论摘要

## 8. 运行与治理要求

- Fail-closed：约束校验失败时默认中止关键执行。
- 审计优先：所有主链动作必须可生成审计产物。
- 小步发布：约束升级先沙箱，后主链。
- 回滚可用：每个约束版本都要有回滚目标。

## 9. 构建顺序（执行建议）

1. 固化约束层基线与工作流契约文档。
2. 接入 memory 与 trading-decision 的最小同步调用链。
3. 打通 `memory -> evolution -> constraints` 升级闭环。
4. 建立架构门禁（字段完整性、版本一致性、证据可追溯）。

## 10. 版本信息

- 版本：v1.0
- 状态：基线生效
- 维护目录：`constraints/system-index/`
- 对应通信契约：`constraints/workflows-spec/communication-contract-v0.1.md`

## 11. 变更记录

### v1.1 (2026-07-20) - 震荡市增强器集成

**背景**：易经推理模型连续10次亏损，经A8批判性分析定位核心矛盾为趋势跟踪模型与震荡市环境错配。

**新增模块**：
- `scripts/memory_l4/ranging_market_enhancer.py` - 震荡市增强器
- `scripts/memory_l4/enhancer_backtest_engine.py` - 增强器回测引擎

**集成点**：
- `polling_trader.py` 开仓决策链（`enhance()` 调用）
- `trading_utils.py` TradeRecord 新增 `enhance_info` 字段

**5项优化措施**：
1. MA200方向性偏向 - 长期趋势过滤反向信号
2. 布林带双信号确认 - 震荡市必须双重确认
3. 动态止损宽度 - 按市场状态调整ATR倍数
4. 置信度校准机制 - 预测-实际胜率校准表
5. 市场环境自适应 - 5种状态差异化参数

**回测验证**：
- 最大回撤降低 54%-87%
- 交易频率降低 80%-96%
- ETH实现从亏损到盈利的转折（-9.4% → +1.5%）

**详细文档**：`constraints/system-index/ranging-market-enhancer.md`

### v1.2 (2026-07-23) - 力学引擎物理推理升级与五角校验架构

**背景**：力学引擎（物理推理引擎）作为趋势策略的核心组件，原实现存在数值稳定性不足（一阶欧拉积分）、噪声过滤缺失、单一校验源等问题。引入高级数学/物理学算法，构建多源交叉校验架构，提升信号可靠性。

**新增模块（3个）**：

| 模块 | 文件 | 职责 | 依赖库 |
|------|------|------|--------|
| 卡尔曼滤波器 | `scripts/memory_l4/bcrm/kalman_filter.py` | 速度-加速度贝叶斯状态估计，过滤市场高频噪声 | pykalman 0.11.2 |
| Ising相变检测器 | `scripts/memory_l4/bcrm/ising_phase_detector.py` | 二维Ising模型统计力学相变检测（Onsager精确解） | numpy |
| TDA早期预警器 | `scripts/memory_l4/bcrm/tda_early_warning.py` | Takens嵌入+Vietoris-Rips持久同调，转折点最早预警 | ripser 0.6.15 + persim 0.3.8 |

**修改模块（3个）**：

| 模块 | 文件 | 变更内容 |
|------|------|---------|
| 力学引擎 | `scripts/memory_l4/bcrm/force_engine.py` | 四象→五象力场（新增流动性力）、欧拉→Verlet辛积分+Langevin随机项、集成可选Kalman后处理 |
| 常量定义 | `scripts/memory_l4/bcrm/_constants.py` | 新增流动性力场常量、Kalman参数、Ising参数、TDA参数共26个 |
| 三角校验器 | `scripts/memory_l4/triangle_verifier.py` | 三角校验→五角校验（BCRM2×力学×A0×Ising×TDA），集成三层预警 |

**三层升级（P0→P1→P2）**：

1. **P0 地基升级**：Verlet辛积分器（二阶精度，时间反演对称）+ Langevin随机项（市场热噪声）
2. **P1 双向增强**：
   - Kalman自适应滤波（pykalman库，过程噪声Q∝波动率，观测噪声R∝买卖价差）
   - Ising相变检测（磁化强度M=市场共识度，能量E=市场紧张度，温度T∝波动率²，临界温度Tc≈2.269）
3. **P2 最早预警**：TDA持久同调（Takens嵌入重构相空间，Vietoris-Rips复形，Betti曲线突增+瓶颈距离）

**五角校验架构**：
```
BCRM2(ML模型)     ──┐
力学引擎(物理)     ──┤  五角校验 → 一致性评分 + 置信度调整 + 风险预警
A0(矛盾分析)      ──┤
Ising(相变)       ──┤
TDA(拓扑)         ──┘
```

**三层预警时序（由早到晚）**：
1. TDA拓扑突变（最早）— Betti突增/瓶颈距离，拓扑结构变化领先于动力学
2. Ising相变（中期）— 能量突变/临界相，统计力学相变信号
3. 力学引擎减速（确认）— reversal_warning，动力学转折确认

**验证结果**：
- 五象力场权重总和=1.0000 ✓
- Verlet稳态1.85 < 欧拉法2.00（辛积分器更稳定）✓
- Kalman噪声平滑MSE降低29.9% ✓
- Ising强趋势识别（M=0.97 ORDERED）✓
- TDA早期转折预警（warning=True, strength=0.62）✓
- 五角校验端到端集成 ✓

**详细文档**：`constraints/system-index/force-engine-architecture.md`
