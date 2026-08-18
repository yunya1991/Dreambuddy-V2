# BCRM 2.0 满仓算力倾斜 + 三维度离场时机优化 — 实现设计 Spec

> 日期: 2026-08-18
> 状态: 待用户审阅 → 用户批准后进入 writing-plans → TDD 实现
> 关联上游提案: [PROP-20260818 BCRM2-FULL-POSITION-EXIT-OPTIMIZATION.md](../../11-易经推理系统/docs/proposals/PROP-20260818-BCRM2-FULL-POSITION-EXIT-OPTIMIZATION.md)
> 实现策略: **A. 双轨并行（4 个独立 Feature Flag + 100% 可切回旧路径）** 用户 2026-08-18 确认
> 方法论: **严格 TDD 测试先行**（每段 Phase A/B/C 先 RED→GREEN→REFACTOR）
> 回滚铁律: 任何一个开关关闭时，生产代码行为 100% 等价于开关引入前的 commit

---

## 1. 实现边界与交付物

### 1.1 本次实现严格不超出的范围（YAGNI 约束）

遵循"最小差异原则"（经验 504984 / 725663）：

| 模块 | 允许改动 | 严格禁止（不在本次升级范围） |
|---|---|---|
| `polling_trader.py` | `__init__` 增加开关/缓存字典；新增 `_mode_*` 辅助函数；`run_once` 增加 MODE 分支（开关关走原路径）；`_execute_trade` 插入 EV / 排名止盈分支（开关关走原离场序列）| 不得修改现有信号过滤函数签名、不得改变新开仓排名权重算法、不得触碰 `_open_position` 与 `_close_position` 的下单参数构造 |
| `bcrm2_adapter.py` | 新增 `infer_coarse()` 和 `_coarse_regime_features()`；新增 `predict_multi_horizon()`（Phase C）| 不得修改现有 `train()` 和 `infer()` 的字节行为（输出字段顺序 / fail_closed 语义 / 五角校验阈值一字不动）|
| `trading_utils.py` | 新增 `calc_position_ev()` 纯函数；`OpenPosition` 新增 `reduce_plan` 可选字段（None 向后兼容）| 不得修改 `PositionTracker` 的 open_position / close_position 核心状态流转 |
| `triple_barrier_labeler.py`（Phase C）| 新增 `multi_horizons` 参数，不传时完全等价旧行为 | 不得修改默认 `[10,20,30]` 标签生成逻辑的一行代码 |
| `dialectical_ml_engine.py`（Phase C）| 新增 `fit_multi_horizon / predict_multi_horizon` 方法 | 不得修改 `train_l1 / train_l2 / predict_single` 的任何参数与训练行为 |
| 进化配置键 | 新增 `ev_weights` / `ev_thresholds` / `tierA_gap` / `coarse_topn` 等（缺失时自动 fallback 到文档默认值）| 不得修改任何已存在进化键的默认值 |

### 1.2 交付物清单（按 Phase 分拆，每个 Phase 独立验收）

| 阶段 | 新增/修改文件（预计） | 交付成果 | 验收通过标准（来自 TDD 验证矩阵） |
|---|---|---|---|
| **Phase A 满仓算力重分配** | `polling_trader.py`（开关+MODE 分支+缓存）/ `bcrm2_adapter.py`（infer_coarse）/ `scripts/memory_l4/tests/test_polling_mode_switch.py` | MODE1/2/3 三档币种集分类、缓存 TTL 机制、Top1 补全推理开关分支 | 单元测试 100% 绿；连续 10 轮 MODE3 耗时均值 ≤ 现状 MODE1 × 50%；Top1 补全推理日志存在率 100% |
| **Phase B EV 风险价值雷达** | `trading_utils.py`（calc_position_ev）/ `polling_trader.py`（EV 四档决策插入）+ 进化配置键新增 `ev_weights` | EV 合成函数、4 档决策分支（插入在 P3 提前退出 → 卦象主离场之间） | 历史回放：EV>+0.3 组后续胜率≥60%；EV<-0.35 组后续胜率≤25%；开关关后 _execute_trade 行为等价旧路径字节签名一致 |
| **Phase C 多horizon + 排名止盈** | `triple_barrier_labeler.py`（multi_horizons）/ `dialectical_ml_engine.py`（多horizon训练推理）/ `bcrm2_adapter.py`（predict_multi_horizon）/ `polling_trader.py`（S(k)/L(k) 合成 + 排名止盈三档）/ `trading_utils.py`（reduce_plan 字段+持久化）/ `scripts/memory_l4/tests/test_multi_horizon_predict.py` + `test_ranked_tp.py` | 维度1 最佳K线预测、维度3 A/B/C 排名止盈、reduce_plan 排队机制持久化 | 维度1 h=1/2/3 方向预测准确率 ≥ 56%；A档换仓后后续 48h 收益 > 持仓续持收益；总盈亏 ≥ 基线 95% / 最大回撤 ≤ 基线 110%；两个独立开关可独立回滚 |

