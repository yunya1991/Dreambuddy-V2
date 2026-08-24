# 方案 C v3.0 一次性全量实施计划（冻结终稿对应）

```
文档状态：实施计划冻结（对齐 Spec v3.0 §一~§十二 + R-01~R-13）
创建日期：2026-08-23
依赖 Spec：docs/superpowers/specs/2026-08-23-cbr-ema-winprob-enhancement-spec.md
落地节奏：一次性全模块实现（Task 1~11 串行），R-10 Pareto 回测与 Task 3+ 并行
预计总耗时：开发 6-8h + 回测 30-60min + 冷启动验证 30min
验收方式：R-01~R-13 逐项打勾，78 项 TDD 全绿，字节等价证明通过
```

---

## 0. 执行前前置检查（5min）

| 步骤 | 操作 | 命令 | 验收 |
|---|---|---|---|
| 0.1 | 当前实盘进程确认：记录 PID 与运行参数 | `ps aux | grep polling_trader | grep -v grep` | 输出 PID、--interval、已运行时长；暂不重启任何实盘 |
| 0.2 | 代码分支与工作区干净度 | `cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2 && git status --short` | 预期无未提交改动（如有先 stash：`git stash push -m "pre-phasec-v3-stash"`） |
| 0.3 | Spec v3.0 冻结校验：文档最后一行非 placeholder | `tail -5 docs/superpowers/specs/2026-08-23-cbr-ema-winprob-enhancement-spec.md` | 末行含 "Spec v3.0 冻结终稿完成"；无 `TODO`/`FIXME` |
| 0.4 | Python 环境与 pytest 可用 | `cd 11-易经推理系统 && python3 -c "import pytest; print(pytest.__version__)"` | pytest 版本输出；无 ImportError |
| 0.5 | runtime 目录与写权限 | `ls -la 11-易经推理系统/scripts/memory_l4/runtime/ 2>/dev/null || echo DIR_NOT_EXIST` | 若不存在则在 1.1 步自动创建 |

---

## Task 1：基础设施层（文件骨架 + 开关架构 + fail-open 桩）

> **目标**：新建 6 个独立类文件与 2 个脚本骨架；在 polling_trader.py 中接入 SW-C3~SW-C8 共 6 个新开关（已接入 C1/C2）；所有新类先写 fail-open 桩 + 字节等价证明通过。
> **耗时**：1.0h
> **依赖**：Task 0 通过

### 1.1 新建 6 个类文件骨架 + 1 个常量文件

```bash
cd 11-易经推理系统/scripts/memory_l4
touch three_layer_weighter.py        # 子系统 1：ThreeLayerWeighter
touch elastic_gate_3l.py             # 子系统 2：ElasticGate3L
touch bcrm_continuity_observer.py    # 子系统 2 R-2：BCRMContinuityObserver
touch btc_self_reflex_valve.py       # 子系统 3 R-3：BTCSelfReflexValve
touch winprob_engine.py              # 子系统 5：WinProbEngine
touch portfolio_risk_fuses.py        # 子系统 6 R-4：PortfolioRiskFuses
touch phase_c_constants.py           # v3.0 所有冻结硬编码常量（§二 非* 参数）
```

**验收**：`ls -la *.py` 列出 7 个新文件。

### 1.2 phase_c_constants.py 写入 §二 冻结硬编码常量

> 非 * 参数（P5/P6/P7/P8/P9/P10/P11/P12/P13/P16/P17）全部从 §二 抄录，类型精确：
> - int: P6=5, P16=200
> - float: P5=90.0, P7=0.60, P8=0.50, P10=0.40, P13=0.03
> - Dict/List: P9_5_THRESHOLDS, P11_G01, P12_G02

**验收**：`python3 -m py_compile phase_c_constants.py` 无错。

### 1.3 6 个类写入 fail-open 桩（每个类 1 个核心方法 + 默认返回值）

| 类名 | 核心方法签名 | fail-open 返回值（对齐 §十 L2~L6） |
|---|---|---|
| `ThreeLayerWeighter` | `daily_recalc(self, stats) -> ThreeLayerWeights` | `w_p=0.45, w_e=0.30, w_b=0.25, source="fail_open"` |
| `ElasticGate3L` | `compute(self, p1_out, elder_grade, score_b, weights) -> float` | `0.10`（L3 fail-open 固定 10% 仓位） |
| `BCRMContinuityObserver` | `append_and_grade(sym, dir, ts, conf, hex) -> Tuple[str,float]` | `("NEUTRAL", 0.65)` |
| `BTCSelfReflexValve` | `get_lambda(self, ctx) -> Tuple[float, Dict]` | `(1.0, {"reason": "fail_open"})` |
| `WinProbEngine` | `get_multiplier(self, q_vec) -> Tuple[float, Dict]` | `(1.0, {"reason": "fail_open"})` |
| `PortfolioRiskFuses` | `tick_and_check(self, ctx) -> FuseAction` | `FuseAction(block_new_open=False, sl_mult_adj=1.0, tp_mult_adj=1.0, emergency_shutdown=False)` |

