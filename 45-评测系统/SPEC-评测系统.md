# SPEC — 45-评测系统

> **版本**: v1.0 (2026-11-01)
> **状态**: 世界级基准修订版（v0.3 + 四领域深度调研 + 决策冻结）
> **定位**: dreambuddy 的统一评测收口底座（L0 基础能力）：各分支产出物经 45 评测通过，方可进入 L0 沉淀与上线部署
> **上游关联**: v0.1–v0.3 设计；四领域调研（AI/ML 评测、金融验收与回测、工程门禁与供应链、平台工程与统计治理）；系统自有能力（33-REA E3 / 23-四层闭环 Backtest / walk-forward 与 time-split / pycg / pytest 测试矩阵）
> **配套文档**: [调研报告-世界级评测基准-v1.0.md](docs/调研报告-世界级评测基准-v1.0.md)、[PLAN-评测系统-实施计划.md](PLAN-评测系统-实施计划.md)
> **变更记录**:
> - v0.1 初版：统一收口定位、三层评测模型、服务化接口、L0/部署闭环
> - v0.2 新增 §6 自有能力沉淀映射，P2 优先复用自有能力
> - v0.3 评审修订（v0.3 原文编号）：根门禁豁免（2.4）、阈值初值（2.5）、env_manifest（5.1.1）、耗时预算（5.4）、与 27 边界（7）、P1 灰度（8）
> - v1.0 世界级基准修订：新增领域模型（§3）、判定语义 INCONCLUSIVE（§4）、评测器插件契约（§6）、数据与基准治理（§7）、统计门禁（§8）、LLM 裁判协议（§9）、人工评测协议（§10）、数据模型（§12）、API 完整契约（§13）、平台工程（§14）、安全合规（§15）、SLO/KPI（§17）；重划金融/工程硬性项；待决断 5 项全部收敛为决策记录（§20）

---

## 0. 文档定位与术语

本文档定义 **45-评测系统** 的设计规格。它为交易、模型训练、代码工程、数据管理、知识沉淀、AI 工程等分支提供统一的评测申请、执行、出分、门禁判定与归档能力。

核心价值：**给任一分支产出物一个统一评测入口，返回带证据、可比较、可追溯的结构化评测报告，实现『评得了、拦得住、可追溯、可复用、可复算』。**

**职责边界**：45 是**评测执行与门禁收口层**，不承担被评测对象的业务实现（模型训练归训练分支、策略实现归交易分支、代码开发归工程分支），也不替代 L0 沉淀流程本身。

| 术语 | 定义 |
|---|---|
| EvalSpec | 评测规格：数据集@版本、切分、评测器、判分器、阈值、seed/温度、环境要求组成的版本化不可变对象 |
| Dataset / Benchmark Registry | 数据集与基准注册表：内容哈希、切分清单、污染检测结果、来源与许可 |
| Evaluator | 评测器：实现某类评测逻辑的插件，含硬性项与加权项定义 |
| Scorer | 判分器：`code`（确定性代码）、`model`（模型裁判）、`human`（人工）三态，与门禁裁决解耦 |
| Run | 一次不可变的评测执行记录：绑定 spec_hash、代码版本、环境快照、开始/结束时间 |
| Gate | 门禁裁决：汇总 Run 的评测项，输出 PASS / BLOCK / INCONCLUSIVE |
| Evidence Bundle | 证据包：原始结果、指标、日志、签名与哈希链，可离线验证 |
| Root Gate | 根门禁：45 自身作为门禁能力，其自身变更走 CI+人工评审通道（2.3） |
| INCONCLUSIVE | 不确定判定：样本不足或置信区间跨越阈值，默认不放行，可补测 |

---

## 1. 背景、调研与目标

### 1.1 问题

- 分支众多（交易、模型训练、代码工程、数据管理、知识沉淀、AI 工程），缺乏统一评测入口与准入标准
- 产出物质量参差，L0 沉淀与上线部署缺少前置质量关卡
- 评测能力分散自建、重复建设、口径不一致，报告无法横向比较
- 历史评测多为“点估计 + 人工拍板”，缺少统计置信与证据链

### 1.2 四领域调研结论（设计依据）

| 领域 | 世界级做法 | 对 45 的启示 |
|---|---|---|
| AI/ML 评测 | 6 抽象（Dataset/EvalSpec/Evaluator/Scorer/Run/Registry）；裁判校准；误差棒；回归门禁 | 建 Registry，判置信下界，裁判必须过校准 |
| 金融验收/回测 | 高可用验收用例化 + 故障注入；DSR/PBO/CPCV；SR 26-2 模型台账 | 回测真实性升硬性项；N_trials 必须登记；双引擎复算 |
| 工程门禁/供应链 | New Code 门禁；SLSA/SBOM/attestation 三方一致；防绕过/flaky | 硬性项收敛三类；覆盖率拆新增/全仓；证据签名绑定 |
| 平台工程/统计 | 异步编排、WORM 证据链、沙箱隔离、分层抽样、Wilson/SPRT | 单机可行方案；阈值版本化+双人审批+shadow |

> 完整来源与论证见 [调研报告](docs/调研报告-世界级评测基准-v1.0.md)。

### 1.3 设计目标

1. **统一收口**：所有分支统一通过 45 提交评测，不允许旁路上线
2. **分层评测**：金融/AI/技术工程三类差异化评测器，共用统一框架
3. **服务化调用**：API + CLI 双入口，L0 沉淀与部署前强制调用
4. **闭环门禁**：PASS 触发沉淀/部署；BLOCK 拦截并返回改进项；INCONCLUSIVE 默认不放行
5. **统计可信**：门禁判置信下界，报告同时给出 n 与 CI
6. **全链路可审计**：申请→执行→出分→判定→归档全链路留痕，证据可离线验证
7. **可复现可比较**：EvalSpec/Run 版本化，报告携带 `run_spec_hash`，同 spec 可复算
8. **优先复用自有能力**：评测器优先抽象系统内已验证的评测/回测能力

