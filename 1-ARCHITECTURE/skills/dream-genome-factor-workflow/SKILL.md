---
name: dream-genome-factor-workflow
description: "Orchestrates genome factor development: recall → RED (3 test files) → GREEN (3 impl files) → wire-up → backtest → regression → cognitive closure. Invoke for genome factor, washout reversal, pump-dump reversal, factor TDD."
version: 1.0.0
created: 2026-09-22
updated: 2026-09-22
license: Internal
status: active
category: orchestration
triggers: [基因组因子开发, genome factor, 洗盘反转基因组, 拉高出货基因组, 因子 TDD]
depends_on: [dream-tdd-dev-workflow, dream-contradiction-theory, tee-red-green-progress, test-driven-development]
provides: [genome-factor-orchestration]
cognitive_links: [VM-1790082413250-87c04f74, VM-1790085845059-f4ed7bce, VM-1790001702811-24bffe86]
---

## Autonomy Boundary

可自主执行：
- 任务编排与流程调度
- 节点间数据流转发
- 编排优化与节点选择
- 执行状态监控与汇报

需用户确认：
- 涉及实盘交易的编排执行
- 修改核心编排规则

禁止：
- 将编排结论直接作为交易指令执行
- 绕过风控或审批流程


# Dream Genome Factor Workflow — 基因组因子开发工作流 SKILL

> 把"recall → RED (3 测试文件) → GREEN (3 实现文件) → 系统接入 → 回测补样本 → 回归验证 → 认知闭环"的基因组因子开发循环固化为可复用编排。元 SKILL 为 `dream-qwen-eval-collab`，基础 TDD 模式复用 `dream-tdd-dev-workflow`，结尾执行 hermes 反思。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-genome-factor-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-genome-factor-workflow/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **基因组因子开发**：用户要求开发新的交易因子基因组
   - 触发词：「基因组因子开发」「genome factor」「因子 TDD」
2. **洗盘/拉高类反转因子**：开发洗盘反转或拉高出货类反转信号
   - 触发词：「洗盘反转基因组」「拉高出货基因组」「做空因子」「做多因子」
3. **新因子模块落地**：需要新增 ending_detector + case_library + genome 三件套
4. **spec 落地**：基因组设计 spec 需要进入实现阶段

**与 `dream-tdd-dev-workflow` 的边界**：`dream-tdd-dev-workflow` 是通用 TDD（RED→GREEN→REFACTOR→hermes）；本 SKILL 是专门面向基因组因子的 7 步编排，包含三件套模式、系统接入、回测补样本、影子模式决策等基因组特有环节。步骤 2/3 直接复用 `dream-tdd-dev-workflow` 的红绿纪律。

---

## 二、7 步标准流程

### 步骤 1：recall + 需求分析

**输入**：用户因子需求文本（或来自 spec）

**处理**：
1. **recall（硬约束，不可跳过）**：
   ```
   recall(context="基因组因子 <因子名> <做多/做空> <关键词>", top_k=5, min_quality="C")
   ```
2. 复用 `dream-contradiction-theory` 识别核心矛盾：新因子与现有系统的张力
3. 确定因子方向（做多 LONG / 做空 SHORT）
4. 列出硬约束（HC 系列，见第六节模板）
5. 确定三件套路径与接口签名

**输出**：因子 TDD 任务包（YAML）

```yaml
因子名: <washout_reversal / pump_dump_reversal / ...>
方向: <LONG 做多 / SHORT 做空>
核心矛盾: <新因子与现有系统的张力>
三件套路径:
  ending_detector: <1-ARCHITECTURE/dreamos/evolution/<factor>_ending_detector.py>
  case_library: <1-ARCHITECTURE/dreamos/evolution/<factor>_reversal_case_library.py>
  genome: <1-ARCHITECTURE/dreamos/evolution/<factor>_reversal_genome.py>
硬约束:
  - HC-X1: 信号走 evolution probe 仓路径 (MAX_EVOLUTION_PROBE_POSITIONS=2)
  - HC-X2: <Detector> label=<LABEL> + conf≥0.80 才进入结束信号判定
  - HC-X3: EndingDetector 异常 → activated=False (FAIL-OPEN)
  - HC-X4: 案例库 <30 时走规则化 EndingDetector
  - HC-X5: ENABLE_<FACTOR>_GENOME 默认 False (关断时链路字节等价)
  - HC-X6: 信号需 ≥ PROBE_THRESHOLD=0.55
  - HC-X7: 平仓后必须 record_case
验收标准:
  - <可量化判据 1>
  - <可量化判据 2>
```

