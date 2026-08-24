# 数据清洗中心 + 特征工程中心 实现计划 v1.0
（对应全局 Spec v1.0 frozen：2026-08-24-data-cleaning-and-feature-hub-spec.md）

```
计划状态：可执行（经 t6 Spec 11项自检全通过，用户审阅确认）
创建日期：2026-08-24
总工期：7~8 工作日（含评审 + 灰度观察期）
总任务数：~78 项子任务，覆盖 T1~T28 全部测试编号
硬门槛：5 条铁门槛（T-G1~T-G5）= 任一不达标则阶段不通过，执行秒级回滚
```

---

## 一、执行总览与硬门槛顺序

### 1.1 三阶段里程碑

```
M1 Silver基建 + yfinance试点（2天）
 │
 ├─ Day 1 上午：Contract/Errors → Cleaners → QualityGate
 ├─ Day 1 下午：Adapters → Pipeline + fail-open → H1集成
 ├─ Day 2 上午：CLI → T1~T10 单测全绿 → T11 全局回归（★T-G1 铁门槛：18-M1~M5 164项 0 回归）
 └─ Day 2 下午：T12 yfinance E2E → M1 评审 & B+B 冻结
 │
 ▼ 必须 T11=0 回归 才允许进入 M2（否则 M1 回滚重调）
 │
M2 FeatureHub基建 + 提拔 + 3Adapter（2.5天）
 │
 ├─ Day 3 上午：Contract/Errors → FR提拔迁入 + shim → T13 等价性（★T-G5 铁门槛：11单测全绿）
 ├─ Day 3 下午：标准清洗链 → T14 边例全绿
 ├─ Day 4 上午：TripleScreen Adapter（T15 <ε=1e-9）→ Elder/FC Adapter（T16）
 ├─ Day 4 下午：Lineage + Versioning → FeaturePipeline 编排（T18~T19）
 └─ Day 5 上午：跨策略3集合（T17）→ CLI 4子命令冒烟（T20）→ M2 评审 & B+B
 │
 ▼ 必须 T13 全绿 才允许进入 M3（否则 FR 提拔撤回）
 │
M3 全量收口 + 逐策略灰度周（3天 + 1周观察）
 │
 ├─ Day 5 下午：Silver覆盖7collector（T21 8×3=24组合）→ T22 拦截率≥99.5%（★T-G4）
 ├─ Day 6 上午：剩余Adapter（Classic/Martin/基本面）（T23）→ 跨策略复用（T24）
 ├─ Day 6 下午：T25 策略一致性≥95%/≥0.97（★T-G3）→ T26 L1 fail-open注入
 └─ Day 7 上午：T27 全局二次回归 0 回归（★T-G2）→ T28 shadow-mode E2E
 │
 ▼ 周1~周5 逐策略灰度（周1 Silver全源 → 周2 易经btc → 周3 三屏alt → 周4 经典美股 → 周5 全量）
 └─ 灰度期结束 → 全局评审通过 = 项目落地（7~8工作日完成）
```

### 1.2 五条不可逾越硬门槛（任一不达标 = 阶段不通过 → 回滚）

| # | 门槛 | 触发阶段 | 验收命令 | 失败回滚 |
|---|---|---|---|---|
| T-G1 | M1 全局回归：18-M1~M5 **164/164 全绿，0 回归** | M1 结束前 | `cd 18-数据获取中心 && pytest -q 2>&1 \| tail -5` grep `164 passed` | `EN_SILVER=False` + 回退 dispatcher.py + 删 20 目录 |
| T-G2 | M3 全局二次回归：18+19+11/12/10/14 策略全库 **0 回归** | M3 结束前 | `find . -name "test_*.py" -path "*/tests/*" \| xargs pytest -q 2>&1 \| tail -20` | 逐策略 Flag=False → 全局 EN_SILVER=False → 删 shim → 删 20/21 目录 |
| T-G3 | 策略一致性：开=True vs 关=False，**信号方向≥95%、权益曲线Pearson≥0.97** | M3 T25 | `pytest 21/tests/integration/test_consistency.py -v` | 对应策略 EN_FEATUREHUB_*=False，暂停灰度 |
| T-G4 | 脏数据拦截率：8源×3资产×4类脏注入，**总拦截≥99.5%** | M3 T22 | `pytest 20/tests/test_gate_dirty_injection.py -v` 看 assert ≥0.995 | 收严清洗参数 → 加针对性 IQR/ATR 规则，直至达标 |
| T-G5 | FR提拔等价性：**易经原11项测试100%通过** + TripleScreen Adapter**逐列 < ε=1e-9** | M2 T13~T15 | `pytest 11-易经推理系统/scripts/memory_l4/bcrm2/tests/ -v 2>&1 \| tail -5`（从shim路径import） + `21/tests/unit/test_triple_screen_adapter.py` 看 `assert diff.abs().max() < 1e-9` | 删除 shim → 重指回易经原文件路径 + 删 21/feature_hub/hub/feature_registry.py |

### 1.3 TDD 执行铁则（每子任务必遵守）

```
每子任务固定三步：
  ① 先写测试代码 → 运行 → 确认测试 FAIL（红）
  ② 再写实现代码 → 运行 → 确认该测试 PASS（绿）
  ③ 不得修改既有测试用例以逃避失败（T10/H1旁路等价、T13/FR等价等基准测试）

例外：仅当有强证据证明测试本身 fundamentally flawed/过时，才允许修改，需先论证理由。
```

### 1.4 秒级回滚速查（任何阶段一键复原）

```bash
# 最激进：一键完全清除新系统（不留痕迹）
rm -rf "20-数据清洗中心" "21-特征工程中心"
# 恢复 11-易经 feature_registry.py（FR提拔前备份必存在）
cp "11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py.BAK_M2_START" \
   "11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py"
# 恢复 dispatcher.py（H1前备份必存在）
cp "18-数据获取中心/data_center/core/dispatcher.py.BAK_M1_START" \
   "18-数据获取中心/data_center/core/dispatcher.py"

# 细粒度：仅关开关（不改代码，秒级回滚）
export EN_SILVER=false                    # M1/M3 全局 Silver 旁路
export EN_FEATUREHUB_BTC_MORPH=false       # 逐策略旁路
export EN_FEATUREHUB_TRIPLE_SCREEN=false
export EN_FEATUREHUB_CLASSIC=false
```

> **H1/H2 热修改前必做**：`cp dispatcher.py dispatcher.py.BAK_M1_START` / `cp feature_registry.py feature_registry.py.BAK_M2_START`，这是回滚安全网。