**验收**：每个文件独立 `py_compile` 无错（7 个文件全通过）。

### 1.4 polling_trader.py 新增 SW-C3~SW-C8 6 个 CLI 参数 + __init__ 变量

> 对齐 Spec §十 10.1 表格：
> - `--enable-elastic-gate-3l` → `self.enable_elastic_gate_3l: bool = kwargs.get(..., False)`
> - `--enable-three-layer-weighter` → `self.enable_three_layer_weighter: bool = False`
> - `--enable-btc-self-reflex-valve` → `self.enable_btc_self_reflex_valve: bool = False`
> - `--enable-win-prob-factor`（已存在，保留）
> - `--enable-bcrm-continuity-obs` → `self.enable_bcrm_continuity_obs: bool = False`
> - `--enable-portfolio-risk-fuses` → `self.enable_portfolio_risk_fuses: bool = False`

> **插入点**：
> 1. `__init__` 参数列表末尾追加（第 291~312 行已有 C1/C2，其后追加 C3~C8）
> 2. `_parse_args`（9033~9068 行附近）追加 6 个 `parser.add_argument`
> 3. `parse_args` 返回 → PollingTrader(...) 构造调用（9105~9123 行附近）追加 6 个 kwargs

**验收**：`python3 -m py_compile polling_trader.py` 无错。

### 1.5 字节等价专项验证脚本 R-03 编写

> 文件：`scripts/memory_l4/_verify_byte_equivalence_v3.py`
> 构造 3 组模拟输入（BTC BLOCK / COIN WEAK / ETH STANDARD），SW-C1~C8 全=False，调用 ElasticGate3L 前后的 final_pos_usdt **字节完全相等**（assert abs(a-b) < 1e-12）。

**验收**：`pytest tests/test_byte_equivalence_v3.py -v` 3 项全部通过（脚本作为 TestCase 运行）。

---

## Task 2：CBR 双闭环建库 R-1 完整实现（子系统 4）

> **目标**：将现有 cbr_engine.py 中 CBRJsonlStore 升级为 v3.0（tag 排序加成 + 时间衰减 + θ_match*/γ_max* 动态参数加载 + 200 条经典战例导入脚本）。
> **耗时**：1.0h
> **依赖**：Task 1 通过
> **TDD**：T6.18~T6.24（7 项新增） + 旧 17 项 = 24 项

### 2.1 cbr_engine.py 追加 v3.0 新字段加载

在 `CBRJsonlStore.__init__` 中：
```python
# 加载动态参数（R-1 季度回测校准值）
self._params_path = self._runtime_dir / "cbr_baseline_params.json"
if self._params_path.exists():
    p = json.loads(self._params_path.read_text())
    self.theta_match_star = float(p.get("theta_match_star", 0.80))
    self.gamma_max_star = float(p.get("gamma_max_star", 0.20))
else:
    self.theta_match_star = 0.80   # 默认初值（字节等价 v2.0）
    self.gamma_max_star = 0.20
```

**验收**：T6.22（参数文件不存在用默认值）通过。

### 2.2 相似度算法追加 tag 加成 + 时间衰减（不改真实 match_score，只改排序 rank_score）

```python
def _rank_score(self, case: Dict, raw_match: float) -> float:
    """tag 只改排序名次，不改真实相似度（防止跨门槛作弊）"""
    tag_mult = 1.0
    tag = case.get("tag", "NORMAL")
    if tag == "MANUAL_CLASSIC": tag_mult = 1.05
    elif tag in ("HIGH_WIN", "HIGH_LOSS"): tag_mult = 1.02
    age_days = (datetime.now() - case.get("entry_ts", datetime.now())).total_seconds() / 86400.0
    age_decay = math.exp(-age_days / 90.0)  # P5=90d 半衰
    return raw_match * tag_mult * age_decay  # 仅排序使用
```

**验收**：T6.19（tag 加成不过 θ_match* 门槛）、T6.21（时间衰减 90d=0.3679）通过。

### 2.3 负基线 HIGH_LOSS 对称 match_boost 计算

在 `predict_topk()` 返回值中附带：
```python
if top_match.tag == "HIGH_LOSS" and top_match.score >= self.theta_match_star:
    match_boost = -self.gamma_max_star * clip(5*(top_match.score - self.theta_match_star), 0, 1) * age_decay
elif top_match.tag == "HIGH_WIN" or top_match.tag == "MANUAL_CLASSIC":
    match_boost = self.gamma_max_star * clip(5*(top_match.score - self.theta_match_star), 0, 1) * age_decay
else:
    match_boost = 0.0
```

**验收**：T6.20（HIGH_LOSS 命中，w_b 压到 0.10~0.12）、T6.24（BTC 今早回放，MANUAL_CLASSIC 排 top1，match_boost=0.20 默认初值）通过。

