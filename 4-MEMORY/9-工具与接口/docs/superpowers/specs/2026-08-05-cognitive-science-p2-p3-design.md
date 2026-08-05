# 认知科学完善 P2/P3 落地设计

> **Spec ID**: COG-P2P3-2026-08-05
> **创建日期**: 2026-08-05
> **关联文档**: [COGNITIVE_ARCHITECTURE.md](../../../0-元记忆/COGNITIVE_ARCHITECTURE.md) §5.4 P2/P3 进化方向
> **基线**: P0 理论补全 + P1 机制增强已完成（v3.2，TDD 9/9 通过）
> **硬约束**: 每项代码落地必须通过认知回测，`path_advantage ≥ +0.2` 才允许升级（对齐 project_memory）

---

## 1. 范围与优先级

| # | 项目 | 形态 | 风险 | 落地顺序 |
|---|------|------|------|---------|
| P2-9 | 主动推理事前预测 | 代码 + 回测 | 低（旁路增强） | 1（先做以积累 prediction 数据） |
| P2-7 | 静息态反刍 | 代码 + 回测 | 低（旁路增强） | 2（消费 episode 含 prediction） |
| P2-8 | 双通道并行决策 | 仅 spec 文档 | 高（动交易核心决策链） | 3（仅设计，不落地） |
| P3-10/11/12 | 自由能/GWT/状态机 | 文档对齐（理论注脚） | 无 | 4（随 P2 落地补注脚） |

**决策依据**：
- P2-9 先于 P2-7：反刍需要消费含 `prediction` 的 episode，P2-9 先落地以积累数据
- P2-8 仅 spec：动 A7 门禁整合逻辑，违背"优化落地需回测验证"硬约束的风险窗口，待 AB-Trading 双通道回测环境就绪后落地
- P3 仅文档对齐：理论隐喻硬编码化违背 YAGNI，作为 P2 代码的理论注脚存在

---

## 2. P2-9 主动推理事前预测（结构化预测）

### 2.1 理论基础

Friston 主动推理——大脑在行动前生成预测，行动中持续比较，预测误差驱动模型更新。当前 A8 是事后校验（交易结束后才验证），缺事前预测环节。

### 2.2 数据模型

```python
@dataclass
class Prediction:
    """事前预测（开仓时生成，平仓后校验）"""
    expected_direction: str       # "LONG" / "SHORT" / "HOLD"，对齐 inference["direction"]
    expected_horizon_bars: int    # 预期持仓周期（K线根数），由 volatility 推导
    stop_loss_prob: float         # 预期止损触发概率 [0,1]，由 A0 矛盾数 + volatility 估算
    target_return_pct: float      # 预期目标收益率（%），由 confidence + volatility 估算
    prediction_confidence: float  # 预测置信度 [0,1]，由 A0 分析置信度映射
    generated_at: str             # ISO 时间戳

@dataclass
class PredictionError:
    """预测误差（平仓后计算）"""
    direction_hit: bool           # 方向是否命中
    target_hit: bool              # 目标收益是否达成
    stop_triggered: bool          # 止损是否触发
    magnitude_error: float        # 误差幅度 = |actual_return - target_return_pct| / target_return_pct
    computed_at: str              # ISO 时间戳
```

### 2.3 模块设计

**新增** `4-MEMORY/9-工具与接口/prediction_engine.py`：

```python
class PredictionEngine:
    """事前预测生成器（对齐 Friston 主动推理）"""

    # 波动率→持仓周期映射（高波动短周期）
    _HORIZON_MAP = [
        (0.02, 48),   # vol<2% → 48根（约1天）
        (0.05, 24),   # vol<5% → 24根（约12小时）
        (0.10, 12),   # vol<10% → 12根（约6小时）
        (float("inf"), 6),  # 高波动 → 6根（约3小时）
    ]

    def generate_prediction(self, inference: dict) -> Prediction:
        """从开仓 inference 生成事前预测"""
        direction = inference.get("direction", "HOLD")
        confidence = inference.get("confidence", 0.5)
        volatility = inference.get("volatility", 0.0)
        a0_warnings = inference.get("a0_warnings", [])
        a0_analysis = inference.get("a0_analysis", {})

        # 持仓周期：波动率反推
        horizon = self._vol_to_horizon(volatility)

        # 止损概率：矛盾数越多 + 波动越大 → 止损概率越高
        contradiction_count = len(a0_warnings)
        stop_loss_prob = min(0.8, 0.2 + contradiction_count * 0.1 + volatility * 2)

        # 目标收益：置信度越高 + 波动越大 → 目标越高
        target_return_pct = confidence * 5 + volatility * 10  # 简化线性映射

        # 预测置信度：A0 置信度直接映射（夹紧到 [0.1, 0.95]）
        prediction_confidence = max(0.1, min(0.95, confidence))

        return Prediction(
            expected_direction=direction,
            expected_horizon_bars=horizon,
            stop_loss_prob=round(stop_loss_prob, 4),
            target_return_pct=round(target_return_pct, 4),
            prediction_confidence=round(prediction_confidence, 4),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def compute_error(self, prediction: Prediction, actual: dict) -> PredictionError:
        """平仓后计算预测误差"""
        actual_direction = actual.get("direction", "")
        actual_return_pct = actual.get("return_pct", 0.0)
        stop_triggered = actual.get("stop_triggered", False)

        direction_hit = (actual_direction.upper() == prediction.expected_direction.upper())
        target_hit = (actual_return_pct >= prediction.target_return_pct)
        magnitude_error = (
            abs(actual_return_pct - prediction.target_return_pct) / max(abs(prediction.target_return_pct), 0.01)
        )

        return PredictionError(
            direction_hit=direction_hit,
            target_hit=target_hit,
            stop_triggered=stop_triggered,
            magnitude_error=round(magnitude_error, 4),
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _vol_to_horizon(self, volatility: float) -> int:
        for threshold, horizon in self._HORIZON_MAP:
            if volatility < threshold:
                return horizon
        return 6
```