---

## 2. Feature Flag 设计（4 个独立开关 = 选项 A 双轨并行核心）

### 2.1 开关清单与关闭时的"旧路径 100%"语义

每个开关**必须定义为 `PollingTrader.__init__` 的实例级 bool 属性**（而不是全局常量），便于 dry_run 时只改实例不改代码；每个开关都必须**在进入分支前先判断**，关闭时直接 GOTO 旧代码路径一字不差：

| # | 开关属性名 | 默认值 | 控制范围 | "开关=False" 严格语义（TDD 测试必须断言） | 对应阶段 |
|---|---|---|---|---|---|
| S1 | `enable_mode_switch` | **True** | 主循环 run_once 的 MODE1/2/3 算力重分配 + 候选粗版推理 + Top1 补全推理 | `run_once` 行为等价于开关不存在：异常检测币种集 = self.coins 全量；推理阶段 full 全量；开仓排名不触发 Top1 补全推理（因为原推理就是全量 full）；`_mode_cache` 字典不写入、不读取 | Phase A |
| S2 | `enable_ev_radar` | **True**（但 Phase B 才写代码，Phase A 不引用这个变量）| `_execute_trade` 持仓分支：P3 提前退出 → 卦象主离场之间插入的 EV 计算+四档决策 | 跳过 EV 计算与四档动作，P3 提前退出判定完直接进入卦象主离场，离场动作序列与开关引入前字节一致 | Phase B |
| S3 | `enable_multi_horizon` | **True**（Phase C 才写，Phase A/B 不引用）| MODE3 时对持仓币跑多 horizon 预测、合成 S(k)/L(k)、替换 dim1 代理信号 | 不调用 `predict_multi_horizon`，不写 `_mode_cache` 的 horizon 条目；EV 雷达里 dim1 仍使用 Phase B 的方向一致性代理 | Phase C |
| S4 | `enable_ranked_tp` | **True**（Phase C 才写，Phase A/B 不引用）| 渐进式排名止盈三档 A/B/C 触发 + reduce_plan 排队持久化 + 替换 timeout_profit_switch 为主路径、旧逻辑降级为兜底 | 不做排名止盈三档计算，29h 超时直接进入原 timeout_profit_switch 分支（全量候选对比置信度）；`OpenPosition.reduce_plan` 恒为 None | Phase C |

### 2.2 开关组合的合法状态矩阵（避免组合爆炸）

TDD 只覆盖以下 6 种状态（其他组合一律**不测试**，视为用户手动配置异常，日志打 WARN 但不 crash）：

| 模式名 | S1 enable_mode_switch | S2 enable_ev_radar | S3 enable_multi_horizon | S4 enable_ranked_tp | 说明 | 推荐灰度阶段 |
|---|---|---|---|---|---|---|
| 回滚模式（SAFE）| False | False | False | False | 100% 等价升级前，出问题一键切 | 任何时候出 Bug 先切 |
| Phase A 验证 | True | False | False | False | 只验证 MODE3 性能收益，不碰离场逻辑 | 实盘第 1~2 天，只看轮询耗时不做任何真实动作 |
| Phase A+B 安全 | True | True | False | False | 验证 EV 雷达分层效果 | 实盘第 3~7 天，只改动态 SL/TP 不开/关新仓 |
| 全功能模式 | True | True | True | True | 完整启用 A/B/C | 实盘第 8 天起，先观察 50 个持仓周期再常态化 |
| 只跳过排名止盈 | True | True | True | False | 多horizon 保留，排名止盈关闭（用户觉得换仓太频繁时用）| 异常降级模式 |
| 只跳过多horizon | True | True | False | True | 用 EV 做排名止盈，不重训多horizon（算力紧张时用）| 异常降级模式 |