### 2.4 编写 200 条经典战例库生成脚本

> 文件：`scripts/memory_l4/cbr_generate_classic_cases.py`
> 逻辑：
> 1. 加载历史 TradeRecord（2025-08-23 ~ 2026-08-23 共 1 年）
> 2. 按 (asset_class, direction) 分 8 大类：{CRYPTO/US_STOCK/GOLD/FOREX} × {LONG/SHORT}
> 3. 每类按 pnl_pct 排序：top-25 → tag=HIGH_WIN；bottom-25 → tag=HIGH_LOSS
> 4. 手动在 BTC/COIN 今早 2 条前打 tag=MANUAL_CLASSIC（entry_ts=2026-08-23T09:00:00）
> 5. 输出 202 条到 runtime/cbr_cases_v03.jsonl

**验收**：T6.18（tag 计数 100 HIGH_WIN + 100 HIGH_LOSS + 2 MANUAL_CLASSIC）通过。

### 2.5 编写季度校准脚本 cbr_baseline_calibrate.py

> 文件：`scripts/memory_l4/cbr_baseline_calibrate.py`
> 网格：θ_match ∈ {0.65, 0.68, 0.71, 0.74, 0.77, 0.80, 0.83, 0.86, 0.89, 0.92, 0.95}（11 档）× γ_max ∈ {0.05, 0.08, 0.11, 0.14, 0.17, 0.20, 0.23, 0.26}（8 档）= 88 组合
> 目标函数：signal_gain = 命中基线家族案例的平均 pnl_pct - 未命中平均 pnl_pct
> 输出：最大 signal_gain 组合写入 runtime/cbr_baseline_params.json

**验收**：T6.23（88 组合跑完，文件正确写入）通过。

### 2.6 CBR 全部 24 项 TDD 全绿验证

```bash
cd 11-易经推理系统
python3 -m pytest scripts/memory_l4/tests/test_cbr_jsonl_append.py -v --tb=short
python3 -m pytest scripts/memory_l4/tests/test_cbr_v3_tag_and_decay.py -v --tb=short
```

**验收**：24 passed 0 failed。

---

## Task 3：BCRMContinuityObserver R-2 完整实现（子系统 2 新增）

> **目标**：独立类文件 bcrm_continuity_observer.py，实现 N=5 滚动窗口 + 五级判定 + get_s_cont() 连续胜率；TDD 3 项（T4.10~T4.12）+ 新 8 项 = 11 项。
> **耗时**：0.8h
> **依赖**：Task 1 通过；与 Task 2 可并行
> **验收对齐**：R-11 历史回放 Pearson ≥ +0.35

### 3.1 ContinuityWindow dataclass + 环形缓存实现

> 对齐 Spec §5.1：window_max=5；entries=Deque[Tuple[ts, conf, hex_name]]；append 自动 overflow popleft；grade() 返回五级标签 + continuity_score。

**关键断言**：
- 空窗 → ("NEUTRAL", 0.65)
- 4/5 同向 → ("ALIGN_FULL", 1.0)
- 3/5 → ("ALIGN_BASIC", 0.85)
- 2/5 → ("NEUTRAL", 0.65)
- 1/5 → ("DIVERGE_BASIC", 0.45)
- 0/5 或 ≥1 笔强反信 conf≥0.85 反方向 → ("DIVERGE_SEVERE", 0.30)

### 3.2 BCRMContinuityObserver 主类

```python
class BCRMContinuityObserver:
    def __init__(self, enable: bool = False):
        self.enable = enable
        self._windows: Dict[Tuple[str, str], ContinuityWindow] = {}  # (symbol, direction)
        # N=20 真实盈亏窗口（供 S_cont 计算）
        self._pnl_window: Deque[Tuple[str, str, datetime, bool]] = deque(maxlen=20)

    def append_and_grade(self, symbol: str, direction: str, ts: datetime,
                         conf: float, hex_name: str) -> Tuple[str, float]:
        # fail-open：任何异常 → ("NEUTRAL", 0.65)
        try:
            if not self.enable: return ("NEUTRAL", 0.65)
            key = (symbol, direction)
            if key not in self._windows:
                self._windows[key] = ContinuityWindow(symbol=symbol, direction=direction)
            return self._windows[key].append_and_grade(ts, conf, hex_name)
        except Exception:
            return ("NEUTRAL", 0.65)

    def get_s_cont(self, symbol: str, direction: str) -> float:
        """N=20 连续窗口真实盈亏胜率。样本<5笔 → 返回 S_BCRM 传入值（退化为全局）"""
        # 对齐 §四.1 差异①：冷启动 N<20 时 S_cont = S_BCRM 退化为旧 100% 全局
        relevant = [e for e in self._pnl_window if e[0]==symbol and e[1]==direction]
        if len(relevant) < 5: return float("nan")  # nan 表示调用方回退 S_BCRM
        wins = sum(1 for e in relevant if e[3])
        return wins / len(relevant)
```