### 步骤 2：RED — 写失败测试（3 个测试文件）

**输入**：因子 TDD 任务包

**处理**（复用 `dream-tdd-dev-workflow` 步骤 2 红绿纪律）：

按三件套分别写测试，每个文件覆盖：

| 测试文件 | 覆盖范围 | 典型用例数 |
|---------|---------|-----------|
| `test_<factor>_ending_detector.py` | 结束信号判定（4 条件 AND + FAIL-OPEN + confidence） | 10-15 |
| `test_<factor>_reversal_case_library.py` | 案例库 CRUD + KNN 搜索 + is_ready | 10-15 |
| `test_<factor>_reversal_genome.py` | 基因组编排（label 路由 + conf 阈值 + enable 开关 + FAIL-OPEN） | 10-15 |

**RED 起手模式**（每个测试文件第一个用例）：

```python
def test_module_importable():
    with pytest.raises(ModuleNotFoundError):
        from dreamos.evolution.<factor>_ending_detector import <EndingDetector>  # noqa
```

**运行确认 RED**：
```bash
pytest test_<factor>_*.py -v
# 预期：全部 failed（模块不存在）
```

**已知坑**（必须遵守）：

| 坑 | 现象 | 解决 |
|----|------|------|
| `sys.path` 未包含父目录 | `ImportError: No module named 'scripts'` | 测试文件头部 insert `_YIJING_ROOT` 和 `_ARCH_ROOT` |
| WashoutDetector 无 classifier | 生产需 W4 classifier 注入，回测无此依赖 | 回测直接构造 Verdict（基于回撤深度计算 confidence） |
| 4 条件 AND 过严 | 信号过少，案例不足 30 | 回测用宽松版（≥2/3 条件满足）生成训练样本 |

**输出**：3 个测试文件路径 + RED 运行日志

### 步骤 3：GREEN — 三件套实现

**输入**：3 个测试文件 + 任务包

**处理**（复用 `dream-tdd-dev-workflow` 步骤 3）：

按依赖顺序实现（每个文件写最简实现让测试通过）：

```
1. <factor>_ending_detector.py
   ├─ <EndingSignal> (frozen dataclass, confidence clamped [0,1])
   └─ <EndingDetector> (check 方法, 4 条件 AND, FAIL-OPEN)
2. <factor>_reversal_case_library.py
   ├─ 复用 WashoutCase 结构
   ├─ add/get/all/__contains__
   ├─ knn_search (欧氏距离)
   └─ is_ready_for_knn (≥ min_cases=30)
3. <factor>_reversal_genome.py
   ├─ <ReversalSignal> (direction=LONG/SHORT/NONE, confidence)
   └─ <ReversalGenome> (detect_signal 编排 + record_case + evolve)
```

**关键设计原则**：
- `confidence = verdict.confidence * 0.6 + ending.confidence * 0.4`
- `enable=False` 时直接返回 NONE（链路字节等价）
- 所有异常 → FAIL-OPEN（返回 not_activated / NONE）
- EndingDetector 规则化条件（做多：RSI<35+量缩+企稳+OI不降；做空：RSI>70+量缩+见顶+OI降）

**运行确认 GREEN**：
```bash
pytest test_<factor>_*.py -v          # 预期：全部 passed → GREEN
```

**输出**：3 个实现文件路径 + GREEN 日志

### 步骤 4：系统接入（engine.py + polling_trader.py）

**输入**：GREEN 实现的三件套

**处理**：

**4.1 engine.py 接入**：
1. `__init__` 新增 `self._<factor>_genome = None`
2. 新增 `get_<factor>_genome()` 延迟初始化方法
3. `evolve()` 末尾追加基因组自进化调用（FAIL-OPEN 包裹）

```python
# engine.py 接入模板
def get_<factor>_genome(self):
    if self._<factor>_genome is None:
        try:
            from dreamos.evolution.<factor>_genome import <Genome>
            from dreamos.evolution.<factor>_ending_detector import <Detector>
            from dreamos.evolution.<factor>_case_library import <Library>
            from dreamos.evolution.washout_bayesian_updater import BayesianUpdater
            self._<factor>_genome = <Genome>(
                washout_detector=None,
                ending_detector=<Detector>(),
                case_library=<Library>(),
                bayesian_updater=BayesianUpdater(),
                enable=False,  # HC-X5: 默认关闭
                sandbox_validate_fn=self._sandbox_validate,
            )
        except Exception:
            self._<factor>_genome = None
    return self._<factor>_genome
```