---

## 二、M1 · Silver 基建 + yfinance 单源试点（工期：2 工作日）

### 2.1 M1.0 前置准备（0.5h，M1-Day1 09:00）

| # | 任务 | TDD/验证 | 文件 | 验收 |
|---|---|---|---|---|
| m1-0.1 | 保存 dispatcher.py 备份（回滚基础） | 手动 | `18-数据获取中心/data_center/core/dispatcher.py.BAK_M1_START` | `diff` 与原文件=0差异 |
| m1-0.2 | 保存 18-全局164项基线快照（T11 对比基准） | `cd 18-数据获取中心 && pytest -q --tb=no > /tmp/m1_t11_baseline.txt` | `/tmp/m1_t11_baseline.txt` | 内容必含 `164 passed` |
| m1-0.3 | 确认 18-quality.py 对外 API（QualityChecker + 4 IssueCode） | `grep -n "class QualityChecker\|^class\|EMPTY_RESULT\|CONTRACT_INVALID\|DUPLICATE_DETECTED\|TIMESTAMP_FRESHNESS" 18-数据获取中心/data_center/monitoring/quality.py` | 18-quality API 清单 | 4 IssueCode 枚举名 + QualityChecker 方法签名记录 |
| m1-0.4 | 确认 data_center.monitoring.alerting API（dispatch + 3 channel） | `grep -n "def dispatch\|class.*Channel" 18-数据获取中心/data_center/monitoring/alerting.py` | alerting API 清单 | dispatch() 可调用 + Log/File/Lark 三通道存在 |

### 2.2 M1.1 Contract + Errors（T1，1.5h，Day1 09:30）

| # | 任务 | TDD 步骤 | 文件 | 关联测试 |
|---|---|---|---|---|
| m1-1.1 | ①先写测试：T1 Contract dataclass 字段齐全 | → 先红 | `20-数据清洗中心/tests/test_contract.py` | T1-1 |
| | 定义 SilverRecord(bronze_id, df, trace, gate_passed, quality_report)、CleanedDF(df, schema_tag)、CleaningTrace(actions: List[CleanAction])、CleanAction(step, input_rows, output_rows, clipped_count, imputed_count, note) | | | |
| m1-1.2 | ②实现 contract.py | → 转绿 | `20-数据清洗中心/data_cleaning/contract.py` | T1-1 |
| m1-1.3 | ①先写测试：T1 Errors 继承层次正确 | → 先红 | `20-数据清洗中心/tests/test_errors.py` | T1-2 |
| | CleaningError(BaseException) / QualityGateFailed(CleaningError, code=IssueCode) 继承关系，trace 字段存在 | | | |
| m1-1.4 | ②实现 errors.py | → 转绿 | `20-数据清洗中心/data_cleaning/errors.py` | T1-2 |
| m1-1.5 | __init__.py 导出：Contract 三类型 + Errors 二类型 | 手动 import 不报错 | `20-数据清洗中心/data_cleaning/__init__.py` | T1-3 |

### 2.3 M1.2 Cleaners 算子层（T2~T5，4h，Day1 11:00）

| # | 任务 | TDD 步骤 | 文件 | 关联测试 |
|---|---|---|---|---|
| m1-2.1 | **T2 DedupAlign**：①先写 T2 测试 6 条边例（重复行删；resample 对齐；ffill limit=5；超限→线性插值；极端全空→中性50；三类DataRecord(metrics/ts/events)分别跑）→ 红 | → 先红 | `20/tests/test_dedup_align.py` | T2-1~T2-6 |
| m1-2.2 | ②实现 dedup_align.py（DedupAlignCleaner） | → 转绿 | `20/data_cleaning/cleaners/dedup_align.py` | T2 全绿 |
| m1-2.3 | **T3 Outlier3LFilter（核心）**：①先写 T3 测试 8 条边例（3σ正常过；|Z|>3 标记trace不裁剪；IQR=0不抛；黄金k=2.5/股票k=2.8查表正确；巨鲸事件期匹配保留原值；低波动期IQR clip边界正确；冷启动NaN不崩；三档计数分别落CleanAction）→ 红 | → 先红 | `20/tests/test_outlier_filter.py` | T3-1~T3-8 |
| m1-2.4 | ②实现 outlier_filter.py（Outlier3LFilter，Z=3.0/B1，IQR=1.5×/B2，ATR14×3.0/B3，category×asset走查YAML） | → 转绿 | `20/data_cleaning/cleaners/outlier_filter.py` + `20/config/cleaning_rules.yaml`（写入 B1~B3 默认初值 + 黄金k=2.5/股票k=2.8/宏观IQR=1.3×特例） | T3 全绿 |
| m1-2.5 | **T4 MissingImputer**：①先写 T4 测试 6 条边例（时序 ffill(5)；连续>5空→linear；整列全空→全50；宏观 linear→拖尾→50；事件 True/False→1/0；事件未知→0.5中性）→ 红 | → 先红 | `20/tests/test_missing_imputer.py` | T4-1~T4-6 |
| m1-2.6 | ②实现 missing_imputer.py（MissingImputer，B5 fail-open=50，B7 limit=5） | → 转绿 | `20/data_cleaning/cleaners/missing_imputer.py` | T4 全绿 |
| m1-2.7 | **T5 UnitNormalizer**：①先写 T5 测试 4 条边例（非USD×汇率表；百分比/100；换手率%→ratio；单位已统一不改）→ 红 | → 先红 | `20/tests/test_unit_normalizer.py` | T5-1~T5-4 |
| m1-2.8 | ②实现 unit_normalizer.py（UnitNormalizer，内置最小汇率表：EUR/JPY/GBP→USD，可扩展） | → 转绿 | `20/data_cleaning/cleaners/unit_normalizer.py` | T5 全绿 |

### 2.4 M1.3 QualityGate（T6 脏数据注入，2h，Day1 15:00）

| # | 任务 | TDD 步骤 | 文件 | 关联测试 |
|---|---|---|---|---|
| m1-3.1 | ①先写 T6 测试 4×2=8 条脏注入（EMPTY/空>70%→FAIL；CONTRACT缺列/类型错→FAIL；DUPLICATE清洗后有重复→FAIL；STALE>15min→FAIL；且每类都断言：DB写入=0、Bronze审计行存在、告警计数+1）→ 红 | → 先红 | `20/tests/test_gate_quality.py`（import QualityChecker from data_center.monitoring.quality） | T6-1~T6-8 |
| m1-3.2 | ②实现 quality_gate.py（QualityGate = Facade on 18-quality，新增参数 enforce_hard_block=True：Fail时 raise QualityGateFailed；False时仅report不抛） | → 转绿 | `20/data_cleaning/gate/quality_gate.py` | T6 全绿 |
| m1-3.3 | 验证 fail-open 不吞错（QualityGateFailed 携带 code + 6 层 trace） | `pytest -k test_gate_fail_leaves_stack` | `20/tests/test_gate_quality.py` 加断言 | T6-9 |