### 1.4 非目标（明确不做）

- 不实现被评测对象（训练、策略、代码、数据加工）
- 不替代 L0 沉淀执行、不替代 27 合规审批、不替代 CI 的快速反馈
- 不追求“逐位可重演”（LLM 裁判存在边界翻转），只承诺“可追溯 + 可复算”
- 不建设独立调度集群（单机 4C16G 约束内做最优解）

---

## 2. 设计原则

### 2.1 Evidence-First（证据优先）

每份报告必须包含：

```
evidence:      证据包 URI + sha256 + 签名/哈希链
score:         0.0–1.0（加权项合成分）
n / ci:        样本量与置信区间（加权项必填）
verdict:       PASS | BLOCK | INCONCLUSIVE（附 block_reasons）
run_spec_hash: EvalSpec 规范化哈希
evaluated_at:  评测时间戳（UTC）
```

### 2.2 六抽象与单一事实源

- `Dataset@version`、`EvalSpec@version`、`Evaluator@version`、`Scorer@version`、`Run`、`Registry` 是唯一事实源
- 任何报告必须可由 `run_id` 反查到 spec、数据集、评测器、判分器与阈值版本
- 修改 spec/数据集/评测器/阈值 → 必须升版本号；旧版本记录永久可查

### 2.3 根门禁豁免（Root Gate）

45 同时是门禁与被门禁对象，若自评会形成循环依赖。决断：

1. 45 自身变更走 **测试矩阵（pytest）+ 人工评审** 双凭证，不调用 45 评测器
2. 45 测试矩阵纳入全仓 CI，CI 不通过即拦截
3. 评测器逻辑变更（影响他人判定）额外要求一次人工评审并在 CHANGELOG 登记
4. 其他 L0 能力不得引用本条款规避评测

### 2.4 门禁判置信下界（Fail-Closed）

- 加权项判定使用 **CI 下界**，而非点估计
- 样本不足 → INCONCLUSIVE（默认不放行），禁止用“看起来达标”放行
- 无法计算置信区间（n 过小、无基线）时，按硬性失败处理并给出补测建议

### 2.5 可复现但不承诺可重演

- 记录：模型快照、prompt 哈希、temperature、seed、依赖版本、数据快照哈希
- 承诺：同 spec + 同环境可复算，结果差异可解释
- 不承诺：LLM 裁判逐样本完全一致；差异必须落在声明的容差内（§8.4）

### 2.6 默认拒绝与最小权限

- 未登记评测器、未登记阈值、未登记数据集 → 拒绝受理
- 评测执行最小权限：只读 object_ref、无外网（allowlist 例外）、密钥仅运行时注入
- 任何“先放行后补评”必须显式开启、限定类别、登记审计并支持回滚

---

## 3. 领域模型（v1.0 新增）

### 3.1 EvalSpec（评测规格）

```yaml
eval_spec:
  spec_id: EVS-20261101-0001
  version: 1.0.0                 # 语义化；任何字段变更递增
  category: finance|ai|engineering
  object_type: strategy|model|service|code_artifact|dataset|knowledge
  dataset_ref: DS-xxx@1.2.0       # 可为空（非数据集类评测）
  split_ref: SPL-xxx@1.0.0        # 切分清单（防泄漏）
  evaluator_ref: EV-finance.backtest@1.2.0
  scorers:
    - {id: SC-code@1.0.0, role: primary}
    - {id: SC-judge@2.1.0, role: secondary}   # 需校准凭证
  thresholds_ref: TH-2026Q4@1
  determinism: {seed: 42, temperature: 0.0, repeats: 1}
  env_ref: ENV-manifest-schema@1
  created_by: <submitter>
  approved_by: <role>
```

**规则**：
- `spec_hash = sha256(canonical_json(spec))`，写入每次 Run 与报告
- 同一 object_ref 可有多个 spec（如 `purpose=l0_settle` 与 `purpose=deploy` 阈值不同）
- spec 变更必须新版本，禁止原地修改；旧版本保留用于历史比较

### 3.2 Run（执行记录）

不可变实体，字段见 §12 `eval_runs`。一次 Run 绑定：`spec_hash`、`evaluator_version`、`scorer_versions`、`code_commit`、`env_snapshot`、`started_at/ended_at`、`budget_ms`、`degraded`、`status`。

### 3.3 Registry（注册表）

| 注册表 | 必填字段 | 作用 |
|---|---|---|
| Dataset Registry | dataset_id、version、content_hash、split_manifest、source、license、contamination_report | 保证评测可复算、防污染 |
| Evaluator Registry | evaluator_id、version、category、entrypoint、hard/weighted items、budget、sandbox、evidence_schema | 插件发现与版本锁定 |
| Scorer Registry | scorer_id、version、type、model_snapshot/prompt_hash、calibration_report | 判分器可信度凭证 |
| Threshold Registry | version、category、item、value、metric、min_n、effective_from、approved_by、reason | 阈值治理与审计 |

### 3.4 Gate（门禁裁决）

Gate 只读 Run + Threshold Registry，输出判定与凭证。Gate 不执行评测、不修改证据。

---

## 4. 判定语义（v1.0 新增）