### 3.3 对接 Score_B 公式（elastic_gate_3l.py 中调用）

```python
# ElasticGate3L 构造时接收 continuity_observer 引用
def _calc_score_b(self, symbol: str, direction: str, conf: float,
                  continuity_grade: Optional[Tuple[str, float]]) -> float:
    if continuity_grade is None or not self._enable_continuity:
        # SW-C7=False → continuity_score=NEUTRAL=0.65，退化为 v2.0 纯 conf
        cont_score = 0.65
    else:
        _, cont_score = continuity_grade
    pure_conf = self._conf_linear(conf)  # 0.70→0.667, 0.95→1.0, <0.70→0.40
    return 0.60 * cont_score + 0.40 * pure_conf  # P7=60:40 冻结比
```

### 3.4 11 项 TDD 全绿 + 语法验证

```bash
python3 -m py_compile bcrm_continuity_observer.py elastic_gate_3l.py
python3 -m pytest scripts/memory_l4/tests/test_bcrm_continuity_obs.py -v --tb=short
```

**验收**：T4.10（单笔 1/5 偶然信号 Score_B=0.67 不自激）、T4.11（连续 4/5 Score_B=0.92）、T4.12（空窗中性）全部通过。

### 3.5 R-11 回放脚本编写 + 验证（与 Task 10 并行，不在此阻塞）

> 文件：`scripts/memory_l4/_continuity_obs_backtest.py`
> 加载 2026-07-01~08-23 BTC 历史 BCRM 推理 + 实际价格曲线，计算 ALIGN_FULL 分布与价格 5% 反转点的 Pearson 相关系数。

**验收**：输出 Pearson ≥ +0.35，p-value < 0.05（R-11 项）。

---

## Task 4：三层动态权重引擎 v3.0（子系统 1 R-1/R-2 差异）

> **目标**：在 three_layer_weighter.py 中实现 §四.1 3 处差异（50%S_BCRM+50%S_cont；tag+衰减 match_boost；S_BTC_only 输出）；TDD 3 项（T3.09~T3.11）+ 继承 8 项 = 11 项。
> **耗时**：0.8h
> **依赖**：Task 2（CBR 返回 match_boost）、Task 3（S_cont 接口）通过

### 4.1 S 构成：50% 全局 + 50% 连续

```python
def _calc_S(self, s_bcrm: float, s_cont: Optional[float]) -> float:
    """§四.1 差异①：50-50 加权；s_cont=nan（样本<5）→ 100% s_bcrm 平滑不跳变"""
    if s_cont is None or math.isnan(s_cont):
        return s_bcrm  # 冷启动退化为 v2.0
    return 0.50 * s_bcrm + 0.50 * s_cont  # P8 冻结比
```

**验收**：T3.09（S_BCRM=0.70, S_cont=0.80 → 综合 S=0.75 → w_b≈0.42）通过。

### 4.2 match_boost：正负基线对称 + 90d 半衰

> 调用 cbr_engine.predict_topk() 返回的 match_boost 值（Task 2.3 已含正负对称）；此处直接接收参数不再二次计算；仅 clip 边界 [ -γ_max*, +γ_max* ]。

**验收**：T3.10（HIGH_LOSS 命中 match_boost=-0.1978 → w_b clip=0.05 卡底）通过。

### 4.3 S_BTC_only 计算（供子系统 3 引用）

```python
def _calc_s_btc_only(self, trade_records_last_10_btc: List[TradeRecord]) -> float:
    """§四.1 差异③：近 10 笔 BTC 专属信号（LONG+SHORT）真实盈亏加权胜率；样本<5 → 0.50 中性"""
    if len(trade_records_last_10_btc) < 5:
        return 0.50  # 小数定律防护，不够门槛 0.60
    wins = sum(1 for t in trade_records_last_10_btc if (t.pnl_pct or 0) > 0)
    return wins / len(trade_records_last_10_btc)
```

**验收**：T3.11（6 胜 4 亏 = 0.60 刚好门槛；样本 4 笔 = 0.50 不过门槛）通过。

### 4.4 11 项 TDD 全绿验证

```bash
python3 -m pytest scripts/memory_l4/tests/test_three_layer_weighter_v3.py -v --tb=short
```

**验收**：11 passed 0 failed。

---

## Task 5：ElasticGate3L 三层弹性放行矩阵（子系统 2 核心）

> **目标**：elastic_gate_3l.py 实现 §五 Score_P/Score_E/Score_B 加权共识 + base_pos_mult 映射 + F1~F4 铁则；9 继承 TDD + 3 新增 = 12 项。
> **耗时**：0.7h
> **依赖**：Task 3（Score_B）、Task 4（权重 w_p/w_e/w_b）通过

### 5.1 Score_P / Score_E / Score_B 独立分映射

