# SPEC-M2: 宏观力传导与微观共振统一（50-NN主矛盾评估器）

> 版本：v0.1（调研设计稿）
> 日期：2026-11-09
> 状态：🟡 设计态，待评审；依赖 SPEC-M1 的 R0（信号活性）先行
> 关联：SPEC-M1（神经传递打通）、40 SPEC §1.1 五层传导、23 SPEC-主要矛盾识别（共振检测）
> 核心命题（用户原话）：宏观通过**直接影响龙头（神经链路），然后通过历史共振传导到具体标的**，实现宏观传导预测与微观共振的统一与矛盾识别——这有别于 23 自进化系统，是神经网络传导的特点。

---

## 零 · 问题定义

宏观对微观代币的影响有两个维度：

| 维度 | 内容 | 现状 |
|---|---|---|
| A. 弹性约束 | 宏观 → 仓位带/杠杆/多空数量上限钳位 | 已实现（40/43 包络 → 50 constraint_loader），SPEC-M1 保持不动 |
| B. 宏观力传导 | 宏观周期 → 龙头 → 板块 → 资金流向/洗盘 → **归一到具体代币的宏观力**，与微观力同维度对撞 | **缺失**。40 只发布 MACRO 级汇总信号，无标的归属；微观力（11-bcrm-tactical 等）是具体的，宏观力是模糊的，两者不在同一坐标系，无法对撞 |

维度 B 缺失的连锁后果（SPEC-M1 已实证）：50 内"宏观 vs 微观"没有对称两方；时序矛盾无对象；D2 资金/D4 情绪维度为空壳。

### 现有资产盘点（调研实证，2026-11-09）

40 已具备传导所需的**大部分原料，但都是静态快照，无共振计算、无标的归属**：

| 资产 | 内容实证 | 缺口 |
|---|---|---|
| `sector_transmission.json` | 四层链 L1_anchor(BTC)/L2_major(ETH,SOL)/L3_growth(AVAX,LINK,ADA)/L4_meme(DOGE,PEPE,WIF)；层级动量中位数、meme_vs_major_gap=-7.59%、regime=bull_consolidation；分层 breadth（L1 100%、L2 100%、全体 88.9%） | 仅同期动量对比，**无 lead-lag/相关系数**；expanding/contracting 判定未外发到标的级 |
| `washout_verdicts.json` | 每标的 verdict（label/confidence/trigger/samples）schema 已通 | **全标的 unknown/conf=0/trigger=false（unknown_fallback）——洗盘模块实质未激活**，R0 必须先修 |
| `fund_flow.json` | 存在（generated_at 同样停滞于 2026-10-26） | 停滞；未映射到标的级 |
| `p3_sector_transmission.py` | 传导梯度判定（expanding=资金下沉扩散 / contracting=缩回主流层=周期晚期信号）+ MA200 regime 联动 | 判定结果只进 cycle_state 摘要，不进总线 |
| 历史共振可行性（原型验证） | 用 40 token_sequence（1D，299 日）实测：ETH corr0=0.948/beta=1.30，SOL corr0=0.893/beta=1.31；滞后衰减 corr0→+1d→+2d = 0.95→0.82→0.71（ETH）| 证明共振系数可从现有数据稳定计算 |

---

## 一 · 核心机制：宏观力的三层传导

```text
宏观周期态 (L0: real_cycle + MA200 + breadth + regime)
    │  直接作用（神经链路第一跳，无衰减）
    ▼
L1 龙头 BTC 的宏观力 F_macro(BTC)
    │  历史共振传导（第二跳起，按共振系数衰减 + 滞后窗口）
    ▼
L2 ETH/SOL → L3 增长型 → L4 meme
    │  F_macro(s) = F_macro(上游) × R(s) ，R=共振系数（含滞后画像）
    ▼
每个标的的宏观力向量（D1趋势/D2资金/D4情绪/洗盘 四分量，归一 [-1,1]）
    │  与微观力（11-* 各源，同维度归一 [-1,1]）同坐标系对撞
    ▼
50：逐标的 × 逐维度 的共振确认 / 矛盾识别（时序矛盾、宏微观矛盾）
```

### 1.1 宏观力向量定义（每标的，4 分量）

| 分量 | 来源（40 已有资产） | 语义 |
|---|---|---|
| D1 趋势力 | real_cycle 方向 × MA200 锚点 × regime（expanding/contracting 加权） | 周期方向力 |
| D2 资金力 | fund_flow + 分层 breadth + layer_momentum 差（所在层 vs L1 层） | 资金是否正流向本层 |
| D4 情绪力 | meme_vs_major_gap、meme_platform 状态（L4 专属放大器） | 情绪过热/过冷 |
| 洗盘力 | washout_verdicts（R0 修复后）→ reversal intent，不下方向票，下调趋势力 continuation、上调尾部风险 | 沿用 SPEC §4.6 reversal 语义 |