| 判定 | 条件 | 处置 |
|---|---|---|
| **PASS** | 全部硬性项通过 + 全部加权项 `CI_lower ≥ threshold` + 无 INCONCLUSIVE | 签发 eval_id 凭证，触发沉淀/部署 |
| **BLOCK** | 任一硬性项失败；或任一加权项 `CI_upper < threshold`（确信不达标）；或存在未登记豁免 | 拦截 + 返回改进项清单 |
| **INCONCLUSIVE** | 硬性项通过，但加权项 CI 跨越阈值 / n < min_n / 关键证据缺失 / 超时且为加权项 | 默认不放行；允许补测/扩样；不得签发凭证 |

**判定优先级**：BLOCK > INCONCLUSIVE > PASS（任一 BLOCK 即 BLOCK；无 BLOCK 但有 INCONCLUSIVE 即 INCONCLUSIVE）。

**加权合成**：`score = Σ w_i × normalized_i`，权重来自 Threshold Registry；硬性项不参与加权，零失败。

**凭证**：`eval_id` 绑定 `run_id + spec_hash + verdict + thresholds_version + expires_at`（默认 7 天有效，部署前需新鲜度校验）。

---

## 5. 三大类评测器标准（v1.0 重划）

### 5.1 金融类（交易策略/交易服务）

**硬性项（零失败，不设加权豁免）**

| # | 项 | 验收要求 |
|---|---|---|
| F-H1 | 功能正确性用例 | 三段式用例（预置条件/测试过程/预期结果）覆盖下单、成交、止损、风控边界、幂等重放；全通过 |
| F-H2 | 高可用验收 | 多副本 + liveness/readiness 探活；5 类故障注入（pod-kill、网络延迟、交易所 API 超时、DB 主备切换、磁盘写满）；订单 RPO=0、RTO≤30s，行情 RTO≤60s |
| F-H3 | 合规审计 | 敏感操作审计留痕、权限边界、审批链路可导出 |
| F-H4 | 数据与执行真实性 | PIT 数据、label 时间戳、purge+embargo 生效；数据快照 hash、镜像/依赖版本、seed 可复算 |
| F-H5 | 成本口径完整 | 佣金+滑点+资金费率+借券费显式声明；引擎与成本参数写入报告 |
| F-H6 | 回测过拟合红线 | PBO（CSCV S=16）>0.50 直接 BLOCK；`N_trials` 未登记视同失败 |
| F-H7 | 统计显著性（主判） | DSR ≥0.95（判 CI 下界）且样本外交易 ≥100、walk-forward ≥5 折；不满足 → INCONCLUSIVE |

**加权项（阈值见 §8，判 CI 下界；权重见下表）**

| # | 项 | 说明 | 权重 |
|---|---|---|---|
| F-W1 | 样本外净 Sharpe | 仅作报告参考（加密日频 0.8 / 股票 0.5 为观察线，不单独拦截） | 0.15 |
| F-W2 | OOS/IS 衰减 | ≤50% | 0.30 |
| F-W3 | 成本×2 稳健性 | 净 Sharpe>0 且 MaxDD ≤1.5× | 0.35 |
| F-W4 | 容量约束 | 单笔 ≤10% ADV | 0.20 |
| F-W5 | 回测综合分 | 上述归一化加权合成 ≥0.70 | — |

> **口径决断（D-04）**：DSR 为主判（硬线），Sharpe 为辅（报告参考 + 低权重），避免“Sharpe 达标但多重检验未校正”放行；权重合计 1.00，F-W5 为合成分。

**切分与复算**：
- 时间序列必须 purged k-fold + embargo（≥ label horizon）
- walk-forward ≥5 折；CPCV（N=6/k=2）用于稳健性复核
- 至少双引擎复算（如 23 内核 + 对照引擎），偏差 >10% 必须在报告说明
- 样本外交易数 <100 或折数 <5 → INCONCLUSIVE

**证据字段（强制）**：eval_id、object_ref、commit/model hash、env_manifest、数据快照 hash + PIT 校验、N_trials 与搜索空间、切分与 embargo、成本参数与引擎版本、DSR/PSR/PBO/衰减四值、故障注入记录（起止/影响请求/错误率曲线/恢复耗时/订单零丢失对账）、合规导出、复现命令、verdict。

### 5.2 AI 类（模型训练、AI 工程）

**硬性项**

| # | 项 | 验收要求 |
|---|---|---|
| A-H1 | 轻量体验 | 关键能力抽检全通过（定性 rubric 且双人独立确认） |
| A-H2 | 防泄漏切分 | 时间序列/样本切分清单存在且生效；训练集与评测集无重叠 |
| A-H3 | 数据污染 | 13-gram 重叠 <0.1%（基准集）；超线即失败 |
| A-H4 | 裁判可信度 | 若使用 model scorer：校准集 ≥200 人工标注、Cohen's κ≥0.60、Krippendorff's α≥0.67；否则只能进加权项 |

**加权项**

| # | 项 | 说明 |
|---|---|---|
| A-W1 | 自动评测综合分 | 内置/自定义评测集；指标 pass@1/ROUGE/F1 或裁判打分 |
| A-W2 | 性能压测 | 固定并发吞吐/延迟达标率 |
| A-W3 | 人工抽评 | 抽样人工均分（§10） |
| A-W4 | 能力/回归/校准三分集 | 三集分别有结果，缺一不可 |

**评测集拆分（强制）**：能力集（验证会不会）、回归集（验证有没有退化）、校准集（验证裁判与人工一致性）。每集样本量建议 ≥200；<30 时只能 INCONCLUSIVE。

**裁判要求**：见 §9。

### 5.3 技术工程类（代码工程、数据管理、知识沉淀）

**硬性项（收敛为三类 + 两条工程底线）**