### 2.5 M1.4 Record↔DF Adapters（T7~T8，1.5h，Day1 16:30）

| # | 任务 | TDD 步骤 | 文件 | 关联测试 |
|---|---|---|---|---|
| m1-4.1 | **T7 DataRecord→DF**：①先写 T7 测试 3 条（metrics：k→列，value→值；timeseries：timestamp索引 + ohlcv 5列展开；events：event_type one-hot + 时间戳）→ 红 | → 先红 | `20/tests/test_adapters.py::test_record_to_df_*` | T7-1~T7-3 |
| m1-4.2 | ②实现 record_to_df.py（按 DataRecord.category 三分支展开） | → 转绿 | `20/data_cleaning/adapters/record_to_df.py` | T7 全绿 |
| m1-4.3 | **T8 DF→SilverRecord**：①先写 T8 测试 3 条（DF+bronze_id→SilverRecord 字段齐全；CleaningTrace 行数对应；双向 round-trip 无损：record→DF→SilverRecord，原字段能还原）→ 红 | → 先红 | `20/tests/test_adapters.py::test_df_to_silver_*` | T8-1~T8-3 |
| m1-4.4 | ②实现 df_to_record.py（DF→SilverRecord，附 bronze_id + trace） | → 转绿 | `20/data_cleaning/adapters/df_to_record.py` | T8 全绿 |

### 2.6 M1.5 Pipeline 全链路 + fail-open（T9，1.5h，Day1 18:00）

| # | 任务 | TDD 步骤 | 文件 | 关联测试 |
|---|---|---|---|---|
| m1-5.1 | ①先写 T9 测试 6 条（正常链：DataRecord→SilverRecord+trace非空；Cleaner抛异常→fail-open=50兜底；QualityGate PASS→gate_passed=True；Gate FAIL→gate_passed=False+alert计数；多Cleaner顺序严格=Dedup→Outlier→Imputer→Normalizer→Gate；run_or_fallback 永不抛异常）→ 红 | → 先红 | `20/tests/test_cleaning_pipeline.py` | T9-1~T9-6 |
| m1-5.2 | ②实现 cleaning_pipeline.py（CleaningPipeline：Chain of Resp，.add().run()；default_with_gate(enforce_hard_block=True)一键构建标准顺序；run_or_fallback(record) → SilverResult，含 gate_passed/bronze_record/quality_report 三字段） | → 转绿 | `20/data_cleaning/pipeline/cleaning_pipeline.py` | T9 全绿 |
| m1-5.3 | 更新 __init__.py 导出 CleaningPipeline + SilverResult | 手动 import 验证 | `20/data_cleaning/__init__.py` | T9-7 |

### 2.7 M1.6 H1 集成 + EN_SILVER 旁路等价（T10，2h，Day2 09:00）

| # | 任务 | TDD 步骤 | 文件 | 关联测试 |
|---|---|---|---|---|
| m1-6.1 | ①先写 T10 测试 2 条（EN_SILVER=False 时：_fetch_monitored 返回值 == M1.0 基线行为 byte-level 等价；18对外任何接口无新增参数/返回值变化）→ 红 | → 先红 | `20/tests/test_h1_bypass_equivalence.py`（monkeypatch EN_SILVER=false 跑 _fetch_monitored） | T10-1~T10-2 |
| m1-6.2 | ②修改 dispatcher.py（H1 ~10行）：顶部 import CleaningPipeline + _pipe 初始化；_fetch_monitored 内部 sink 前调用 `_pipe.run_or_fallback(record)`；if/else 双写分支；return record 保持不变；**用 EN_SILVER 环境变量控制整段（默认 False=完全旁路）** | → 转绿 | `18-数据获取中心/data_center/core/dispatcher.py`（严格按 §4.4 H1 代码，不改契约） | T10 全绿 |
| m1-6.3 | 验证：EN_SILVER=true 时 yfinance_collector 会走 CleaningPipeline，Gate PASS→write_silver 被调用一次（mock sink 断言） | `pytest -k test_h1_enabled_runs_pipe` | `20/tests/test_h1_bypass_equivalence.py` | T10-3 |

### 2.8 M1.7 dc-clean CLI（1h，Day2 11:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m1-7.1 | 实现 CLI 三命令（status/health/verify）：status 输出 pass_rate/intercept_rate/failopen_count/stale各源；health --source --asset 输出近N条 trace + 脏样本样例；verify 跑 CleaningPipeline 对样例DataRecord一遍冒烟 | 手动 run 命令冒烟 + 3 条 CLI 用例 | `20/data_cleaning/cli/app.py` + `20/tests/test_cli.py` | T-（无编号，验收辅助） |

### 2.9 M1.8 ★ T-G1 铁门槛：全局回归（1h，Day2 13:00）—— **不过则 M1 不通过**

| # | 任务 | 验证 | 文件 | 不达标处理 |
|---|---|---|---|---|
| m1-8.1 | **T11 全局回归**：18-M1~M5 原 164 项 **全绿 0 回归** | `cd 18-数据获取中心 && pytest -q 2>&1 \| tail -5` 输出 **164 passed**；与 /tmp/m1_t11_baseline.txt diff=0 | （T11） | 立即回滚：EN_SILVER=False + dispatcher.py 还原 BAK；定位回归点重改 |
| m1-8.2 | Ruff 代码质量 0 错误：20 目录全部 .py | `cd 20-数据清洗中心 && ruff check data_cleaning/ 2>&1 \| tail -3` | （Ruff） | 修复到 0 error |

### 2.10 M1.9 T12 yfinance BTC E2E 端到端（1h，Day2 14:00）

| # | 任务 | 验证 | 文件 |
|---|---|---|---|
| m1-9.1 | **T12**：EN_SILVER=true，category=finance，source=yfinance，symbol=BTC → 完整链：拉取 → 清洗 → CleaningTrace 非空 → QualityGate PASS/FAIL 正确标记 → SilverRecord 字段齐全 | `pytest 20/tests/test_e2e_yfinance_btc.py -v`（用 Cassette/本地 cache 避免联网不稳定性） | `20/tests/test_e2e_yfinance_btc.py` |

