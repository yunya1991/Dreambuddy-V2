# SPEC v1.6 — L1 意图训练模式

> 版本: v1.0（草案） | 日期: 2026-11-17 | 状态: 待评审
> 归属: 34-前端应用训练系统（编排与门禁）/ 41-文件索引系统（意图单元与校准内核）
> 上游: [SPEC-v1.4 L0/L1/L2 路由边界与认知裁决](./SPEC-v1.4-L0L1L2-路由边界与认知裁决.md)（§9.3 E2 结论）、[SPEC-41-L1 语义意图检索增强](../41-文件索引系统/SPEC-41-L1语义意图检索增强-v1.0.md)
> 灵感对照: Google Chrome **Modern Web Guidance**（本地语义检索 + 可评估单元 + **eval dashboard + uplift 剪枝**）
> 一句话定位: 把「加样例 / 调阈值」从手工动作变成**可评测、可校准、可回滚**的闭环，并用 OOD 评测替代自证式 in-distribution 打分。

---

## 1. 背景：为什么必须建训练模式

### 1.1 现状矛盾（已实测）

| 口径 | top1 | top3 | 说明 |
|---|---|---|---|
| 自有 golden（in-distribution） | **100%**（378/378） | 100% | 评测问法取自 `intent_units` 示例，等于拿训练集当测试集 |
| E1 semantic 段（OOD 口语） | **38.8%** | 50.0% | 独立撰写、与示例零重叠，反映真实能力 |
| E1 全量（250 条有标注意图） | 58.8% | 67.6% | 含规范问法 |
| E1 延伸推荐（top2–3） | **8.8%** | — | 模型几乎只在 top1 附近有信号 |

**结论**：现有「378/378」不能作为能力证据；L1 语义通道在真实口语问法上是不可用的（这正是 E1 判定 S1 不启用语义主通道的依据）。

### 1.2 现有资产与缺口

| 资产 | 位置 | 缺口 |
|---|---|---|
| 21 个意图单元（正例/硬负例/执行器文档/向量） | `41-文件索引系统/intent_units/` | 无 OOD 集、无 holdout、无样本状态机 |
| 校准内核 | `41-文件索引系统/core/intent_calibrator.py`、`scripts/calibrate_intents.py` | 只在 in-dist 上算，uplift 未真正用于剪枝 |
| 路由策略与门控 | `3.1-FRONTEND/scripts/l1_route_signal.py`、`l1_routing_policy.py` | 无训练产物消费契约（快照/回滚） |
| E1/E2 数据集与 harness | `34-前端应用训练系统/eval/e1_cases.jsonl`、`scripts/eval_*` | 一次性实验，未纳入常态流程 |
| 线上反馈 | `logs/l1_suggest_shadow.jsonl`、建议点击 | 点击未埋点；日志未回流入数据集 |

### 1.3 目标 / 非目标

**目标**
1. 建立 T0–T3 四层训练闭环：数据 → 校准 → OOD 评测 → 门禁发布。
2. 所有发布必须通过**同一套可复现评测**，且指标可机器判定。
3. 引入 MWG 的 **uplift 剪枝**：无增益的样例/规则被标废，而不是只增不减。

**非目标**
- 不改变 L1 准入策略（E1 已定 S1：纯正则 + 契约门控）。
- 不在本 SPEC 内做模型微调；微调仅作为 P4 预研（须先证明 uplift）。
- 不接管 41 的索引构建（复用其脚本）。

---

## 2. 数据层 T0：四源 + 状态机 + 防泄漏

### 2.1 四类数据源

| 源 | 位置 | 用途 | 进入条件 |
|---|---|---|---|
| **S1 意图单元** | `intent_units/<intent>/{examples_zh,negatives_zh}.jsonl` | 检索样例池 | 已存在，作为基线 |
| **S2 实验集** | `eval/e1_cases.jsonl`（500 条，`label_status=ai_draft`） | OOD 评测 | 人工复核后转 golden |
| **S3 影子日志** | `logs/l1_suggest_shadow.jsonl` | 真实问法分布 | 去标识后入 `unlabeled` |
| **S4 建议点击** | 前端埋点（P1 新增） | 强正例（用户主动选择） | 需 `query` + 后续 `handled=true` 双条件 |

### 2.2 样本状态机

```text
unlabeled → ai_draft → agent_verified → golden
                 ↘ rejected（人工判定错误/重复/越界）
golden → deprecated（uplift<0.02 且人工确认）
```