### 1.2 共振系数 R(s)（历史共振画像，离线日更）

对每标的相对其**上游节点**（L2→BTC，L3→ETH，L4→SOL/DOGE 择主，预注册）计算：

```text
R(s) = {
  corr0:       同日收益相关（主传导强度，[-1,1]）
  lag_profile: {+1d: corr, +2d: corr}     # 滞后衰减画像 → 传导到达窗口
  beta:        对上游的收益 beta           # 力的放大系数
  down_corr:   上游大跌日(<-2%)的条件相关   # 防御性共振（下跌传导总是更强，实测=1.0）
  window:      60d 滚动 + 30d 最小样本，EMA 半衰期 20d
}
```

- 数据底座：40 `token_sequence.parquet`（原型已验证可算，见§零盘点）。
- 存储：40 侧 `resonance_matrix.json`（新增产出物，日更），42 适配器随 40 信号 payload 外发；50 只读。
- fail-open：样本不足 / 数据停滞 → R=恒等（corr0=1, 无衰减），审计 `degraded=resonance_fallback`。**禁止用静态默认值冒充**——R0 的 macro_stale 规则同样适用于 R。

**估计器风险（评审增补，P1 必须回应）**：滞后相关可能测的是"公共因子慢动"（common beta）而非真实"定向传导"。P1 回放需同时计算：①滞后相关（现方案）；②Granger 式检验（上游收益对标的未来收益的增量预测力，控制标的自相关后）；③按 regime 分组的条件 R。若 ② 不显著而 ① 显著 → 说明是公共 beta，传导语义降级为"宏观因子暴露"，t_arrive 机制禁用（t_arrive 只在存在真实 lead-lag 时启用）。regime 切换信号（40 regime 字段变更）触发 R 的即时重算，不等每周例行。

**矛盾去重（评审增补）**：t < t_arrive 时的宏微观反向**就是**时序矛盾的触发场景——时序矛盾是宏微观矛盾在存在传导滞后时的**裁决机制**，不是额外独立罚项。同一标的同一维度只允许生成一个矛盾对象：`存在有效 lead-lag → temporal_conflict（按到达窗口衰减微观）；无 lead-lag（upstream=none 或 Granger 不显著）→ macro_micro_conflict（按 SPEC-M1 horizon 规则裁决）`。禁止双重惩罚（置信度折半两次）。

### 1.3 标的级宏观力计算

```text
F_macro(L1=BTC) = F_cycle                       # 龙头直接承接宏观，无衰减
F_macro(s) = F_macro(upstream(s)) × corr0(s)    # 第二跳起按共振衰减
             × layer_gate(s)                    # 层门：expanding 时下层 ×1.0；contracting 时下层 ×0.5（资金缩回主流层）
强度 |F| 与置信度随跳数单调递减；beta 只放大期望幅度（expected_return 排序用），不放大方向强度。
滞后到达窗口：lag_profile 首个 <0.5×corr0 的偏移日 = 宏观力预期到达日 t_arrive。
```

**类别的力差别**（用户要点）：L1/L2 的宏观力以 D1/D2 为主；L3 以 D2 为主（资金传导滞后 1 跳）；L4 以 D4 为主（情绪放大器，meme_gap 权重翻倍），D1 权重减半——分量权重按层预注册（见下表），不自由学习。

| 层 | D1 趋势 | D2 资金 | D4 情绪 | 滞后 |
|---|---|---|---|---|
| L1 龙头 | 1.0 | 1.0 | 0.3 | 0d |
| L2 主流 | 0.9 | 1.0 | 0.5 | 0-1d |
| L3 增长 | 0.6 | 1.0 | 0.8 | 1-2d |
| L4 meme | 0.3 | 0.6 | 2.0 | 2d+ |

（数值为预注册先验，R2 后由历史共振回归校准，走训练门禁。）

---

## 二 · 归一化与矛盾识别

### 2.1 归一（宏观力与微观力同坐标系）

- 微观力：50 现有 path 的 `signed_conf = sign(direction) × confidence × weight（source 归一后，SPEC-M1 M3）`，按标的聚合到 [-1,1]。
- 宏观力：§1.3 的 F_macro(s) 各分量天然 ∈ [-1,1]。
- **同一标的 × 同一维度** 上形成力对：`(F_macro, F_micro)`。至此宏观力完成标的归属，"模糊宏观 vs 具体微观"的不对称消除。

### 2.2 三类矛盾对象（逐标的生成，进 50 contradiction.py，对齐 SPEC-M1 M5/M6）