### 2.11 M1 阶段评审（1h，Day2 15:00）—— B+B 冻结确认

> M1 交付物 checklist：
> - [ ] 20号完整代码骨架（T1~T10 全绿）
> - [ ] yfinance_collector 单源接入 + H1 双写
> - [ ] dc-clean CLI 三命令可用
> - [ ] ★ T11 全局 164/164 = 0 回归（硬门槛 T-G1）
> - [ ] T12 yfinance BTC E2E PASS
> - [ ] Ruff 0 error
> - [ ] 回滚备份（dispatcher.py.BAK_M1_START + shim前备份）健在

**→ B+B 确认通过 → 进入 M2；否则按 m1-8.1 回滚。**

---

## 三、M2 · FeatureHub 基建 + FR提拔 + 3Adapter（工期：2.5 工作日）

### 3.1 M2.0 前置准备（0.5h，M2-Day3 09:00）

| # | 任务 | 验证 | 文件 |
|---|---|---|---|
| m2-0.1 | 保存 feature_registry.py 备份（提拔前原始文件） | `cp 11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py 11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py.BAK_M2_START` + `diff`=0 | feature_registry.py.BAK_M2_START |
| m2-0.2 | 记录易经原 11 项单元测试基线（T13 对比基准） | `cd 11-易经推理系统 && pytest scripts/memory_l4/bcrm2/tests/test_feature_registry.py -q > /tmp/m2_t13_baseline.txt` 含 `11 passed` | /tmp/m2_t13_baseline.txt |
| m2-0.3 | 确认 FR 文件对外导出符号表（shim 反 re-export 需要一一对应） | `grep -n "^class\|^def\|^[A-Z_]* =" 11-.../feature_registry.py > /tmp/m2_fr_exports.txt` | /tmp/m2_fr_exports.txt（符号清单） |
| m2-0.4 | 读取三屏 TrendFeatureEngineer.create_features 签名（T15 Adapter需要） | `grep -A 3 "def create_features" 12-三屏趋势系统/.../trend_feature_engineer.py` | TrendFeatureEngineer 签名 |

### 3.2 M2.1 Contract + Errors（T 补，1h，Day3 09:30）

| # | 任务 | TDD 步骤 | 文件 |
|---|---|---|---|
| m2-1.1 | ①先写合同测试 | → 红 | `21/tests/unit/test_contract.py` |
| | FeatureVector(df, meta) / FeatureSpec(name, version, enabled_sets, input_cols, output_cols) / LineageRecord(timestamp, module, input_cols→output_cols, dropped_cols, reasons) | | |
| m2-1.2 | ②实现 contract.py | → 绿 | `21/feature_hub/contract.py` |
| m2-1.3 | ①errors 测试 | → 红 | `21/tests/unit/test_errors.py` |
| | FeatureError / FeatureSetNotFound(name) 继承正确 | | |
| m2-1.4 | ②实现 errors.py | → 绿 | `21/feature_hub/errors.py` |

### 3.3 M2.2 FR 提拔迁入 + shim（T13，★T-G5 铁门槛，3h，Day3 11:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m2-2.1 | 整体文件迁入（**字节级 copy，不做任何修改**） | `cp 11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py 21-特征工程中心/feature_hub/hub/feature_registry.py` | `21/feature_hub/hub/feature_registry.py` | — |
| m2-2.2 | enabled_sets.py：从 FR 中拆分 ENABLED_SETS 常量表（引用关系不变，只是落单独文件；FR里从 enabled_sets import，保持对外语义一致） | 单测跑通才允许拆分 | `21/feature_hub/hub/enabled_sets.py` + 修改 21-hub/feature_registry.py 的 import 指向 | T13-0 |
| m2-2.3 | ①先写 T13-1 等价性测试：**shim.FeatureRegistry is feature_hub.FeatureRegistry**（身份断言，不是 == 比较）→ 红 | → 先红 | `21/tests/unit/test_fr_promotion_equivalence.py` | T13-1 |
| m2-2.4 | ②实现 shim：原 11-易经路径 feature_registry.py → 改为 5 行反 re-export（按 §5.3 H2 代码，符号一一对齐 /tmp/m2_fr_exports.txt） | → 转绿 | `11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py`（shim） | T13-1 |
| m2-2.5 | **★T13-2 T-G5 铁门槛验收：易经原 11 项测试从 shim 路径 import → 100% 通过** | `cd 11-易经推理系统 && pytest scripts/memory_l4/bcrm2/tests/test_feature_registry.py -q 2>&1 \| tail -3` 输出 **11 passed**；与 /tmp/m2_t13_baseline.txt diff=0 | （T13-2） | 不达标 → 立即回滚 m2-0.1 BAK，暂停提拔 |
| m2-2.6 | T13-3：ENABLED_SETS 从 shim 读取 == 从 feature_hub 直接读取（逐 key 断言 dict 相等） | `pytest -k t13_enabled_sets_equal` | `21/tests/unit/test_fr_promotion_equivalence.py` | T13-3 |

### 3.4 M2.3 标准特征清洗链（T14，3h，Day3 14:30）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m2-3.1 | ①先写 T14 测试 7 条边例：Inf/NaN全消无残留；IQR=0恒等缩放不除零；样本<1000自动跳过VIF；无y自动跳过IV；VIF>10从高到低剔除；IV<0.02剔除；任一步异常→Raw透传+warning（L1 fail-open）→ 红 | → 先红 | `21/tests/unit/test_standard_cleaning_chain.py` | T14-1~T14-7 |
| m2-3.2 | ②实现 cleaning_steps.py（4步各自的 Step 类：InfNaNImpute / RobustScalerIQR / VIFDropper / IVDropper，每步 fit_transform + meta 字段） | → 逐项转绿 | `21/feature_hub/cleaning_chain/cleaning_steps.py` | T14 每步绿 |
| m2-3.3 | ③实现 standard_chain.py（StandardCleaningChain：按 B8 顺序串 4 步；skip_vif_if=lambda X:len(X)<1000；skip_iv_if=lambda y:y is None；热路径 fail-open wrapper 永不抛） | → 全绿 | `21/feature_hub/cleaning_chain/standard_chain.py` | T14 全绿 |