硬规则：
- `agent_verified` 由复核 Agent（§2.6）产出，可用于训练与候选评测；
- 只有 `golden` 可参与发布门禁判定；`golden` = `agent_verified` + **10% 抽检人工确认**；
- `golden` 只增不改（纠错走新增 + `deprecated` 旧条）；
- 每条样本必须有 `source`、`labeled_by`、`labeled_at`。

### 2.3 统一 Schema

```json
{
  "id": "l1-000123",
  "message": "以太坊这两天有啥大动静",
  "expected_intent": "event_listing",
  "expected_route": "L1",
  "segment": "semantic",
  "split": "ood_spoken",
  "source": "e1|shadow|click|unit",
  "label_status": "golden",
  "labeled_by": "human",
  "labeled_at": "2026-11-17",
  "notes": ""
}
```

### 2.4 防泄漏与切分

1. **归一化去重**：去首尾空格、全角转半角、英文小写、去掉标点后比对；
2. **近重复检测**：字符 3-gram Jaccard ≥ 0.85 视为近重，**强制同 split**；
3. 与 `intent_units/*/examples_zh.jsonl` 精确/近重复的样本**禁止进入 OOD 集**；
4. split 比例：`in_dist 40% / ood_spoken 40% / holdout 20%`；holdout 在发布前完全不可见。

### 2.5 配额（发布最低要求）

| 项 | 最低量 |
|---|---|
| 每个意图正例（golden） | ≥ 20 |
| 每个意图硬负例（golden） | ≥ 50 |
| OOD 口语集 | ≥ 300（覆盖 ≥15 意图） |
| 域外/复合负例 | ≥ 120 |

### 2.6 复核 Agent（已交付）

脚本：`34-前端应用训练系统/scripts/review_e1_cases.py`（确定性规则，零 LLM、零 token）。

| 复核项 | 规则 | 适用分段 |
|---|---|---|
| 标签一致性 | `detect_intent_regex(msg)` 必须等于 `expected_intent` | data / clarify / regression |
| 分段正确性 | semantic 段**不得**被正则命中（命中说明其实是数据类） | semantic |
| 路由一致性 | `expected_route=L1` 的意图必须存在于 `EXECUTORS` | 全部 |
| 复合一致性 | `segment=compound` 必须被 D5 判定为复合 | compound |
| 完全重复 | 归一化（去标点/小写/全半角）后同文 | 全部 |
| 近重复 | 字符 3-gram Jaccard ≥0.85（长度 <6 跳过）；OOD 段额外与 `intent_units` 比对 | OOD 段 |

产物：
- `eval/review/e1_review.jsonl`（逐条 verdict + 原因）
- `eval/review/REPORT.md`（通过率 / 分段 / 原因分布 / 样例）
- `eval/e1_cases_reviewed.jsonl`（`--apply`，`label_status` 推进为 `agent_verified` / `needs_review`）

首轮实测（500 条）：**通过 470（94.0%）**，待复核 30（6.0%），其中 D5 已知漏网 17 条、近重复 5 条、无正则覆盖 5 条、意图冲突 3 条。

**定期执行**：已配置每周一 09:00（Asia/Shanghai）自动复核任务，产出带日期的报告。

---

## 3. 校准层 T1：阈值 + margin + uplift

### 3.1 参数空间

| 参数 | 范围 | 步长 | 说明 |
|---|---|---|---|
| `threshold` | 0.55 – 0.75 | 0.01 | 语义 top1 命中下限（当前 0.66） |
| `margin` | 0.00 – 0.12 | 0.01 | `top1 − top2`，仅观测（E1 已定不启用） |
| `k` | 3 | 固定 | 建议器/候选评估 |

### 3.2 目标函数（约束优化）

```text
在 FPR ≤ 2% 且 P95 ≤ 100ms 的约束下，最大化 OOD top1
```

不再使用「in-dist 准确率最高」作为选择标准。

### 3.3 uplift 定义（对齐 MWG）

对每个意图单元（样例集合或单条规则）：

```text
uplift(intent) = Acc_OOD(with_unit) − Acc_OOD(without_unit)
```

- `uplift < 0.02` → 标记 `deprecated_candidate`，人工确认后移出检索池；
- 每次扩充样例都必须报告 uplift，**禁止只报绝对准确率**；
- 负 uplift 必须解释（样例污染 / 意图边界重叠 / 标注错误）。