### 2.4 接入点

**`polling_trader._record_opening_event`**（L2288-2335）：
- event dict 新增 `prediction` 字段
- 调用 `PredictionEngine().generate_prediction(inference)` 生成预测
- 失败静默（try/except，不阻断开仓事件记录）

**`case_registry._build_thinking_chain`**（L283-322）：
- 新增 `PREDICTION` stage，写入 prediction 快照
- EXIT 阶段（L463-475）调用 `PredictionEngine().compute_error(prediction, actual)` 计算 `prediction_error`
- `prediction_error` 写入 case，供贝叶斯更新读取

### 2.5 贝叶斯更新驱动

平仓后，若 case 含 `prediction_error`：
- 误差小（`direction_hit=True` 且 `magnitude_error<0.5`）→ 提升该次决策引用的 A0/矛盾分析相关记忆置信度
- 误差大（`direction_hit=False` 或 `magnitude_error>1.0`）→ 降低置信度 + 触发矛盾分析标记

复用现有 `BayesianMemoryUpdater.update_confidence()`，传入 `observation_success=direction_hit`。

### 2.6 回测验证

```
A组（无 prediction）：episode 仅事后 A8 校验
B组（有 prediction）：episode 含 prediction + prediction_error 驱动贝叶斯

指标：
  - prediction_calibration：预测置信度 vs 实际命中率的相关性（目标 r>0.3）
  - path_advantage ≥ +0.2
  - 贝叶斯更新区分度：误差大组 vs 误差小组的后续记忆置信度变化
```

---

## 3. P2-7 静息态反刍（统计聚类版）

### 3.1 理论基础

DMN 默认模式网络——大脑空闲时活跃，整合记忆、创意涌现（类睡眠记忆巩固）。当前 daemon 空闲时不做任何事。

### 3.2 数据模型

```python
@dataclass
class RuminationFinding:
    """反刍发现的模式"""
    pattern_key: str              # "BTC|ranging|LONG" 格式
    observed_rate: float          # 观察到的胜率/盈亏率
    baseline_rate: float          # 基线胜率/盈亏率
    sample_n: int                 # 样本数
    deviation_pct: float          # 偏离基线百分比
    finding_text: str             # 自然语言描述
    generated_at: str             # ISO 时间戳
```

### 3.3 模块设计

**新增** `4-MEMORY/9-工具与接口/rumination_engine.py`：