**4.2 polling_trader.py 接入**：
1. 新增类属性 `ENABLE_<FACTOR>_GENOME: bool = False`
2. 在 probe 候选注入段（做多/做空信号注入）

```python
# polling_trader.py 接入模板
ENABLE_<FACTOR>_GENOME: bool = False  # HC-X5: 默认关闭

# 信号注入段
if self.ENABLE_<FACTOR>_GENOME:
    try:
        _evo = getattr(self, "_evolution_engine", None)
        if _evo is not None:
            _genome = _evo.get_<factor>_genome()
            if _genome is not None and _genome.enable:
                for _coin, _inf in all_inferences.items():
                    # ... detect_signal → 注入 open_candidates
    except Exception:
        pass  # FAIL-OPEN
```

**验证**：
```bash
pytest test_<factor>_wireup.py -v   # wireup 测试
```

### 步骤 5：回测补样本（目标 ≥30 案例）

**输入**：三件套实现 + 本地 K 线数据

**处理**：

1. 编写回测脚本 `<factor>_reversal_backtest.py`
2. 加载本地 BTC 1D K 线（`BTC_1D_full.csv`）
3. 滑动窗口检测信号（窗口 365 天，步进 1 天）
4. 模拟交易（持仓 7 天，TP=15%，SL=20%）
5. 记录案例到 JSONL（标签 `<direction>_success` / `<direction>_fail`）

**回测参数模板**：

```python
WINDOW_SIZE = 365      # 窗口大小
STEP = 1               # 步进天数
HOLD_DAYS = 7          # 持仓天数
TP_PCT = 0.15          # 止盈
SL_PCT = 0.20          # 止损
CONF_THRESHOLD = 0.75  # 放宽 confidence 阈值
PROBE_THRESHOLD = 0.50  # 放宽 probe 阈值
```

**回测宽松策略**（案例不足时）：
- EndingDetector 用宽松版（≥1/3 或 ≥2/3 条件满足）
- 降低 CONF_THRESHOLD 和 PROBE_THRESHOLD
- 步进从 3 天改为 1 天

**判定标准**：
- ≥30 案例 → 可升级 KNN 路径
- 胜率 ≥50% → 可考虑启用（做多方向）
- 胜率 <40% → 保持影子模式（做空方向常见）

**输出**：
- `<factor>_reversal_backtest_cases.jsonl`（案例数据）
- `<factor>_reversal_backtest_summary.json`（统计摘要）

### 步骤 6：回归验证（零回归）

**输入**：全部实现 + 接入 + 测试

**处理**：

```bash
# 阶段因子测试
pytest test_<factor>_*.py --tb=no -q

# 全量回归（含阶段1 + 阶段2 + wireup + W1-W5）
pytest test_washout_*.py test_pump_dump_*.py --tb=no -q
```

**零回归判据**：
- 新增测试全 passed
- 原有测试无新增 failed（预存失败不算回归）
- `ENABLE_<FACTOR>_GENOME=False` 时 wireup 测试确认链路字节等价

### 步骤 7：认知闭环 + hermes 反思

**输入**：全部交付物 + 回测结果

**处理**：

1. **record（硬约束记忆闸门）**：
   ```
   record(content="[硬约束][<因子域>] <HC-X1~X7 全部约束摘要>",
          quality_level="B", tags="硬约束,<因子域>,HC-X1~X7")
   ```

2. **verify**：
   ```
   verify(memory_id="VM-xxx", success=true)
   ```

3. **record（经验总结）**：
   ```
   record(content="<回测胜率/PnL/案例数/优化方向>",
          quality_level="C", tags="<因子域>,回测,胜率,优化方向")
   ```

4. **hermes 反思**：
   ```
   本次基因组因子开发流程是否值得形成/衍生 SKILL？
   ├── 是（满足任一）：
   │   ├── 流程被复用 ≥ 2 次（洗盘 + 拉高出货 = 2 次）
   │   ├── 涉及多步编排（≥ 3 步，本 SKILL 7 步满足）
   │   └── 用户明确要求「形成 SKILL」
   │   → 已形成本 SKILL（dream-genome-factor-workflow）
   │
   └── 否：仅 record 经验
   ```