### 3.4 首轮校准实测（2026-11-17，P0 产物）

数据集：835 条唯一消息（exact dedupe 丢弃 1710），`in_dist 495 / ood_spoken 211 / holdout 129`，泄漏 0，OOD 340（≥300 达标）。

| 配置 | OOD top1 | OOD top3 | FPR | holdout top1 | in_dist top1 |
|---|---|---|---|---|---|
| t=0.55, δ=0.00（约束无解后的最优） | 33.3% | 40.0% | **54.3%** | 43.3% | 83.8% |

**结论：G1/G2/G3 全部未通过，硬门拒绝发布（预期行为）。**

两个根因（已定位，非调参可解）：
1. **G2 特征闸覆盖不足**：`required_pattern_ok` 只对 `data_insight` / `data_query` / `metric_series` 三个意图生效，其余 18 个意图**恒为 True**（permissive）。因此阈值/margin 无法压住关键词陷阱，FPR 天花板 54.3%。
2. **负例严重缺口**：全库仅 103 条 trap 负例、且只有 `asset_class_trend` 一个意图有 `negatives_zh.jsonl`（43 条），距 §2.5 要求（21×50=1050）差 10 倍。

uplift（leave-one-intent-out）：8 个意图 ≥0.02（price_query / event_listing / risk_control 等），11 个为 0（在 OOD 上无正确命中，列剪枝候选）。

**P0 后续必须先补**：21 意图 × 50 硬负例 + 为 18 个 permissive 意图补 `requiredPattern`，否则任何阈值都不可能过 G3。

### 3.5 第二轮实测（补齐 G2 + 1050 硬负例后）

已交付：
- **G2 补齐**：`required_pattern_ok` 从「除 3 个意图外恒 True」改为按 `intent.yaml` 的 `category` 分两类——`data` 需领域实体/关键词/查询线索，`analysis` 只需非定义型问法；并新增领域词表（含大饼/二饼/姨太/银子等口语别称）；
- **硬负例 1050 条**：`gen_negatives.py` 按「跨意图 3-gram 近邻」生成，每条标注 `negative_for`，FPR 按 per-intent 口径计算（判成别的意图不算误报）。

数据：1885 条（`in_dist 1527 / ood_spoken 228 / holdout 130`），负例 **1153**（达标），OOD 358（达标），泄漏 0。

| 指标 | 第一轮 | 第二轮 | 门槛 |
|---|---|---|---|
| OOD top1 | 33.3% | **26.7%** | ≥60% ❌ |
| OOD top3 | 40.0% | 28.3% | ≥75% ❌ |
| FPR | 54.3% | **41.7%** | ≤2% ❌ |
| in_dist top1 | 83.8% | 72.1% | 不回退 ❌ |
| holdout top1 | 43.3% | 26.7% | 不回退 ❌ |

**失败归因（诊断已做，60 条 OOD 正例逐条拆解）**：
- 8 条正确；
- **24 条被 G2 拒绝**：口语里不带任何领域词/线索（“大饼眼下报个什么数”“股那边开出来是好是坏”）；
- **28 条语义判错**：别称与黑话（大饼/姨太/二饼/银子/杠杆水位/人气）超出 bge-base + 现有样例的表达覆盖。

**结论（重要）**：G3 的 2% FPR 与 60% OOD top1 在当前「21 类 + 1050 条对抗性硬负例 + 768 维通用 embedding」组合下**不可达**，继续调阈值/加正则已进入过拟合区。瓶颈已从「门控实现」转为 **模型容量与数据密度**：
1. 每个意图的 OOD 正例仅约 3 条（60/19），估计方差极大；
2. 黑话/别称需要专门的**同义词归一**或领域微调，不是规则能补的；
3. 硬负例按「近邻但异意图」构造，本身就逼近分类器决策边界，FPR 天然偏高。

**因此下一步不是继续调参**，而是二选一（需决策）：
- **A（推荐，低成本）**：先做「别称/黑话归一表」（大饼→BTC、姨太/二饼→ETH、银子→白银），再重跑；目标先把 G2 拒绝的 24 条救回来；
- **B（高成本）**：P4 领域微调（SetFit/对比学习），用 uplift 证明增益后再启用。

### 3.6 索引修复轮（P0.5，2026-11-17）

