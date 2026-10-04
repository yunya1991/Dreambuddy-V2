# 洗盘基因组（做多因子）设计文档

> **版本**: v1.0.0
> **日期**: 2026-09-22
> **阶段**: 阶段1（洗盘基因组），后续阶段2（拉高出货基因组）待阶段1验证后启动
> **前置条件**: W5 洗盘判定三层防御已落地（46/46 测试 GREEN），ENABLE_WASHOUT_DETECTOR=True 已启用

## 1. 背景与动机

### 1.1 当前状态

W5 洗盘判定系统已用于**离场**（WashoutSLGuard + P3EarlyExit + WashoutHoldStrategy），回测验证显示：
- 89.4% 止损后 24h 反弹率（洗盘现象真实存在）
- W5 净价值 +79.47%
- 洗盘判定有交易价值

### 1.2 缺口

W5 仅用于离场防御（避免被洗盘扫损），未用于**开仓进攻**（捕捉洗盘结束后的反弹机会）。

### 1.3 目标

在自进化系统中引入洗盘基因组，作为 evolution probe 仓的做多方向：
- 复用 W5 WashoutDetector 判定"洗盘中"
- 新建 WashoutEndingDetector 判定"洗盘结束信号"
- 基因组输出做多信号 → evolution probe 仓开仓
- 平仓后案例入库 → KNN/贝叶斯优化 → 自进化闭环

## 2. 架构设计

### 2.1 整体架构

```
WashoutDetector (复用 W5)
    ↓ label=WASHOUT + conf≥0.80
WashoutEndingDetector (新增, 规则化)
    ↓ ending_signal=True
WashoutReversalGenome (新增, 编排层)
    ↓ 做多信号 + confidence
EvolutionEngine → evolution probe 仓
    ↓ PROBE_THRESHOLD=0.55, MAX_PROBE=2
开仓 → 持仓 → 平仓
    ↓
WashoutReversalCaseLibrary (新增, 独立案例库)
    ↓ 案例入库
KNN + 贝叶斯 → 优化判定（案例库≥30 后激活）
```

### 2.2 与离场 W5 的关系

| 维度 | 离场 W5 | 洗盘基因组 |
|------|---------|-----------|
| 应用时机 | 持仓中 | 未持仓时 |
| WashoutDetector | 复用 | 复用 |
| 案例库 | WashoutCaseLibrary | WashoutReversalCaseLibrary（独立） |
| 动作 | SL 放宽/P3 抑制/hold | 开多 |
| reward | 避免被扫损的损失 | 开仓后 PnL |

**关键原则**：共享 WashoutDetector（形态识别），独立案例库（标签语义不同），独立动作层（开仓 vs 离场）。

## 3. 组件设计

### 3.1 WashoutEndingDetector（新增）

**文件**: `1-ARCHITECTURE/dreamos/evolution/washout_ending_detector.py`

**职责**: 判定洗盘是否结束（规则化先行，案例库≥30 后可升级 KNN）

**规则化条件**（全部满足才激活）:
- 条件1：连续 2 根 K 线成交量萎缩≥40%（相对前 10 根均值）
- 条件2：RSI(14) < 35（超卖）
- 条件3：价格企稳（下影线>实体 或 收盘价>前根收盘价）
- 条件4：OI 不再下降（OI 变化率 > -0.5%，FAIL-OPEN 数据缺失时放行）

**输出契约**:
```python
@dataclass(frozen=True)
class EndingSignal:
    activated: bool          # 是否激活
    confidence: float       # 置信度 [0.0, 1.0]
    reason: str             # 触发原因摘要
    timestamp: str           # ISO 8601 UTC

    @staticmethod
    def not_activated(reason: str) -> "EndingSignal":
        ...
```

**FAIL-OPEN**: 任何异常 → activated=False + 6 层堆栈日志，不阻塞。

### 3.2 WashoutReversalCaseLibrary（新增）