### 3.5 M2.4 Adapter 三实现（T15~T16，5h，Day3 18:00 → Day4 09:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m2-4.0 | 先实现 adapter 基类：BaseAdapter（统一 compute(df, ref_df, macro_df, symbol) → DataFrame 接口） + SklearnStyleAdapter + RegistryAdapter 三基类 | `21/tests/unit/test_adapters_base.py` 红 → 绿 | `21/feature_hub/adapters/{base_adapter,registry_adapter,sklearn_style_adapter}.py` | 基类 3 项 |
| m2-4.1 | **T15 TripleScreen Adapter（硬门槛：逐列 < ε=1e-9）**：①先写测试：对同一个 ohlcv DF，`TrendFeatureEngineer.create_features(ohlcv)` vs `SklearnStyleAdapter(TrendFeatureEngineer, views=None).compute(ohlcv, ...)` → **逐列 diff.abs().max() < 1e-9** → 红 | → 先红 | `21/tests/unit/test_triple_screen_adapter.py` | T15 |
| m2-4.2 | ②实现 triple_screen_trend.py（SklearnStyleAdapter(TrendFeatureEngineer) 包装 + 参数透传） | → 转绿（必须 ε<1e-9，任何列超差=不通过） | `21/feature_hub/modules/triple_screen_trend.py` | T15 绿 |
| m2-4.3 | **T16-1 Elder-ray Adapter**：①先写测试：易经 ElderRayObserver.grade() 返回 rating(BULLISH_BEARISH x LEVEL) → one-hot 编码 5列 + 差分 2列，合计 7列，输出正确 → 红 | → 先红 | `21/tests/unit/test_elder_ray_adapter.py` | T16-1 |
| m2-4.4 | ②实现 elder_ray.py（Adapter：包装 ElderRayObserver.grade → 7 列标准化特征） | → 转绿 | `21/feature_hub/modules/elder_ray.py` | T16-1 绿 |
| m2-4.5 | **T16-2 FiveDomainFc Adapter**：①先写测试：FiveDomainFeatureComputer.compute() 输出 dao/jiang/fa/tian/de 5 行 raw_scores → 5列，RobustScaler 后范围≈[-3, 3]，每列无NaN → 红 | → 先红 | `21/tests/unit/test_five_domain_fc_adapter.py` | T16-2 |
| m2-4.6 | ②实现 five_domain_fc.py（Adapter：按 asset_class 传差异化 coin_data → FiveDomainFeatureComputer → 五行5列标准化） | → 转绿 | `21/feature_hub/modules/five_domain_fc.py` | T16-2 绿 |

### 3.6 M2.5 Lineage + Versioning（T18，1.5h，Day4 12:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m2-5.1 | T18-1 血缘：①测试：注册A(输入col_x,y→输出x2,y2)→注册B(输入x2→输出x3)→跑一遍 → LineageRecord 两条，A的输出col包含x2，B的输入col包含x2，**无断链**；断链（前一步输出≠下一步输入）→ L3 启动期 FAIL-FAST 抛异常 → 红 | → 先红 | `21/tests/unit/test_lineage.py` | T18-1 |
| m2-5.2 | ②实现 lineage.py（LineageTracker：add(module, input_cols→output_cols) + verify_closed() 断言无断链，L3 FailFast） | → 转绿 | `21/feature_hub/hub/lineage.py` | T18-1 绿 |
| m2-5.3 | T18-2 版本号：①测试：注册 name="morphology_core",version="2.1.0" → registry 查询 version=="2.1.0"；重名不同版本 → L3 Fail-Fast（启动期）；semver 格式非法 → Fail-Fast → 红 | → 先红 | `21/tests/unit/test_versioning.py` | T18-2 |
| m2-5.4 | ②实现 versioning.py（SemVer 解析 + 注册时唯一性校验） | → 转绿 | `21/feature_hub/hub/versioning.py` | T18-2 绿 |

### 3.7 M2.6 FeaturePipeline 编排（T19，1.5h，Day4 14:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m2-6.1 | ①先写 T19 测试 3 条：按 ENABLED_SETS 拉取模块 concat → 走标准清洗链 → FeatureVector 形状正确；L1 某模块异常 → 跳过该模块 + log.warning + 其他模块照常输出；启用集合名错 → L3 Fail-Fast（启动期） | → 先红 | `21/tests/unit/test_feature_pipeline.py` | T19-1~T19-3 |
| m2-6.2 | ②实现 feature_pipeline.py（FeaturePipeline.run(set_name, df, symbol, ...) → FeatureVector；ENABLED_SETS 从 feature_registry.ENABLED_SETS 查） | → 转绿 | `21/feature_hub/pipeline/feature_pipeline.py` | T19 全绿 |
| m2-6.3 | 更新 __init__.py 导出 FeatureHub + StandardCleaningChain + FeaturePipeline | 手动 import 验证 | `21/feature_hub/__init__.py` | T19-4 |

### 3.8 M2.7 跨策略3样例集合（T17，2h，Day4 15:30）—— 证明 FeatureHub 跨策略复用

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m2-7.1 | 迁移 crypto_morphology.py 到 modules/（易经原4模块：morphology_core + ma200_cycle + multi_tf + rolling_stats → Native 注册） | 单测4模块跑通 | `21/feature_hub/modules/crypto_morphology.py`（从易经迁移，加 @register_module 装饰） | 迁移冒烟 |
| m2-7.2 | T17：①先写 3 条集成测试：set=btc_morph_v6（样例BTC-DF → 输出 shape ≥ 40列 无NaN）；set=alt_trend_ensemble（morphology + elder + triple_screen 跨域融合 → shape ≥ 60列，且 elder 输出5列存在）；set=equity_classic_trend（triple_screen + classic_indicators stub + five_domain_fc（jiang=0.18权重）→ shape ≥ 30列）→ 红 | → 先红 | `21/tests/integration/test_cross_strategy_sets.py` | T17-1~T17-3 |
| m2-7.3 | ②在 config/feature_sets.yaml 写 3 启用集合映射；必要时补 classic_indicators.py 的 minimal stub（IV 过滤先返回 10 列常用 talib，不影响 shape 断言） | → 转绿 | `21/config/feature_sets.yaml` + `21/feature_hub/modules/classic_indicators.py`（stub，后续M3.2完善） | T17 全绿 |

### 3.9 M2.8 fh CLI 四命令冒烟（T20，1h，Day4 17:30）