---

## 3. 主循环改造详细设计（Phase A = 开关 S1）

### 3.1 run_once 三段式结构（经验 725663：必须分阶段，不能在同一段混执行+决策）

对齐"先风控 → 再推理 → 再执行"的清晰时序，结构如下（**开关关闭时，分支条件永远走 else，即旧 run_once 原封不动**）：

```
run_once():
   ├─ Phase 0: 全局风控预检查（STATUS_CHECK / PAUSE / DAILY_LOSS_LIMIT / CONSECUTIVE_LOSS）
   │           （和现状完全一致，任何开关不影响这一步）
   │
   ├─ Phase 1: 决策前置（MODE 判定 + 币种集生成 + 异常检测）
   │   ├─ if S1=OFF → 旧路径（现状）
   │   │     anom_coins = self.coins 全量
   │   │     infer_full_coins = self.coins 全量
   │   │     infer_coarse_coins = []
   │   │     topup_full_coins = []
   │   │     mode_tag = "MODE-OFF"
   │   │
   │   └─ if S1=ON → MODE 新路径
   │         occupancy = _count_total_positions() / max_positions
   │         mode = MODE1/2/3 判定
   │         held_coins = 实际持仓币种集合
   │         candidate_pool_coins = self.coins - held_coins - blacklist_coins
   │         anom_coins = held_coins ∪ pick(candidate_pool_coins, MODE2→Top4, MODE3→Top3)
   │         infer_full_coins = held_coins ∪ pick(candidate_pool_coins, MODE1→all, MODE2→Top5)
   │         infer_coarse_coins = MODE3→pick(candidate_pool_coins, Top3) ∩ not(infer_full_coins)
   │         topup_full_coins = []  ← 推理阶段结束后填（粗推理 Top1 补全）
   │
   │   → 执行异常检测：对 anom_coins 中每币按 MODE 决定拉 K 数（MODE3 候选只用 30 根），命中 anom_cache 直接用，过期写回 anom_cache（TTL=MODE_CACHE_TTL_ANOMALY）
   │
   ├─ Phase 2: 推理阶段（Full 集合 + Coarse 集合，结果合并到 all_inferences）
   │   ├─ for coin in infer_full_coins → 现状完整 _fetch_and_infer，结果写 all_inferences[coin]
   │   ├─ if S1=ON and infer_coarse_coins 非空
   │   │     for coin in infer_coarse_coins
   │   │        命中 coarse_cache 直接用
   │   │        未命中 → 拉 120 根K（MODE3_COARSE_KLINE_LIMIT_BCRM）
   │   │                    → adapter.infer_coarse()（只 3 模块+轻量regime，不触发 KG/A0/五角/重训）
   │   │                    → 写入 coarse_cache（TTL=MODE_CACHE_TTL_INFER_COARSE）
   │   │        结果写入 all_inferences[coin]，但 all_inferences[coin]["_coarse"] = True 打标
   │   │     粗推理结束 → 按粗置信度排序 infer_coarse_coins → Top1 加入 topup_full_coins（且从未持仓/未黑名单）
   │   ├─ if S1=ON and topup_full_coins 非空 → 【安全底线：补全推理】
   │   │     for coin in topup_full_coins:
   │   │        完整 _fetch_and_infer（full 全流程：9模块+A0+KG+五角+可能触发重训），直接覆盖 all_inferences[coin]
   │   │        强制写入日志："[MODE3][补全推理] {coin} 粗→完整版 粗置信度=X.XX 完整置信度=Y.YY A7=PASS 五角=PASS"
   │   │     若补全推理 fail_closed → 直接从 all_inferences 中删除该币（不进后续开仓排名，避免粗排误开）
   │
   ├─ Phase 3: 执行阶段（持仓管理 + 新开仓排名）
   │   ├─ 持仓管理（现状逐币种循环）→ 完全不动，依赖 all_inferences 的任何持仓币种一定在 infer_full_coins 里（一定是 full 结果，不可能是 coarse）
   │   ├─ 新开仓排名循环（现状）
   │   │   └─ 增加一条 MODE3 门禁：若 all_inferences[coin].get("_coarse", False) is True 且该币不在 topup_full_coins 历史已补全 → 直接 skip + 日志告警（防止"补全推理失败却继续用粗结果开仓"的安全漏洞）
   │
   └─ run_once 收尾：self._cycle_idx += 1（缓存 TTL 时间基推进）→ 超期条目从 _mode_cache 中 purge（简单策略：每次保留最近 TTL×4 周期的条目，其余直接清空字典，避免 OOM）
```

