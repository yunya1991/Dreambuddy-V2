# PROP-20260818 BCRM 2.0 满仓算力倾斜 + 三维度离场时机优化

> **链状态**: D链✅(产出=用户需求驱动提案) → Z1✅代码扫描 → Z2✅架构设计 → Z3 本文档 → 待 用户决策 Gate → E链代码实现
> **扫描范围**: `scripts/memory_l4/polling_trader.py#L3898-L4173`（run_once 主循环）+ `scripts/memory_l4/polling_trader.py#L2234-L3013`（_execute_trade 离场分支）+ `scripts/memory_l4/yijing_exit_system.py`（主离场系统）+ `scripts/memory_l4/bcrm2/triple_barrier_labeler.py`（三重屏障标签）+ `scripts/memory_l4/bcrm2/dialectical_ml_engine.py`（L3推理输出）
> **设计版本**: v1.0 | **创建日期**: 2026-08-18 | **状态**: 待用户确认

---

## 一、背景与问题定义（Z1 扫描关键发现）

### 1.1 用户需求锚点

实盘观察到的典型场景：
> "易经推理 BCRM 2.0 买入和卖出币种，入场后确实有一定盈利，但是入场之后计算不足。理论上满仓 3 单之后，应该把更多推理资源投入到现有持仓标的的最佳离场时机上，其他没持仓的币种计算已经不重要。"

离场时机关注三个维度：
1. **最佳离场K线数预测**：预测未来 1/2/3/6 根 K 线的方向延续/反转概率，找到收益拐点；
2. **风险-价值综合评估**：量化"继续持仓的期望收益 vs 下行风险"，主动决策走/留/调；
3. **超时排名止盈**：持仓一定时间后，把持仓 vs 新候选做综合排名止盈换仓，不硬等 29h 超时。

### 1.2 现状硬伤（代码证据级）