| # | 项 | 验收要求 |
|---|---|---|
| E-H1 | 秘密泄露 | secret scanning 命中即失败，无豁免 |
| E-H2 | 可利用漏洞 | 制品/依赖 CRITICAL=0；HIGH 且有修复版本=0 |
| E-H3 | 可追溯性 | `commit_sha ↔ build_digest ↔ SBOM subject digest` 三方一致，且 attestation 可验证 |
| E-H4 | 新增行覆盖率 | ≥0.80（Sonar way；按 base_sha 自算，不信任提交方数字） |
| E-H5 | 旁路痕迹 | CI 出现 `\|\| true`、`--exit-code 0`、skip 标记等绕过痕迹即失败 |

**加权项**

| # | 项 | 说明 |
|---|---|---|
| E-W1 | 用例通过率 | ≥0.95（flaky 隔离后要求 1.00） |
| E-W2 | 全仓行覆盖率 | ≥0.60，灰度后上调至 0.70 |
| E-W3 | 新代码重复率 | ≤3% |
| E-W4 | 新代码安全热点复核 | 100% |
| E-W5 | 基准集对照（pycg） | ≥0.70 |
| E-W6 | 供应链健康度 | OpenSSF Scorecard ≥7.0/10 |

**与 CI 的边界**：

| 留在 CI | 必须由 45 复核 |
|---|---|
| 每 commit lint/单测、SARIF 上传、push protection、SBOM/attestation 生成 | 用 base_sha 自算 diff coverage；校验 digest/SBOM/证明签名；结论指向最新 sha（7 天内有效）；门禁裁决与凭证签发；抽样 10% 重跑一致性 |

**防绕过/防 flaky**：
- 快照式隔离：45 从 object_ref 拉取，干净沙箱执行，禁用提交方预置覆盖率文件
- 覆盖率/测试报告必须含 `base_sha` + job 签名，缺字段即 BLOCK
- flaky：允许 1 次自动重跑并记录 `rerun_pass`；用例级 flaky 率 >1% → quarantine（不计分子、14 天修复）；未登记 quarantine 而失败即 BLOCK

### 5.4 通用准入验证器（L1）

抽象自 33-REA E3 三重验证门禁：

1. **网络层**：object_ref 可达、端点健康、依赖资源可解析
2. **内容层**：结构完整性、schema 校验、元数据规范、哈希一致
3. **交叉层**：声明与实际一致（如 commit 与制品、模型版本与权重哈希、数据集版本与内容哈希）

L1 全类型执行，零致命项；≤60s。

### 5.5 自有能力沉淀映射

| 自有能力 | 来源 | 沉淀为 | 归入位置 |
|---|---|---|---|
| E3 三重验证门禁 | 33-REA | 通用准入验证器 | `evaluators/common` + L1 |
| Backtest 三层分层 | 23-四层闭环 | 金融类回测评测器内核 | `evaluators/finance` |
| walk-forward / time-split | Screen1 训练链路 | 防泄漏切分组件 | `evaluators/common` + finance/ai |
| pycg 基准标尺 | 33-REA 附录A | 基准集对照评测 | `evaluators/engineering` |
| pytest 测试矩阵 | fis-p0 / SPEC-41 | 45 自身质量门禁（根门禁凭证） | `tests/` |

**原则**：抽象模式而非迁移代码；原链路保持运行；登记来源模块与版本。

---

## 6. 评测器插件契约（v1.0 新增）

### 6.1 Manifest

```yaml
evaluator:
  id: EV-finance.backtest
  version: 1.2.0
  category: finance
  object_types: [strategy]
  entrypoint: evaluators.finance.backtest:BacktestEvaluator
  inputs: [object_ref, env_manifest, dataset_ref, split_ref]
  outputs: [EvalItem]
  hard_items: [F-H1, F-H2, F-H3, F-H4, F-H5, F-H6, F-H7]
  weighted_items: [F-W1, F-W2, F-W3, F-W4, F-W5]
  budget_ms: 1800000
  sandbox: required|forbidden
  side_effects: none|isolated
  evidence_schema: contracts/evidence/finance_backtest.v1.json
  compatible_with: ["EV-finance.backtest@>=1.0.0 <2.0.0"]
```

### 6.2 接口

```python
class Evaluator(Protocol):
    def validate(self, req: EvalRequest) -> list[ValidationIssue]: ...
    def run(self, ctx: EvalContext) -> EvalRunResult: ...   # 必须产出 EvalItem 列表
    def evidence_schema(self) -> dict: ...
```

**约束**：
- 评测器无副作用、可重复执行；外部状态只读
- 输出必须逐项映射到 Registry 中声明的 `hard_items/weighted_items`
- 未声明项不得计分；新增项必须升版本并在 CHANGELOG 登记
- 评测器自身走 `tests/` 测试矩阵 + 人工评审（§2.3）

---

## 7. 数据与基准治理（v1.0 新增）

### 7.1 Dataset Registry 字段

`dataset_id`、`version`、`content_hash`、`split_manifest`（train/val/test 时间边界与样本 id 列表哈希）、`source`、`license`、`contamination_report`、`created_at`、`owner`。

### 7.2 切分与泄漏

- 金融/时序：purged k-fold + embargo，embargo ≥ label horizon
- AI 通用：train/val/test 三分，按样本 id 而非文件切分，避免同源泄漏
- 切分清单必须随 EvalSpec 版本化；切分变更即 spec 变更

### 7.3 污染检测

- 评测集与训练集做 13-gram 重叠检查，红线 <0.1%
- 基准集（如 pycg）单独登记来源与版本，禁止用训练数据派生

### 7.4 基准与对照