对齐 §五（79~82 行）：
```python
SCORE_P = {"STANDARD": 1.0, "WEAK": 0.60, "BLOCK": 0.10}          # F1 BLOCK 也给 10%
SCORE_E = {"ALIGN_FULL": 1.0, "ALIGN_BASIC": 0.85, "NEUTRAL": 0.65,
           "DIVERGE_BASIC": 0.45, "DIVERGE_SEVERE": 0.30}
```

### 5.2 Score_consensus → base_pos_mult 映射函数

```python
def _consensus_to_base(self, c: float) -> float:
    """§三 83 行：0.20以下=0.05；0.20~0.70线性0.05~0.85；0.70以上0.85~1.50"""
    if c < 0.20: return 0.05
    if c < 0.70: return 0.05 + (0.85 - 0.05) * (c - 0.20) / 0.50  # 0.05→0.85
    return 0.85 + (1.50 - 0.85) * min((c - 0.70) / 0.30, 1.0)     # 0.70→1.00 映射到 0.85→1.50
```

### 5.3 F1~F4 四条铁则叠加（顺序严格 F1→F2→F3→F4）

| 铁则 | 触发 | 动作 |
|---|---|---|
| F1 | 永不 BLOCK | 结果 clip 下届 = 0.05（if result < 0.05: result = 0.05） |
| F2 | P1 原始 = BLOCK | result = min(result, 0.10*)（P14* 回测动态顶，默认 0.10） |
| F3 | Elder 五级 = DIVERGE_SEVERE | result *= 0.70（严重反信 7 折） |
| F4 | CBR top1 家族 match ≥ θ_match* | result *= 1.20（基线家族红利） |

最终 result = clip(result, 0.05, 1.50*)（P15* 全局上界，默认 1.50）。

### 5.4 12 项 TDD 全绿验证

```bash
python3 -m pytest scripts/memory_l4/tests/test_elastic_gate_3l.py -v --tb=short
```

**验收**：R-07 今早 BTC/COIN 回放，BTC ∈ [0.80,0.86]、COIN ∈ [0.85,0.95]（手动运行回放脚本验证）。

---

## Task 6：BTC 自反调控闸门 R-3（子系统 3）

> **目标**：btc_self_reflex_valve.py 实现 §六 5 条门槛 + G-01 冷却熔断；8 继承 + 5 新增 = 13 项 TDD。
> **耗时**：0.8h
> **依赖**：Task 4（S_BTC_only）、Task 3（ContinuityObserver grade）通过

### 6.1 5 条门槛逐条实现 + λ 公式

> 对齐 §六.1 表格 T1~T5；每条 return (1.0, {"failed": "T2"}) 方式旁路；5 条全中才进入 λ 计算。
> λ 公式：clip(1 - 0.40 · C_obs · (n_rev/(0.60·N_windows)) · S_BTC_only, 0.60, 1.0)（P10=0.40 惩罚上限）。

### 6.2 G-01 冷却熔断状态机 + 持久化

> 状态文件：`runtime/btc_reflex_cooling.lock`（存在即冷却中，含 end_date 和 reason）。
> 每次 get_lambda() 开头检查：lock 文件存在且 end_date ≥ 今日 → 直接 return (1.0, {"cooling": True, "until": end_date})。

### 6.3 三个作用点在 polling_trader.py 中注入

> 对齐 Spec §五.3（继承 v2.0）：
> ① **开仓时**：final_position_usdt × λ（在 _open_position 中，资金调控之后、真实下单之前）
> ② **持仓中 TP**：tp_mult × λ（在 ExitManager._eval 中读取 context.btc_reflex_lambda）
> ③ **持仓中 SL**：sl_mult × sqrt(λ)（SL 用 √λ，比 TP 慢，防止 λ=0.60 时 SL 太近被扫）

### 6.4 13 项 TDD 全绿验证

```bash
python3 -m pytest scripts/memory_l4/tests/test_btc_self_reflex_v3.py -v --tb=short
```

**验收**：T5.09（T2 不过 → λ=1.0）、T5.12（5 条全中 → λ≈0.66）、T5.13（G-01 触发 → 冷却 3 日 λ=1.0）通过。

---

## Task 7：WinProbEngine 盈亏概率（子系统 5，继承 v2.0 无修改）

> **目标**：winprob_engine.py 实现 3 层 gate + TopK + Brier 自适应 w_winprob；8 项 TDD 全继承。
> **耗时**：0.5h
> **依赖**：Task 2（CBR KNN 相似度）通过

### 7.1 winprob_engine.py 实现