```python
class RuminationEngine:
    """静息态反刍引擎（对齐 DMN 默认模式网络）"""

    DEVIATION_THRESHOLD = 0.15    # 偏离基线 15% 才记录
    MIN_SAMPLE_SIZE = 3           # 最小样本数
    LOOKBACK_DAYS = 7             # 回看近 7 天

    def ruminate(self, episodes_dir: str, lookback_days: int = 7) -> List[RuminationFinding]:
        """从近期 episode 提取模式"""
        episodes = self._load_recent_episodes(episodes_dir, lookback_days)
        if len(episodes) < self.MIN_SAMPLE_SIZE:
            return []

        # 按 coin × regime × direction 三维聚合
        groups = self._group_episodes(episodes)
        baseline = self._calc_baseline(episodes)

        findings = []
        for key, group in groups.items():
            if len(group) < self.MIN_SAMPLE_SIZE:
                continue
            observed = self._calc_win_rate(group)
            deviation = (observed - baseline) / max(baseline, 0.01)
            if abs(deviation) >= self.DEVIATION_THRESHOLD:
                findings.append(RuminationFinding(
                    pattern_key=key,
                    observed_rate=observed,
                    baseline_rate=baseline,
                    sample_n=len(group),
                    deviation_pct=round(deviation, 4),
                    finding_text=self._build_finding_text(key, observed, baseline, len(group)),
                    generated_at=datetime.now(timezone.utc).isoformat(),
                ))
        return findings

    def _load_recent_episodes(self, episodes_dir, lookback_days):
        """加载近 N 天 episode（复用 paths.episodes_dir()）"""
        ...

    def _group_episodes(self, episodes):
        """按 coin × regime × direction 聚合"""
        ...

    def _calc_win_rate(self, group):
        """计算组胜率"""
        wins = sum(1 for e in group if e.get("pnl_pct", 0) > 0)
        return wins / len(group) if group else 0.0

    def _calc_baseline(self, episodes):
        """计算全局基线胜率"""
        return self._calc_win_rate(episodes)

    def _build_finding_text(self, key, observed, baseline, n):
        """生成自然语言 finding 文本"""
        coin, regime, direction = key.split("|")
        return (f"近{self.LOOKBACK_DAYS}天 {coin} {regime} {direction} "
                f"胜率 {observed:.1%} vs 基线 {baseline:.1%} "
                f"(样本{n}, 偏离{(observed-baseline)/max(baseline,0.01):+.1%})")
```

### 3.4 接入点

**`cognitive_daemon.CognitiveDaemon`**：
- `__init__` 新增 `self._last_activity_ts = time.time()` 和 `self._last_rumination_date = None`
- `start()` 主循环（L703-709）保持不变
- `_tick()`（L711-）：
  - 有变更 → 更新 `self._last_activity_ts = time.time()`
  - 无变更 → 检查空闲：`time.time() - self._last_activity_ts >= 1800`（30分钟）
  - 空闲超 30min 且当日未反刍（`self._last_rumination_date != today`）→ 调 `self._ruminate()`
- 新增 `_ruminate()` 方法：
  ```python
  def _ruminate(self):
      """静息态反刍：从近期 episode 提取模式，记录为 C 级假设记忆"""
      try:
          from rumination_engine import RuminationEngine
          from cognitive_loop_entry import record
          engine = RuminationEngine()
          findings = engine.ruminate(self.episodes_dir)
          for f in findings:
              record(
                  content=f.finding_text,
                  quality_level="C",  # 假设级，需后续验证
                  tags=["rumination", "pattern", f.pattern_key.split("|")[0]],
                  source="rumination",
              )
          self._last_rumination_date = date.today().isoformat()
          self._last_activity_ts = time.time()  # 重置空闲计时
      except Exception as e:
          if self.verbose:
              print(f"[Daemon] 反刍失败: {e}", file=sys.stderr)
  ```

### 3.5 防循环机制

- 当日只反刍一次（`_last_rumination_date` 去重）
- 反刍后重置空闲计时（避免连续触发）
- 反刍产出的记忆标记 `quality_level="C"` + `source="rumination"`，需后续 A8 验证才能升级
- 失败静默（不阻断 daemon 主循环）

### 3.6 回测验证

```
A组（无反刍）：recall 不含 rumination 记忆
B组（有反刍）：recall 含 rumination 记忆

指标：
  - recall_hit_rate：反刍记忆被后续 recall 命中的比例（目标>0）
  - path_advantage ≥ +0.2
  - finding_quality：产出 finding 的样本数中位数（目标≥3，避免小样本噪声）
```

---

## 4. P2-8 双通道并行决策（仅 spec，不落地）

### 4.1 理论基础

左右脑并行处理——左脑逻辑 + 右脑直觉，胼胝体整合。当前交易决策全走左脑分析链（A0→A1→A2→A3→A7），做梦部只在连续 HOLD 后触发（非并行）。

### 4.2 设计方向（待 AB-Trading 双通道回测环境就绪后落地）

```
开仓决策流（双通道并行）：
  ├─ 左脑通道（分析型）：A0 矛盾分析 → A1 调研 → A2 第一性原理 → A3 策略
  │   输出：direction + confidence + 0-100 分
  │
  ├─ 右脑通道（直觉型，并行）：
  │   ├─ 易经卦象 → direction + 置信区间
  │   └─ 做梦部潜意识分析 → direction + 置信区间
  │   输出：right_direction + right_confidence
  │
  └─ 胼胝体整合（A7 门禁）：
      ├─ 三者一致 → 高置信标准仓
      ├─ 左右一致但与 A0 相反 → 取 A0 方向 + 降置信
      └─ 左右分歧 → 取 A0 方向 + 降置信 + 标记分歧
```

### 4.3 Feature Flag 设计