**文件**: `1-ARCHITECTURE/dreamos/evolution/washout_reversal_case_library.py`

**职责**: 独立案例库，存储洗盘反转做多案例

**案例结构**:
- 复用 `WashoutCase` dataclass（case_id/coin/entry_time/exit_time/features_snapshot/actual_label/pnl_pct/reward/timestamp）
- actual_label 扩展：`reversal_long_success` / `reversal_long_fail`
- reward：`tanh(pnl_pct/0.02)` 归一化（复用 BayesianUpdater.compute_reward）

**KNN 检索**:
- 复用欧氏距离 + key 并集缺失填 0.0 + 稳定排序
- 从 washout_case_library.py 抽取通用 KNN 逻辑（或直接复用）

**降级规则**:
- 案例库 < min_cases=30 → 走规则化 EndingDetector
- 案例库 ≥30 → KNN 检索 + 贝叶斯更新优化判定

### 3.3 WashoutReversalGenome（新增）

**文件**: `1-ARCHITECTURE/dreamos/evolution/washout_reversal_genome.py`

**职责**: 基因组主类，编排 WashoutDetector + EndingDetector + 案例库

**核心接口**:
```python
class WashoutReversalGenome:
    def __init__(
        self,
        washout_detector: WashoutDetector,  # 复用 W5
        ending_detector: WashoutEndingDetector,
        case_library: WashoutReversalCaseLibrary,
        bayesian_updater: BayesianUpdater,  # 复用
        enable: bool = False,
    ):
        ...

    def detect_signal(
        self, coin: str, df: pd.DataFrame, macro_data: Dict
    ) -> WashoutReversalSignal:
        """主入口: 检测洗盘反转做多信号.

        流程:
            1. WashoutDetector.run(coin, df, macro) → verdict
            2. verdict.label=WASHOUT + conf≥0.80 → EndingDetector.check(df, macro)
            3. ending_signal=True → 输出做多信号

        Returns:
            WashoutReversalSignal(direction=LONG, confidence, reason)
        """

    def record_case(self, case: WashoutCase) -> None:
        """平仓后案例入库."""

    def evolve(self, proposal: Optional[Dict] = None) -> Dict:
        """复用 EvolutionEngine._sandbox_validate 沙箱验证."""
```

**输出契约**:
```python
@dataclass(frozen=True)
class WashoutReversalSignal:
    direction: str           # "LONG" 或 "NONE"
    confidence: float        # [0.0, 1.0]
    washout_verdict: WashoutVerdict  # 洗盘判定结果
    ending_signal: EndingSignal     # 结束信号
    reason: str
    timestamp: str
```

**confidence 计算**:
- `confidence = washout_verdict.confidence * 0.6 + ending_signal.confidence * 0.4`
- 需 ≥ PROBE_THRESHOLD=0.55 才进入 probe 仓候选

### 3.4 EvolutionEngine 接入

**文件**: `1-ARCHITECTURE/dreamos/evolution/engine.py`（修改）

**新增方法**:
```python
def get_washout_reversal_genome(self):
    """获取洗盘反转基因组（延迟初始化）."""
    if self._washout_reversal_genome is None:
        # 构造基因组，注入 washout_detector + ending_detector + case_library
        ...
    return self._washout_reversal_genome
```

**evolve() 末尾追加**:
```python
# 洗盘反转基因组自进化
try:
    genome = self.get_washout_reversal_genome()
    if genome is not None:
        genome.evolve(proposal)
except Exception as e:
    logger.warning("washout_reversal_genome evolve FAIL-OPEN: %s", e)
```

### 3.5 PollingTrader 接入

**文件**: `11-易经推理系统/scripts/memory_l4/polling_trader.py`（修改）

**接入点**: evolution probe 仓开仓候选列表生成时

