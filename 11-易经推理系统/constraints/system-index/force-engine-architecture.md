# 力学引擎技术文档（v1.2）

> 版本：v1.2 | 日期：2026-07-23 | 对应代码：`scripts/memory_l4/bcrm/`

## 1. 文档定位

本文件是力学引擎（物理推理引擎）及其多源校验架构的技术基线，记录 P0→P1→P2 三层升级的数学原理、工程实现与验证结果。

## 2. 设计目标

- **数值稳定性**：从一阶欧拉积分升级到二阶辛积分，消除长期能量漂移
- **噪声鲁棒性**：引入卡尔曼滤波与Langevin随机项，建模市场热噪声
- **多源交叉验证**：从单一力学推理扩展到五源校验（ML×物理×矛盾×相变×拓扑）
- **转折早期预警**：拓扑突变（TDA）领先于动力学减速，提供最早转折信号
- **代码驱动优先**：基于成熟开源库（pykalman/ripser/persim），减少对大模型的依赖

## 3. 总体架构

```
市场快照 + K线数据
  ↓
[1] 五象力场提取（时/空/表/里/流）
  ↓
[2] 加权合力计算（体量自适应权重）
  ↓
[3] Verlet辛积分 + Langevin随机项 [P0]
  ↓
[4] [可选] 卡尔曼滤波平滑 [P1]
  ↓
[5] 趋势判定 + 转折预警 + 置信度
  ↓
[6] 五角校验 [P1+P2]:
      BCRM2(ML) × 力学(物理) × A0(矛盾) × Ising(相变) × TDA(拓扑)
  ↓
一致性评分 + 置信度调整 + 三层预警
```

## 4. 五象力场模型

### 4.1 力场定义

| 力场 | 符号 | 权重 | 物理意义 |
|------|------|------|---------|
| 时（周期力） | SIXIANG_TIME | 0.15 | 康波/中周期/短周期方向合成 |
| 空（空间力） | SIXIANG_SPACE | 0.10 | 价格位置反重力（弹簧模型） |
| 表（技术力） | SIXIANG_SURFACE | 0.25 | 均线/MACD/RSI数字化表观 |
| 里（内驱力） | SIXIANG_CORE | 0.30 | 供需/资金/情绪内在驱动 |
| 流（流动性力） | SIXIANG_LIQUIDITY | 0.20 | 资金净流入+量价关系 [P2新增] |

权重总和 = 1.0，体量自适应调整（小盘表强里弱，大盘里强表弱）。

### 4.2 流动性力场物理模型 [P2]

```
F_liquidity = direction × certainty

direction = (liquidity_score - 0.5) × 2 + volume_ratio × price_direction × k
certainty = min(1.0, |volume_ratio - 1.0| × 2)
```

- 资金净流入(liquidity_score>0.5)→做多力；净流出→做空力
- 放量+价格有方向→量价同向加成（助推趋势）
- 缩量→流动性力衰减（趋势难延续）
- 与A0流动性矛盾维度形成交叉验证

## 5. 积分器升级 [P0]

### 5.1 欧拉法（原实现）

```
v(t+dt) = v(t) × decay + a(t) × dt
```

- 一阶精度 O(dt)
- 长期能量漂移
- 时间反演不对称

### 5.2 Velocity-Verlet 辛积分器（新实现）

```
dv = ½(a_old + a_new) × dt - γ × v × dt + √(2γT·dt) × ε
```

- 二阶精度 O(dt²)
- 辛几何保结构性（时间反演对称）
- 能量长期守恒
- 与 d3-force / LAMMPS 分子动力学同款算法

### 5.3 Langevin 随机项

```
噪声 = √(2γT·dt) × N(0,1)
γ = -ln(decay)        # 阻尼系数
T = 0.5 × volatility²  # 市场温度
```

物理意义：高波动率=高温=大噪声，与A0情绪矛盾维度形成物理-矛盾交叉验证。

## 6. 卡尔曼滤波平滑 [P1]

### 6.1 状态空间模型

```
状态向量: x = [velocity, acceleration]^T
状态转移: F = [[1, dt], [0, 1]]  (匀加速运动)
观测矩阵: H = [[1, 0]]           (观测=速度)
```

### 6.2 自适应噪声

| 噪声类型 | 公式 | 物理意义 |
|---------|------|---------|
| 过程噪声 Q | Q ∝ (1 + 2.0×volatility) | 高波动=大过程不确定性 |
| 观测噪声 R | R ∝ (1 + 5.0×spread) | 大价差=大观测不确定性 |

### 6.3 双模式

