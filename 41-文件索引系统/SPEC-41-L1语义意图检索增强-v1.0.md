# SPEC — 41-L1 语义意图检索增强

> **版本**: v1.1 (2026-11-15)
> **状态**: **P0-P4 已实现并验证**（15 个满足语料门禁的意图向量；21 意图执行器文档按需 retrieve；35 项 41 意图测试 + 41 项路由测试 + 18 项 TS 注册表测试通过；golden set 378/378）
> **定位**: 为 L1 意图识别增加**本地语义检索通道**，增强正则兜底的语义鲁棒性
> **灵感来源**: Google Chrome [Modern Web Guidance](https://github.com/GoogleChrome/modern-web-guidance-src)（Google I/O 2026）的「本地 embedding 语义检索 + 倒转模式 + 可评估单元 + 内容校准」架构
> **归属**: 41-文件索引系统（L0 检索供给层），以 L1 意图消费形态对外
> **上游关联**: [SPEC-41-文件索引系统-v1.1](./SPEC-41-文件索引系统-v1.1.md) §7.10（L1 doc_search 意图）、[l1-intent-registry.ts](../3.1-FRONTEND/src/lib/l1-intent-registry.ts)、[l1_route_signal.py](../3.1-FRONTEND/scripts/l1_route_signal.py)
> **变更记录**:
> - v1.1（2026-11-15）评审修订：① 修正函数名 detect_intent / golden set 377 条 / 21 意图；② embedder 复用改为 subprocess 桥接（对齐 vector_bridge.py）；③ 明确语义命中仍需 route_confidence 门控；④ 倒转模式改为「注册表不变 + 执行器文档按需 retrieve」；⑤ 性能数字修正为 100~300ms；⑥ calibration 正例 ≥95%；⑦ 新增语言自动识别（中/英）；⑧ 新增云端模型下载方案；⑨ 新增 300+ 统计算法评估接入；⑩ 补充测试计划 + 可观测性指标

---

## 0. 一句话定位

给 L1 意图识别加一条**零 token、本地运行的语义匹配通道**——用 embedding + cosine similarity 匹配用户问法与意图示例，作为正则 `fallbackPattern` 之外的第二通道，解决"问法语义变体匹配不上正则"的漏路由问题；同时引入**可评估意图单元 + 内容校准**机制，让每个意图规则的有效性可度量、可裁剪。

---

## 1. 背景与动机

### 1.1 现状

L1 意图识别当前依赖两条链路：

1. **正则兜底**（[l1-intent-registry.ts](../3.1-FRONTEND/src/lib/l1-intent-registry.ts) `fallbackPattern` / `requiredPattern`）：**21 个意图**，每条手写正则，按注册表顺序匹配
2. **模型预测 + 置信度门控**（`route_confidence`，C3 匹配度 + C4 预测误差，阈值 0.65）

正则兜底的问题：
- **维护成本高**：每条正则需穷举问法变体，新增意图时容易漏写
- **语义盲区**：用户换一种说法（同义词/口语/缩写），正则就漏匹配
- **顺序依赖**：注册表顺序决定优先级，后注册的意图可能被前面的宽泛正则吞掉
- **无效果度量**：加了正则就觉得管用，无法量化每条规则的真实 uplift

### 1.2 Modern Web Guidance 的启发

MWG 是 Chrome 团队为编码 Agent 构建的本地语义检索系统，核心架构可直接迁移到意图识别场景：

| MWG 模式 | 原用途 | 迁移到 L1 意图识别 |
|----------|--------|-------------------|
| **本地 embedding 语义检索** | 把用户 query 与 161 个 guide 的向量做 cosine 匹配，返回 top-5 | 把用户 message 与 21 个意图的示例向量做 cosine 匹配，取 top-1 作为语义命中意图 |
| **倒转模式（Inverted Pattern）** | SKILL.md 只放搜索指令（~250 tokens 常驻），guide 按需 retrieve | 注册表保持不变（正则常驻），执行器文档/正例反例按需 retrieve |
| **分块前缀策略** | 每个 chunk 前缀 `guide_id (category)\nFeatures: ...`，提升匹配精准度 | 每个意图示例前缀 `intent_id (category)\nKeywords: ...`，让 embedding 携带意图身份 |
| **可评估单元 + Calibration** | 每个 guide 有正例/反例 + Playwright grader，要求正例 100% / 反例 0% | 每个意图有正例/反例集 + grader，要求正例必命中该意图、反例必不命中 |
| **内容校准（Uplift）** | 度量 guide 的真实 uplift（引导通过率 − 未引导通过率），裁掉无效内容 | 度量每条意图规则的 uplift（有规则 vs 无规则的准确率差），裁掉 uplift≈0 的规则 |

### 1.3 设计目标

1. **语义兜底**：正则未命中时，用语义匹配补漏，降低漏路由率
2. **零 token、本地运行**：复用项目已有的 `bge-small-zh-v1.5` embedding 模型，CPU 推理，无 API 调用
3. **可评估**：每个意图的匹配规则有正例/反例 + 自动化 grader
4. **可校准**：能量化每条规则的 uplift，支持裁剪无效规则
5. **不破坏现有链路**：作为正则的并行通道，FAIL-OPEN 降级，不影响现有路由

---

## 2. 核心设计

### 2.1 双通道意图匹配

```
用户 message
    ├─ 通道 A：正则匹配（现有 fallbackPattern / requiredPattern）
    │      └─ 命中 → 返回意图
    └─ 通道 B：语义匹配（本 SPEC 新增）
           ├─ embed(message) → 与所有意图向量 cosine similarity
           ├─ top-1 意图 similarity ≥ 语义阈值（zh=0.65，P2 校准）→ 命中
           └─ 未达阈值 → 不命中（走 L2）
```

**通道优先级**：A 命中优先于 B（正则对实体词匹配更精准）；A 未命中时才走 B；B 未命中走 L2。

### 2.2 意图向量构建（借鉴 MWG 分块前缀策略）

每个意图预计算一个**意图向量**，由该意图的所有正例句 embedding 取均值得到。每个正例句的 embedding 文本格式：

```
{intent_id} ({category})
Keywords: {keyword1}, {keyword2}, ...

{example_sentence}
```

- **前缀携带意图身份**：即使例句本身语义模糊，前缀的 intent_id + category + keywords 也能引导 embedding 空间归位
- **多例句均值**：一个意图的多个正例句取均值，得到该意图的"语义质心"
- **预计算存储**：构建时一次性计算，序列化到 JSON 文件，查询时只做 cosine 点积

> **⚠️ A/B 验证结论（P0 已完成）**：在 golden set 上做 80/20 分割对比，**无前缀准确率 71.2%（42/59），有前缀仅 39.0%（23/59）**。前缀策略对意图匹配引入噪声（不同于 MWG 的 guide chunk 归位场景），**默认关闭前缀策略（use_prefix=False）**。

### 2.3 倒转模式：执行器文档按需 retrieve

现有 [l1-intent-registry.ts](../3.1-FRONTEND/src/lib/l1-intent-registry.ts) 包含完整正则，常驻上下文。借鉴 MWG 的"SKILL.md 只放搜索指令"思路：

- **注册表（保持不变，常驻）**：`intent` + `category` + `fallbackPattern` / `requiredPattern`（正则必须常驻，匹配要快）+ 向量文件路径引用。**注册表结构不变，不做轻量化改造**——正则才是体积主体，拆出去反而增加匹配开销。
- **执行器文档（按需 retrieve，新增）**：每个意图的执行器规范、边界条件、完整正例/反例集拆到独立文件，按 intent_id 按需加载。这是倒转模式的真正收益点——避免把所有意图的执行细节常驻上下文。
- **后续扩展**：语义文章检索（doc_search）和 300+ 统计算法评估也采用同一按需 retrieve 模式，详见 §6.5。

### 2.4 可评估意图单元（借鉴 MWG guide 契约）

每个意图是一个可评估单元，目录结构：

```
41-文件索引系统/intent_units/
└── {intent_id}/
    ├── intent.yaml          # 意图元数据（id/category/description/keywords）
    ├── executor.md          # 执行器规范与边界条件（P4，按需 retrieve）
    ├── examples_zh.jsonl    # 中文正例句（golden set，来自 34 系统 l1_intent_golden.jsonl）
    ├── examples_en.jsonl    # 英文正例句（可空，不足则该意图不启用英文语义通道）
    ├── negatives_zh.jsonl   # 中文反例句（不应命中该意图的问法）
    ├── negatives_en.jsonl   # 英文反例句
    └── vector.json          # 预计算意图向量 {"zh": [...], "en": [...]}（构建产物，不入库）
```

### 2.5 Calibration 与 Uplift 度量

**Calibration（必须通过）**：
- 正例集中 **≥95%** 命中该意图（语义 similarity ≥ 阈值 或 正则命中）——不追求 100%，避免阈值压过低导致反例误命中飙升
- 反例集中 **≤2%** 误命中该意图
- 不通过则调整阈值/正则/补充例句，不允许带病上线

**Uplift 度量（定期运行）**：
- 对每个意图，用**标注过意图标签的历史 query**（初始用 golden set 近似，后续用真实流量标注集）跑两组实验：有该意图规则 vs 无该意图规则
- `uplift = (有规则准确率) - (无规则准确率)`
- uplift < 0.02 的规则标记为"待裁剪"，人工确认后移除

---

## 3. 架构设计

### 3.1 系统组件

```
41-文件索引系统/
├── core/
│   ├── intent_embedder.py      # 意图 embedding 构建器（subprocess 桥接 bge-small-zh + all-MiniLM-L6）
│   ├── intent_vector_store.py  # 意图向量存储（zh/en 双套）与 cosine 检索
│   ├── intent_matcher.py       # 双通道匹配器（正则 + 语义）+ 语言自动识别
│   ├── intent_calibrator.py    # 校准与 uplift 度量
│   ├── intent_doc_retriever.py # 执行器文档/正例反例按需加载（P4）
│   └── embedder_bridge.py      # embedder 客户端：常驻服务(127.0.0.1:8099) → in-process → subprocess 三级降级（见 SPEC-41-L1-新闻意图检索 §8.8）
├── intent_units/               # 意图可评估单元（每个意图一个目录）
│   ├── data_query/
│   ├── price_query/
│   └── ...
├── scripts/
│   ├── build_intent_vectors.py # 预计算意图向量（zh/en）
│   ├── calibrate_intents.py    # 跑 calibration + uplift
│   ├── embed_server.py         # 常驻向量服务（模型只加载一次，POST /embed + GET /health）
│   └── intent_search_cli.py    # 调试用 CLI：输入 message 输出匹配意图 + 得分
├── deploy/
│   └── dreambuddy-embedder.service  # 常驻服务 systemd unit（User=luke、HF_HUB_OFFLINE=1、MemoryMax=2G）
└── tests/
    ├── test_intent_matching.py # 双通道匹配测试
    └── test_embed_server.py    # 常驻服务与三级降级链路测试
```

### 3.2 数据流

```
构建时：
  intent_units/{intent}/examples.jsonl
    → intent_embedder（按语言分组：zh→bge-small-zh, en→all-MiniLM-L6）
    → 每条加前缀 → embed → 均值
    → intent_units/{intent}/vector.json {zh_vector, en_vector}

查询时：
  message
    → lang_detect(message)  # 中文字符占比 ≥30% → zh，否则 en
    → intent_matcher.match(message, lang)
        ├─ 通道 A：正则遍历 _FALLBACK_PATTERNS（现有 detect_intent）
        ├─ 通道 B：embed(message, lang) → intent_vector_store.cosine_top1(lang)
        │             ├─ similarity ≥ SEMANTIC_THRESHOLD → 语义命中
        │             └─ 否则 → 不命中
        └─ 合并：A 优先，A 未命中用 B，B 未命中返回 None
```

### 3.3 与现有 L1 路由链路的集成

集成点在 [l1_route_signal.py](../3.1-FRONTEND/scripts/l1_route_signal.py) 的 `detect_intent()` 函数内部（正则遍历完未命中后追加语义匹配）：

```python
# 现有 detect_intent() 末尾
def detect_intent(message: str) -> str:
    for intent, pattern in _FALLBACK_PATTERNS:
        if pattern.search(message):
            return intent
    if _DATA_INSIGHT_PATTERN.search(message):
        return "data_insight"
    if _is_deterministic_series(message):
        return "metric_series"
    if resolve_source(message) or _DATA_QUERY_PATTERN.search(message):
        return "data_query"

    # ===== 新增：正则未命中时走语义通道 =====
    semantic = intent_matcher.semantic_match(message)
    if semantic:
        intent = semantic["intent"]
        # 语义命中仍需通过 requiredPattern 校验（data_query/data_insight 通用意图）
        if intent in ("data_query", "data_insight") and not _check_required_pattern(intent, message):
            return ""  # 语义命中但校验不过，交回 L2
        return intent
    return ""
```

**关键约束（route_confidence 交互澄清）**：
- 语义通道是**与正则同级的兜底**，不改变 `route_confidence` 的值，也不绕过其门控
- 语义命中的**非确定性意图**（data_insight / path_insight / event_analysis 等）→ 仍走 `route_query` 主流程的 recall + `evaluate_route`，需 `route_confidence ≥ 0.65` 才 L1_DIRECT
- 语义命中的**确定性意图**（whale_flow / calendar_event / stat_query 等 DETERMINISTIC_INTENTS）→ 走 `_route_deterministic` 跳过 recall 直答（与正则命中同等待遇）
- 语义命中的 **metric_series** → 仍需检查 `_is_deterministic_series(message)`，为 true 才跳过 recall，否则走正常门控
- 语义命中的 **doc_search** → `route_query` 返回 `l1_no_executor` 交 L2（doc_search 无 L1 执行器）
- DETERMINISTIC_INTENTS 不主动走语义通道（实体词正则更可靠），但若正则漏了、语义命中了，按上述规则处理

### 3.4 Embedding 模型选型与语言自动识别

**中文模型**：复用项目已有的 `BAAI/bge-small-zh-v1.5`（[9-RAG-INFRA 配置](../2-KNOWLEDGE/9-RAG-INFRA/vector_store/config.py)），512 维。

**英文模型**：新增 `sentence-transformers/all-MiniLM-L6-v2`（384 维），与 MWG 一致，英文金融语义质量优于 bge-zh。

**语言自动识别**：查询时先做轻量语言检测，路由到对应模型：

```
message → lang_detect(message)
    ├─ zh (含中文字符 ≥ 30%) → bge-small-zh-v1.5
    └─ en (否则)             → all-MiniLM-L6-v2
```

- 意图向量构建时也按语言分别构建：每个意图维护 zh_vector 和 en_vector 两套
- 中文 query 只与 zh_vector 比较，英文 query 只与 en_vector 比较，避免跨语言向量空间不兼容
- 语言检测用字符级规则（`[\u4e00-\u9fa5]` 占比），零依赖、<1ms

| 维度 | bge-small-zh-v1.5 | all-MiniLM-L6-v2 |
|------|-------------------|------------------|
| 语言 | 中文优先 | 英文 |
| 维度 | 512 | 384 |
| 模型大小 | ~100MB | ~22MB |
| 项目已有 | ✅ 已部署 | ❌ 需新增 |
| 推理耗时（CPU） | 150~300ms | 80~150ms |

**云端模型下载方案**：
- 9-RAG-INFRA 的 bge-small-zh-v1.5 在云端（43.160.201.117）通过 `venv-trading` 已部署，sentence-transformers 会自动从 HuggingFace 缓存
- 本地 41 系统的 .venv **不含** sentence-transformers/torch（见 requirements.txt），因此 embedding 推理必须通过 **subprocess 桥接**调用云端/venv-trading 的 embedder
- all-MiniLM-L6-v2 首次使用时需下载（~22MB），由 venv-trading 的 sentence-transformers 自动缓存到 `~/.cache/huggingface/`
- 离线环境预案：若云端无法访问 HuggingFace，提前把模型权重 rsync 到 `~/.cache/huggingface/hub/`，或用 `HF_HUB_OFFLINE=1` 强制走本地缓存
- FAIL-OPEN：embedder  subprocess 调用失败时，语义通道降级关闭，退回纯正则匹配

**结论**：中文用 bge-small-zh-v1.5，英文用 all-MiniLM-L6-v2，语言自动识别路由；embedding 推理通过 subprocess 桥接 venv-trading，不引入 41 侧新依赖。

### 3.5 向量存储与桥接机制

不引入 ChromaDB（意图向量只有 21 条，暴力 cosine 足够）：

- 存储格式：`intent_units/{intent}/vector.json`，内含 `zh_vector`（512 维）+ `en_vector`（384 维）
- 查询时全部加载到内存（21 × (512+384) × 4 bytes ≈ 75KB），暴力点积
- 与 MWG 的 `use-cases.vectors.gen.json.gz` 思路一致——小规模数据无需向量数据库

**Embedder 桥接（对齐 vector_bridge.py 模式）**：
- 41 的 .venv 无 sentence-transformers/torch，embedding 推理通过 **subprocess** 调用 venv-trading 的 embedder（与 [vector_bridge.py](./scripts/vector_bridge.py) 同构）
- 协议：stdin 收 `{"texts": [...], "lang": "zh|en"}`，stdout 出 `{"vectors": [[...], ...]}`
- 构建时（build_intent_vectors.py）批量调用，查询时（intent_matcher.semantic_match）单条调用
- 进程内单例：embedder 子进程常驻（vector_bridge_daemon.py 的 socket 模式），避免每次冷启动加载模型

---

## 4. 接口设计

### 4.1 意图匹配接口

```python
class IntentMatcher:
    def match(self, message: str, lang: str = "auto") -> MatchResult:
        """双通道意图匹配。

        - lang: "auto"（自动检测）/ "zh" / "en"
        返回:
            MatchResult(intent, channel, score, confidence, lang)
            - channel: "regex" | "semantic" | "none"
            - score: 正则命中为 1.0，语义命中为 cosine similarity
            - intent 为 None 时 channel="none"
        """

    def semantic_match(self, message: str, lang: str = "auto") -> Optional[SemanticMatch]:
        """纯语义匹配（供正则未命中时调用）。"""

    def regex_match(self, message: str) -> Optional[str]:
        """纯正则匹配（复用现有 detect_intent 的 _FALLBACK_PATTERNS 遍历）。"""
```

### 4.2 向量构建接口

```python
class IntentEmbedder:
    def build_intent_vector(self, intent_id: str) -> dict:
        """读取 intent_units/{intent_id}/examples.jsonl，按语言分组后 embed 取均值。
        返回 {"zh": [512 floats], "en": [384 floats]}。
        英文例句不足时 en_vector 为 None（该意图不启用英文语义通道）。
        """

    def build_all(self) -> dict[str, dict]:
        """构建所有意图向量，写入 vector.json。"""
```

### 4.3 校准接口

```python
class IntentCalibrator:
    def calibrate(self, intent_id: str) -> CalibrationResult:
        """跑正例/反例集，返回通过率。
        - positive_pass_rate: 正例命中率（目标 1.0）
        - negative_pass_rate: 反例误命中率（目标 0.0）
        - passed: 是否通过 calibration
        """

    def measure_uplift(self, intent_id: str, eval_queries: list[dict]) -> float:
        """度量该意图规则的 uplift。"""
```

### 4.4 执行器文档按需检索接口（P4）

```python
class IntentDocRetriever:
    def retrieve(self, intent_id: str) -> dict:
        """仅加载 intent_units/{intent_id}/ 下的 executor.md、intent.yaml
        和完整 examples/negatives JSONL；同实例重复请求读取缓存。
        返回 found/degraded/metadata/executor_doc/examples/negatives/errors。
        非法 intent、目录缺失、文档缺失或 JSONL 损坏均显式降级，不向上抛异常。
        """
```

### 4.5 调试 CLI

```bash
# 输入 message，输出匹配意图 + 各通道得分
python scripts/intent_search_cli.py "BTC现在啥价"
# 输出:
# {
#   "intent": "price_query",
#   "channel": "regex",
#   "regex_match": "price_query",
#   "semantic_top3": [
#     {"intent": "price_query", "similarity": 0.78},
#     {"intent": "data_query", "similarity": 0.42},
#     {"intent": "metric_series", "similarity": 0.38}
#   ]
# }
```

---

## 5. 阈值与参数

| 参数 | 初始值 | 说明 | 校准方式 |
|------|--------|------|----------|
| `SEMANTIC_THRESHOLD_ZH` | **0.65**（P2 校准） | 中文语义命中的 cosine 下限 | golden set ROC：正则 100% 覆盖正例，语义仅控反例 FPR；阈值 0.65 时 FPR=0%，有效 TPR=100% |
| `SEMANTIC_THRESHOLD_EN` | 0.50 | 英文语义命中的 cosine 下限（all-MiniLM-L6 分布不同，单独校准） | 用英文 golden set 跑 ROC（待英文语料就绪） |
| `SEMANTIC_TOP_K` | 3 | 返回 top-K 语义候选（调试用，实际取 top-1） | 固定 |
| `MIN_POSITIVE_EXAMPLES` | 5 | 每个意图每语言最少正例句数（不足则该语言不启用语义通道） | 固定 |
| `LANG_DETECT_ZH_RATIO` | 0.30 | 中文字符占比阈值，≥ 此值判定为 zh | 固定 |
| `CALIBRATION_POSITIVE_PASS` | 0.95 | calibration 正例通过率下限 | 固定 |
| `CALIBRATION_NEGATIVE_PASS` | 0.02 | calibration 反例误命中率上限 | 固定 |
| `UPLIFT_PRUNE_THRESHOLD` | 0.02 | uplift 低于此值标记待裁剪 | 人工确认后执行 |

> **P2 校准结论（2026-11-17）**：golden set 332 正例 + 30 反例 ROC 分析显示，**正则通道已 100% 覆盖所有正例**，语义通道在正例上的有效 TPR 恒为 100%（无正则漏过正例）。语义通道的唯一作用是控制 unknown 反例的 FPR。反例最高 max_sim=0.642，取阈值 `SEMANTIC_THRESHOLD_ZH=0.65`：FPR=0%（≤2% 目标），端到端正例覆盖率=100%。语义兜底召回（正则漏过正例）约 88%，作为正则的安全网。golden set 测试在该轮从 367/378 提升至 374/378（7 个 unknown 误命中全部消除）；随后修复 4 例 leader_compare 前置规则造成的跨资产误路由，当前 golden set 为 378/378。

---

## 6. 与既有模块的边界

### 6.1 与 41-文件索引系统主 SPEC 的关系

- 本 SPEC 是 41 系统的**子能力扩展**，不修改主 SPEC 的 L1/L2/L3 分层
- 意图向量存储在 `intent_units/` 目录，不进入 PostgreSQL 索引库（意图向量不是文件索引）
- 复用 41 的 `core/` 目录组织代码，不新建独立模块

### 6.2 与 L1 意图注册表的边界

- [l1-intent-registry.ts](../3.1-FRONTEND/src/lib/l1-intent-registry.ts) 仍是**意图注册的单一事实源**（正则 + requiredPattern）
- 本 SPEC 的语义通道是**消费方**，读取注册表中的意图列表，但不修改注册表
- 正例/反例集与 [34 系统 l1_intent_golden.jsonl](../34-前端应用训练系统/l1_intent_golden.jsonl) 同源维护

### 6.3 与 9-RAG-INFRA 的边界

- 复用 `bge-small-zh-v1.5` 模型，新增 `all-MiniLM-L6-v2`，但**不共用 ChromaDB collection**
  - 9-RAG-INFRA 的 ChromaDB 存的是文档 chunk 向量（4,540 chunks）
  - 本系统的意图向量只有 21 条，用 JSON 文件存储，暴力检索
  - 避免把意图向量混进文档检索 collection，保持职责单一
- embedding 推理通过 **subprocess 桥接**调用 venv-trading 的 embedder（与 [vector_bridge.py](./scripts/vector_bridge.py) 同构），41 的 .venv 不新增 sentence-transformers/torch 依赖

### 6.4 与 route_confidence 的边界

- 语义通道是**正则兜底的增强**，不参与 `route_confidence` 计算
- `route_confidence` 的 C3 匹配度仍基于认知库 recall，语义命中不改变其值
- 语义命中的意图仍需通过 `canHandleL1` 校验（通用意图的 requiredPattern）

### 6.5 后续扩展：语义文章检索 + 300+ 统计算法评估

本 SPEC 的语义检索架构（本地 embedding + cosine + 按需 retrieve + 可评估单元）可复用于两个后续场景：

**1. 语义文章检索（doc_search 意图增强）**
- 当前 doc_search 走 41 的 BM25 全文检索（SPEC-41 §5.4 recall）
- 后续可在 BM25 结果上叠加**语义重排**：用 bge-small-zh 对 query 和 top-N 文档片段做 cosine 重排
- 架构复用：intent_vector_store → doc_vector_store（文档 chunk 向量），intent_matcher → doc_reranker
- 与 9-RAG-INFRA ChromaDB 的分工：ChromaDB 做粗召回（4,540 chunks），41 做语义重排（top-50 精排），对齐 §7.12 协同设计

**2. 300+ 统计算法评估接入**
- 54-L1架构能力聚合层已注册 300+ 统计算法（stat_query 意图族）
- 当前算法选择靠正则匹配算法名（如 "回撤"→drawdown、"Hurst"→持续性），对同义词/口语问法不鲁棒
- 可复用本 SPEC 的**意图向量 + cosine 匹配**模式：每个算法维护示例句向量，用户问法语义匹配到对应算法
- 评估接入：每个算法的 examples.jsonl 需新增人工审核 sidecar 语料（当前 54 注册表无 examples 字段），calibration 用历史 stat_query 真实 query 验证
- 实施时需先盘点 300+ 算法的覆盖率与示例句完备性，分批纳入

> 这两个扩展不在本 SPEC P0-P4 实现范围内，但架构预留了扩展位（向量存储/匹配器/校准器均可参数化），后续单独立项。P4 预研已完成：[语义文章检索可行性评估](./docs/P4-语义文章检索可行性评估-v1.0.md)、[统计算法语义接入可行性评估](./docs/P4-统计算法语义接入可行性评估-v1.0.md)。文章精排遵循主 SPEC §7.8「41 只到召回、业务模块自持精排」的职责边界。

---

## 7. 实施路线

| 阶段 | 内容 | 验收 |
|------|------|------|
| **P0** ✅ | intent_embedder（subprocess 桥接 bge-small-zh + all-MiniLM-L6）+ intent_vector_store：按语料门禁构建意图 zh/en 双向量（当前 15 个中文可用）；intent_search_cli 调试可用；**A/B 验证前缀策略** | 输入 message 能输出 top-3 语义候选 + 相似度；前缀策略 A/B 结论明确 |
| **P1** ✅ | intent_matcher 双通道匹配：正则优先，正则未命中走语义；集成到 `detect_intent()`；语言自动识别 | 正则漏匹配的 query 能被语义通道补回；41 项 l1_route_signal 测试全绿；FAIL-OPEN（L1_SEMANTIC_MATCH=0）验证通过 |
| **P2** ✅ | 阈值校准：用 l1_intent_golden.jsonl 跑 ROC，确定 `SEMANTIC_THRESHOLD_ZH/EN`；calibration 流水线 | `SEMANTIC_THRESHOLD_ZH=0.65`：正则 100% 覆盖正例，FPR=0%，有效 TPR=100%，端到端覆盖率=100%；golden set 测试 378/378 |
| **P3** ✅ | 可评估单元 + uplift 度量：negatives 纳入 unknown OOS；`core/intent_calibrator.py` per-intent 校准 + uplift；calibrate_intents.py 输出表格 + JSON 报表 | 15/15 向量意图通过 calibration（TPR≥95%, FPR≤2%）；asset_class_trend TPR=100%（4 例跨资产误路由已修复，同赛道 leader_compare 回归通过）；uplift 报表可查（golden set 正则 100% 覆盖，uplift 结构性≈0，待真实流量复评） |
| **P4** ✅ | 倒转模式：执行器文档按需 retrieve（注册表不变）；语义文章检索 + 统计算法评估预研 | 21/21 注册意图文档可按需加载，11 项 retriever 测试通过；两份可行性评估报告完成（见 §6.5 链接） |

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| 语义通道误命中（把不该 L1 直答的问法路由到 L1） | 语义命中仍需通过 canHandleL1 校验；P2 校准后阈值 zh=0.65（FPR=0% on golden set 反例），正则 100% 覆盖正例，语义仅作兜底 |
| bge-small-zh-v1.5 推理延迟影响 L1 直答 SLA（≤800ms） | 意图向量预计算，查询时只做一次 embed（zh 150~300ms / en 80~150ms）+ 21 次点积（<1ms）；总延迟 100~300ms，在 SLA 内；embedder 子进程常驻避免冷启动 |
| 正例句不足导致意图向量不准 | MIN_POSITIVE_EXAMPLES=5 门控，不足的意图/语言不启用语义通道；从 l1_intent_golden.jsonl 补充 |
| 语义通道与正则通道结果不一致 | 正则优先（实体词匹配更可靠）；不一致时记日志，定期 review |
| 意图向量与 golden set 不同步 | build_intent_vectors.py 纳入定时对账（与 41 的 reconcile 同节奏），examples.jsonl 变更后自动重建 |
| embedder subprocess 桥接开销 | 子进程常驻（socket 模式，对齐 vector_bridge_daemon.py），单条查询 IPC <5ms；构建时批量调用 |
| 云端无法下载 all-MiniLM-L6-v2 | 提前 rsync 模型权重到 `~/.cache/huggingface/hub/`，或 `HF_HUB_OFFLINE=1` 走本地缓存；FAIL-OPEN 退化为仅中文 |
| 中英文语言检测误判 | 中文字符占比阈值 30%，可校准；混合语句优先判 zh（金融场景中文为主） |
| 前缀策略引入噪声（意图匹配不同于 guide chunk） | P0 强制 A/B 验证，有前缀 vs 无前缀在 golden set 上对比 top-1 准确率，择优 |
| 分块前缀策略需验证 | 见上条，A/B 验证后决定是否保留前缀 |
| 反例集构建成本高 | 初始从 golden set 交叉生成（A 意图的正例作为 B 意图的反例）；后续人工补充 |
| 300+ 统计算法覆盖率不均 | 分批纳入，先覆盖高频算法（回撤/季节性/相关性等），低频算法延后 |

---

## 9. 测试计划

沿用工程 pytest 体系（Python 侧）：

| 层级 | 覆盖内容 | 关键用例 |
|------|----------|----------|
| 单元测试 | 语言检测 | 纯中文/纯英文/中英混合/空串/标点 |
| 单元测试 | 向量存储与 cosine | 21 意图双向量加载/点积正确性/top-1 选取/阈值过滤 |
| 单元测试 | 双通道匹配 | 正则命中优先/正则未命中走语义/双通道均未命中返回 None/语义命中 canHandleL1 校验失败 |
| 单元测试 | 阈值过滤 | similarity ≥ 阈值返回 / < 阈值丢弃 |
| 单元测试 | FAIL-OPEN 降级 | embedder subprocess 不可用时退回纯正则/不抛异常 |
| 集成测试 | 与 detect_intent 集成 | golden set 正则命中不受影响/正则漏匹配被语义补回 |
| 集成测试 | calibration 流水线 | 正例 ≥95% / 反例 ≤2% 判定通过/边界阈值 |
| 集成测试 | subprocess 桥接 | embedder 子进程启动/批量 embed/单条 embed/异常返回 [] |
| 端到端 | L1 路由全链路 | 语义命中非确定性意图走 recall 门控/语义命中确定性意图直答/doc_search 交 L2 |

验收基线：全部测试通过率 100%，核心路径（语言检测/匹配/降级）行覆盖率 ≥ 85%。

---

## 10. 可观测性

语义通道指标纳入 41 系统 status() 输出（对齐 SPEC-41 §8.1）：

| 指标 | 来源 | 说明 |
|------|------|------|
| `semantic_match_p95_ms` | intent_matcher 滑动窗口 1000 次 | 语义匹配耗时 P95（含 embed + cosine） |
| `semantic_hit_rate` | 统计日志 | 正则未命中后语义补回的比例（语义命中数 / 正则未命中数） |
| `semantic_false_positive_rate` | calibration 结果 | 语义命中但 canHandleL1 校验失败率 |
| `semantic_regex_disagreement_rate` | 统计日志 | 双通道结果不一致率（仅调试用，生产以正则为准） |
| `embedder_bridge_alive` | 常驻服务 `GET /health`（`ready` / `zh_dim` / `rss_mb` / `pid`） | 常驻向量服务存活与就绪状态；未部署常驻服务时退化为进程内 embedder 探测（`is_inproc_available()`） |
| `lang_zh_ratio` / `lang_en_ratio` | 统计日志 | 中英文 query 占比 |

---

## 11. 参考

- [Modern Web Guidance 源码](https://github.com/GoogleChrome/modern-web-guidance-src)（架构参考：本地 embedding 检索 + 倒转模式 + 可评估 guide + uplift 校准）
- [Modern Web Guidance 架构分析（Joan León）](https://joanleon.dev/en/modern-web-guidance-semantic-retrieval/)（all-MiniLM-L6-v2 + cosine + 分块前缀策略）
- [SPEC-41-文件索引系统-v1.1](./SPEC-41-文件索引系统-v1.1.md)（L0 归属 / L1 doc_search 意图 / ChromaDB 豁免 / 向量层复用决策）
- [l1-intent-registry.ts](../3.1-FRONTEND/src/lib/l1-intent-registry.ts)（现有意图注册表 + 正则兜底，21 意图 SSoT）
- [l1_route_signal.py](../3.1-FRONTEND/scripts/l1_route_signal.py)（L1 路由链路 + detect_intent + DETERMINISTIC_INTENTS）
- [l1_intent_golden.jsonl](../34-前端应用训练系统/l1_intent_golden.jsonl)（377 条意图 golden set，正例句来源）
- [vector_bridge.py](./scripts/vector_bridge.py) / [vector_bridge_daemon.py](./scripts/vector_bridge_daemon.py)（subprocess/socket 桥接模式参考）
- [9-RAG-INFRA vector_store/config.py](../2-KNOWLEDGE/9-RAG-INFRA/vector_store/config.py)（bge-small-zh-v1.5 模型配置）
- [embedder.py](../2-KNOWLEDGE/9-RAG-INFRA/vector_store/embedder.py)（懒加载 + TF-IDF FAIL-OPEN 回退参考）
- [SPEC-54-L1架构能力聚合层](../54-L1架构能力聚合层/SPEC-54-L1架构能力聚合层.md)（L1 六类能力面 + 确定性意图门禁口径 + 300+ 统计算法注册）