5. **影子模式决策**（如胜率不达标）：
   - 记录用户决策：保持 `ENABLE=False`，影子模式不参与实际交易
   - 记录后期优化方向

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 因子需求 / spec | 因子 TDD 任务包（YAML） |
| 步骤 2 | 任务包 | 3 个测试文件 + RED 日志 |
| 步骤 3 | 测试文件 + 任务包 | 3 个实现文件 + GREEN 日志 |
| 步骤 4 | GREEN 实现 | engine.py + polling_trader.py 接入 + wireup 测试 |
| 步骤 5 | 三件套 + K 线数据 | 案例库 JSONL + 统计 JSON |
| 步骤 6 | 全部交付物 | 零回归测试日志 |
| 步骤 7 | 回测结果 | record + verify + hermes 反思 |

---

## 四、相关 SKILL 与文档

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `dream-qwen-eval-collab` | 本 SKILL 的元编排，hermes 反思决策树来源 |
| 基础 | `dream-tdd-dev-workflow` | 通用 TDD 5 步流程（步骤 2/3 复用其红绿纪律） |
| 上游 | `dream-contradiction-theory` | A0 矛盾分析（步骤 1 复用） |
| 工具 | `tee-red-green-progress` | TEE 红绿进度机制 |
| 工具 | `test-driven-development` | 通用 TDD 方法论 |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 治理 | `dream-skill-index-governance` | SKILL 索引/版本/生命周期管理 |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、已落地因子清单

| 因子 | 方向 | 文件前缀 | 案例数 | 胜率 | 平均 PnL | 状态 |
|------|------|---------|--------|------|---------|------|
| 洗盘反转基因组 (阶段1) | 做多 LONG | `washout_reversal` | 69 | 66.7% | +3.01% | ✅ 影子模式 (False) |
| 拉高出货基因组 (阶段2) | 做空 SHORT | `pump_dump_reversal` | 93 | 32.3% | -2.97% | ✅ 影子模式 (False) |

> 两个因子均默认关闭 (`ENABLE=False`)，影子模式不参与实际交易。做空因子胜率偏低，后期优化方向：延长持仓/降低 TP/加入趋势确认。

---

## 六、硬约束模板（HC-X 系列）

每个新因子需定义以下 7 条硬约束（HC-X1 ~ HC-X7），在步骤 1 任务包中明确：

| 编号 | 约束 | 做多因子示例 (HC-G) | 做空因子示例 (HC-P) |
|------|------|---------------------|---------------------|
| HC-X1 | 信号走 evolution probe 仓 | MAX_EVOLUTION_PROBE_POSITIONS=2 | 同左 |
| HC-X2 | 主检测器 label + conf 阈值 | WASHOUT + conf≥0.80 | WEAKNESS + conf≥0.80 |
| HC-X3 | EndingDetector 异常 → FAIL-OPEN | activated=False | activated=False |
| HC-X4 | 案例库 <30 走规则化 | 规则化 EndingDetector | 规则化 EndingDetector |
| HC-X5 | 默认关闭 | ENABLE_..._GENOME=False | ENABLE_..._GENOME=False |
| HC-X6 | 信号阈值 | ≥PROBE_THRESHOLD=0.55 | ≥PROBE_THRESHOLD=0.55 |
| HC-X7 | 平仓后 record_case | 必须 | 必须 |

---

## 七、认知闭环

**任务开始前**（硬约束，不可跳过）：
```
recall(context="基因组因子 <因子名> <关键词>", top_k=5, min_quality="C")
```

**任务完成后**：
```
# 硬约束记忆
record(content="[硬约束][<因子域>] HC-X1~X7 摘要", quality_level="B",
       tags="硬约束,<因子域>,HC-X1~X7")

# 经验记忆
record(content="<回测胜率/PnL/优化方向>", quality_level="C",
       tags="<因子域>,回测,胜率,优化方向")

# 验证升级
verify(memory_id="VM-xxx", success=true)
```

**已沉淀的认知记忆**：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| `VM-1790082413250-87c04f74` | B | 拉高出货做空因子硬约束 HC-P1~P7 |
| `VM-1790085845059-f4ed7bce` | B | 做空因子影子模式用户决策 |
| `VM-1790045029883-531d6f46` | B | 洗盘基因组阶段1 TDD 开发经验 |
| `VM-1790001702811-24bffe86` | B | hermes 反思决策树硬约束 |

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-22 | 初始版本，7 步流程 + 三件套模式 + 回测补样本 + 影子模式决策 + 2 因子落地验证 |