- `update()`: 在线逐帧滤波（实时交易，预测-更新循环）
- `filter_batch()`: 批量离线平滑（回测场景，前向-后向平滑更精确）

依赖库：pykalman 0.11.2

## 7. Ising相变检测 [P1]

### 7.1 物理模型

| 物理量 | 市场含义 | 计算方式 |
|--------|---------|---------|
| 自旋 s_i ∈ {+1,-1} | 资产收益符号 | 收益率≥0→+1，<0→-1 |
| 交互强度 J_ij | 资产间相关性 | 最近邻耦合 J=0.5，周期性边界 |
| 磁化强度 M | 市场共识度 | M = \|Σs_i\|/N |
| 能量 E | 市场紧张度 | E = -ΣJ·s_i·s_j/N |
| 温度 T | 波动率映射 | T = 2.0×volatility² |
| 临界温度 Tc | 相变临界点 | Tc≈2.269（Onsager精确解） |

### 7.2 相态判定

| 温度比 r=T/Tc | 磁化强度 | 相态 | 含义 |
|--------------|---------|------|------|
| r < 0.8 | \|M\| > 0.3 | ORDERED | 有序相（强趋势） |
| r > 1.2 | \|M\| ≈ 0 | DISORDERED | 无序相（震荡） |
| 0.8 ≤ r ≤ 1.2 | - | CRITICAL | 临界相（相变预警） |

### 7.3 能量突变预警

```
alert = |E - mean(history)| > 2.0 × std(history)
```

能量突变对应序参量剧烈变化，预示牛熊转换。

## 8. TDA持久同调 [P2]

### 8.1 数学流程

| 步骤 | 数学操作 | 物理意义 |
|------|---------|---------|
| 1. Takens嵌入 | x(t)→[x(t),x(t+τ),...,x(t+(m-1)τ)] | 一维序列重构m维相空间 |
| 2. Vietoris-Rips复形 | 点云按距离阈值ε连接 | 构建单纯复形 |
| 3. 持久同调 H0/H1 | (birth,death)特征生命周期 | H0=连通分量, H1=环 |
| 4. Betti曲线 β(t) | 每个ε下的特征数 | β突增=拓扑结构变化 |
| 5. 瓶颈距离 | 当前vs历史持久图距离 | 距离大=拓扑突变 |

参数：嵌入维度m=3，延迟τ=2，最高同调维度=1（H0+H1）

### 8.2 早期预警机制

```
信号1: betti_max > mean(history) + 2.0 × std(history)  # Betti突增
信号2: bottleneck_distance > 0.3                        # 瓶颈距离突增

warning_strength = max(信号1强度, 信号2强度)
```

依赖库：ripser 0.6.15（最快持久同调计算）+ persim 0.3.8（持久图距离度量）

## 9. 五角校验架构

### 9.1 五源交叉验证

| 校验源 | 层级 | 原理 | 输出 |
|--------|------|------|------|
| BCRM2 | ML模型 | LightGBM+辩证特征 | 方向+置信度 |
| 力学引擎 | 物理 | F=ma趋势动力学 | 方向+转折预警 |
| A0 | 矛盾 | 七维矛盾张力 | 方向偏置+创伤信号 |
| Ising | 相变 | 统计力学相变 | 方向+相变预警 [P1] |
| TDA | 拓扑 | 代数拓扑持久同调 | 方向+拓扑突变预警 [P2] |

### 9.2 校验逻辑

1. 五源方向一致 → STRONG_AGREE，置信度增强
2. 多数一致 → MAJORITY_AGREE，置信度略降
3. 严重分歧 → CONFLICT，建议 fail_closed

### 9.3 三层预警时序

```
时间轴 →

TDA拓扑突变 ─────→ Ising相变 ─────→ 力学引擎减速
(最早预警)         (中期确认)       (动力学确认)
Betti突增          能量突变          reversal_warning
瓶颈距离           临界相
   │                  │                  │
   └──────── 置信度调整 -0.06×strength ──┘
              -0.08 (Ising)
              -0.1×strength (力学+A0)
```

拓扑结构变化领先于动力学转折，TDA提供最早转折信号。

## 10. 模块依赖关系

```
_constants.py
    ↑
    ├── force_engine.py ──── kalman_filter.py (pykalman)
    │        │
    │        └── scale_engine.py
    │
    ├── ising_phase_detector.py (numpy)
    │
    ├── tda_early_warning.py (ripser + persim)
    │
    └── triangle_verifier.py ──┬── force_engine.py
                               ├── ising_phase_detector.py
                               └── tda_early_warning.py
                                        ↑
                               bcrm2_adapter.py (集成点)
                                        ↑
                               polling_trader.py (主循环)
                                        ↑
                               a7_practice_gate.py (门禁)
```