### 3.2 MODE 币种集构造算法（_decide_mode_coins 工具函数）

```python
def _decide_mode_coins(self) -> Tuple[str, list, list, list]:
    """返回 (mode_tag, anom_coins, infer_full_coins, infer_coarse_coins)
    - 只看 self.enable_mode_switch；不依赖任何推理结果
    - 持有币种是从 position_tracker + OKX 去重并集得到（避免 OKX 查询失败导致漏算持仓）
    """
    held_from_tracker = {p.symbol for p in self.position_tracker.all_open_positions()}
    okx_positions = self.okx_client.get_positions() if self.okx_client else {"ok": False, "positions": []}
    held_from_okx = {p["instId"].split("-")[0] for p in okx_positions.get("positions", [])} if okx_positions.get("ok") else set()
    held_coins = held_from_tracker | held_from_okx

    candidate_pool = [c for c in self.coins
                      if c not in held_coins
                      and c not in self.blacklist_coins
                      and not self._check_dynamic_blacklist(c)]
    # 候选默认排序：先按昨日波动率（如果有缓存），再按历史交易次数倒序（如果 position_tracker 有已关闭记录可统计）；纯静态 fallback：字母序
    candidate_pool = self._default_candidate_rank(candidate_pool)

    N_max = self.max_positions
    actual_held_n = max(len(held_coins), self._count_total_positions())  # 取两者较大值作为计数，避免漏单
    occupancy = (actual_held_n / N_max) if N_max else 0.0

    if not self.enable_mode_switch:
        return ("MODE-OFF", list(self.coins), list(self.coins), [])

    # MODE 阈值
    if occupancy >= self.MODE_OCCUPANCY_MODE3:  # 1.00 默认
        mode = "MODE3_FULL"
        anom_candidate_n = self.MODE3_COARSE_CANDIDATE_TOPN          # 3
        infer_full_candidate_n = 0                                    # MODE3 候选 full 0，后续补 top1
        infer_coarse_candidate_n = self.MODE3_COARSE_CANDIDATE_TOPN  # 3
    elif occupancy >= self.MODE_OCCUPANCY_MODE2:  # 0.67 默认
        mode = "MODE2_HALF"
        anom_candidate_n = 4                                         # 2 单 + Top4 候选
        infer_full_candidate_n = 5                                   # 持仓 + Top5 候选完整推理
        infer_coarse_candidate_n = 0
    else:
        mode = "MODE1_LIGHT"
        anom_candidate_n = len(candidate_pool)                       # 空仓/轻仓全量（现状）
        infer_full_candidate_n = len(candidate_pool)
        infer_coarse_candidate_n = 0

    anom_coins = list(held_coins) + candidate_pool[:anom_candidate_n]
    infer_full_coins = list(held_coins) + candidate_pool[:infer_full_candidate_n]
    infer_coarse_coins = candidate_pool[infer_full_candidate_n: infer_full_candidate_n + infer_coarse_candidate_n]
    return mode, anom_coins, infer_full_coins, infer_coarse_coins
```

### 3.3 缓存读写 TTL 机制（_cache_get / _cache_set 工具函数）

TDD 不接受"按秒的 wall-clock"作为 TTL（不可重现），所以统一用 `self._cycle_idx` 作为时间基：