现有 `run_once` 主循环 [polling_trader.py#L3898-L4173](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L3898-L4173) 的算力分配呈现**"空仓/满仓一视同仁"**：

| 阶段 | 当前做法 | 满仓时的浪费 | 单轮耗时估算（15 币种） |
|---|---|---|---|
| ① 异常检测 | 对 self.coins 全部币种（15 个）拉 K 线 + `AnomalyDetector.get_summary()` | 满仓 3 单后，**12 个无持仓币种**的异常结果永远不会触发开仓（L4132 `>=max_positions` 直接 break） | ~15s |
| ② 全币种推理 | 全部币种跑完整 `_fetch_and_infer`：OKX 160+ 根 K 线 + BCRM 2.0 9 模块 518 特征 + LGBM 训练/推理 + 五角校验 | 无持仓币种的完整推理结果被丢弃 90%；3 个持仓币只拿到了和"开仓前同密度的一次方向推理"，没有任何额外的离场专用算力倾斜 | 20~40s |
| ③ 持仓管理（离场评估） | 复用阶段②产出的 inference：`signal_reverse`(UP↔DOWN 对比) + `P3 early_exit` + `yijing_exit_system.evaluate`（卦象风险/价值分 6 动作） + 29h 超时后 `timeout_profit_switch` 排名 + classic 备用 | **核心硬伤**：BCRM 2.0 真正的预测能力（多 horizon 方向概率、EV 量化）在持仓阶段被浪费了，只用了卦象+信号反转两个弱信号；超时排名止盈要等 29h 才启用（太滞后） | 2~5s |

**满仓时实际算力浪费率**：异常检测 80% + 阶段②推理 85% ≈ 单轮 **83% CPU/IO 预算纯浪费**，而离场精细评估只拿到 <17% 资源。这直接导致用户观察到的"入场后计算不足"。

### 1.3 现有离场链路的行为边界（Z1 事实清单）

| 离场类型 | 触发位置 | 触发条件 | 问题（本提案要解决的） |
|---|---|---|---|
| 信号反转平仓 | `_execute_trade#L2272-L2349` | pos_side 与 inference 方向相反 + 置信度超阈值 + 2 次确认 | 只用了方向 UP/DOWN，没看"反转在未来 1~3 根是否确认" |
| P3 提前退出 | `_execute_trade#L2354-L2413` | inference.early_exit_signal=True（TDA+Ising 预警）+ 2 次确认 | 没结合 BCRM 未来 EV，可能假预警止盈或漏掉真风险 |
| 29h 超时排名止盈 | `_execute_trade#L2450-L2536` | `position_age_sec > 104400`(29h) + `upl > 0` + 有更强候选置信度 | **只在盈利+超时才触发，太滞后**；排名只看置信度一个维度，没结合浮盈/EV/延续分 |
| 易经主离场（6 动作） | `_execute_trade#L2546-L2827` | 卦象→风险分/价值分→ FORCE_CLOSE / RAISE_TP / LOWER_SL / LOWER_TP / TIGHTEN_SL / HOLD | **只基于卦象**，没有 BCRM 2.0 的量化 EV 与多 horizon 概率融合 |
| 经典备用离场 | `_execute_trade#L2867-L3013` | 持仓超时>29h 且易经离场不可用 | 最后兜底层，没问题，不用改 |

**结论**：离场系统的行为边界和设计初衷一致，但**完全没有把 BCRM 2.0 的核心能力（多 horizon 预测 + 量化EV）作为输入**，这是本次要补的核心缺口。

---

## 二、设计原则（Z2 设计前置约束）

> 所有后续实现必须符合以下原则，违反则判定为设计回退。

1. **算力分配按持仓率反线性倾斜**：`持仓占用率 = current_positions/max_positions`，占用率越高，推理算力越往持仓币转移（不是二元切，是连续 0→1 平滑过渡）。
2. **离场决策的多源融合，不是替换**：保留现有 4 类离场判断（信号反转 / P3 预警 / 卦象主离场 / 经典备用），新增"BCRM 多 horizon + EV + 排名止盈"融合层，**融合层优先级高于卦象主离场，低于信号反转和 P3 预警（这俩是硬风控）**。
3. **渐进式三阶段落地**：Phase A 只做算力重分配（零离场逻辑改动，风险最低）→ Phase B 做 EV 雷达（也不动 BCRM 训练流程）→ Phase C 上多 horizon + 排名止盈（重头戏，有回测保护）。每阶段独立验证可回退。
4. **所有新增阈值有进化接口**：EV 权重、强制离场阈值、排名系数都挂 `_load_evolution_config`，支持自进化引擎调参（不硬编码死）。
5. **实盘可观测性**：每轮轮询输出 MODE、算力分配比例、3 个持仓币的 EV/最佳K线数/排名分，写入 trader_*.jsonl 审计日志，同时飞书告警有"满仓切换模式"的心跳事件。

---

## 三、总体架构

### 3.1 满仓 MODE 切换（三维度的算力底座）

```
                    ┌─────────────────────────────────────────┐
                    │          run_once 入口                  │
                    │  Step0. 风控预检查 + 持仓占用率计算      │
                    │  occupancy = current_pos / max_positions │
                    └─────────────────────┬───────────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
     ┌──────────────────┐      ┌──────────────────┐       ┌──────────────────────┐
     │  MODE 1 空仓/轻仓 │      │  MODE 2 半仓      │       │  MODE 3 FULL 满仓 ★  │
     │  occupancy 0,1    │      │  occupancy 2      │       │  occupancy = 3       │
     ├──────────────────┤      ├──────────────────┤       ├──────────────────────┤
     │ 异常检测: 全币种 │      │ 异常检测: 持仓 +  │       │ 异常检测: 仅持仓3币  │
     │ 推理分配: 90%开仓 │      │ Top4 候选         │       │ + Top3 候选（粗筛）  │
     │        10%持仓   │      │ 推理分配: 50%持2  │       │ 推理分配: 70% 持仓3  │
     │ 离场评估: 现状   │      │        50% 开仓   │       │ （每币额外多horizon）│
     │                  │      │ 离场评估: 现状   │       │           30% Top3   │
     └──────────────────┘      └──────────────────┘       │ （粗版推理，降特征 ） │
                                                           │ 离场评估: ★三维度新  │
                                                           └──────────────────────┘
```

**MODE 判定伪代码**：

```python
current_positions = self._count_total_positions()   # OKX 实际持仓数
occupancy_rate = current_positions / self.max_positions
if occupancy_rate >= 1.0:
    mode = "MODE3_FULL"          # 满仓（≥3），核心模式
elif occupancy_rate >= 0.67:
    mode = "MODE2_HALF"          # 半仓（2）
else:
    mode = "MODE1_LIGHT"         # 空仓/轻仓（0 或 1）
```

### 3.2 三维度离场融合架构（MODE3 内部结构）

```
              对每个持仓币 coin 执行：
 ┌─────────────────────────────────────────────────────────────────────┐
 │① K 线/浮盈/年龄更新（基础，和现状一致）                                │
 └──────────────────────────┬──────────────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │② ★ PhaseC: BCRM 多 horizon 预测（维度 1）                            │
 │   horizons: [1,2,3,6,10,20,30] → 每个输出 P_up(h) / P_down(h)       │
 │   → 合成：短期延续曲线 S(k)、远期饱和曲线 L(k)                        │
 │   → 输出：HORIZON_K_STAR（最佳离场K线数）、SHORT_TERM_REVERSAL_RISK、 │
 │          CONTINUATION_SCORE（拿6h吃掉20h利润的比例）                │
 └──────────────────────────┬──────────────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │③ ★ PhaseB: 风险-价值 EV 雷达（维度 2）                               │
 │   7 信号加权合成：方向一致(28) + BCRM期望收益(22) + 卦象价值(20)     │
 │                    - 卦象风险(15) - 回撤压力(10) - 波动惩罚(05)     │
 │                    - 价值超时衰减(10)                                │
 │   → 输出：EV ∈ [-1, +1]（4档强持/观察/预警/强平）                    │
 └──────────────────────────┬──────────────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │④ 现有硬风控优先级（不替换，先跑）                                      │
 │   → 静态 SL/TP 命中 → OKX端已自动平 → 本地清理                        │
 │   → 信号反转（signal_reverse）+ 2次确认 → 平仓反手                    │
 │   → P3 提前退出（TDA+Ising）+ 2次确认 → 平仓                         │
 │   → 维度1 SHORT_TERM_REVERSAL_RISK > 阈值 + 有盈利 → 收紧止损/降止盈 │
 └──────────────────────────┬──────────────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │⑤ ★ Phase B+C: EV 融合决策（主离场决策层）                            │
 │   → EV < -0.35 → 离场确认后 FORCE_CLOSE（优先级高于卦象主离场）       │
 │   → EV ∈ [-0.1, +0.3] → NO_INTERVENE（传给卦象做动态 SL/TP 微调）    │
 │   → EV > +0.3 → LOWER_SL / RAISE_TP（交给 yijing_exit_system 接口） │
 └──────────────────────────┬──────────────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │⑥ ★ PhaseC: 持仓排名止盈（维度 3）                                    │
 │   排名对象：3 持仓币 × Top3 候选池 → 综合排名分 = 0.4EV + 0.3 浮盈  │
 │                                                   + 0.3 延续分       │
 │   A档（立即）/ B档（排队）/ C档（保护期内不参与）                    │
 │   → A/B 档止盈后，资金腾给 Top1 候选（走现有新开仓排名路径）          │
 └──────────────────────────┬──────────────────────────────────────────┘
                            ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │⑦ 现有易经卦象主离场 + Classic 备用（兜底层，不受影响）                │
 └─────────────────────────────────────────────────────────────────────┘
```

---

## 四、详细设计（Z3 执行层面的规格）

### 4.1 Phase A：满仓算力重分配（零离场逻辑改动，风险最低）

**目标**：单轮轮询耗时从 ~45s → ~20s；MODE3 时把节省的 25s 预算留给后续 Phase B/C（暂不启用 B/C 时，就是更快完成一轮，减少推理和行情的时间错位）。

#### 4.1.1 MODE1 / MODE2 / MODE3 三档具体行为

| 项目 | MODE1（0-1 单） | MODE2（2 单） | MODE3（3 单 = 满仓）|
|---|---|---|---|
| **异常检测币种集** | `self.coins` 全部（现状） | 持仓 2 币 + 其他币种 Top4（按昨日波动率+历史交易数预排） | 持仓 3 币 + 候选 Top3（其他币种跳过） |
| **异常检测拉K** | 现状 每币 100 根 | 同上，每币 100 根 | 持仓币 100 根，候选只拉 30 根（只看极端异常） |
| **完整推理币种集** | `self.coins` 全部（现状） | 持仓 2 币（完整推理 160 根 K）+ 其他币种按粗筛分数取 Top5（完整推理） | 持仓 3 币（**增强推理**，Phase B/C 启用）+ 候选 Top3（**粗版推理**：80 根 K + 只跑 bagua+classic_exp+trend 模块，不跑 cross_asset/macro/cycle，不做 LGBM 重训（只 inference 缓存模型），得到粗置信度 + 粗方向就停） |
| **完整推理开关** | 现状 BCRM 2.0 全流程 | 持仓 2 币全流程，候选 Top5 全流程 | 持仓 3 币全流程 + 增强；候选 Top3 **关闭五角校验、关闭 A7 门禁（因为不实际开仓，只是排优先级）** |
| **日志输出** | 现状 | 追加日志头 `[MODE2 半仓]` + 算力分配比例 | 追加日志头 `[MODE3 FULL]` + 算力分配比例 + 候选粗筛 Top3 列表 |
| **新开仓排名** | 现状全候选 | 现状全候选（候选池足够大） | **注意**：候选 Top3 粗版推理的置信度不能直接用于开仓，只能当"排名参考"——真要开仓（平仓腾资金后），要对排名第 1 的候选补跑一次完整推理（和现状全流程一致），通过 A7 + 五角校验才下单。这条是 MODE3 的安全底线。 |

#### 4.1.2 缓存层（Phase A 就加，后续 Phase B/C 共用）

新增实例缓存字典（生命周期 = 跨轮询，带 TTL），挂在 `PollingTrader` 上：

| 缓存 Key 结构 | Value | TTL（轮询数） | 用途 |
|---|---|---|---|
| `("anomaly", coin, cycle_id)` | anomaly_summary 结果 | 2（下一/下下轮）| MODE3 时无持仓币的异常检测结果跳过拉取时，直接用缓存兜底 |
| `("inference_coarse", coin, bar_ts_rounded_1h)` | coarse_inference {direction, confidence, fail_closed, is_ranging} | 2 | MODE3 候选粗版推理缓存，1h 内同一整点 K 线不重算 |
| `("kline_short", coin, bar, limit)` | 最新 limit 根 K 线 list | 1 | 粗推理拉到的 80 根 K 线，供后续完整推理复用（减少 OKX API 调用） |
| `("position_horizon_preds", coin, bar_ts_rounded_1h)` | dim1 的 S(k)/L(k)/HORIZON_K_STAR 三元组 | 2 | Phase C 用，持仓币 1h 内不重跑多 horizon 训练 |
| `("position_ev", coin, bar_ts_rounded_1h)` | dim2 的 EV + 7 子分 | 2 | Phase B 用，1h 内复用 |

**缓存写入点**：对应拉取/推理完成后立即写；**读取失效**：bar_ts_rounded_1h 推进到下一小时后自动失效（用"最近 K 线收盘价时间戳"判断，不需要系统时间对齐，避免时区错）。

#### 4.1.3 Phase A 文件变更清单（零离场逻辑）

| 文件 | 操作 | 变更点 |
|---|---|---|
| `scripts/memory_l4/polling_trader.py` | 修改 | `run_once` 主循环重写：Step 0 预检查 MODE 判定 → Step 1 异常检测按 MODE 过滤币种集合 → Step 2 推理阶段分 full/coarse → Step 3 MODE3 时，新开仓前对 Top1 补全完整推理 → 新增缓存字典 + 读取/写入逻辑 → 日志头打印 MODE + 算力分配 |
| `scripts/memory_l4/bcrm2_adapter.py` | 修改 | `BCRM2Adapter` 新增 `predict_coarse(...)` 接口：只启用 `[bagua_feature_engine, classic_experience_features, market_regime]` 三个模块（特征数从 518 降到 ~160）；关闭 LGBM 训练开关（只 inference 缓存模型，模型缺失时 fail_closed=True）；关闭五角校验调用 |
| `tests/` | 新增 `test_polling_mode_switch.py` | MODE1/2/3 切换的单元测试：模拟 0/1/2/3 持仓数，断言异常检测/推理币种集合、补全推理触发、缓存读写 TTL |

#### 4.1.4 Phase A 验证指标（不启用 B/C 时也要能验证收益）

- **耗时指标**：MODE3 单轮轮询平均耗时 ≤ 22s（现有 45s 的 50% 以内），连续跑 10 轮取均值；
- **正确性指标**：连续 3 轮 MODE3，候选 Top1 补全推理的粗版→完整版置信度差 ≤ 0.08；粗版方向和完整版一致率 ≥ 90%（证明粗版没把好的候选全丢掉）；
- **安全底线**：MODE3 下任何一次开仓（因为平仓腾资金）前，都能在日志里找到"补跑完整推理 + A7 + 五角校验"三条记录，缺一条就视为 Bug。

---

### 4.2 Phase B：风险-价值 EV 雷达（不新增 BCRM 训练，改动小）

**目标**：把现有零散的 5 个风险价值信号（卦象风险/价值、回撤、波动率、持仓时长）+ BCRM 方向一致率，**合成为一个 [-1, +1] 的 EV 分**，作为主离场决策层的输入，让"离场"从卦象单一规则变成多源融合。

#### 4.2.1 7 信号输入定义（均为 0~1 归一化后再加权）

| # | 信号 | 计算来源 | 归一化 | 权重 | 符号（正=好） |
|---|---|---|---|---|---|
| (1) | `dim1_dir_consistency`（Phase C 启用后替换，Phase B 先用"inference 方向一致性"代理）| Phase B 代理：`1.0 if inference.direction == pos_side_dir else 0.0`（pos_side_dir: long=UP→1, short=DOWN→-1）；Phase C 换成 dim1 的短期延续 S(1~3) 均值 clip to [0,1] | 已经是 [0,1] | **0.28** | + |
| (2) | `dim2_bcrm_expected_value`（BCRM 期望收益代理）| `(P_correct * TP_ATR_roi - (1-P_correct) * SL_ATR_roi)`，P_correct = 持仓方向置信度；TP_ATR_roi = 开仓时 base_tp_roi（存在持仓 tracker）；SL_ATR_roi = 开仓时 base_sl_roi | 用历史分布做 Winsorize：EV ≤-0.03→0；≥+0.03→1；中间线性 | **0.22** | + |
| (3) | `yijing_value_score`（卦象价值） | 现有 `yijing_exit_system.evaluate` 输出的 `yijing_value_score`（0~1） | 已经是 [0,1] | **0.20** | + |
| (4) | `yijing_risk_score`（卦象风险） | 现有 `yijing_exit_system.evaluate` 输出的 `yijing_risk_score`（0~1，越大越危险） | 已经是 [0,1] | **-0.15** | −（负权重） |
| (5) | `drawdown_pressure`（回撤压力）| `max(0.0, -unrealized_pnl_pct) / (1.5 * base_sl_roi)`：当前浮亏 / (1.5倍 ATR 止损 ROI)，1.0 代表距离 ATR_SL 还有 50% 空间，>1 代表快扫止损了 | clip to [0, 1] | **-0.10** | − |
| (6) | `volatility_penalty`（波动率惩罚）| P3 波动率分层：LOW=0 / NORMAL=0.2 / HIGH=0.5 → 对应 trading_utils.volatility_regime 的输出 | 映射后 [0,1] | **-0.05** | − |
| (7) | `age_decay`（持仓超时价值衰减）| Phase B 先用：`min(1.0, position_age_sec / (29*3600))`；Phase C 强化为：超时后非线性衰减（如 x=1.2 → 罚 1.5） | clip to [0,1] | **-0.10** | − |

**EV 合成公式**（所有权重挂 `_load_evolution_config` 的进化键，支持自进化调整）：

```python
EV = (
    + 0.28 * dim1_dir_consistency
    + 0.22 * dim2_bcrm_expected_value
    + 0.20 * yijing_value_score
    - 0.15 * yijing_risk_score
    - 0.10 * drawdown_pressure
    - 0.05 * volatility_penalty
    - 0.10 * age_decay
)
```

> 权重和 = +0.70 - 0.40 = +0.30 → 正向偏置 0.30（符合"默认持有优先，不轻易离场"的设计）。

#### 4.2.2 EV 四档决策输出

| EV 区间 | 档位 | 动作 | 优先级（相对现有离场） |
|---|---|---|---|
| **EV < −0.35** | ❌ **强制离场档** | 走离场确认 2/2（和 signal_reverse 一样的确认机制，避免单根K假信号），确认后执行 `market_close`，`exit_reason = "ev_force_close:{7信号明细摘要}"` | **第 4 优先级**，在 静态SL/TP > signal_reverse(2/2) > P3_early_exit(2/2) **之后**，卦象 FORCE_CLOSE **之前**（因为 EV 是量化合成，比卦象更硬）|
| **−0.35 ≤ EV < −0.1** | ⚠️ **离场预警档** | 传给 yijing_exit_system：覆盖卦象动作 → 强制输出 `TIGHTEN_SL`（收紧止损到 base 0.7）或 `LOWER_TP`（降低止盈到 base 0.85），`reason = "ev_early_protect"` | 第 5 优先级，和卦象动态 SL/TP 同级，但 EV 信号会覆盖卦象同币种同轮的动作 |
| **−0.1 ≤ EV ≤ +0.3** | ⚖️ **观察档** | NO_INTERVENE，什么都不改，交给卦象动态 SL/TP 微调路径 | 兜底，不阻断现有任何动作 |
| **EV > +0.3** | ✅ **强烈持有档** | 传给 yijing_exit_system：覆盖卦象动作 → 输出 `LOWER_SL`（放宽止损到 base 1.2，保护不被洗出）或 `RAISE_TP`（提高止盈到 base 1.5），`reason = "ev_hold_strengthen"` | 第 5 优先级，同预警档 |

**保护期门禁复用**：EV 的 4 档动作**全部继承现有 `_is_position_protected(position_age_sec)` 保护期门禁**——开仓 6h 内，只允许 `EV < -0.35` 强制离场（极端情况），其他 EV 预警/持有动作都屏蔽（和保护期屏蔽卦象 SL/TP 调整的设计一致）。

#### 4.2.3 Phase B 文件变更清单

| 文件 | 操作 | 变更点 |
|---|---|---|
| `scripts/memory_l4/trading_utils.py` | 修改 | `RiskManager` 或新增纯函数 `calc_position_ev(...)`：输入 7 个信号 + 权重 dict，输出 EV 标量 + 7 子分 dict（用于日志审计） |
| `scripts/memory_l4/polling_trader.py` | 修改 | `_execute_trade` 持仓分支，在"P3 提前退出 → 易经主离场"之间，插入 EV 计算 + EV 四档决策；保护期门禁判断复用现有 `in_protection` 变量；`exit_reason` 写入 EV 触发标记 |
| `configs/baseline_config.json` 或进化 config | 修改 | 新增进化键：`ev_weights`（7 个权重 + 强制阈值 -0.35 + 预警阈值 -0.1），支持 `_load_evolution_config` 热重载 |
| `tests/` | 新增 `test_position_ev.py` | 7 种典型持仓场景（方向一致浮盈大、方向相反浮亏、卦象风险高等）的 EV 计算断言 + EV 四档决策断言 |

#### 4.2.4 Phase B 验证指标

- **分层验证（回测）**：在 P0 回测数据集上，对历史交易按开仓后 24h、48h、72h 三个时点算 EV，切 EV 分档；验证：强持档 EV>+0.3 的实际后续胜率 ≥ 60%；强平档 EV<-0.35 的实际后续胜率 ≤ 25%（阈值区间需要回测调，这是验收标准）；
- **日志审计**：持仓币每轮轮询日志打印 `EV=+0.xx (子分 d1= d2= d3= ... d7=)`，飞书告警 FORCE_CLOSE 时附带 EV 子分明细，便于后验追查。

---

### 4.3 Phase C：BCRM 多 horizon 预测 + 排名止盈（重头戏，有回测保护）

**目标**：
- 回答用户维度 1：**未来 1/2/3/6 根 K 线方向延续/反转的概率曲线** → 找到最佳离场K线数 HORIZON_K_STAR；
- 回答用户维度 3：**持仓达到一定时间（12h 起步，不是硬等 29h）后，按综合排名分排名止盈**，把 `timeout_profit_switch` 从超时被动触发改成渐进主动评估。

#### 4.3.1 维度1：BCRM 多 horizon 预测设计

**标签改造（triple_barrier_labeler）**：新增 `multi_horizons=[1,2,3,6,10,20,30]` 模式（不替换现有 `horizons=[10,20,30]`，是并行开关）：

```
   当前 T 时刻，对每个 horizon h ∈ {1,2,3,6,10,20,30}：
   运行 triple_barrier(T, T+h, tp=2.5*ATR, sl=1.5*ATR)（TP/SL 倍率比基线略低，匹配短期 horizon 的震荡）
   输出标签 y_h ∈ {+1（上穿TP）, −1（下穿SL）, 0（未触发）}
```

**L3 推理输出改造**：Phase C 前 `DialecticalMLEngine.predict()` 输出 `{direction, final_confidence}`（单一 horizon）；Phase C 新增 `predict_multi_horizon(...)` 接口，输出每个 horizon 的 `P_up(h) / P_down(h)`：

```python
# 新接口返回结构（对齐现有格式）
{
    "direction": "UP",         # 主方向（用 h=20 的最大概率，与开仓时对齐）
    "final_confidence": 0.78,  # 主置信度（同现状）
    "multi_horizon": {
        1:  {"P_up": 0.52, "P_down": 0.48},
        2:  {"P_up": 0.58, "P_down": 0.42},
        3:  {"P_up": 0.61, "P_down": 0.39},
        6:  {"P_up": 0.67, "P_down": 0.33},
        10: {"P_up": 0.71, "P_down": 0.29},
        20: {"P_up": 0.78, "P_down": 0.22},
        30: {"P_up": 0.80, "P_down": 0.20},
    }
}
```

**两条合成曲线**（维度 1 最终输出）：

```python
# (1) 短期趋势延续曲线 S(k) — 只看 k=1..6
# pos_sign = +1 做多 / -1 做空
S(k) = Σ_{h=1..k} ( P(pos_sign==+1 ? P_up(h) : P_down(h)) - 0.5 )

# S(k) ≥ 0 表示短期趋势延续；S(k) < 0 表示短期反转
# HORIZON_K_STAR 拐点 = 使 S(k+1) - S(k) ≤ 0 的最小 k
#   （即"多拿 1 根 K 线不再增加收益"的第一根 k*）
#   如果 1~6 全递增 → k* = 6（短期延续强）

# (2) 远期收益饱和曲线 L(k) — 看 k=6/10/20/30
# 预测价值分 = 持仓方向方向置信度
L(k) = P_correct_at_k * (1 - exp(-k / τ))   # τ=15（时基常数=15根）
# 归一化到 L(30)：L_norm(k) = L(k)/L(30)
# CONTINUATION_SCORE = L_norm(6)
#   = 6 根 K 线后已经吃掉了 30 根总利润的百分之几
#   > 0.9 表示 6h 就接近饱和，适合止盈
```

**SHORT_TERM_REVERSAL_RISK = 1 - (S(3) + 1.5)/3  clip to [0,1]**：S(3)<0（3 根累计反转）→ 风险≈1，立刻触发 EV 雷达的 dim1 替换 + 止损收紧。

#### 4.3.2 维度3：渐进式排名止盈（替换现有 timeout_profit_switch 单一开关）

**排名对象**：每轮轮询对 **3 个持仓币 + Top3 候选池**（Phase A MODE3 粗版推理的结果）算综合排名分：

```
   排名分 = 0.4 * EV（Phase B 结果，已经是 [-1,1]，映射到 [0,1]：(EV+1)/2 ）
          + 0.3 * (当前浮盈 / (3 * ATR))  clip to [0,1]
          + 0.3 * CONTINUATION_SCORE（Phase C dim1 结果，[0,1]）
```

**三档排名止盈触发**：

| 档位 | 触发条件（与关系） | 动作 | 相对现有离场的位置 |
|---|---|---|---|
| **A 档（立即止盈换仓）** | ① 该持仓 `浮盈 ≥ 2×ATR`（已经达到"不亏"的 2 倍波动收益）+ ② 排名分 < 第 1 名候选排名分 × **0.70**（强机会落差，70% 系数是进化阈值）+ ③ 持仓 ≥ `HORIZON_K_STAR`（已经过了最佳离场点，再拿边际收益低）| 离场确认 1/1（不再要求 2/2，因为盈利厚 + 排名落差大）→ 止盈平仓 → 资金腾给第 1 名候选（但要先补跑完整推理 + A7 + 五角校验，和 Phase A 安全底线一致） | **优先级高于卦象 FORCE_CLOSE，但低于 EV 强制离场档**（EV<-0.35 是风险先出，排名止盈是盈利先出，顺序要先风险后收益）|
| **B 档（排队止盈，延迟 N 轮）** | ① 持仓 ≥ 12h（29h 的 40%，不是硬等超时）+ ② 浮盈 > 0 + ③ EV < 0.1（增长潜力低）+ ④ 排名分 ≤ 第 1 名候选 × **0.85** | 写入 `PositionTracker.reduce_plan = {"type": "ranked_tp", "wait_cycles": 2, "trigger_rank": ...}`；下轮轮询复查：若下轮排名仍没反超，止盈；若 EV/EV 反弹，取消排队 | 中优先级，在 A 档之后、卦象 HOLD 之前 |
| **C 档（不参与排名止盈）** | ① 保护期内（<6h），或 ② 浮盈 < 0.5×ATR（还没跑出安全边际），或 ③ 排名分 > 全部候选（是当前最强机会） | 继续持有，不触发任何排名止盈逻辑 | — |

**对现有 `timeout_profit_switch` 的替换**：保持 29h 超时分支作为"兜底"，但超时后先跑 A/B 档排名止盈评估（新逻辑），如果 A/B 都没命中，再走现有"对比候选置信度"的旧逻辑（兜底兼容）。不直接删旧分支，避免回退时行为突变。

#### 4.3.3 Phase C 文件变更清单

| 文件 | 操作 | 变更点 |
|---|---|---|
| `scripts/memory_l4/bcrm2/triple_barrier_labeler.py` | 修改 | `TripleBarrierLabeler.generate()` 新增 `multi_horizons: List[int]` 参数，支持并行返回多 horizon 标签 list；默认 `[10,20,30]`（向后兼容）|
| `scripts/memory_l4/bcrm2/dialectical_ml_engine.py` | 修改 | 新增 `predict_multi_horizon(X_test, horizons)` 方法：每个 horizon 对应一组 L1/L2 模型（训练时 `fit_multi_horizon`，与现有 `fit` 接口并行，不替换）；模型缓存 Key 增加 `horizon_h` 后缀；返回结构对齐 4.3.1 节定义 |
| `scripts/memory_l4/bcrm2_adapter.py` | 修改 | `BCRM2Adapter` 新增 `predict_multi_horizon(coin, klines, horizons=[1,2,3,6,10,20,30])` 接口；封装训练缓存、特征复用、推理调用、`position_horizon_preds` 缓存写入 |
| `scripts/memory_l4/polling_trader.py` | 修改 | `_execute_trade` 持仓分支在 EV 计算前，插入 dim1 多 horizon 预测（MODE3 才启用，MODE1/2 跳过）→ 计算 S(k)/L(k)/k*/CONTINUATION_SCORE → dim1 替换 EV 雷达的 `dim1_dir_consistency`（代理 → 真实值）→ EV 计算完成后 → 插入 维度3 A/B/C 排名止盈评估 → 29h 超时路径降级为兜底；新增 `reduce_plan` 写入/读取 `PositionTracker` 持久化（重启不丢排队状态）|
| `scripts/memory_l4/trading_utils.py` → `PositionTracker` | 修改 | `OpenPosition` dataclass 新增 `reduce_plan: Optional[dict] = None` 字段 + 持久化 JSON 序列化/反序列化；`close_position` 后自动清理 reduce_plan |
| `p0_backtest_verify.py`（或回测集成）| 修改 | 回测框架支持"维度1 多horizon + 维度3 排名止盈"的回放模拟：对持仓时点按历史 K 线重算（或从训练集抽样）S(k)/L(k)，统计 A/B/C 档命中率和排名止盈后的收益提升 |
| `tests/` | 新增 `test_multi_horizon_predict.py` + `test_ranked_tp.py` | 单元测试：标签器多 horizon 输出长度断言；engine 多 horizon 预测返回结构断言；排名止盈 A/B 档触发条件边界断言；reduce_plan 持久化读写断言 |

#### 4.3.4 Phase C 验证指标（强验证）

- **维度1 预测准确性**：回测集中对 500+ 个持仓窗口，h=1/h=2/h=3 的方向预测准确率（`sign(S(k))` vs 未来 h 根K真实涨跌）≥ 56%（随机 50% 的基础上有 6 个点的真实信息增益，否则维度1 没价值，回退到 Phase B 代理）；
- **维度3 排名止盈有效性**：对比"启用排名止盈 vs 不启用"的回测：A 档止盈后换下的候选，后续 48h 平均收益 ≥ 原持仓继续持有的收益（即"换仓真的赚了"）；B 档排队止盈没命中的，后续浮盈增加比例 ≥ 40%（证明 EV 反弹判断有效）；
- **不劣化基线**：启用全部 Phase A/B/C 后，P0 回测的总盈亏 ≥ 基线 95%、最大回撤 ≤ 基线 110%。不要求立刻比基线好，但绝对不能比基线差太多（差 5% 以上判定为回退）。

---

## 五、合成执行顺序总结（对单个持仓币）

本章节把 Phase A/B/C 合起来的最终执行顺序写成伪代码，作为 E 链实现的顺序蓝本：

```python
def _manage_single_position(coin, inference):
    pos_info = _check_positions(coin)          # OKX拉取：持仓、浮盈、年龄
    tracker_pos = position_tracker.get_open(inst_id)
    in_protection = _is_position_protected(pos_info.age_sec)

    # ================================================================
    # ① 基础数据 + Phase A MODE3：启用 BCRM 多 horizon（dim1）
    # ================================================================
    mode = _get_current_mode()                 # MODE1/2/3
    if mode == "MODE3_FULL":
        h_preds = bcrm2_adapter.predict_multi_horizon(coin, klines, horizons=[1,2,3,6,10,20,30])
        S, L, k_star, cont_score, rev_risk = _synthesize_horizon_curves(h_preds, pos_side)
        dim1_signal = _normalize_S3(S(3))      # 给 EV 雷达用
    else:
        dim1_signal = 1.0 if inference.direction == pos_side_dir else 0.0   # Phase B 代理
        k_star, cont_score = None, None        # 后续 dim3 用默认
        rev_risk = 0.0

    # ================================================================
    # ② Phase B：EV 风险价值雷达
    # ================================================================
    ev_subscores = calc_position_ev_subscores(
        dim1_dir_consistency = dim1_signal,
        bcrm_expected_value  = _expected_value_proxy(inference, tracker_pos),
        yijing_value_score   = yijing_hex.value,
        yijing_risk_score    = yijing_hex.risk,
        drawdown_pressure    = _drawdown_pressure(upl_ratio, tracker_pos.base_sl_roi),
        volatility_penalty   = volatility_regime(inference.volatility),
        age_decay            = min(1.0, pos_info.age_sec / (29*3600)),
        weights              = evo_config.ev_weights,
    )
    EV = sum(ev_subscores.weighted)            # [-1, +1]

    # ================================================================
    # ③ 现有硬风控（最高优先级，完全保留现状）
    # ================================================================
    if pos_info.sl_tp_hit:                     # OKX端已自动平
        return _cleanup_local_position(...)
    if _check_signal_reverse(inference, pos_side, in_protection):   # 2次确认
        return _close_and_maybe_reverse(...)
    if _check_p3_early_exit(inference, in_protection):              # 2次确认
        return _close_position(...)
    if rev_risk > REVERSAL_RISK_THRESHOLD and upl_ratio > 0:        # 维度1 短期反转
        return _adjust_sl_tp("TIGHTEN_SL/LOWER_TP", reason="dim1_rev_risk")

    # ================================================================
    # ④ Phase B：EV 四档决策（主离场决策层）
    # ================================================================
    if EV < -0.35 and not in_protection:
        confirmed, cnt = _exit_confirm(coin, "ev_force_close")
        if not confirmed: return _log_wait
        return _close_position(reason=f"ev_force_close:{ev_subscores.summary}")
    elif EV < -0.1 and not in_protection:
        return _adjust_sl_tp("TIGHTEN_SL/LOWER_TP", reason=f"ev_warn:{EV:.2f}")
    elif EV > +0.3 and not in_protection:
        return _adjust_sl_tp("LOWER_SL/RAISE_TP", reason=f"ev_strong_hold:{EV:.2f}")
    else:
        pass   # NO_INTERVENE，交给下一层

    # ================================================================
    # ⑤ Phase C：渐进式排名止盈（维度3）
    # ================================================================
    if mode == "MODE3_FULL":
        ranking = _rank_positions_vs_candidates(EV, upl_ratio, cont_score, candidates_coarse)
        a_hit = _check_tp_tier_A(pos_info, ranking, k_star)
        b_hit = _check_tp_tier_B(pos_info, ranking, EV, tracker_pos.reduce_plan)
        if a_hit:
            _log_rank_tp("A档", ranking)
            return _close_position(reason="ranked_tp_A")
        elif b_hit:
            _enqueue_or_execute_tier_B(tracker_pos)

    # ================================================================
    # ⑥ 兜底：现有易经卦象主离场 + 29h timeout_profit_switch(旧) + Classic 备用
    # ================================================================
    return _existing_yijing_and_classic_exit_flow(...)   # 现状完全保留
```

---

## 六、分阶段落地计划 + 变更回滚策略

| 阶段 | 工作量（估算）| 验收方式 | 回滚开关 |
|---|---|---|---|
| **Phase A：满仓算力重分配** | 1~2 天（主循环重写 + 粗版推理接口 + MODE 切换测试）| 实盘 dry_run 模式连续 20 轮：MODE3 轮询耗时 ≤22s；Top1 候选补全推理日志齐全；MODE1/2 行为与基线一致 | `PollingTrader.__init__` 加 `enable_mode_switch: bool = True`，False 就走现状 run_once 代码路径（100% 回滚兼容）|
| **Phase B：EV 风险价值雷达** | 2~3 天（EV 合成函数 + 4档决策 + 进化配置 + 回测验证）| P0 回测 + 分层验证：强持档胜率≥60%、强平档≤25%；实盘 dry_run 连续 50 个持仓币的 EV 日志无异常 | `enable_ev_radar: bool = True`，False 就跳过 EV 计算与 4 档动作，直接到卦象层（100% 回滚兼容）|
| **Phase C：多 horizon + 排名止盈** | 4~6 天（triple 多 horizon + engine 多预测 + adapter + 排名止盈 + reduce_plan + 完整回测）| P0 回测维度1 准确率 ≥56%；维度3 换仓收益正增量；总盈亏 ≥ 基线 95% + 回撤 ≤ 基线 110% | `enable_multi_horizon: bool = True` + `enable_ranked_tp: bool = True`，两个独立开关，任何一个关了就回退 Phase B 状态，二者全关回退 Phase A 状态 |

**回滚原则**：三阶段开关是独立的，允许只启用 Phase A（最快验证安全）、A+B（风险控制就好）、A+B+C（全功能）三种组合。没有"牵一发而动全身"的耦合。

---

## 七、待用户确认的 3 个关键参数（影响实现阈值）

> 以下是文档里暂定的初始值，如果用户倾向保守/激进，改这 3 个数字（全部在进化 config 键里，后续可自动调，不用改代码）。

| 参数 | 本 Spec 初始值 | 含义 | 激进→保守调整方向 |
|---|---|---|---|
| `MODE3 occupancy 边界` | `occupancy_rate >= 1.0`（即持仓=3 才进 MODE3） | 什么时候开始算力倾斜 | 保守：`>= 0.67`（2 单就切 MODE2+半倾斜，更稳但省更少时间）|
| `EV 强制离场阈值` | `EV < -0.35` → FORCE_CLOSE | 什么时候算"这笔持仓已经不划算了"主动走 | 激进：-0.2（走得早，锁定小利润但少吐回）；保守：-0.5（让利润奔跑但可能吐更多）|
| `排名止盈 A 档候选落差系数` | `0.70`（持仓排名分 < 候选 Top1 × 70% 才换） | 新机会要比持仓强多少才值得止盈换仓 | 激进：0.85（差一点就换，换手率高）；保守：0.50（候选要比持仓强一倍才换，更倾向持有老仓）|

---

## 八、风险评估与缓解

| 风险项 | 严重度 | 缓解措施 |
|---|---|---|
| **Phase C 多 horizon 训练耗时爆炸**：每个持仓币每轮训练 7 个 horizon 的 LGBM，原本 70s → 7×70s，MODE3 反而更慢 | 🔴 高 | **缓存策略拉满**：`position_horizon_preds` 1h 内不重算（bar_ts_rounded_1h 对齐）；7 个 horizon 的特征矩阵只算一次（bagua+cross_asset 特征共享），只切标签不同；极端情况下只训练 h=1/3/10/20 四个 horizon，2/6/30 用插值（折衷方案） |
| **Phase C 多 horizon 预测反而降低准确率**：h=1~3 太短，噪音大，EV 雷达被假信号误导 | 🟠 中 | Phase B 先上代理版 `dim1_dir_consistency` 看 EV 雷达效果；dim1 真实值做**灰度发布**：前 50% 轮询开、50% 关，对比两组的后续胜率/收益，有显著提升才永久开，否则回退代理 |
| **排名止盈 A 档换仓频繁，手续费吃掉收益**：排名止盈 A 档 1/1 离场确认，止盈后立刻开新仓，一天多次换仓 | 🟠 中 | ① 同一币种 24h 内 A 档止盈次数 ≤ 2（进化可配置），超了就强制走 B 档排队；② A 档只在"新候选扣除双向往返手续费后净收益仍 > 持仓后续 EV 估计"时触发（手续费前置校验） |
| **MODE3 粗版推理把好候选漏掉**：关闭 cross_asset/macro/cycle 后，真实高置信度候选排到 Top3 外，机会丢失 | 🟡 低 | Phase A 验证指标里已要求"粗→完整版方向一致率≥90%、置信度差≤0.08"；验证不通过就把粗版特征模块加回（比如把 wdh 时间维度也加上），耗时换准确度 |
| **Phase A/B/C 叠加后，_execute_trade 分支复杂度高，难排障** | 🟡 低 | 每个阶段都有独立的日志前缀标记：`[MODE]` / `[EV]` / `[HORIZON]` / `[RANK-TP]`；异常时按前缀 grep 就能定位是哪个阶段触发的离场；同时所有离场都写 `exit_reason` 字符串，case 复盘时一眼看到离场来源 |

---

## 九、术语表（避免歧义）

| 术语 | 在本 Spec 中的定义 |
|---|---|
| **MODE** | PollingTrader.run_once 的三种算力分配模式，按当前持仓占用率动态切 |
| **Full/Coarse 推理** | Full = 现状 BCRM 2.0 全流程 9 模块 518 特征 + 五角校验；Coarse = 只开 3 个核心模块 ~160 特征、不训练不校验（候选粗排用，不能直接开仓） |
| **多 horizon 预测** | 对未来 h=1,2,3,6,10,20,30 根 K 线分别输出方向概率 P_up(h)/P_down(h) |
| **S(k) 短期延续曲线 / L(k) 远期饱和曲线** | 多 horizon 概率合成的两条决策曲线，用于找最佳离场K线数 k* |
| **EV（风险价值合成分）** | [-1, +1] 连续值，由 7 个信号加权合成，是主离场决策的核心量化分 |
| **渐进式排名止盈** | 不是等 29h 超时才排名，持仓 ≥12h 起按 EV+浮盈+延续分的综合分，与候选池 A/B/C 三档止盈换仓 |
| **reduce_plan** | PositionTracker 新增的持久化字段，用于 B 档排队止盈的状态保存（重启不丢）|

---

## 十、E 链实现文件级清单汇总（用户确认后按 Phase 交付）

| 文件 | Phase A | Phase B | Phase C |
|---|:---:|:---:|:---:|
| `scripts/memory_l4/polling_trader.py` | ✅ 主循环 MODE 切换 + 缓存 + Top1 补全推理 | ✅ 插入 EV 四档决策 | ✅ 插入多horizon/排名止盈/reduce_plan |
| `scripts/memory_l4/bcrm2_adapter.py` | ✅ `predict_coarse()` 接口 | — | ✅ `predict_multi_horizon()` 接口 |
| `scripts/memory_l4/bcrm2/triple_barrier_labeler.py` | — | — | ✅ multi_horizons 参数 |
| `scripts/memory_l4/bcrm2/dialectical_ml_engine.py` | — | — | ✅ `fit/predict_multi_horizon()` 方法 |
| `scripts/memory_l4/trading_utils.py` | — | ✅ `calc_position_ev()` 纯函数 | ✅ `OpenPosition.reduce_plan` 字段 + 持久化 |
| 进化配置键（evo_config 热重载）| — | ✅ `ev_weights` + 阈值 | ✅ 落差系数 + A 档 24h 换仓次数上限 |
| 回测脚本集成（`p0_backtest_verify.py` 或新文件）| — | ✅ EV 分层回放验证 | ✅ 多horizon准确率 + 排名止盈换仓收益验证 |
| 单元测试 | ✅ `test_polling_mode_switch.py` | ✅ `test_position_ev.py` | ✅ `test_multi_horizon_predict.py` / `test_ranked_tp.py` |

**合计新增/修改文件数**：Phase A 3~4 文件 → Phase B 3~4 文件 → Phase C 6~7 文件。每阶段独立测试，每阶段验证通过后才推进下一阶段。