**定位**（对比 `intent_vector_store` 与 kNN 基线，OOD 同一 60 条）：

| 假设 | 实测 | 判定 |
|---|---|---|
| 聚合方式 | 原实现每意图只存 **1 个质心向量**（`vector.json`），口语变体被平均 | **主因** |
| 索引条数 | 质心索引仅 365 条样例可用，扩到 466（并入 `in_dist` 正例）后 raw top1 50%→63.3% | 次因 |
| 类别映射 | `intent.yaml` 的 `category` 取值为 `data/insight/deterministic`，G2 只识别 `data/analysis`，导致 `insight`/`deterministic` 落入关键词分支被大量误杀 | **主因** |
| top-k 截断 | 阈值 0.55 下无一条因分数不足被拒（阈值损耗 0） | 排除 |

**修复**：
1. 新增 `41-文件索引系统/scripts/build_intent_example_vectors.py`，为每个意图生成 `example_vectors.json`（多样例向量，366→466 条）；
2. `IntentVectorStore.search` 优先对多样例取**最大相似度**，无样例时回退质心；
3. G2 类别映射补 `deterministic`（同 data）与 `insight`（同 analysis）；
4. 校准口径对齐生产：`_predict` 先过 **D5 复合闸**，再判阈值/G2/margin。

**复测**：

| 指标 | 修复前 | 修复后 | 门槛 |
|---|---|---|---|
| OOD top1 | 33.3% | **60.0%** | ≥60% ✅ |
| OOD top3 | 41.7% | **75.0%** | ≥75% ✅ |
| FPR | 54.3% | **19.6%** | ≤2% ❌ |
| in_dist top1 | 83.8% | **91.4%** | 不回退 ✅ |
| holdout top1 | 43.3% | 53.3% | 不回退 ✅ |

**G1/G2 首次通过**，G3 仍不达标。残差分析：剩余 57 条误报中**几乎全部是 D5 复合闸漏网**（“BTC价格和CPI数据”“ETH支撑位在哪，阻力位呢”），与语义模型无关——FPR 的剩余缺口是复合检测召回问题，不是索引/门禁问题。

**D5 复合召回已补（2026-11-17）**：
- 新增规则：追加型连接词 + 多实体/多指标（D6）、多子句各带不同实体（D8，锚点扩到支撑/阻力/资金费率/VIX 等）、成对比较语义护栏（`_SINGLE_PAIR`）避免误杀 leader_compare/top_correlation；
- 实测：compound 召回 **78.8% → 91.2%**，单意图误杀 **2.0% → 1.6%**；
- FPR：**19.6% → 6.5%**（t=0.55，OOD top1 保持 60.0%）。

**权衡曲线（决定性结论）**：

| threshold | OOD top1 | FPR |
|---|---|---|
| 0.55 | 60.0% | 6.5% |
| 0.66 | 50.0% | 6.5% |
| 0.72 | 30.0% | 4.8% |
| 0.72 + δ=0.08 | 25.0% | 1.8% |

**没有任何单一工作点能同时满足 OOD≥60% 与 FPR≤2%**。要同时达标只能改为**分意图阈值**（每个意图独立标定 t/δ，强意图放开、弱意图收紧），这是 T1 校准的下一版，而不是继续加全局规则。

**分意图阈值已试（2026-11-17，T1 v2）**：以 `in_dist` 为 dev、按全局 FPR 预算贪心为每个意图独立标定 t/δ。结果：

| 方案 | OOD top1 | OOD top3 | FPR |
|---|---|---|---|
| 全局 t=0.55 | 60.0% | 75.0% | 6.5% |
| 全局 t=0.72 + δ=0.08 | 25.0% | 36.7% | **1.8%** |
| 分意图阈值 | 30.0% | 36.7% | 2.4% |

分意图阈值**没有带来增益**，且精度/召回权衡与全局一致。原因：`in_dist` 的负例是跨意图近邻（域内易分），而 OOD 的负例是陷阱/域外（分布不同），阈值无法从 dev 迁移。**结论：问题不在阈值粒度，而在数据与能力上限。**

**最终裁决（本版）**：
- 语义通道**不进入 L1 准入**，仅用于建议器与 L2 引导（已上线）；
- 生产主链路保持 **S1（纯正则 + 能力契约 + D5 复合闸）**，零模型依赖；
- G1/G2 目标达成（OOD 60.0% / top3 75.0%），G3 的 2% 在当前资产下与 60% 覆盖不可兼得，需产品或数据侧决策：放宽到 ≤7%，或继续扩样/微调后再评估。