```python
def _cache_get(self, key: tuple, ttl_cycles: int):
    """命中返回 (True, payload)；未命中或过期返回 (False, None)"""
    if key not in self._mode_cache:
        return False, None
    payload, written_cycle = self._mode_cache[key]
    if self._cycle_idx - written_cycle > ttl_cycles:
        del self._mode_cache[key]
        return False, None
    return True, payload

def _cache_set(self, key: tuple, payload):
    self._mode_cache[key] = (payload, self._cycle_idx)
    # 防 OOM 清理：每 30 轮 purge 一次超过最大 TTL×4 的条目
    if self._cycle_idx % 30 == 0:
        max_ttl = max(self.MODE_CACHE_TTL_ANOMALY, self.MODE_CACHE_TTL_INFER_COARSE,
                      self.MODE_CACHE_TTL_KLINE_SHORT, self.MODE_CACHE_TTL_HORIZON_PREDS,
                      self.MODE_CACHE_TTL_POSITION_EV)
        cutoff = self._cycle_idx - max_ttl * 4
        self._mode_cache = {k: v for k, v in self._mode_cache.items() if v[1] >= cutoff}
```

---

## 4. 离场层改造详细设计（Phase B/C = 开关 S2/S3/S4）

### 4.1 Phase B EV 雷达插入点（S2=enable_ev_radar，插入在 _execute_trade）

对齐合成执行顺序（Spec 引用 PROP 伪代码）：

```
_execute_trade(coin, inference) 流程（括号里是【开关关闭时】的行为）：
  ① 基础数据 pos_info / tracker_pos / in_protection  ← 现状不变
  ② 【S3=ON: MODE3 多horizon 预测 → dim1_signal = 真实 S(3)】
     【S2/S3 任一 OFF: dim1_signal = 方向一致性代理】       ← （Phase B 默认走这条）
  ③ 【S2=ON: calc_position_ev → EV + ev_subscores】
     【S2=OFF: 跳过，EV=None】
  ④ 静态SLTP / 信号反转 / P3提前退出（硬风控） ← 现状不变，任何开关不动
  ⑤ 维度1 反转风险收紧止损（仅 S3=ON MODE3 触发）        ← （Phase C，Phase B 跳过）
  ⑥ 【S2=ON: EV 四档决策】
        EV<-0.35 且非保护期 → 离场确认 2/2 → ev_force_close
        -0.35≤EV<-0.1 且非保护期 → _adjust_sl_tp(TIGHTEN_SL/LOWER_TP, reason=ev_warn)
        EV>+0.3 且非保护期 → _adjust_sl_tp(LOWER_SL/RAISE_TP, reason=ev_strong_hold)
     【S2=OFF: 整个⑥块跳过，直接进入⑦】
  ⑦ 【S4=ON: 排名止盈三档 A/B/C】
     【S4=OFF: 跳过，直接进入⑧】
  ⑧ 兜底：易经卦象主离场 / 29h timeout_profit_switch（旧）/ Classic 备用  ← 现状一字不改
```

### 4.2 Phase C 多horizon + 排名止盈插入点（S3=enable_multi_horizon, S4=enable_ranked_tp）

**关键约束（避免 cycle 依赖）**：
- `predict_multi_horizon` 的输出结构必须完全包含 `infer()` 的现有字段（next_state.{direction,confidence,derivation} + hexagram + 风控参数），只是**额外多了 `multi_horizon: {h: {P_up, P_down}}` 字段**——这样 coarse/full/多horizon 三种推理结果在调用方眼里**仍然是同一个 dict 结构**，不用改写下游任何"访问方向/置信度"的代码。
- `reduce_plan` 是 `OpenPosition` dataclass 的**新可选字段**，默认值 = None；position_tracker 的 JSON 序列化/反序列化如果遇到老版本 JSON 里没有 reduce_plan，自动补 None，不抛出异常（向前兼容）。
- 排名止盈 A 档的**"新候选双向往返手续费前置校验"**：用 `(0.05%+0.1%) × 2 = 0.3%`（同回测脚本参数）硬编码为默认门槛，后续可挂进化配置键 `ranked_tp_roundtrip_fee_pct`；只有在【候选后续期望收益（= coarse置信度 × ATR×TP 倍率）- 持仓续持 EV 估计 - 往返手续费】> 0 时，A 档才换仓，否则降级为 B 档排队（避免"手续费吃掉换仓收益"，TDD 必须写覆盖这个 case 的测试）。

---

## 5. TDD 验证矩阵（每个阶段先失败测试 → 再通过）

### 5.1 Phase A 测试集：test_polling_mode_switch.py