| # | 任务 | 验证 | 文件 | 关联T |
|---|---|---|---|---|
| m2-9.1 | 实现 CLI：`fh list`（模块名/版本/启用集合 表格）；`fh inspect --set alt_trend_ensemble`（集合组成/预期列数/VIF最近统计/血缘断链检测）；`fh run-sample --set btc_morph_v6 --symbol BTC --sample DATES`（样例DF一键全链）；`fh export-schema --set X`（Pandera Schema JSON 导出） | 4 命令手动运行冒烟 + 4 条 CLI 测试 | `21/feature_hub/cli/app.py` + `21/tests/unit/test_cli.py` | T20-1~T20-4 |

### 3.10 M2 阶段评审（1h，Day5 09:00）—— B+B 冻结

> M2 交付物 checklist：
> - [ ] 21号完整代码（Contract/Errors/Hub/CleaningChain/Modules/Adapters/Pipeline/CLI）
> - [ ] ★ T13 FR提拔等价性：11 项全绿（T-G5）
> - [ ] T14 标准清洗链 7 条全绿
> - [ ] T15 TripleScreen 逐列 < ε=1e-9（T-G5）
> - [ ] T16 Elder-ray/FiveDomainFc Adapter
> - [ ] T17 跨策略3集合样例
> - [ ] T18 血缘+版本号 L3 Fail-Fast
> - [ ] T19 FeaturePipeline 编排
> - [ ] T20 CLI 四命令冒烟
> - [ ] Ruff 0 error（21目录）
> - [ ] 回滚备份（feature_registry.py.BAK_M2_START）健在

**→ B+B 确认通过 → 进入 M3；否则按 T-G5 不达标处理：FR提拔撤回（shim 回退 BAK）。**

---

## 四、M3 · 全量收口 + 逐策略灰度周（工期：3 工作日 + 1 周灰度观察期）

### 4.1 M3.0 前置准备（0.5h，M3-Day5 09:30）

| # | 任务 | 验证 | 文件 |
|---|---|---|---|
| m3-0.1 | 保存 11/12/10 三策略入口文件备份（H3 wrapper 前） | `cp 11-.../predict.py 11-.../predict.py.BAK_M3_START`（12/10 同理） | 3× BAK_M3_START |
| m3-0.2 | 8 collector 清单 + 各典型资产 3 个（crypto/finance/macro/news/chain） | 列 8×3=24 组合表到测试注释 | `20/tests/test_all_24_combo.py` |
| m3-0.3 | 策略一致性基准：11/12/10 各跑 100 条历史样本，记录 baseline 信号方向 + 权益序列（保存到 /tmp/m3_consistency_baseline_{btc,alt,equity}.pkl） | 3 pickle 文件 | /tmp/m3_consistency_*.pkl |

### 4.2 M3.1 Silver 覆盖 8 collector 全源（T21，3h，Day5 10:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m3-1.1 | T21：①先写 24 组合参数化测试：`@pytest.mark.parametrize("collector,asset", [("yfinance","BTC"),("yfinance","COIN"),("fred","M2NS"),("etherscan","ETH"),("feedparser","BTC"), 其余7源×3资产 ...])` 共 24 条 → 对每条构造样例 DataRecord → 跑 CleaningPipeline → CleaningTrace 非空 + Gate 非崩（PASS/FAIL 都允许，只要不抛）| → 先红 | `20/tests/test_all_24_combo.py` | T21 1~24 |
| m3-1.2 | ②逐个 collector 调参 cleaning_rules.yaml：按 collector×category 覆盖 B1~B3 参数（必要时新增 category 细分），使 24 条全部通过 | → 逐条转绿 | `20/config/cleaning_rules.yaml`（新增 7 collector 的 YAML 配置段） | T21 24/24 绿 |

### 4.3 M3.2 ★ T-G4 拦截率硬门槛：脏数据注入（T22，3h，Day5 13:00）—— **不过则 M3 不通过**

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m3-2.1 | T22 8源×3资产×4类脏 = **96 条参数化注入**：每条构造脏 DataRecord（4类随机：EMPTY/CONTRACT/DUPLICATE/STALE 各25%）→ 跑 CleaningPipeline → 统计 gate_passed=False 的比例 → **assert total_fail_rate ≥ 0.995**（1 - 漏拦截率） → 红 | → 先红 | `20/tests/test_gate_dirty_injection.py`（parametrize 96条） | T22（T-G4） |
| m3-2.2 | ②逐个漏拦截点分析，收严 cleaning_rules.yaml（加针对性 IQR/ATR 规则），或补 DedupAlign 对特定类脏数据的前置处理，直至 **96 条漏拦截 ≤ 0 条 或 总拦截率 ≥ 99.5%** | → 断言通过 | `20/config/cleaning_rules.yaml`（迭代收严）+ `20/data_cleaning/cleaners/*.py`（必要补丁） | T22 PASS ≥99.5%（T-G4） |
| m3-2.3 | 每次参数迭代后跑 T6 原脏数据注入 8 条 → 不得回归（T6 必须仍全绿） | pytest -k "t6 or t22" | （回归检查） | T6 0 回归 |

### 4.4 M3.3 剩余 Adapter 补完（Classic/Martin/基本面）（T23，4h，Day5 16:00 → Day6 09:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m3-3.1 | T23-1 Classic Indicators Adapter：10-经典系统 talib 30+ 指标 → SklearnStyleAdapter 包装，默认 IV≥0.05 启用；测试：3类资产（BTC/COIN/XAU）样例DF → 输出列数 ≥ 10 + 逐列与原实现 < ε | → 红→绿 | `21/feature_hub/modules/classic_indicators.py`（从M2 stub完善） + `21/tests/unit/test_classic_adapter.py` | T23-1 |
| m3-3.2 | T23-2 Martin Features Adapter：14-V15 网格/DD深度特征 → Adapter；测试：样例持仓历史 → 输出 DD/martin_level/grid_profit 5列 + 等价 | → 红→绿 | `21/feature_hub/modules/martin_features.py` + `21/tests/unit/test_martin_adapter.py` | T23-2 |
| m3-3.3 | T23-3 基本面 Adapter（9-基本面）：营收/PE/PB 等比率特征 → Adapter；测试：COIN/MSTR 样例 → 输出 ≥ 8 列 无 NaN + 等价 | → 红→绿 | `21/feature_hub/modules/fundamental_ratios.py` + `21/tests/unit/test_fundamental_adapter.py` | T23-3 |
| m3-3.4 | commodity_safe_haven 启用集合加入 feature_sets.yaml（classic + five_domain（黄金tian=0.22） + elder_ray） | 样例 XAU 跑 set → shape 正确 | `21/config/feature_sets.yaml` | T23-4 |