- 外部基准只作对照，不直接依赖其运行时
- 基准集对照分数必须记录基准版本与运行环境

---

## 8. 评分、阈值与统计治理（v1.0 新增）

### 8.1 阈值表（含 min_n 与统计方法）

| 类别 | 评测项 | 阈值 | 统计方法 | min_n | 类型 |
|---|---|---|---|---|---|
| 金融 | 回测综合分 | ≥0.70 | n<200 bootstrap；否则 Wilson/聚类稳健 | 100 笔 | 加权 |
| 金融 | DSR（主判） | ≥0.95 | 解析式 + bootstrap | 100 笔 | 硬性 |
| 金融 | OOS/IS 衰减 | ≤50% | 点估计 + CI | 100 笔 | 加权 |
| 金融 | 成本×2 稳健 | 净 Sharpe>0；MaxDD≤1.5× | 点估计 | 100 笔 | 加权 |
| 金融 | 容量 | 单笔 ≤10% ADV | 点估计 | 20 笔 | 加权 |
| 金融 | 净 Sharpe | 报告参考（0.8/0.5 观察线） | Wilson | 100 笔 | 参考 |
| AI | 自动评测综合分 | ≥0.75 | Wilson/bootstrap | 200 | 加权 |
| AI | 性能压测达标率 | ≥0.80 | Wilson | 30 次 | 加权 |
| AI | 人工抽评均分 | ≥0.75 | Wilson + α | 100/层 | 加权 |
| AI | 裁判校准 κ/α | κ≥0.60；α≥0.67 | Cohen's κ / Krippendorff α | 200 | 硬性 |
| 工程 | 用例通过率 | ≥0.95 | Wilson | 全量 | 加权 |
| 工程 | 全仓覆盖率 | ≥0.60（灰度后 0.70） | 点估计 | — | 加权 |
| 工程 | 新增行覆盖率 | ≥0.80 | 点估计 | — | 硬性 |
| 工程 | 基准集对照 | ≥0.70 | Wilson | 基准规模 | 加权 |
| 工程 | Scorecard | ≥7.0/10 | 点估计 | — | 加权 |

> 数值来源：部分为规范原文（Sonar way 0.80/3%、DSR/PBO 论文、κ/α 规则），其余为工程初值，P1.5 灰度期用 Wilson CI 校准（见调研报告 §5）。

### 8.2 门禁统计规则

1. 加权项判定 `CI_lower ≥ threshold`；`CI_upper < threshold` → BLOCK
2. CI 跨越阈值 → INCONCLUSIVE
3. 报告必须含 `n`、`ci_lower`、`ci_upper`、`method`
4. 小样本（n<200）禁止用正态近似，改用 Wilson 或 bootstrap（≥1000 次重采样）
5. 聚类样本（同一策略多市场）按 cluster bootstrap

### 8.3 回归判定

- 每次评测绑定 `baseline_run_id`（上一通过版本）
- 回归 = 新分与基线差的 95%CI 下界 < 0（确有退化），而非点估计下降
- 回归项单独列出 `baseline_diff`，不改变主 verdict，但写入报告与告警

### 8.4 容差与 flaky

- 同 spec 复算容差：确定性指标 ±0；模型裁判 ±5%（需在 spec 声明）
- flaky 用例：允许 1 次重跑，记 `rerun_pass`；quarantine 规则见 §5.3

### 8.5 阈值治理

- `config/thresholds.yaml` 版本化；只允许上调（放宽需双人审批 + CHANGELOG + 7 天 shadow）
- 每次变更写 Threshold Registry：`approved_by`、`reason`、`effective_from`
- SPRT（α=0.05/β=0.1）监测通过率漂移；季度用 golden set 复核
- 灰度期误拦截率看 Wilson 上界，目标 ≤1%

---

## 9. LLM-as-Judge 可信度协议（v1.0 新增）

**适用范围**：AI 类自动评测中的裁判模型、报告生成中的语义判定。

### 9.1 校准准入

- 校准集 ≥200 条人工标注，覆盖好/中/差三档
- Cohen's κ≥0.60 且 Krippendorff's α≥0.67（ordinal）
- 校准报告写入 Scorer Registry，含 `metascore`、混淆矩阵、分档召回

### 9.2 偏差控制

- A/B 顺序对调各判一次；不一致记 `tie`（不计入分子/分母，单独统计）
- rubric 明令禁止长度加分；长度与分数做相关性检查（|r|<0.2）
- 双裁判取均值；两裁判差 >1 档（5 分制）记 `disagreement` 并抽样人工复核

### 9.3 锁定与追溯

- 记录 `judge_model_id + snapshot_date + prompt_hash + temperature(=0) + max_tokens`
- 同 spec 复算差异 >5% 时，报告标记 `judge_drift` 并触发人工抽检
- 未过校准的裁判只能进加权项，且权重 ≤0.3；不得进硬性项

---

## 10. 人工评测协议（v1.0 新增，闭环原待决断项）

### 10.1 抽样

- 分层抽样：按类别/难度/来源分层；每层 n≈100（p=0.5、±10%、95%）
- 双标重叠 10–20%；标记者盲测（不告知版本与预期）
- 样本不足时按 Wilson 区间报告，不得用点估计下结论

### 10.2 一致性

- Krippendorff's α 下限 0.67，目标 0.80（ordinal）；Cohen's κ≥0.60
- α 不足：先扩样与校准会，仍不足则该评测项记 INCONCLUSIVE
- 分歧仲裁：第三方仲裁 + 记录仲裁理由；仲裁样本计入最终分

### 10.3 成本与记录