| 测试名 | RED 失败原因 | GREEN 最小实现 | 断言内容 |
|---|---|---|---|
| `test_switch_off_mode_tag_is_MODE_OFF_and_full_sets_all_coins` | _decide_mode_coins 不存在 | 新增开关=False 实例属性 + 工具函数骨架返回 MODE-OFF + 全量 | self.coins = [A..F]，开关关 → anom_coins/infer_full_coins 必须等于 self.coins；infer_coarse_coins=[] |
| `test_switch_on_0_positions_is_MODE1_and_full_all_coins` | occupancy=0 判定没写 | _count_total_positions monkeypatch 返回 0 | mode=MODE1_LIGHT；held=[]；candidate_pool 全 full；coarse=[] |
| `test_switch_on_2_of_3_positions_is_MODE2_half_sets` | occupancy>=0.67 分支 | monkeypatch 返回 2 held，N=3 | mode=MODE2_HALF；held 2 全在 anom/full；候选 anom Top4、infer_full Top5、coarse=0；最终 held∩infer_full = 2 全部存在 |
| `test_switch_on_3_of_3_positions_is_MODE3_full_top3_coarse_top1_toppedup` | MODE3 分支 + coarse 分支 + 补全推理钩子 | monkeypatch 返回 3 held，N=3 + 候选池 12 个币 | mode=MODE3_FULL；anom=held3+Top3cand(共 6)；infer_full=held3；infer_coarse=Top3；topup_full_coins 最终长度=1 且是 coarse Top1 排序第一（按粗置信度模拟）|
| `test_cycle_cache_ttl_expires_after_2_cycles_anomaly_and_1_cycle_kline` | _cache_get/_cache_set 不存在 | 新增两个工具函数 | cycle_idx=0 写；cycle_idx=1 读命中 anomaly+kline；cycle_idx=2 读 anomaly 命中、kline 过期；cycle_idx=3 读两者都过期（对应 TTL 值）|
| `test_MODE3_coarse_result_must_have_coarse_flag_and_then_toppedup_overwrite` | _fetch_and_infer 循环中 coarse 分支未打标，以及 topup_full 覆盖分支未写 | Phase2 推理阶段 coarse 打 "_coarse"=True 标，topup_full 执行后 all_inferences[top1] 中 "_coarse" 被清除，且日志出现 "[补全推理]" 字样（用 monkeypatch self._log 收集）|
| `test_MODE3_new_open_without_toppedup_must_raise_guard_error` | Phase3 开仓门禁分支未写 | 新开仓排名循环中粗结果未补全 → 捕获 guard skip + warn 日志，不允许走到 _open_position（TDD 用 monkeypatch _open_position，断言它 never called）|

### 5.2 Phase B 测试集：test_position_ev.py

| 测试名 | RED 失败原因 | GREEN 最小实现 |
|---|---|---|
| `test_ev_subscores_weights_sum_matches_spec` | calc_position_ev 不存在 | 实现纯函数 + 7 子分；用全中值输入（每子分=0.5 归一化值）断言 EV=0.3（文档中的正偏置基线）|
| `test_ev_force_close_below_minus_0_35_not_in_protection` | _execute_trade 的 EV 插入点不存在 | monkeypatch tracker_pos 持仓 20h + EV 合成返回 -0.40；断言离场确认计数器 +1，_close_position 被调用 1 次，exit_reason 前缀="ev_force_close" |
| `test_ev_force_close_disabled_in_protection` | in_protection 门禁未写 | 同样 EV=-0.40 但持仓 age=2h（<6h）；断言 _close_position never called，日志标记 "protected skip EV_force" |
| `test_ev_switch_off_passes_directly_to_yijing` | 开关关短路分支未写 | enable_ev_radar=False 运行 10 次循环；断言 calc_position_ev 函数从未被调用（monkeypatch 计数=0），直接进入卦象主离场路径 |
| `test_ev_stratified_backtest_win_rates`（回放）| 回测钩子未写 | 加载 P0 历史交易样本，按开仓后 24h 时点算 EV，EV>+0.3 的 50 笔后续胜率 ≥ 0.60（允许 ±0.05 样本误差）；EV<-0.35 的 50 笔后续胜率 ≤ 0.25（允许 ±0.05）|