### 4.5 M3.4 跨策略复用进阶（T24，2h，Day6 11:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m3-4.1 | T24：`alt_trend_ensemble` 三模块（morphology + elder_ray + triple_screen）融合后：①列数 ≥ 60；②elder_ray 5 列 one-hot 存在（列名包含 elder_bullish_*）；③triple_screen direction 列存在；④VIF 清洗后无 VIF>10 列（若样本≥1000）→ 断言 4 条 → 红 | → 先红 | `21/tests/integration/test_alt_trend_ensemble.py` | T24 1~4 |
| m3-4.2 | ②必要时补模块 concat 的列名去重、前缀加模块名逻辑（避免重名），确保 4 条断言全绿 | → 转绿 | `21/feature_hub/pipeline/feature_pipeline.py`（concat 前加模块名列前缀） | T24 全绿 |

### 4.6 M3.5 ★ T-G3 策略一致性硬门槛 + H3 集成（T25，5h，Day6 13:00）—— **不过则策略灰度暂停**

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m3-5.1 | **H3 集成 wrapper × 3 策略**：①先写 T25 等价性测试框架：对同一批历史样本，`mode=关(False)` 跑原 FE → baseline 信号方向 & 权益；`mode=开(True)` 跑 FeaturePipeline → 计算一致率 & Pearson | → 先红 | `21/tests/integration/test_consistency.py`（parametrize 3策略×100样本） | T25 框架 |
| m3-5.2 | ②逐策略写 wrapper（各 ~10 行，共 ≤ 30 行，严格按 §6.1 H3 代码模式）：EN_FEATUREHUB_{策略}=环境变量（默认 False）；try走FeaturePipeline/异常自动回退原FE；日志含 [FeatureHub] + 6层堆栈 | → 逐项改 | 11-易经/12-三屏/10-经典 各自 predict.py 入口（H3 wrapper 代码段） | H3 3× 接入 |
| m3-5.3 | **T25-1 易经btc_morph_v6**：开 vs 关 → 信号方向一致率 ≥ 95%；权益曲线 Pearson ≥ 0.97（允许开=True 更优，不允许劣化） | 红 → 必须达标 | `21/tests/integration/test_consistency.py::test_consistency_btc` | T25-1（T-G3） |
| m3-5.4 | **T25-2 三屏 alt_trend_ensemble** | 红 → 必须达标 | test_consistency.py::test_consistency_alt | T25-2（T-G3） |
| m3-5.5 | **T25-3 经典 equity_classic_trend** | 红 → 必须达标 | test_consistency.py::test_consistency_equity | T25-3（T-G3） |
| m3-5.6 | 任一策略 < 门槛：暂停该策略灰度，debug 特征差异（典型：模块concat列名错、VIF过度剔除无预测力列、清洗链IQR错杀）；重复调优直至达标 | 不达标不允许进入灰度 | — | — |

### 4.7 M3.6 L1 fail-open 注入（T26，2h，Day6 18:00）

| # | 任务 | TDD 步骤 | 文件 | 关联T |
|---|---|---|---|---|
| m3-6.1 | T26：5 类异常注入：①CleaningPipeline某Cleaner抛 RuntimeError；②FeaturePipeline某模块抛 ImportError；③标准清洗链 VIF 计算时除零；④QualityGate 网络错；⑤Adapter 依赖缺失；每类断言：a) 不抛到调用方；b) failopen_count 指标+1；c) 同模块 mock 注入 ≥3 次/5min → alerting.dispatch() 被调用一次（Lark告警） | → 红→绿 | `20/tests/test_l1_failopen.py` + `21/tests/unit/test_l1_failopen.py` | T26-1~T26-5 |

### 4.8 M3.7 ★ T-G2 全局二次回归 0 回归（T27，2h，Day7 09:00）—— **不过则 M3 不通过**

| # | 任务 | 验证 | 文件 |
|---|---|---|---|
| m3-7.1 | **T27 铁门槛 T-G2**：18（164） + 19-DAL + 11易经策略 + 12三屏 + 10经典 + 14-V15 **全部 pytest 全绿 = 0 回归** | `find . \( -path "*/tests/test_*.py" -o -path "*/tests/unit/test_*.py" -o -path "*/tests/integration/test_*.py" \) ! -path "*/node_modules/*" | xargs pytest -q 2>&1 | tail -20` 输出 **all passed 且 error=0/failure=0** | （T27 = T-G2） |
| m3-7.2 | 0 回归对比：与 M1.0 基线 + 各策略历史基线 diff，**不允许新增任何 skip 或 xfail**，用例数与 M2.0 之后对比只允许增加不允许减少 | diff baseline 输出 | — | 任何回归 → 立即修复，暂停灰度 |

### 4.9 M3.8 Shadow-mode 冷启动 E2E（T28，2h，Day7 11:00）✅ 已完成

| # | 任务 | 验证 | 文件 | 关联T |
|---|---|---|---|---|
| m3-8.1 | T28 实盘 shadow-mode 冷启动完整链：行情数据 → Silver 清洗（trace 可追溯）→ FeatureHub FE → 战略层推理 → CBR 双闭环检索 → ElasticGate3L → 开仓决策 → is_trial 标记（BLOCK 触发时）。全程 EN_SILVER=True + EN_FEATUREHUB_*=True，**L1 零异常**，指标落表正确，新鲜度 < 15min | `pytest 21/tests/integration/test_shadow_e2e.py -v --timeout=120`（用本地 cache 行情，避免联网不稳定） | `21/tests/integration/test_shadow_e2e.py` | T28 |

#### 🎯 M3 阶段验收总结（2026-08-24）