- 记录每层工时、单样本成本、标注者 ID（脱敏）
- rubric 版本化，与 EvalSpec 绑定；rubric 变更需重算历史基线

---

## 11. 系统架构

```
45-评测系统/
├── SPEC-评测系统.md
├── PLAN-评测系统-实施计划.md
├── docs/                          # 调研报告与运维文档
├── core/
│   ├── gateway.py                 # 受理、幂等、env_manifest 校验
│   ├── registry.py                # Dataset/Evaluator/Scorer/Threshold 注册表
│   ├── dispatcher.py              # 按类别路由评测器
│   ├── runner.py                  # 执行编排（任务/重试/取消/超时）
│   ├── gate.py                    # 门禁裁决（PASS/BLOCK/INCONCLUSIVE）
│   └── reporter.py                # Evidence-First 报告与哈希链
├── evaluators/
│   ├── common/                    # 通用准入验证器（E3 模式）
│   ├── finance/                   # 用例/高可用/合规/回测内核
│   ├── ai/                        # 体验/自动/压测/人工/防泄漏
│   └── engineering/               # 扫描/测试/基准集/追溯
├── scorers/
│   ├── code/                      # 确定性判分
│   ├── model/                     # 模型裁判（校准凭证）
│   └── human/                     # 人工评测工作流
├── api/
│   ├── routes.py                  # REST
│   └── cli.py                     # evalctl（CI 门禁入口）
├── contracts/
│   ├── schemas/                   # EvalSpec/EvalRequest/EvalReport JSON Schema
│   └── evidence/                  # 各类证据 schema
├── config/
│   ├── thresholds.yaml
│   └── categories.yaml
├── storage/
│   ├── repo.py                    # PG 访问
│   ├── evidence.py                # 哈希链/Merkle/签名
│   └── object_store.py            # WORM 对象存储
└── tests/                         # 45 自身测试矩阵（根门禁凭证）
```

**部署拓扑（单机 4C16G）**：FastAPI（API）+ Celery worker（评测执行）+ Redis（broker）+ PostgreSQL（状态/记录）+ MinIO（WORM 证据）+ gVisor 沙箱。

---

## 12. 数据模型（v1.0 新增，PostgreSQL）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `eval_requests` | eval_id PK、idempotency_key UNIQUE、category、purpose、priority、object_ref、env_manifest jsonb、spec_id、status、created_at | 受理与幂等 |
| `eval_runs` | run_id PK、eval_id FK、evaluator_id/version、attempt、spec_hash、code_commit、budget_ms、degraded、started_at、ended_at、status | 不可变执行记录 |
| `eval_items` | item_id PK、run_id FK、name、kind(hard/weighted)、score、n、ci_lower、ci_upper、status、evidence_id | 评测项级结果 |
| `evidence` | evidence_id PK、run_id FK、sha256、uri、prev_hash、hash、signed_by、created_at | 证据链 |
| `eval_reports` | eval_id PK、run_id、verdict、score、thresholds_version、baseline_run_id、block_reasons jsonb、report_uri、decided_at | 判定与报告 |
| `thresholds` | version、category、item、value、metric、min_n、effective_from、approved_by、reason | 阈值版本 |
| `callbacks` | callback_id PK、eval_id FK、target、payload_hash、attempts、status、last_error | 回调重试 |
| `registry_items` | reg_type、item_id、version、manifest jsonb、content_hash、created_at | Dataset/Evaluator/Scorer 注册 |

**规则**：报告二进制落 WORM 桶，库内只存 URI+sha256；所有状态变更写审计日志；证据链日终生成 Merkle 根并归档。

---

## 13. 服务化接口（v1.0 完整契约）

### 13.1 提交

```
POST /api/v1/eval/submit
Headers: Idempotency-Key: <uuid>
{
  "object_ref": "...",
  "category": "finance|ai|engineering",
  "object_type": "strategy|model|service|code_artifact|dataset|knowledge",
  "submitter": "...",
  "purpose": "l0_settle|deploy",
  "priority": "normal|high",
  "spec_id": "EVS-...",
  "env_manifest": {
    "runtime": "...",
    "endpoints": ["..."],
    "resources": ["..."],
    "secret_refs": ["..."]
  }
}
→ 202 { "eval_id": "...", "status": "accepted", "spec_hash": "..." }
```

受理即拒条件：spec 未登记、评测器未登记、env_manifest 缺 endpoints/资源不可达、类别与 object_type 不匹配。

### 13.2 查询 / 列表 / 取消

```
GET /api/v1/eval/{eval_id}
→ { eval_id, status, verdict, score, n, ci, evidence_uri, block_reasons[], sla{budget_ms,elapsed_ms,degraded}, run_spec_hash }

GET /api/v1/eval?submitter=&category=&verdict=&from=&to=&limit=
DELETE /api/v1/eval/{eval_id}   # 仅 queued/running 可取消；已判定不可撤销
```

### 13.3 门禁回调

- PASS 回调 L0 沉淀流程与部署流水线，携带 `eval_id + verdict + expires_at + signature`
- 回调签名：HMAC-SHA256（密钥来自 `secret_ref`）；接收方校验签名与新鲜度
- 失败回调按指数退避重试（1s/5s/30s/5min，最多 5 次），记录 `callbacks`

### 13.4 CI/CLI 门禁

```
evalctl gate --eval-id <id> --purpose deploy
exit 0 = PASS | 2 = BLOCK | 3 = INCONCLUSIVE | 4 = ERROR
```

支持 `--wait` 与超时；CI 用退出码阻断，不允许解析日志判断。

---

## 14. 运行与平台工程（v1.0 新增）

### 14.1 编排