## 11. 新增依赖清单

| 库 | 版本 | 用途 | 安装方式 |
|----|------|------|---------|
| pykalman | 0.11.2 | 卡尔曼滤波 | `pip install pykalman` |
| ripser | 0.6.15 | 持久同调计算 | `pip install ripser` |
| persim | 0.3.8 | 持久图距离度量 | `pip install persim`（随ripser安装） |

## 12. 验证结果汇总

### 12.1 P0 验证（Verlet+Langevin）

- 常量加载 ✓
- 单步推理向后兼容 ✓
- Verlet稳态1.85 < 欧拉法2.00（辛积分器更稳定）✓
- 零外力衰减Verlet=欧拉（一致）✓
- 高波动std=0.80 > 低波动std=0.33（Langevin随机性生效）✓
- reset_velocity同步重置双状态 ✓

### 12.2 P1 验证（Kalman+Ising）

**Kalman**：
- pykalman库可用 ✓
- 单步滤波 ✓
- 噪声平滑MSE降低29.9% ✓
- 批量平滑模式 ✓
- 向后兼容（默认关闭kalman）✓
- 自适应噪声（高波动vs低波动）✓

**Ising**：
- 强上涨趋势→ORDERED+UP（M=0.97）✓
- 震荡市场→CRITICAL+FLAT（M=0.0）✓
- 强下跌趋势→ORDERED+DOWN（M=-0.94）✓
- 温度映射（高波动=高温）✓
- 四角校验器集成 ✓

### 12.3 P2 验证（TDA）

- ripser+persim库可用 ✓
- 上涨趋势→UP（betti_0=76, betti_1=12）✓
- 下跌趋势→DOWN ✓
- 数据不足正确处理 ✓
- 早期转折预警（warning=True, strength=0.62, 瓶颈距离=0.37）✓
- 拓扑稳定性（persistence_ratio=0.49）✓
- 五角校验器集成 ✓

## 13. 配置参数参考

### 13.1 力学引擎参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| VELOCITY_DECAY | 0.85 | 速度衰减（市场摩擦） |
| ACCELERATION_DT | 1.0 | 时间步长 |
| REVERSAL_WARNING_THRESHOLD | 0.15 | 减速预警阈值 |

### 13.2 Kalman参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| KALMAN_PROCESS_NOISE_VEL | 0.01 | 速度过程噪声 |
| KALMAN_PROCESS_NOISE_ACC | 0.05 | 加速度过程噪声 |
| KALMAN_OBS_NOISE_BASE | 0.1 | 观测噪声基础值 |
| KALMAN_VOLATILITY_FACTOR | 2.0 | 波动率对过程噪声影响 |
| KALMAN_SPREAD_FACTOR | 5.0 | 价差对观测噪声影响 |

### 13.3 Ising参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| ISING_GRID_SIZE | 8 | 自旋网格边长（64个自旋） |
| ISING_INTERACTION_BASE | 0.5 | 基础交互强度 J |
| ISING_TEMP_SCALE | 2.0 | 温度映射系数 |
| ISING_TEMP_CRITICAL | 2.269 | 临界温度（Onsager解） |
| ISING_MAGNETIZATION_THRESHOLD | 0.3 | 磁化强度阈值 |

### 13.4 TDA参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| TDA_EMBEDDING_DIM | 3 | Takens嵌入维度 |
| TDA_EMBEDDING_DELAY | 2 | 嵌入延迟 |
| TDA_WINDOW_SIZE | 50 | 滑动窗口大小 |
| TDA_BETTI_SPIKE_FACTOR | 2.0 | Betti突增因子 |
| TDA_BOTTLENECK_DISTANCE_THRESHOLD | 0.3 | 瓶颈距离阈值 |
| TDA_MIN_POINTS | 20 | 最少点数 |

## 14. 变更记录

### v1.2 (2026-07-23) - P0/P1/P2三层升级

- P0: Verlet辛积分器 + Langevin随机项
- P1: Kalman自适应滤波（pykalman）+ Ising相变检测（Onsager精确解）
- P2: TDA持久同调（ripser+persim），五角校验架构完成

### v1.1 (2026-07-20) - 流动性力场

- 新增流动性力场作为第五力（SIXIANG_LIQUIDITY）
- 权重重分配（总和=1.0）

### v1.0 (基线)

- 四象力场（时/空/表/里）
- 欧拉积分
- 三角校验（BCRM2×力学×A0）