### 5.3 Phase C 测试集：test_multi_horizon_predict.py + test_ranked_tp.py

| 测试名 | RED 失败原因 | GREEN 最小实现 |
|---|---|---|
| `test_multi_horizons_shape_7_keys_match_list` | 新接口不存在 | horizons=[1,2,3,6,10,20,30] → 返回结构中 multi_horizon dict 必须严格有这 7 个 key，每个含 "P_up"+"P_down" ∈ [0,1] |
| `test_S_k_and_L_k_and_kstar_sane_synthetic` | 合成函数不存在 | 构造 7 个概率向量的合成用例（单调递增 P_up 一组 + 先升后降拐点一组）→ 断言 S(6)>=0、CONTINUATION_SCORE∈[0,1]、HORIZON_K_STAR∈[1,6] |
| `test_dim1_prediction_accuracy_backtest >= 0.56` | 训练/推理完整链路不存在 | BTC 历史数据上抽样 500 个持仓窗口，h=1/2/3 的 sign(S(k)) 与 真实方向 AUC ≥ 0.56（若真实训练数据不足 500 样本，此测试标记 @skip 并警告，但不阻止 Phase C 其余功能合并）|
| `test_ranked_tp_A_tier_roundtrip_fee_gate_downgrade_to_B` | 手续费前置校验未写 | 构造"候选期望收益 - 持仓EV - 手续费 = -0.1%(负数)"场景 → A 档不通过，降级写入 reduce_plan B 档排队；断言 close_position not called |
| `test_reduce_plan_persists_across_json_roundtrip` | reduce_plan 字段不存在 → 老 JSON 反序列化失败 | OpenPosition dataclass 新增 reduce_plan=None；老 JSON 无 reduce_plan 反序列化成功字段为 None；新 JSON 写入 B 档排队信息后 reload 还原一致 |
| `test_ranked_tp_switch_off_falls_to_old_timeout_profit_switch` | 开关关短路分支未写 | enable_ranked_tp=False + 29h 超时 + 盈利 → 断言走到旧 timeout_profit_switch 分支（用 monkeypatch 旧分支计数器）|

---

## 6. Spec 自检（brainstorming Skill 要求）

> **✅ 完成自检，未发现以下问题**

1. **Placeholder 扫描**：全文无 TBD/TODO，所有阈值给了默认值，所有开关给了语义；唯一"允许根据历史数据调"的是 Phase B 的分层胜率门槛（已明确给出 ±0.05 容错范围）。
2. **内部一致性**：§1.1 的禁止改动表与 §2/§3/§4 的设计没有矛盾（例如：明确说"不改 _open_position 的下单参数"，§3 新主循环里 Phase3 确实只加门禁，不改参数构造）。
3. **Scope 检查**：Scope 只覆盖 A/B/C 三个阶段 + 4 个独立开关，不涉及 BCRM 1.0 代码路径、不涉及指标离场系统、不涉及 Dashboard 仪表盘前端展示——范围足够收敛。
4. **歧义检查**：所有"可能有两解"的行为都明确选了一种并写入文档（例：occupancy_rate 的计算方式是 `actual_held_n / N_max`，而 `actual_held_n = max(position_tracker.count, OKX_API.count)`，避免 API 失败时计算偏低误判 MODE 进入半仓；粗推理开仓必须 Top1 补全推理且未 pass A7/五角就直接删除候选，避免开仓漏洞，不存在"用粗推理直接下单"还是"只做排序"的歧义）。
5. **TDD 可执行性检查**：§5 的每个测试都可以不依赖真实 OKX API（用 monkeypatch position_tracker / okx_client / _fetch_and_infer 的返回值）完成 RED→GREEN，避免"需要真实行情才能跑测试"的问题（只有 Phase B/C 的分层回放测试需要 P0 回测数据集，但已标注为"@skip 如果数据不足"）。

---

## 7. 下一步（brainstorming 终端状态门）

**Spec 已写完并归档到 `docs/superpowers/specs/2026-08-18-bcrm2-mode-evolution-design.md`。请你审阅这份实现设计 Spec，确认没有修改/补充后，我再进入下一个阶段：调用 writing-plans 生成详细实现计划，然后严格按 TDD 循环 Phase A → B → C 推进。**