```python
# polling_trader 配置
right_channel_enabled: Dict[str, bool] = {
    "BTC-USDT-SWAP": False,  # 默认关闭，回测验证后按币种启用
    "ETH-USDT-SWAP": False,
}
```

### 4.4 落地前置条件

- AB-Trading 双通道回测环境就绪
- 右脑通道（易经/做梦）强制输出可量化字段（置信区间+方向）
- 认知回测验证 `path_advantage ≥ +0.2` 后才启用

**本 spec 仅产出设计文档，不落地代码。**

---

## 5. P3 文档对齐（理论注脚）

P3 三项随 P2 落地补注脚到 [COGNITIVE_ARCHITECTURE.md](../../../0-元记忆/COGNITIVE_ARCHITECTURE.md)：

### 5.1 P3-10 自由能统一理论

§2 已有统一框架。P2-9 落地后补注脚：
> `prediction_error`（P2-9）= 自由能信号。误差越小 = 自由能越低 = 模型越准确。贝叶斯更新由 prediction_error 驱动 = 最小化自由能的工程实现。

### 5.2 P3-11 GWT 意识模型

P2-7 反刍产出记忆 = "认知系统在 REFLECT 态意识到模式"。补注脚：
> 反刍产出记忆写入 L1/L2 = 信息进入全局工作空间 = "认知系统意识到了这些模式"。recall 命中反刍记忆 = "意识被激活影响决策"。

### 5.3 P3-12 三重脑网络状态机

P2-7(REFLECT) + P1-5(SALIENCE) + 交易(EXECUTE) 三态映射。补 §5.4 表格注脚：
> 三态状态机已由 P2-7 + P1-5 + 交易执行部分实现：REFLECT（daemon 空闲反刍）↔ SALIENCE（salience_score 检测显著事件）↔ EXECUTE（交易执行+事前预测）。状态切换由 daemon 空闲计时和文件变更显著性驱动。

---

## 6. 错误处理

| 场景 | 处理 |
|------|------|
| PredictionEngine 生成失败 | 静默，event 不含 prediction 字段，不影响开仓 |
| episode 数据不足（<3 样本） | 反刍跳过该组，不产出 finding |
| daemon 反刍失败 | 静默，记录错误，不阻断主循环 |
| 贝叶斯更新无引用记忆 | 跳过更新，记录 warning |
| episode 缺 prediction 字段（历史数据） | compute_error 返回 None，不驱动贝叶斯 |

---

## 7. 测试策略

### 7.1 单元测试（TDD）

**`test_prediction_engine.py`**：
- `generate_prediction` 字段完整性 + 边界值
- `compute_error` 方向命中/目标达成/止损触发
- `_vol_to_horizon` 波动率分档
- 失败静默（inference 缺字段时返回默认 Prediction）

**`test_rumination_engine.py`**：
- `ruminate` 三维聚合正确性
- 偏离阈值过滤（<15% 不产出）
- 最小样本数过滤（<3 不产出）
- 空 episode 目录返回空列表

### 7.2 集成测试

**`test_cognitive_daemon_rumination.py`**：
- daemon 空闲超 30min 触发反刍
- 当日只反刍一次
- 反刍失败不阻断主循环

**`test_polling_trader_prediction.py`**：
- 开仓事件含 prediction 字段
- prediction 生成失败时 event 仍正常记录

### 7.3 认知回测

**`cognitive_backtest.py`** 新增：
- `backtest_p2_9_active_inference()` — 事前预测回测
- `backtest_p2_7_rumination()` — 反刍回测
- 各自计算 `path_advantage`，≥ +0.2 才标记 upgrade

---

## 8. 落地顺序与验收标准

| 步骤 | 内容 | 验收 |
|------|------|------|
| 1 | TDD: prediction_engine + 单测 | 单测全通过 |
| 2 | 接入 polling_trader + case_registry | 开仓事件含 prediction |
| 3 | TDD: rumination_engine + 单测 | 单测全通过 |
| 4 | 接入 cognitive_daemon | 空闲反刍触发 |
| 5 | 认知回测 P2-9 + P2-7 | path_advantage ≥ +0.2 |
| 6 | P2-8 spec 文档（本文档 §4） | 文档存在 |
| 7 | P3 注脚写入 COGNITIVE_ARCHITECTURE.md | 文档更新 |
| 8 | verification-before-completion | 全部测试通过 + 文档对齐 |

---

## 9. 非目标（YAGNI）

- **不做**：LLM 驱动的反刍（用户偏好代码驱动，AI 仅在必要时）
- **不做**：完整价格路径预测（超出现有架构能力）
- **不做**：P2-8 双通道代码落地（待回测环境就绪）
- **不做**：P3 独立代码模块（理论隐喻硬编码化违背 YAGNI）
- **不做**：反刍记忆的自动升级（C 级需 A8 验证才升级，保持人工/流程门禁）