> 8 项继承清单：
> - G1 总开关开
> - G2 同大类同方向 ≥ 30 条配对样本（P17）
> - G3 近 50 次预测 Brier ≤ 0.25（P17）
> - TopK=10 相似案例加权 pred_win_rate
> - w_winprob = EMA(Brier 反归一化到 [0,0.40])，Brier>0.25 → 0（自动旁路 24h）
> - winprob_mult = clip(1 + w_winprob·(pred_win_rate - 0.50), 0.80, 1.20)
> - 与 ElasticGate3L 冲突时，final_pos_mult_after = clip(§五 × §六 λ × winprob_mult, 0.05, 1.50*)（防止双放大）
> - fail-open：任何异常 → 1.0

### 7.2 8 项 TDD 全绿验证

```bash
python3 -m pytest scripts/memory_l4/tests/test_winprob_engine.py -v --tb=short
```

**验收**：8 passed 0 failed。

---

## Task 8：PortfolioRiskFuses R-4 子系统 6（G-02 + G-04 + Pareto 参数）

> **目标**：portfolio_risk_fuses.py 实现 6-2 G-02 黑天鹅熔断 + 6-3 G-04 3% 终极熔断；10 项新增 TDD；Pareto 脚本框架编写。
> **耗时**：1.0h
> **依赖**：Task 6（BTCSelfReflexValve.λ）通过

### 8.1 G-02 黑天鹅熔断 3 条门槛 + 3 个动作

> 对齐 §九.1.2：cond1（同方向≥5）、cond2（15min 浮亏≤-0.50%）、cond3（λ≤0.75）同时命中 →
> ① block_new_open_until_ts = ts+3600（1h）
> ② 所有持仓 sl_mult × 0.90
> ③ 所有持仓 tp_mult × 1.05

### 8.2 G-04 单日 3% 终极熔断 + _phase_c_emergency_shutdown

> 对齐 §九.1.3：daily_drawdown ≥ 3% →
> ① 8 个开关全 False（SW-C1~C8）
> ② 写 lock 文件 `runtime/phase_c_emergency_shutdown_until_{YYYYMMDD+1}.lock`
> ③ PollingTrader.__init__ 中检测 lock → 强制覆盖 CLI enable_* 参数

### 8.3 emergency_clear 脚本编写

> 文件：`scripts/memory_l4/phase_c_emergency_clear.py`
> 功能：
> 1. `--reason "..."` 必填参数
> 2. 删除 runtime/phase_c_emergency_shutdown_until_*.lock
> 3. 追加写 logs/phase_c_emergency_audit.log（JSONL：ts, operator, reason, cleared_lock_file）

### 8.4 10 项 TDD 全绿验证

```bash
python3 -m pytest scripts/memory_l4/tests/test_portfolio_risk_fuses.py -v --tb=short
```

**验收**：T9.01（405 组合 Pareto）、T9.04（G-02 缺 1 条不触发）、T9.07（G-04 触发全关 lock）、T9.09（clear 脚本审计日志）通过。

---

## Task 9：polling_trader.py 全链路接入 + 六层 fail-open 级联

> **目标**：将 6 个子系统在 polling_trader 中按正确顺序接入调用链；每个子系统 try/except 包裹；影子日志 22 字段完整写入；字节等价验证通过。
> **耗时**：1.2h
> **依赖**：Task 1~8 全部通过
> **验收对齐**：R-01（py_compile 全通过）、R-02（78 TDD 全绿）、R-03（字节等价）、R-04（六层 fail-open）、R-05（影子日志 22 字段）、R-08（Spec 无遗留）

### 9.1 _init_phase_c_components() 新增方法（与 _phase1_three_components 合并）

> 初始化顺序：BCRMContinuityObserver → CBRJsonlStore → ThreeLayerWeighter → ElasticGate3L → BTCSelfReflexValve → WinProbEngine → PortfolioRiskFuses
> 每个独立 try/except，失败时 component = None，对应 SW 开关视为 False（字节等价旁路）。

### 9.2 核心调用链顺序（在 _open_position 中 P1 过滤之后）

```
Step A：PortfolioRiskFuses.tick_and_check() → G-02 new_open gate 检查（GATE-1）
Step B：P1 过滤（原逻辑保留，SW-C3=False 时 return 原硬 BLOCK）
Step C：SW-C3=True → ElasticGate3L.compute(p1_out, elder_grade, score_b, weights) → base_pos_mult
Step D：SW-C5=True → × BTCSelfReflexValve.get_lambda() → λ 应用到开仓仓位
Step E：SW-C6=True → × WinProbEngine.get_multiplier() → winprob_mult
Step F：clip 全局 [0.05, 1.50*]
Step G：G-02 new_open gate（若 True 直接 return 不下单）
Step H：CBR entry_snapshot 半条写入（SW-C1=True）
Step I：真实 OKX 下单（shadow_mode=True 时 BLOCKED-OPEN）
```

### 9.3 离场回填 CBR exit_snapshot（_close_position 成功后）

> CBRJsonlStore.finalize_by_case_id(pre_case_id, exit_snapshot, pnl_pct, pnl_usdt, is_profit)（SW-C1=True 才执行；找不到 pre_case_id 静默跳过）。