- Celery + Redis broker + PG 状态机；`acks_late=True`，`eval_id` 唯一键幂等
- 取消：revoke + DB `cancel_requested` 标志，worker 在检查点退出
- 优先级：`high` / `normal` 双队列；重试指数退避，硬性项失败不重试
- 任务粒度：一个评测项一个子任务，便于并行与隔离

### 14.2 SLA 与降级

| 阶段 | 预算 |
|---|---|
| L1 静态检查 | ≤60s |
| 金融类 L2 | ≤30min |
| AI 类 L2 | ≤60min |
| 工程类 L2 | ≤15min |

降级规则：
1. 单项超预算：加权项记 TIMEOUT 扣分；硬性项超时 → BLOCK
2. 整体超预算且硬性项已过：可申请“先放行 + 异步补评”（默认关闭，金融类禁用）
3. 补评不通过 → 事后回滚 + 审计登记

### 14.3 沙箱

- Docker + gVisor(runsc)；配额 cpu=1、mem=2g、pids=256、超时 kill
- rootfs 只读 + tmpfs；非 root + seccomp；`network=none` 仅 allowlist
- 密钥通过 `secret_ref` 运行时注入，日志与证据脱敏
- 工程类评测在沙箱内拉取 object_ref，禁止使用提交方预置产物

### 14.4 证据链

- 每条证据存 `sha256 + prev_hash`，形成链；日终生成 Merkle 根（RFC 6962 思路）
- 证据包可离线验证：哈希链 + 签名 + 报告 JSON
- 对象存储 MinIO Object Lock（compliance 模式），保留期与审计要求一致
- 落地：`storage/object_store.py`（`LocalWormStore` 文件系统对象锁 / `MinioWormStore` 服务端对象锁）；`config/object_store.yaml` 配置 `mode` 与 `retention_days`（默认证据 365 / 报告 1095 / 审计 365 天），环境变量 `EVAL_WORM_MODE` / `EVAL_WORM_ROOT` / `EVAL_WORM_ENDPOINT` / `EVAL_WORM_BUCKET` 覆盖；`evalctl evidence --archive` 将证据包归档为 `evidence/<eval_id>.json`（保留期内禁止覆盖/删除，MinIO 模式缺依赖 fail-closed）
- 落地：`storage/evidence.py`（链/根/包）+ `evalctl evidence --eval-id --out` 构建、`evalctl evidence --verify <bundle> [--require-signature]` 离线验证（退出码 0/4）；签名密钥仅由 `EVAL_EVIDENCE_KEY` 注入，签名主体由 `EVAL_EVIDENCE_SIGNER` 标注

### 14.5 可观测性

- 指标：受理量、队列积压、各阶段耗时、超时率、PASS/BLOCK/INCONCLUSIVE 比例、误拦截率、回调失败率
- 日志：结构化 JSON，含 eval_id/run_id/item_id，禁止打印密钥与样本内容
- OpenLineage：Run START/COMPLETE facet 登记数据血缘；报告 URI 登记 41 索引
- 告警：队列积压 >10 或 SLA 达标率 <90% 触发

### 14.6 备份与容灾

- PG 每日快照 + WAL 归档；证据桶版本化/对象锁
- 恢复演练季度一次，RPO≤24h（评测记录）、RTO≤4h

---

## 15. 安全与合规

- **RBAC**：submitter（提交）、evaluator-admin（评测器/阈值）、approver（阈值放宽/豁免）、auditor（只读全量）
- **密钥**：仅 `secret_ref` 引用，运行时注入；禁止写入报告、日志、证据
- **数据分级**：公开/内部/敏感；敏感样本在证据中脱敏或只存哈希
- **保留期**：评测记录与报告 ≥3 年；证据 ≥1 年；审计日志 ≥1 年
- **审计**：所有阈值变更、豁免、取消、补评、回滚均留痕
- **依赖安全**：45 自身依赖纳入 SBOM 与漏洞扫描（自我评测走根门禁通道）

---

## 16. 与既有系统的边界与协同

| 系统 | 边界 |
|---|---|
| L0 能力分层 | 45 自身是 L0 能力（根门禁）；同时是其他 L0 能力的准入门禁，形成“能力互锁” |
| 41-文件索引 | 报告与证据 URI 纳入索引，支持检索追溯 |
| 33-REA | E3 模式被抽象复用；33 原链路继续运行，45 不迁移其代码 |
| 23-四层闭环 | 回测执行归 23；45 负责验收口径、证据与判定 |
| 27-策略治理审批 | 27 管合规审批，45 管质量评测；策略上线需双凭证（27 审批 + 45 eval_id），互不豁免 |
| GitHub CI | CI 产出并快速反馈；45 复核、裁决、签发凭证（§5.3 边界表） |
| 部署流水线 | 部署前校验 eval_id 有效性与新鲜度；无凭证拒绝执行 |
| DreamOS/DSH | 通过 API/CLI 调用；45 不嵌入其调度内部 |

---

## 17. 非功能指标（SLO/KPI）

| 指标 | 目标 |
|---|---|
| API 可用性 | ≥99.5% |
| 受理延迟 | p95 ≤2s |
| L1 完成 | p95 ≤60s |
| SLA 达标率 | 灰度期 ≥90%，正式 ≥95% |
| 误拦截率 | Wilson 上界 ≤1% |
| 证据完整率 | 100%（缺字段即 BLOCK） |
| 同 spec 复算一致率 | ≥95%（确定性项 100%） |
| 分支覆盖率 | P3 后 100% 上线分支接入 |
| 队列积压 | 常态 <10 |

---