| 矛盾 | 触发条件 | 裁决 |
|---|---|---|
| **宏微观矛盾** `macro_micro_conflict` | 同标的同维度，sign(F_macro) ≠ sign(F_micro)，且 \|双方\| ≥ 0.3 | 按 SPEC-M1 M6 的 horizon 规则：≤1d 微观主导 0.7；≥5d 宏观主导 0.7；过渡带各半折置信度 |
| **时序矛盾** `temporal_conflict`（狭义新增） | 宏观力未到达（now < t_arrive）但微观已反向；或宏观已到达但微观仍顺旧向 | 微观方向在 t_arrive 前有效但置信度按 `(1 - (t_arrive-now)/lag)` 衰减；到达后切换宏观主导。**时序矛盾不是压制微观，而是给微观一个有效期** |
| **维度间矛盾** | D1 看多 vs D2 资金流出 / D4 过热（如 meme_gap>15% 且 contracting） | 复用 23 四维权重的维度级裁决（SPEC-M1 M5 Step2）；防御性共振（down_corr）触发时 D2 空头力 ×1.3 |

### 2.3 共振确认（统一面）

- 宏观传导预测方向 == 微观共振方向（同标的同维度同号）→ `resonance_confirm`：置信度 ×1.10~1.15（沿用 SPEC §4.4 一致性奖励区间），并在 dominance 中合并为一股力（不重复计票）。
- 跨层共振加强：宏观力沿 L1→L2→L3 同号传递且各层微观力同号 → transmission_resonance，主矛盾 strength 上调一档（0.55→0.65 映射），作为"神经网络传导"特有的加强信号。

---

## 三 · 与 23 自进化系统的区别（设计声明）

| 维度 | 23 | 50（本 SPEC） |
|---|---|---|
| 共振定义 | **同期同 horizon** 多源信号方向一致度（≥0.6） | **跨层级 lead-lag 传导**的到达确认 + 同号加强；含时间结构（t_arrive/lag_profile） |
| 宏观角色 | 无独立宏观力，宏观仅经适配器做约束 | 宏观是一级矛盾力量，经龙头→共振衰减传导到每个标的 |
| 矛盾对象 | 维度间（C1-C8）为主 | 同维度内的宏微观力对 + 时序到达窗口 + 维度间 |
| 学习闭环 | W6 维度权重 | W6 维度权重 + 共振系数 R 的离线回归校准（40 侧，走 P5/P6 门禁） |

23 的既有共振/裁决/W6 机制**继续复用**（SPEC-M1 复刻清单不变）；本 SPEC 是在其上增加"传导"这一神经链路特有的时间与层级结构，不另起炉灶。

---

## 四 · 数据契约变更

1. **40 新增产出** `resonance_matrix.json`（日更，含 R(s) 全量 + 数据样本数 + generated_at）；`sector_transmission.json` 增补 `transmission.state/meme_gap` 已有字段经 42 外发（SPEC-M1 M7 同一通道）。
2. **42 适配器** cycle_state_adapter 增读 resonance_matrix，40 信号 payload 携带；washout_verdicts 修复激活后按 SPEC-M1 M7 同款外发。
3. **50 侧** mappings 增 `40-resonance` 源（role=macro_force，随 40-cycle 同权重族）；dimension_forces 消费标的级宏观力；contradiction.py 生成 §2.2 三类矛盾对象。
4. **新鲜度**：resonance_matrix 与 washout 纳入 M8 源年龄校验（ttl=168h/72h）。

## 五 · 依赖与阶段

| 依赖 | 说明 |
|---|---|
| SPEC-M1 R0（硬前置） | 40 流水线复活（否则 R 用死数据计算）、washout 模块激活（当前全 unknown_fallback）、CYCLE_STATE_BRIDGE 打开 |
| SPEC-M1 R1 | macro_force 角色、dimension_forces、contradiction 三步法先行落地 |
| 本 SPEC 阶段 | P1：resonance_matrix 离线计算 + 原型回放验证（用 token_sequence 复算 299 日，检验 F_macro 与后续收益的方向一致性）；P2：42 外发 + 50 归一化 + 宏微观矛盾；P3：时序到达窗口 + 维度间矛盾；P4：R 校准闭环 |

**P1 退出标准**：在 3+ 标的历史数据上，F_macro(s) 与 s 后续 5-20 日收益方向一致率 > 52%（宏观力本身弱先验，目标不是单独盈利而是为矛盾裁决提供有效一极）；t_arrive 窗口预测误差中位数 ≤ 1d。

## 六 · 验收清单

1. 任一标的可输出 `(F_macro, F_micro)` 四分量力对，且双方都在 [-1,1]；L4 标的的 D4 权重 ≠ L1（类别力差别可观测）。
2. 构造宏观转向 fixture：t < t_arrive 时微观方向票有效但衰减，t ≥ t_arrive 后宏观主导，审计含 temporal_conflict 对象与 t_arrive。
3. meme_gap>15% + contracting 时，D4 与 D1 的维度间矛盾被识别并记录。
4. 共振确认路径：宏微观同号时置信度提升 ≤1.15 且不重复计票（path 数不变）。
5. resonance_matrix 停滞 >7d 时 50 侧 degraded=resonance_stale，宏观力自动退化为 SPEC-M1 的约束通道。