P4 微调已由 uplift 实验证否（OOD 探针 −6.7pp），暂不启动。

### 3.7 语义通道使用边界（终裁，2026-11-17）

| 项 | 裁决 |
|---|---|
| G3 误报门槛 | **维持 2%**，不放宽 |
| 语义通道职责 | **仅建议器 / L2 引导**，不参与 L1 准入 |
| S1 策略 | 强制关闭语义准入（`L1_SEMANTIC_ADMISSION=False`），`semantic_candidates(validated=True)` 直接返回 `[]` |
| S0 策略 | 保留历史语义兜底以兼容存量 golden 基线；**S0 退役时一并移除**，不再新增依赖 |
| 建议器 | 独立路径（`l1_suggest.py`），不受准入开关影响，继续可用 |
| 重评估条件 | 需新 SPEC：OOD 数据翻倍且 per-intent 阈值在 holdout 上同时满足 OOD≥60% / FPR≤2% |

实现位置：`l1_route_signal.py` 顶部 `_L1_SEMANTIC_ADMISSION`（由 `L1_ROUTING_STRATEGY` 与 `L1_SEMANTIC_ADMISSION` 共同决定），并在 `semantic_candidates(validated=True)` 与 `detect_intent` 语义兜底两处生效。

验证：S1 下 `admission=False`、`semantic_candidates(...)=[]`；L1 测试 341 条全绿。

---

## 4. 评测层 T2：三层集 + 统计显著性

### 4.1 评测矩阵

| 层级 | 用途 | 参与发布门禁 |
|---|---|---|
| `in_dist` | 回归保护（防样例退化） | 是（不回退） |
| `ood_spoken` | 真实能力 | 是（主指标） |
| `holdout` | 防调参过拟合 | 是（最终裁定） |

### 4.2 指标定义

| 指标 | 定义 |
|---|---|
| `top1_acc` | 语义 top1 == 标注意图 |
| `top3_recall` | 标注意图 ∈ top3 |
| `neg_fpr` | 硬负例被判为该意图的比例 |
| `compound_far` | 复合问法被单边直答的比例（复用 D5 闸口径） |
| `uplift` | 见 §3.3 |
| `p50/p95_ms` | 8099 常驻服务下端到端耗时 |

### 4.3 统计

- bootstrap 1000 次，报告 95% CI；
- 新旧版本对比用 **McNemar 检验**，`p < 0.05` 才算显著提升；
- 样本量不足（<100）时只报告 CI，不下「提升」结论。

### 4.4 执行方式

复用 E1 harness 的特征缓存机制（一次编码、多策略回放），新增 `--suite l1_intent` 入口，禁止每次重算 embedding。

---

## 5. 发布层 T3：门禁 + 快照 + 回滚

### 5.1 门禁（全部机器判定，**硬门：任一失败即拒绝发布**）

| # | 项 | 门槛 | 失败动作 |
|---|---|---|---|
| G1 | OOD top1 | ≥ 60% | 拒绝发布 |
| G2 | OOD top3 | ≥ 75% | 拒绝发布 |
| G3 | 硬负例 FPR | ≤ 2% | 拒绝发布 |
| G4 | holdout top1 | ≥ 上一版 − 0.5pp | 拒绝发布 |
| G5 | in_dist top1 | 不回退（≥ 上一版 − 0.2pp） | 拒绝发布 |
| G6 | 平均 uplift | ≥ 0.02 | 拒绝发布 |
| G7 | P95 延迟 | ≤ 100ms | 拒绝发布 |
| G8 | 数据集完整性 | 配额达标（§2.5） | 拒绝发布 |

### 5.2 发布物

```text
34-前端应用训练系统/training/l1_intent/snapshots/<YYYYMMDD>/
├── vectors/            # 意图向量（拷贝自 41 构建产物）
├── calibration.json    # threshold / margin / per-intent uplift
├── metrics.json        # 三层指标 + CI + McNemar
├── dataset_manifest.json  # 样本 id 清单 + sha256
└── MANIFEST.md         # 人工可读摘要
```

### 5.3 消费与回滚