### 9.4 六层 fail-open 注入测试（R-04）

> 编写 `tests/test_six_layer_failopen.py` 12 项：
> - L1（SW-C3=False → 原硬逻辑）
> - L2（SW-C4=False 或子系统 1 异常 → 冷启动权重）
> - L3（Score 异常 → 0.10）
> - L4（SW-C5=False 或 5 门槛任一不满足 → λ=1.0）
> - L5（SW-C6=False 或 WinProb 异常 → 1.0）
> - L6（G-04 3% → 全关 lock 文件）

每项用 Exception/None/NaN 三种注入。

### 9.5 影子日志 22 字段完整写入

> 在 shadow_logger.py ShadowLogger 中追加字段（对齐 R-05）：
> 7 three_layer_* + 3 btc_self_reflex_* + 2 winprob_* + 5 bcrm_continuity_* + 3 pareto_params_* + 2 fuses_status_*
> 全部 Optional[X]=None（SW 关时写入 None，保持旧记录向后兼容）。

### 9.6 R-01~R-05 全项验收

```bash
# R-01 py_compile 全通过
python3 -m py_compile scripts/memory_l4/cbr_engine.py scripts/memory_l4/elder_ray_engine.py \
  scripts/memory_l4/three_layer_weighter.py scripts/memory_l4/elastic_gate_3l.py \
  scripts/memory_l4/btc_self_reflex_valve.py scripts/memory_l4/winprob_engine.py \
  scripts/memory_l4/bcrm_continuity_observer.py scripts/memory_l4/portfolio_risk_fuses.py \
  scripts/memory_l4/polling_trader.py

# R-02 78 TDD 全绿
python3 -m pytest scripts/memory_l4/tests/test_*.py -v --tb=short 2>&1 | tail -30

# R-03 字节等价
python3 scripts/memory_l4/_verify_byte_equivalence_v3.py

# R-04 六层 fail-open
python3 -m pytest scripts/memory_l4/tests/test_six_layer_failopen.py -v

# R-05 影子日志字段
head -1 scripts/memory_l4/runtime/shadow/shadow_$(date +%Y%m%d).jsonl | python3 -m json.tool | head -30
```

---

## Task 10：Pareto 参数回测（R-4 6-1）+ R-11 连续性回放

> **目标**：并行启动两个长耗时脚本；不阻塞 Task 11（冷启动验证），但 R-10/R-11 验收必须在实盘重启前通过。
> **耗时**：30-60min（与 Task 11 并行）
> **依赖**：Task 8 脚本框架完成

### 10.1 Pareto 网格搜索 405 组合（R-10）

> 文件：`scripts/memory_l4/phase_c_pareto_calibrate.py`
> 启动命令：

```bash
cd 11-易经推理系统/scripts/memory_l4 && nohup python3 phase_c_pareto_calibrate.py \
  > runtime/phase_c_pareto_stdout.log 2> runtime/phase_c_pareto_stderr.log &
echo $! > runtime/phase_c_pareto_pid.txt
```

> 参数网格（§九.1.1 表格）：5×3×3×3×3 = 405 组合
> Walk-forward：训练=前 24 月，验证=下 1 月，滚动 12 折
> Pareto 筛选：样本外 Sharpe ≥ 95% 最优 AND 最大回撤 ≤ 10%
> 输出：`runtime/phase_c_default_params.json`（5 字段中位数） + `runtime/phase_c_pareto_report.md`

**验收**：`tail runtime/phase_c_pareto_stdout.log` 显示 405/405 完成；Pareto 组合数 5~20；JSON 5 字段齐全。

### 10.2 R-11 BCRMContinuityObserver 历史回放

```bash
cd 11-易经推理系统/scripts/memory_l4 && python3 _continuity_obs_backtest.py
```

**验收**：输出 Pearson ≥ +0.35，p-value < 0.05。

---

## Task 11：shadow-mode 冷启动 + R-12/R-13 熔断模拟 + 实盘重启准备

> **目标**：9 个方案 C 开关全开 + shadow-mode 冷启动 2 轮；G-02/G-04 注入式模拟通过；实盘重启前最终检查清单。
> **耗时**：1.0h
> **依赖**：Task 9（全链路接入）通过；与 Task 10 并行

### 11.1 shadow-mode 冷启动 2 轮验证（R-06）