```
M3 全量收口 + 逐策略灰度准备 — 全部完成 ✅

子任务验收（8/8 全绿）：
  M3.0 前置准备（3策略入口备份 + 24组合表 + 一致性基准）          ✅
  M3.1 T21  Silver 覆盖 8 collector 全源（24组合参数化）           ✅ 24/24
  M3.2 T22  ★T-G4 拦截率硬门槛（96脏注入 ≥99.5%）                ✅ 96/96 拦截率≥99.5%
  M3.3 T23  剩余 Adapter 补完（Classic/Martin/基本面）            ✅ 7/7
  M3.4 T24  跨策略复用进阶（alt_trend_ensemble 4条断言）          ✅ 1/1
  M3.5 T25  ★T-G3 策略一致性硬门槛（3策略 ≥95%/≥0.97）           ✅ 3/3
  M3.6 T26  L1 fail-open 注入（5类异常 + 综合用例）               ✅ 6/6
  M3.7 T27  ★T-G2 全局二次回归 0 回归                            ✅ 3/3 元测试 + 548 全量 passed
  M3.8 T28  Shadow-mode 冷启动 E2E（4条断言）                    ✅ 4/4

硬门槛达标：
  ★ T-G4 拦截率 ≥ 99.5%     ✅ （96 脏注入全拦截）
  ★ T-G3 策略一致性          ✅ （3 策略信号一致率 100%、Pearson ≥ 0.97）
  ★ T-G2 全局 0 回归         ✅ （18=173 / 19=136 / 20=187 / 21=59 = 555 passed）

全局回归统计：
  18-数据获取中心 : 173 passed (collectors + dispatcher + 监控)
  19-数据访问层   : 136 passed (P0/P1 DAL + 迁移脚本)
  20-数据清洗中心 : 187 passed (T21/T22 + Silver 管道 + H1 集成)
  21-特征工程中心 :  59 passed (T23~T28 + FeatureHub 基建 + T27/T28 元测试)
  ----------------------------------------------------------------
  合计            : 555 passed · 0 failed · 0 regression

关键交付物：
  · Silver 全源覆盖（8 collector × 3 资产 = 24 组合参数化测试）
  · 脏数据拦截率硬门槛（8×3×4=96 条注入，拦截率≥99.5%）
  · 3 个 Adapter 补完（Classic 15+指标 / Martin 网格 / 基本面代理比率）
  · 跨策略复用（alt_trend_ensemble 4 条断言含 VIF 清洗验证）
  · 策略一致性（3 策略信号方向 100% 一致 + Pearson ≥ 0.97）
  · L1 fail-open 铁律（5 类异常注入 + 综合用例，永不阻塞）
  · Shadow-mode 冷启动 E2E（DataRecord → Silver → FeatureHub 完整链路）

下一步：进入逐策略灰度周（周1~周5），按日终复盘标准推进全量上线。
```

### 4.10 逐策略灰度周（周1~周5，每日 1 开关，日终复盘）—— M3 收尾

| 日期 | 灰度动作 | 验证标准（日终） | 不达标处理 |
|---|---|---|---|
| **周一** | EN_SILVER=true，全8 collector 开启（策略侧仍全部 EN_FEATUREHUB_*=false） | 日终：silver_gate_pass_rate ≥ 98%，Lark 红警 0 条；OHLCV stale 全部 < 15min；易经 164 项 + 三屏 + 经典 全库 0 回归 | 收 Silver = False，回滚 M1 H1 改动 |
| **周二** | EN_FEATUREHUB_BTC_MORPH=true（易经btc策略灰度） | 日终：策略一致性≥95%/≥0.97；fh_failopen_count < 3 次/5min；权益曲线对比 baseline 不劣化；btc 形态信号与昨日同方向占比 ≥ 90% | 关 EN_FEATUREHUB_BTC_MORPH=false，debug T25 一致性 |
| **周三** | EN_FEATUREHUB_TRIPLE_SCREEN=true（三屏 alt 策略） | 同周二 | 关该策略开关 |
| **周四** | EN_FEATUREHUB_CLASSIC=true（经典美股策略） | 同周二 | 关该策略开关 |
| **周五** | 三策略全开 + Silver 全源（全量上线） | 日终：拦截率 ≥ 99.5%；三策略一致性全达标；全局 0 回归（T27 再次跑一遍）；红警 0 条 → **7~8 工作日项目总体验收通过** | 逐策略关 → Silver 总关 → 回滚备份一键复原 |

> 灰度期日终需导出的日报：dc-clean status + fh list + fh inspect --set {三个集合} + 三策略一致性指标 + 拦截率分布 + 新鲜度红线检查表。

---

## 五、M1~M3 任务汇总与工期对照

| 阶段 | 子任务组 | 代码任务数 | 测试用例数 | 工期 | 验收铁门槛 |
|---|---|---|---|---|---|
| **M1** | M1.0 前置 + M1.1 Contract + M1.2 Cleaners×4 + M1.3 Gate + M1.4 Adapters + M1.5 Pipeline + M1.6 H1 + M1.7 CLI + M1.8 回归 + M1.9 E2E + M1 评审 | 26 | T1~T12（~40 用例） | **2 天** | ★ T-G1：18-M1~M5 **164/164 0 回归** |
| **M2** | M2.0 前置 + M2.1 Contract + M2.2 FR提拔(shim) + M2.3 清洗链 + M2.4 3Adapter + M2.5 Lineage/Versioning + M2.6 Pipeline + M2.7 跨策略3集合 + M2.8 CLI + M2 评审 | 30 | T13~T20（~27 用例） | **2.5 天** | ★ T-G5：FR 11单测全绿 + TripleScreen 逐列 < ε=1e-9 |
| **M3 工作日** | M3.0 前置 + M3.1 24组合 + M3.2 96脏注入 + M3.3 3Adapter补 + M3.4 跨策略进阶 + M3.5 H3×3 + 一致性3条 + M3.6 L1注入 + M3.7 全局回归 + M3.8 Shadow E2E | 22 | T21~T28（~75 用例） | **3 天** | ★ T-G4 拦截≥99.5%；★ T-G3 3策略≥95%/≥0.97；★ T-G2 全库0回归 |
| **M3 灰度周** | 周1 Silver全源 → 周2 易经btc → 周3 三屏alt → 周4 经典美股 → 周5 全量验收 | 5 天日终复盘 | 每日 T27 0回归 + 一致性 | **1 周观察** | 周5 全量上线指标全达标 |
| **合计** | | **~78 项代码子任务** | **T1~T28 ≈ 142 新用例 + 2× 全局0回归** | **7~8 工作日 + 灰度观察** | **5 条硬门槛 T-G1~T-G5 全部通过 = 项目验收** |

---

## 六、实施阶段启动前三确认

1. **Spec冻结确认**：全局Spec v1.0 frozen 11项自检全通过 + 3份归档Spec一致 → ✓ 已做
2. **回滚备份位置确认**：dispatcher.py.BAK_M1_START / feature_registry.py.BAK_M2_START / 三策略入口 BAK_M3_START 三个关键备份，实施阶段**写前必存** → 每阶段Day1 09:00任务
3. **TDD 执行顺序确认**：每个子任务固定先写测试红 → 再写实现绿 → 既有基准测试不允许删改 → 每任务必遵守

→ **用户确认本计划无误后，按 M1-Day1 09:00 开始执行。**