## 18. 实施路线与灰度

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| P0 契约与骨架 | EvalSpec/Run/Registry schema、PG 八表、thresholds.yaml、API 骨架、`evalctl` | schema 校验通过；契约测试 GREEN；空跑受理 |
| P1 灰度受理 | 受理/归档/查询，**只受理不拦截**；env_manifest 校验 | 全分支可受理；报告可归档；无副作用 |
| P1.5 校准 | 真实提交观察 SLA、误拦截、n 分布；Wilson 校准阈值 | SLA≥90%；零误拦截；阈值表定版 |
| P2 评测器接入 | common（E3）→ finance（回测内核）→ 防泄漏切分 → engineering（基准/追溯） | 各评测器出分；来源登记完整；测试矩阵 GREEN |
| P3 强制门禁 | L0 沉淀/部署强制卡点；27 双凭证；凭证新鲜度校验 | 无有效 eval_id 被拒；全链路审计可查 |
| P4 世界级加固 | 证据链签名/Merkle、gVisor 沙箱、人工评测工作流、SLO 看板 | 离线验证通过；沙箱隔离验证；SLO 达标 |

---

## 19. 风险与对策

| 风险 | 对策 |
|---|---|
| 标准一刀切误伤 | 三类差异化 + New Code 门禁 + 阈值版本化 + 灰度误拦截监控 |
| 评测成为上线瓶颈 | 并行子任务、耗时预算、超时降级、增量评测 |
| 评测器自身无质量保障 | 根门禁：测试矩阵 + 人工评审 + CHANGELOG |
| 阈值被“刷过” | CI 下界判定 + min_n + 基线比较 + SPRT 漂移监测 |
| 裁判不可靠 | 校准准入 + 双裁判 + 顺序对调 + 快照锁定 |
| 回测结论不可信 | PBO 硬线 + N_trials 登记 + 防泄漏切分 + 双引擎复算 |
| 证据可伪造 | 三方一致 + 签名证明 + 抽样重跑 + WORM |
| 沙箱逃逸 | gVisor + 非 root + 只读 rootfs + 网络 allowlist |
| 异步补评被滥用 | 默认关闭、金融类禁用、事后回滚 + 审计 |
| 与 27 职责推诿 | 双凭证显式声明，互不豁免 |
| 历史产出物无记录 | P1→P3 分批补评，先灰度后强制 |

---

## 20. 决策记录（v1.0 冻结）

> 原待决断 5 项已全部收敛为决策；阈值具体数值仍按 P1.5 校准流程滚动复核，不再作为阻塞项。

**D-01 阈值校准机制**
- §8.1 数值为 v1 暂定值；P1.5 灰度期以 Wilson 95%CI + bootstrap 复核，样本门槛：每类 ≥30 次真实评测，加权项 n≥200
- 调紧（提高阈值）可直接生效；调松需双人审批 + 7 天 shadow + CHANGELOG
- 灰度退出条件：误拦截率 Wilson 上界 ≤1%，SLA 达标率 ≥90%

**D-02 双引擎复算协议**
- 主引擎：23-四层闭环 Backtest 内核（canonical）；对照引擎：按资产类别固定一个独立适配器（vectorbt 或 backtrader），版本锁定并写入报告
- 字段映射：returns / equity / trades / fees / slippage / sharpe / max_dd / win_rate，按日频对齐
- 偏差容忍：≤10% 视为一致；10–20% 报告必须给出归因（成本/滑点/复权/成交假设）并人工复核；>20% 判 INCONCLUSIVE，进入冲突裁决（evaluator-admin + 策略 owner）并记录裁决
- 主引擎结果不可复算（数据/seed/代码版本任一缺失）→ 直接 BLOCK（F-H4 失败）

**D-03 人工评测成本与来源**
- 标注者：内部两名（交易、AI 各一名）交叉标注；双标重叠 15%
- 抽样：每层 n=100；单次评测最多 2 层（200 样本），超出需 approver 批准
- 成本按工时记录，不折算金额；外部标注暂不引入，触发条件：单月人工样本 >1000 或 α<0.67
- 排期不足时优先扩样而非降 n；仍不足 → INCONCLUSIVE

**D-04 DSR / Sharpe 口径**
- DSR 为主判：DSR ≥0.95（CI 下界）为硬性项 F-H7；Sharpe 为辅：仅报告参考，不单独拦截，权重 0.15
- 理由：Sharpe 未校正多重检验，单独达标可能来自试验次数膨胀；DSR 依赖 `N_trials`，与 F-H6 一致
- 回测综合分权重：成本×2 稳健 0.35、OOS/IS 衰减 0.30、容量 0.20、Sharpe 0.15

---

## 21. 参考

**内部**：v0.1–v0.3 SPEC、调研报告 v1.0、33-REA E3、23-四层闭环 Backtest、walk-forward/time-split、pycg、SPEC-41 测试矩阵、27-策略治理审批。

**外部**（完整 URL 见调研报告 §7）：
- AI：OpenAI Evals、lm-evaluation-harness、HELM、MLflow Evaluate、Vertex AI、Azure AI Foundry、LangSmith、DeepEval、RAGAS、promptfoo、Evidently
- 金融：TCE 高可用白皮书、Chaos Mesh、LitmusChaos、AWS FIS、DSR/PBO（Bailey & López de Prado）、SR 26-2、GIPS、qlib/vectorbt/zipline
- 工程：SonarQube Quality Gate、SLSA、in-toto、Sigstore、SBOM（CycloneDX/SPDX）、OpenSSF Scorecard、SARIF、trivy/grype/Semgrep
- 平台/统计：Celery、Temporal、Argo、MinIO Object Lock、RFC 6962、OpenLineage、gVisor、Krippendorff、Wilson CI、SPRT
</content>