```bash
cd 11-易经推理系统
# SIGSTOP 旧实盘进程（从 Task 0.1 记录的 PID，如 49849）
kill -STOP <OLD_PID>
ps -o pid,stat,command -p <OLD_PID>   # 预期 STAT=Ts（停止+睡眠中）

# 启动 shadow-mode（方案 C 8 开关全开）
nohup python3 start_daemon.py \
  --interval 300 \
  --confidence 0.7955 \
  --max-positions 5 \
  --position-pct 0.20 \
  --shadow-mode \
  --enable-cbr-cycle-log \
  --enable-elder-ray-c4 \
  --enable-elastic-gate-3l \
  --enable-three-layer-weighter \
  --enable-btc-self-reflex-valve \
  --enable-win-prob-factor \
  --enable-bcrm-continuity-obs \
  --enable-portfolio-risk-fuses \
  > logs/trading_screen_shadow_v3.log 2>&1 &
echo $! > logs/shadow_v3_pid.txt

# 观察 2 轮（10 分钟）
sleep 600
tail -50 logs/trading_screen_shadow_v3.log
grep "BLOCKED-" logs/trading_screen_shadow_v3.log | wc -l   # 预期 ≥ 1（BLOCKED-OPEN/CLOSE/REDUCE）
grep -i "error\|critical" logs/trading_screen_shadow_v3.log | grep -v "WARN" | wc -l  # 预期 = 0
grep "fd_total\|fd_strategy\|fd_mask\|sal_style\|sal_cap_mode" logs/trading_screen_shadow_v3.log | wc -l  # 战略层影子正常
grep "three_layer_\|btc_self_reflex_\|winprob_\|bcrm_continuity_\|pareto_params_\|fuses_status_" logs/trading_screen_shadow_v3.log | wc -l  # R-05 22 字段影子
```

**验收**：R-06 四项①②③④全满足。

### 11.2 R-12 G-02 黑天鹅模拟

> 注入式测试 `tests/test_portfolio_fuse_g02_sim.py`：
> 构造 5 笔 BTC LONG 持仓 + rolling_15min_pnl=-0.60% + λ=0.70 →
> 断言 block_new_open_until_ts 未来 1h + 每个持仓 sl_mult×0.9 + tp_mult×1.05。

### 11.3 R-13 G-04 终极熔断模拟

> 注入式测试 `tests/test_portfolio_fuse_g04_sim.py`：
> prev_equity=1000, curr_equity=969（3.1%）→ 8 个开关全=False + lock 文件生成 + 下次 __init__ lock 覆盖 CLI + emergency_clear 正确。

### 11.4 实盘重启准备清单

> **在用户明确说"重启实盘"之前，以下步骤不执行！**
> ① SIGCONT 恢复旧实盘进程：`kill -CONT <OLD_PID>`（从 shadow-mode 冷启动退出）
> ② 确认 Task 10 Pareto 回测 JSON 文件生成 → 自动覆盖默认初值
> ③ 确认 R-11 Pearson ≥ +0.35
> ④ 确认旧实盘 30min 内无 ERROR 日志 → 可安全 kill 旧实盘 → 带新 CLI 开关正式启动
> ⑤ 启动后前 3 轮（15min）持续盯日志，确认：无 ERROR；BCRM 信号正确写入 CBR；弹性仓位合理；G-02/G-04 未误触发

---

## 附录：R-01~R-13 验收打勾表

> 实施过程中每完成一项，在对应位置打 ✅

| # | 验收项 | 状态 | 通过证据（文件路径/日志截图锚点） |
|---|---|---|---|
| R-01 | 9 文件 py_compile 0 Error | ☐ | |
| R-02 | 78 项 TDD 100% 绿 + 覆盖率 ≥ 85% | ☐ | |
| R-03 | 字节等价 3 笔模拟（差异 < 1e-12） | ☐ | `_verify_byte_equivalence_v3.py` 输出 |
| R-04 | 六层 fail-open 12 项注入通过 | ☐ | `test_six_layer_failopen.py` 12/12 |
| R-05 | 影子日志 22 字段完整合法 | ☐ | shadow JSONL 字段检查 |
| R-06 | shadow-mode 冷启动 4 项通过 | ☐ | `trading_screen_shadow_v3.log` 证据 |
| R-07 | BTC/COIN 今早回放落入目标区间 | ☐ | `_replay_20260823_btc_coin_v3.py` 输出 |
| R-08 | Spec v3.0 0 处遗留内容 | ☐ | grep 0 处结果 |
| R-09 | 本文档行数 ≥ 500 行（已满足，检查锚点） | ☐ | wc -l → 本文档 |
| R-10 | Pareto 405 组 100% 跑完 + JSON 5 字段 | ☐ | `phase_c_pareto_report.md` |
| R-11 | 连续性回放 Pearson ≥ 0.35, p<0.05 | ☐ | `_continuity_obs_backtest.py` 输出 |
| R-12 | G-02 黑天鹅模拟 3 动作执行 | ☐ | `test_portfolio_fuse_g02_sim.py` |
| R-13 | G-04 终极熔断模拟 4 动作执行 | ☐ | `test_portfolio_fuse_g04_sim.py` |

---

> **文档结束**。下一个动作：从 Task 0 开始串行执行（Task 10 并行启动回测脚本），每完成一个 Task 在上方打勾表中更新 R-01~R-13 状态。遇到阻塞按 fail-open 铁则执行，绝不阻塞交易主流程。