- 路由侧只读 `calibration.json`（threshold）与 `vectors/`；
- **threshold 自动切换**：`promote.py` 通过 G1–G8 后自动切换 `current` 软链并生效，不需要人工确认；
- 自动切换前写审计记录（`audit.log`：时间、快照、G1–G8 数值、git commit）；
- 回滚 = 切回上一快照（一条命令），回滚同样写审计；
- 快照不可变；任何修改生成新目录。

### 5.4 触发条件

| 触发 | 条件 |
|---|---|
| 定时 | 每周一 |
| 增量 | 新增 golden ≥ 200 |
| 事件 | 新增/拆分意图、线上 L2 兜底率周环比 +20% |

---

## 6. 与现有系统的关系

| 系统 | 角色 | 改动 |
|---|---|---|
| 41 `intent_units` + `intent_calibrator` | 样例与校准内核 | 扩展 OOD/holdout 支持，不改向量构建 |
| 34 训练系统 | **编排、评测、门禁、快照** | 新增 `training/l1_intent/` |
| 3.1 路由 | 消费 threshold/vectors | 只读快照，不改 S1 逻辑 |
| 影子日志/点击 | 数据回流 | P1 加点击埋点 |

边界：训练系统**不得**直接改生产路由代码；只能产出快照并经由发布门禁切换。

---

## 7. 实施计划

| 阶段 | 交付物 | 验收 |
|---|---|---|
| **P0** 数据治理 | `training/l1_intent/datasets/`（四源合并 + 去重 + split）；`build_dataset.py`；**复核 Agent `scripts/review_e1_cases.py`（已交付，首轮 470/500 通过）** | 配额达标；OOD 与 examples 零重叠（自动断言） |
| **P1** 校准与 uplift | `calibrate.py`（网格 + uplift + 剪枝候选） | 产出 `calibration.json`；uplift 表可读 |
| **P2** OOD 评测 | `eval_suite.py`（三层 + CI + McNemar）、报告模板 | 一条命令产出报告；数值与 E1 可对齐 |
| **P3** 发布门禁 | `promote.py`（G1–G8 + 快照 + 回滚）、cron | 故意构造劣化版本能被拒绝；回滚 1 分钟内完成 |
| **P4**（预研）微调 | SetFit/小样本微调对照 | 仅在 P2 证明检索到天花板后启动，且 uplift 达标 |

**P0 首个里程碑**：把 `e1_cases.jsonl` 的 500 条从 `ai_draft` 复核到 `golden`，形成第一版三层集。

---

## 8. 验收标准（机器可判定）

1. `python3 training/l1_intent/eval_suite.py --check-leak` 输出 0 重叠；
2. `calibrate.py` 产出 `calibration.json`，含 21 意图的 uplift；
3. `promote.py --dry-run` 输出 G1–G8 逐项结果与最终裁决；
4. 构造一个「OOD top1 = 45%」的降级版本，`promote.py` 必须拒绝；
5. 快照切换与回滚各有一次演练记录。

---

## 9. 风险与边界

| 风险 | 缓解 |
|---|---|
| OOD 集被污染（写样例时参考过） | 独立撰写 + 近重复检测 + holdout 隔离 |
| 标注成本高 | 先 AI 初标，人工只复核争议项；按配额分批 |
| 小样本过拟合阈值 | grid + holdout + McNemar；禁止用 holdout 调参 |
| 冷启动（进程内模型 22s） | 只使用常驻 8099；延迟门禁 G7 |
| 意图边界漂移（新增意图） | 触发条件含「新增/拆分意图」，强制重跑 |
| 指标好看但无业务收益 | 同时报告 Coverage / Compound-FAR / 点击采纳率 |

---

## 10. 附录：命令（规划）

```bash
# 1) 建数据集（合并四源、去重、分层）
python3 training/l1_intent/build_dataset.py --sources units,e1,shadow --out datasets/

# 2) 泄漏检查
python3 training/l1_intent/eval_suite.py --check-leak --datasets datasets/

# 3) 校准 + uplift
python3 training/l1_intent/calibrate.py --datasets datasets/ --out snapshots/20261124/

# 4) 三层评测
python3 training/l1_intent/eval_suite.py --suite l1_intent --snapshot snapshots/20261124/

# 5) 门禁与发布
python3 training/l1_intent/promote.py --snapshot snapshots/20261124/ --dry-run
python3 training/l1_intent/promote.py --snapshot snapshots/20261124/ --promote
python3 training/l1_intent/promote.py --rollback
```