**逻辑**:
```python
# 在 evolution probe 仓候选列表生成处
if self.ENABLE_WASHOUT_REVERSAL_GENOME:
    genome = self._evolution_engine.get_washout_reversal_genome()
    if genome is not None:
        for coin in candidate_coins:
            df = self._get_df(coin)
            macro = self._get_macro_data(coin)
            signal = genome.detect_signal(coin, df, macro)
            if signal.direction == "LONG" and signal.confidence >= PROBE_THRESHOLD:
                # 加入 evolution probe 仓候选
                open_candidates.append({
                    "coin": coin,
                    "direction": "LONG",
                    "confidence": signal.confidence,
                    "source": "washout_reversal_genome",
                })
```

## 4. 硬约束

| 编号 | 约束 | 说明 |
|------|------|------|
| HC-G1 | 基因组信号走 evolution probe 仓路径 | 不增加总风险敞口（MAX_EVOLUTION_PROBE_POSITIONS=2） |
| HC-G2 | WashoutDetector conf≥0.80 才进入结束信号判定 | 低置信度不触发 |
| HC-G3 | EndingDetector 任何异常 → activated=False | FAIL-OPEN 不阻塞 |
| HC-G4 | 案例库 <30 时走规则化 EndingDetector | 不阻塞开仓 |
| HC-G5 | ENABLE_WASHOUT_REVERSAL_GENOME=False 时降级 | 链路字节等价 |
| HC-G6 | 基因组信号需 ≥ PROBE_THRESHOLD=0.55 | 与 evolution probe 仓一致 |
| HC-G7 | 平仓后必须 record_case | 案例入库是自进化闭环关键 |

## 5. 开关架构

```python
class PollingTrader:
    ENABLE_WASHOUT_REVERSAL_GENOME: bool = False  # 默认关闭，验证后启用
```

关断时行为:
- `get_washout_reversal_genome()` 返回 None
- `evolve()` 跳过基因组
- probe 仓候选列表不注入基因组信号
- 链路字节等价「基因组不存在」

## 6. 测试策略

### 6.1 单元测试

| 测试文件 | 测试内容 |
|----------|----------|
| `test_washout_ending_detector.py` | 规则化条件判定 + FAIL-OPEN + 边界值 |
| `test_washout_reversal_case_library.py` | add/get/knn_search + 降级规则 + 标签语义 |
| `test_washout_reversal_genome.py` | 编排流程 + 信号输出 + confidence 计算 + FAIL-OPEN |
| `test_washout_reversal_wireup.py` | EvolutionEngine + PollingTrader 接入 + 零回归 |

### 6.2 测试矩阵

- WashoutDetector 返回 WASHOUT+conf≥0.80 → EndingDetector 被调用
- WashoutDetector 返回 WEAKNESS/UNKNOWN → EndingDetector 不被调用
- EndingDetector 条件全满足 → 信号 direction=LONG
- EndingDetector 条件不满足 → 信号 direction=NONE
- 案例库 <30 → 走规则化
- 案例库 ≥30 → KNN 路径激活
- ENABLE_WASHOUT_REVERSAL_GENOME=False → 链路字节等价

## 7. 实施路径

TDD 开发流程:

1. **RED**: 写失败测试（test_washout_ending_detector.py + test_washout_reversal_case_library.py + test_washout_reversal_genome.py + test_washout_reversal_wireup.py）
2. **GREEN**: 实现代码使测试通过
3. **REFACTOR**: 抽取通用 KNN/贝叶斯逻辑（可选，后续优化）
4. **接入**: EvolutionEngine + PollingTrader 修改
5. **验证**: 全量回归测试 + 零回归确认

## 8. 后续演进

| 阶段 | 内容 | 前置条件 |
|------|------|----------|
| 阶段1（本spec） | 洗盘基因组（做多因子） | W5 已落地 |
| 阶段2 | 拉高出货基因组（做空因子） | 阶段1 验证通过 |
| 阶段3 | 通用 KNN/贝叶斯下沉到 EvolutionEngine | 阶段1+2 验证通过 |
