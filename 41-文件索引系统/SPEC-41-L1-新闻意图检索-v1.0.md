# SPEC-41-L1-新闻意图检索 v1.0

**状态**：**P0–P5 全部完成并云端验收**（P0 探针→P0′ bge-base→P1 意图与正则→P2 `news_digest.json`→P3 `exec_news_search`→P4 embedder 健康断言→P5 云端全量门禁）；性能风险已根治（§8.8 常驻向量服务），逐项证据见 §13
**日期**：2026-11-15
**归属域**：41-文件索引系统（L1 语义意图检索）／39-金融语义蒸馏系统（数据产物）／3.1-FRONTEND（注册表 + 执行器）／34-前端应用训练系统（golden 门禁）
**关联**：[SPEC-41-L1语义意图检索增强-v1.0](./SPEC-41-L1语义意图检索增强-v1.0.md)
**决策来源**：用户 2026-11-15 确认（认知库 `VM-1794722072605-d5319c70`，B 级，confidence 0.70）

---

## 1. 背景与问题

### 1.1 现状：新闻检索在 L1 是空白

实测 10 条新闻类 query 的 `detect_intent` 结果：

| 查询 | 当前路由 |
|---|---|
| 最近有什么新闻 | `unknown` |
| 最新的监管新闻 | `event_line_query`（错） |
| 今天有哪些利好新闻 | `unknown` |
| 以太坊相关的新闻 | `unknown` |
| 地缘政治新闻 | `unknown` |
| 新闻里最重要的三条 | `unknown` |
| 通胀主题的新闻 | `data_query`（错） |
| 帮我找几条高影响的新闻 | `unknown` |
| 24小时新闻情绪怎么样 | `unknown` |
| 新闻监控 | `unknown` |

10 条中 8 条 `unknown`、2 条误判。

结构原因：

1. `event_listing` 只存在于前端 [l1-intent-registry.ts](../3.1-FRONTEND/src/lib/l1-intent-registry.ts)，Python 侧 `_FALLBACK_PATTERNS` 无该条目 → 前后端不一致；
2. `event_listing` 不在 `l1_route_signal.EXECUTORS` 中 → 即使前端预测出来，也走 `_unknown_result(..., "l1_no_executor")` 推给 L2；
3. `intent_units/event_listing/` 的 `examples_zh.jsonl` 为 0 字节、无 `vector.json` → 语义层不可达（21 个意图单元中 4 个如此：`event_listing`、`leader_compare`、`persistence_strength`、`top_correlation`）。

### 1.2 标签可得，但检索不可直接用榜单

`hot_news.json`（前端新闻 tab 的数据源）是**影响力榜**，不是检索库：

| 实测项 | 数值 | 后果 |
|---|---|---|
| topic=`other` | 676 / 853 = **79.2%** | 按主题过滤会漏八成 |
| event_type=`macro_other` | 626 / 853 = **73.4%** | 同上 |
| top50 内 topic=`other` | 31 / 50 = 62% | 榜单本身大半未分类 |
| top50 情绪 | 利好 34 / 利空 16 / **中性 0** | 检索不到中性新闻 |
| top50 importance | 71.0 – 96.1 | 无中低影响档 |
| 榜单项数 / 窗口 | 50 / 24h | 无历史纵深 |
| 以太坊 标题命中 | **0 / 50** | "以太坊的新闻"必然空 |
| 加密 / 原油 标题命中 | **0 / 50** / **0 / 50** | 同上 |

而近 24h **全量事件**里内容是存在的：以太坊 1、比特币 14、加密 5、美联储 33。

→ **结论：检索必须跑全量事件集，不能跑 top50 榜单；榜单只服务展示。**

### 1.3 symbols 不可信，必须走标题文本匹配

实测反例（`semantic_events.jsonl`）：

```json
{"raw": "以太坊跌破1800美元，日内跌7.73%", "timestamp": "2026-11-14T20:54:46Z",
 "symbol": "BTC", "sentiment": {"score": -0.9943}}
```

以太坊新闻被标注为 `symbol=BTC`。因此**放弃 symbols 作为检索键**，改用标题文本匹配（用户决策 ③）。

### 1.4 两套标签的真实关系

- 前端新闻 tab 的标签**就是** 39 产出的：`fundamental_snapshot.py` 直接读 `39-金融语义蒸馏系统/hot_news.json`（支持 `HOT_NEWS_PATH`）。
- 真正的第二套是 **newsflash `od_event_type` 7 类**，仅 `exec_event_listing` 使用，口径与情绪算法（关键词计数）均为旧版。
- 因此 canonical 取向为：**39 的 11 topic / 13 event_type 唯一 canonical；`od_event_type` 降级为 legacy 粗分组**。

---

## 2. 目标 / 非目标

### 2.1 目标

| # | 目标 | 判据 |
|---|---|---|
| G1 | 新闻检索意图在 L1 可用 | 附录 A 的 B 组 8/8 路由到 `event_listing` |
| G2 | 按 39 现有标签输出 | 支持 topic / sentiment / importance_min / 时间窗 / 标题关键词 五槽位 |
| G3 | 窗口默认 7 天、可扩 30 天 | 无强调词 → 168h；用户强调更早 → 720h；"最新/今天" → 24h 榜单 |
| G4 | 语义通道首次真实参与 | 附录 A 的 A 组 ≥10/12 由**纯语义**命中 |
| G5 | 无数据必须如实 | 0 命中时输出覆盖数，禁止编造条目 |

### 2.2 非目标

- 不做正文全文检索（`bodies` 不入库，见 §5.3）
- 不做跨天语义相似检索（向量化新闻正文不在本期）
- 不改前端新闻 tab 的 UI 与标签口径
- 不改动 24h 榜单的排序逻辑
- 不删除 `exec_event_listing`（仅标 legacy）

---

## 3. 标签契约

### 3.1 canonical（唯一事实源，来自 39）

`topic`（11）：`rates_policy` / `inflation` / `labor` / `growth` / `crypto_reg` / `geopolitics` / `earnings` / `capital_action` / `tech_ai` / `commodities` / `other`

`event_type`（13）：`rate_decision` / `fomc` / `cpi` / `nfp` / `earnings` / `guidance` / `regulatory` / `legal` / `mna` / `buyback` / `dividend` / `product` / `macro_other`

`sentiment.label`：`利好` / `利空` / `中性` / `未知`

`importance`：0–100，≥70 高影响、≥50 警示；分项 type 0.30 / sentiment 0.25 / recency 0.20 / source 0.15 / corroboration 0.10

### 3.2 legacy（仅降级输出，永不反向）

`od_event_type`（7）← 11 topic 单向映射：

| od_event_type | ← topic |
|---|---|
| `monetary_policy` | `rates_policy` |
| `crypto_regulation` | `crypto_reg` |
| `us_data` | `inflation` / `labor` / `growth` |
| `us_policy` | `capital_action` |
| `geopolitics` | `geopolitics` |
| `market` | `commodities` / `tech_ai` |
| `project` | `tech_ai` / `capital_action` |

反向不可行（`us_data` 分不出 CPI 与非农）→ **禁止 7→11 反推**。

---

## 4. 意图划界规则：罗列（listing）vs 演变（line）

### 4.1 定义

- **event_listing（罗列）**：目的是"取回一组新闻条目"。输出是列表，每条独立。
- **event_line_query（演变）**：目的是"跟踪同一主题的多次事件如何发展"。输出是一条线（起止时间、跨度、频次/情绪变化）。

### 4.2 判定信号

| 信号 | event_listing | event_line_query |
|---|---|---|
| 时间演化谓词 | 无 | 有：演变 / 后续 / 进展 / 动态 / 动向 / 变化 / 趋势 / 局势 / 发酵 / 升级 / 走向 |
| 选条信号 | 有：数量词（几条/三条/有哪些/有没有/列出）、主题名词（新闻/消息/快讯/热点/动静）、时间范围（最近/今天/这两天/上周） | 不需要 |
| 解读谓词 | 无（有则归 event_analysis） | 无 |
| 对象 | 单条事件 / 关键词 | 主题 / 政策 / 局势 / 事件族 |

### 4.3 决策顺序（高 → 低，先命中先返回）

```
1. 确定性单维数据意图（metric_series / whale_flow / calendar_event / technical_indicator / stat_query）
   —— 有执行器且无歧义，优先
2. doc_search —— 显式文档对象（文档/SPEC/手册/wiki）
3. event_line_query —— 存在时间演化谓词 且 对象为主题/事件族
4. event_listing —— 存在选条信号 且 无解读谓词
5. event_analysis —— 存在解读谓词（意味着/影响/为什么/怎么解读）
6. 其余语义意图链
```

### 4.4 冲突裁决表（必须落进 golden）

| 查询 | 现状 | 目标 | 理由 |
|---|---|---|---|
| 最近市场在交易什么消息 | `event_line_query` | **`event_listing`** | "交易什么消息"是取条目，无演化谓词 |
| 最新的监管新闻 | `event_line_query` | **`event_listing`** | "最新"是时间范围，非演化 |
| 通胀主题的新闻 | `data_query` | **`event_listing`** | "主题的新闻"是选条，非数值查询 |
| 最近都出了些什么事 | `event_line_query` | 保留 `event_line_query` | "出了些什么事"含变化语义，容忍不定 |
| 美联储加息这件事后续怎么演变 | `event_line_query` | 保持 | 明确演化谓词 |
| 巨鲸动向最近的变化 | `whale_flow` | 保持 | 确定性意图优先（§4.3-1） |
| 这个事件后面会怎么发酵 | `event_analysis` | 保持 | 解读谓词优先于演化词表缺失 |

> §4.4 前三行是**行为变更**，必须在 golden 中显式标注 `variant=news_v1`，并在实施时单独核验不引发其他意图回退。

---

## 5. 意图与槽位设计

### 5.1 意图升级（方案 A）

在 `l1_route_signal.py`：

1. `_FALLBACK_PATTERNS` 新增 `event_listing`，与 TS 注册表对齐并补足选条信号；
2. `EXECUTORS` 注册 `event_listing → exec_news_search`；
3. `DETERMINISTIC_INTENTS` **不加入** `event_listing`（它需要检索，不是确定性单维输出）。

### 5.2 槽位（纯规则抽取，零 token）

| 槽位 | 取值 | 抽取方式 |
|---|---|---|
| `topic` | 11 topic 之一 | 复用 39 `TOPIC_RULES` 关键词（与打标同一词表 → 映射零误差） |
| `sentiment` | `利好` / `利空` / `中性` / `all` | 词表：利好/利空/看多/看空/负面/正面 |
| `importance_min` | 0 / 50 / 70 | 词表：重要/关键/高影响 → 70；一般 → 0 |
| `window_h` | 24 / 168 / 720 | 见 §5.4 |
| `keyword` | 实体或标题词 | `entity_aliases.json`（39 `query_entity` 同源）展开 + 原词 |
| `limit` | 默认 5，上限 10 | 数量词解析 |

### 5.3 数据边界

- **只读标题**（`raw` / `title`），不读正文 `bodies.jsonl`；
- **不在运行时解析 `semantic_events.jsonl`**（11.4MB；SPEC §5.2 明令禁止在快照/问答链路解析）；
- 运行时只读两个小产物：`hot_news.json`（40KB）/ `news_digest.json`（目标 ≤4MB）。

### 5.4 窗口三级（用户决策 ①）

| 触发 | window_h | 数据源 |
|---|---|---|
| 含"最新/今天/刚刚/24小时/现在" | 24 | `hot_news.json`（榜单，带 5 维 importance 与 clusters） |
| 默认（无时间强调） | **168（7 天）** | `news_digest.json` |
| 含"上周/更早/之前/历史/这个月/30天" | **720（30 天，上限）** | `news_digest.json` |

- 720h 为**上限**，不默认开启；找不到 30 天强调词时一律 168h。
- 答案中必须回显实际生效窗口（`window_h`）。

---

## 6. 数据产物：`news_digest.json`（39 侧）

### 6.1 为什么不能直接用 `hot_news.json`

榜单是 top50 + 24h + importance 排序，天然挤出加密类内容（§1.2）。检索需要全量 + 30 天。

### 6.2 生成方式（复用，不重写）

`gen_semantic_events.py` 的 `build_hot_news(rows, window_h, cluster_window_h, top_n)` 已是**纯函数**，`window_h` / `top_n` 已参数化但硬编码为 24 / 50。本期新增独立脚本（不改原函数签名）：

**`39-金融语义蒸馏系统/scripts/gen_news_digest.py`**

- 输入：`semantic_events.jsonl` 中 `source=="events.jsonl"` 且 `event` 非空的行（30 天约 6,500 行）
- 参数：`--window-days`（默认 30，上限 30）、`--out`（默认 `news_digest.json`）
- 逻辑：按 `normalize_title` 去重（保留最早 + `dup_count`）→ 计算 importance → 输出
- 幂等：覆盖写 + 临时文件原子 rename
- 调度：由 39 现有日更链路在 `gen_semantic_events` 之后追加一次

### 6.3 schema

```json
{
  "schema": "news_digest/v1",
  "generated_at": "2026-11-15T13:22:00",
  "window_days": 30,
  "max_window_days": 30,
  "model": "finbert-tone-chinese",
  "degraded": false,
  "coverage": {"2026-11-14": 1035, "2026-11-15": 210, "2026-11-09": 19},
  "topic_dist": {"other": 4058, "geopolitics": 210},
  "stats": {"total": 6500, "dedup_saved": 320, "high_impact": 410},
  "items": [
    {
      "id": "sha1(title+ts)[:16]",
      "ts": "2026-11-14T20:54:46Z",
      "title": "以太坊跌破1800美元，日内跌7.73%",
      "topic": "crypto_reg",
      "event_type": "macro_other",
      "sentiment": {"label": "利空", "score": -0.9943},
      "importance": 86.4,
      "origin": "jin10",
      "source_count": 2,
      "dup_count": 1
    }
  ]
}
```

约束：`items` ≤ 8,000；单条 `title` ≤ 200 字符；文件 ≤ 4MB；**不含正文**；`coverage` 必须覆盖窗口内每一天（缺失日补 0）。

### 6.4 已知数据缺陷（必须透出，不得掩盖）

实测 `semantic_events.jsonl` 日覆盖极不均匀：

```
2026-11-14: 1035    2026-11-15: 210（截断）
2026-11-09: 19      2026-11-10: 9      其余多日 < 50
```

→ 30 天窗口下"上周的新闻"可能近乎空。执行器必须在 0 命中或低命中时输出 `coverage`，说明"该日采集异常"，而不是回答"没有相关新闻"。

---

## 7. 执行器设计：`exec_news_search`

位置：`3.1-FRONTEND/scripts/data_query_executor.py`，注册进 `l1_route_signal.EXECUTORS["event_listing"]`。

### 7.1 流程

```
slots 解析（§5.2）
  → 选数据源（§5.4）
  → 标题文本匹配：对 items[].title 做大小写无关子串匹配（keyword 及其别名）
  → 标签过滤：topic（仅当解析出的 topic != other）/ sentiment / importance_min
  → 排序：importance DESC, ts DESC
  → 截断 limit
  → 组装答案（含 window_h / 命中数 / 总条数 / coverage / 未分类占比）
```

### 7.2 输出契约

```json
{
  "intent": "event_listing",
  "handled": true,
  "degraded": false,
  "window_h": 168,
  "source": "news_digest",
  "matched": 3,
  "scanned": 6500,
  "coverage_note": "11-09 仅 19 条（采集异常）",
  "unclassified_ratio": 0.79,
  "items": [{"ts": "...", "title": "...", "topic": "...", "sentiment": "利空", "importance": 86.4}]
}
```

### 7.3 硬约束

1. **0 命中禁止编造**：返回 `matched=0` + `coverage_note` + `unclassified_ratio`，答案文本为"近 N 天未检索到与『X』相关的新闻（当期共 M 条，其中未分类 Z%）"。
2. **topic=`other` 不过滤**：解析出 `other` 或未解析出 topic 时，按无 topic 过滤执行，并回显 `topic_filter=none`。
3. **FAIL-OPEN**：产物缺失/解析失败 → `degraded=true` + 空列表，不抛异常、不阻断主链路。
4. **零 token**：全程规则 + 文件读取。
5. **`exec_event_listing` 标 legacy**：保留可调用，标注 `legacy=true`，不参与 `event_listing` 主链路；其输出若被复用，必须转换为 canonical topic（§3.2）。

---

## 8. 语义通道首次激活（本轮的关键设计）

### 8.1 问题

当前 golden 377 条中**没有一条"仅语义可达"的正例**：正则未命中的 40 条全是 `unknown` 负例，语义 top1 上界 0.6462 < 0.65。因此 `golden` 对 embedder 退化零判别力（实测 `L1_SEMANTIC_MATCH=0` 与 `=1` 逐条差异 = 0，两种模式均 378 passed）。

### 8.2 本期做法（用户决策）

附录 A 的 **A 组 12 条措辞故意保持正则不可覆盖**，仅靠语义通道命中。这将是语义通道第一次真实参与 L1 路由。

### 8.3 必须先解决阈值（硬前置）

- 现阈值：`SEMANTIC_THRESHOLD_ZH = 0.65`，距现有负例上界 0.6462 仅 **0.0038** 余量。
- A 组措辞无强关键词，向量分数分布与现有正例（中位数 0.7392）不同，**很可能被 0.65 直接拒掉**，表现为"意图加了但从不触发"（新的假绿）。
- 因此实施顺序强制为：

```
加 30 条探针 → 用 golden 测量 A/B/C/D 四组分数分布
  → 若 A 组召回 < 10/12 或负例放行 > 0：重扫阈值（含分意图阈值）
  → 记录新的 正例下界 / 负例上界 / 余量，写入本 SPEC 附录
  → 才允许进入执行器联调
```

- 允许的分意图阈值：若全局阈值无法同时满足 A 组召回与负例 0 放行，允许对 `event_listing` 单独设阈值，但**必须在 SPEC 中登记数值与实测余量**，禁止隐式硬编码。

### 8.4 P0 实测结果（2026-11-15）：**未通过**

已执行：30 条探针入库（golden 377 → 407）→ 重建 `intent_units/event_listing`（20 正例）→ 构建 `vector.json`（512 维）→ 全量阈值扫描。

**（1）质心匹配下，A 组 0/12**——不是阈值问题，是 `event_listing` 质心与 A 组措辞近乎正交：

| 查询 | event_listing 相似度 | 竞争意图（top1） |
|---|---|---|
| 帮我盯一下这两天有没有什么值得注意的事 | **-0.031** | data_query 0.621 |
| 币圈今天闹什么了 | 0.032 | event_line_query 0.644 |
| 有没有关于美联储的新东西 | 0.018 | data_query 0.612 |
| 市场最近都在聊什么 | **-0.056** | event_line_query 0.626 |
| 有什么我该知道的事 | -0.027 | event_analysis 0.488 |

阈值扫描（质心）：

| 阈值 | A 组命中 | 负例放行 | 全域语义准确 |
|---|---|---|---|
| 0.55 | 0/12 | 17 | 0.804 |
| 0.60 | 0/12 | 9 | 0.838 |
| 0.62 | 0/12 | 5 | 0.876 |
| 0.65（现值） | **0/12** | **0** | 0.915 |
| 0.70 | 0/12 | 0 | 0.937 |

→ 负例上界仍为 0.6462，**任何阈值都无法让 A 组命中**。

**（2）根因**：`event_listing` 的 20 正例是**双峰分布**（8 条含"新闻/快讯/消息"的正式措辞 + 12 条无共同词汇的口语措辞），bge-small-zh 下两组嵌入近正交，取均值后质心塌缩到原点附近（模长极小），与两类查询的余弦都趋近 0。

**（3）max-pooling 实验（未改代码，仅离线验证）**：改为"逐例句取最大相似度"后：

- A 组 12/12 = 1.000（**自匹配泄漏**，因 A 组本身就是例句，不可作为判据）
- 留出改写 6/6 正确：`有点什么新鲜事` 0.663、`今天有什么动静` 0.710、`最近有啥值得一看的` 0.701、`这两天出什么事了吗` 0.865、`消息面有啥变化` 0.807、`最近市场在聊啥` 0.961
- **但负例上界从 0.6462 升到 0.834**（`price_query`），`event_listing` 自身也出现 0.741 的负例命中

→ 要挡住 0.834 的负例，阈值需 ≥0.87，留出改写只剩 1/6 通过。**max-pooling 同样不具备分离性。**

**（4）结论**：在 bge-small-zh-v1.5 + 单一质心/最大相似度两种匹配下，"无共同词汇的口语措辞纯语义命中 event_listing"**不可实现**。P0 门禁判定 FAIL，按 §11 **不得进入 P1**。

**（5）待决策的四个选项**（未获授权前不实施）：

| 选项 | 内容 | 代价 | 对盲区的影响 |
|---|---|---|---|
| A′ | A 组改用正则覆盖（保留功能交付），彻底放弃本轮"纯语义"目标 | 最小 | 盲区保留 |
| B′ | 换更强中文向量（bge-base/large-zh、bge-m3）重跑同一实验 | 需下载 400MB–2GB，需重测全部 21 意图 | 可能真正修复盲区 |
| C′ | 查询侧加 BGE 检索指令前缀重测（此前 A/B 测试结论是基于旧样本集） | 中等，改动 `embedder_bridge` | 未知 |
| D′ | 两段式：先用轻规则判"信息类问句"，再语义消歧 | 中等 | 部分修复（语义参与但非唯一判据） |

**（6）当前仓库状态**：golden 407 条中 **21 条红**（20 条 `event_listing` 正例 + 1 条 accuracy gate，`event_listing 0/20`），为 P0 预期的 TDD RED 状态；P1 未启动前 CI 会保持红。

### 8.5 P0-b 补充实验（2026-11-15）：换向量模型可行，根的方案是 **bge-base**

**（1）34 域已有的 Transformer 意图模型（检查结果）：不可用**

`34-前端应用训练系统/models/e3_baseline_intent` 是真实的 `BertForSequenceClassification`（768 hidden，48 标签，409MB safetensors），训练于 `corpus/intent_pairs.jsonl`，报告 test_acc 0.957。但实测：

| 查询 | 该模型 top1 | 概率 |
|---|---|---|
| 帮我盯一下这两天有没有什么值得注意的事 | data_query | 0.073 |
| 有啥新动静吗 | data_query | 0.073 |
| 最新的监管新闻 | data_query（`event_listing` 仅第 2，0.051） | 0.093 |
| 以太坊的RSI是多少 | data_query（应为 technical_indicator） | 0.105 |

48 标签下均匀分布为 0.021，实测 top1 概率 0.04–0.11，`event_listing` **从未 top1**。原因是训练集极度失衡（`news_event` 2512 / 2998，`event_listing` 仅 6 条），0.957 的准确率由多数类撑起。**结论：该 checkpoint 不能用于新闻意图判定，也不建议在 48 类上微调。**

**（2）换 `bge-base-zh-v1.5` 后（同一质心匹配，仅换模型）：**

| 口径 | bge-small（现状） | **bge-base** |
|---|---|---|
| A 组 12 条 top1 = event_listing | **0/12** | **12/12** |
| A 组 EL 相似度区间 | -0.056 ~ 0.032 | **0.615 ~ 0.834** |
| 留出改写（6 条未入 golden） | 0/6 | **6/6**（0.673–0.768） |
| 负例全意图上界 | 0.6462 | **0.692** |

阈值扫描（bge-base）：

| 阈值 | A 组命中 | 负例放行 |
|---|---|---|
| 0.65 | 11/12 | 1 |
| 0.67 | 10/12 | 1 |
| **0.70** | **9/12** | **0** |
| 0.73 | 8/12 | 0 |

→ **模型能力是瓶颈，不是阈值**。换 bge-base 后 A 组从 0/12 变为 9–12/12，但余量仍薄（0.70 vs 负例 0.692，仅 0.008），须配合分意图阈值与全量重扫。

**（3）云端资源评估（实测 43.160.201.117）：**

| 项 | 值 | 结论 |
|---|---|---|
| 内存 | 15Gi 总 / 5.0Gi 已用 / **10Gi 可用** | 放得下 |
| CPU | 4 核，**无 GPU** | 单条 encode 预计 50–150ms，可接受 |
| 磁盘 | 92G 可用 | 充裕 |
| 现有 | 无 ollama / 无本地 LLM | 需新增 |

**（4）选型结论**：用 **bge-base-zh-v1.5（400MB，约 0.8GB 常驻）**，不用生成式小 LLM。理由：本任务是"短句 → 意图/检索查询"，embedding + 质心即可，0.5B 生成式模型会引入 0.4GB+ 常驻、200–600ms CPU 延迟与新的运行时依赖，收益不成比例。

**（5）实施代价（必须登记）**：换模型 = 全部 21 个意图向量维度 512 → 768，**必须全量重建**，且现有 0.65 阈值是 bge-small 上调出来的，需在全 407 条上重扫并重新登记余量。这是本期新增的 P0′ 前置任务。

### 8.6 P0′ 执行结果（2026-11-15）：换模型完成，golden 红项 21 → 3

**已实施（3 处代码改动）**

| 文件 | 改动 |
|---|---|
| `41-文件索引系统/core/embedder_bridge.py` | 主模型改为 `BAAI/bge-base-zh-v1.5`，支持 `L1_ZH_MODEL` 覆盖（本地路径/HF id）；加载失败回退 `bge-small-zh-v1.5`；补充 `import os` |
| `41-文件索引系统/core/intent_matcher.py` | `SEMANTIC_THRESHOLD_ZH` 0.65 → **0.66**（含校准依据注释） |
| `41-文件索引系统/core/intent_vector_store.py` | 新增**维度守卫**：`len(vec) != len(query_vector)` 时跳过，避免 512/768 维混合后 zip 截断静默算出无意义余弦 |

**已重建**：17 个中文意图向量全部 768 维（4 个无例句意图仍为空：`leader_compare` / `persistence_strength` / `top_correlation` 等）。

**阈值重扫（407 条，bge-base）**

| 阈值 | A 组命中 | 负例放行 | 正例语义 top1 |
|---|---|---|---|
| 0.60 | 12/12 | 6 | 325/354 |
| 0.64 | 11/12 | 2 | 306/330 |
| 0.66（**选定**） | **11/12** | **1**（误标项） | 282/304 |
| 0.70 | 9/12 | 0 | 234/250 |

**反例真实上界 0.646**（`帮我总结一下这篇文章` → doc_search）。唯一越过 0.66 的是 `今天新闻` 0.692 → `event_listing`，该条被 golden 标为 `unknown`，实为**误标**；且长度为 4 < 语义通道最小长度 5，生产中不会进入语义通道，故不影响 FPR。余量 **0.646 → 0.66 = 0.014**（旧模型 0.0038 且 A 组 0/12）。

**golden 实测：408 项中 3 红**（P0 时为 21 红）：

| 红项 | 原因 | 归属 |
|---|---|---|
| 有什么我该知道的事 | 语义 0.615 < 0.66，A 组唯一漏网 | P1 决定是否补例句/降分意图阈值 |
| 通胀主题的新闻 | 正则 `data_query` 先命中 | **P1**（`event_listing` 需置于 `data_query` 之前） |
| 24小时新闻情绪怎么样 | 正则先命中其他意图 | **P1**（同上） |

**部署前置（关键风险）**：云端若仍只有 bge-small（512 维），新向量（768 维）会被维度守卫全部跳过 → 语义通道静默降级为纯正则（FAIL-OPEN，不报错）。因此**云端必须先装 `bge-base-zh-v1.5` 并预热缓存，再同步新向量**，且用 `is_inproc_available()` + 一次余弦冒烟（≥0.6）确认，不可只看服务是否起来。

**待确认的数据问题**：golden 中 `今天新闻` 标为 `unknown` 属误标，建议改为 `event_listing`（改后反例上界仍为 0.646，不影响阈值）；未获授权前未改动。

### 8.7 P1 + 云端部署结果（2026-11-15）

**P1 已上线（commit `2c38d0f8ce`）**

| 项 | 结果 |
|---|---|
| `今天新闻` 误标修正 | golden 改为 `event_listing` / `terse`（验证：反例上界仍 0.646，阈值不动） |
| `event_listing` 正则前移 | 置于 `contradiction_insight` / `data_query` 之前，收掉最后 2 条正则红项 |
| 正则防误伤 | 加 `^(?!.*(新闻数|新闻条数|消息数|新闻量|统计|走势|趋势))` 负向断言 + 移除"快讯"，避免抢走 `data_query` / `metric_series` 既有用例 |
| golden | **408/408 全绿** |
| 语义关断对照 | `L1_SEMANTIC_MATCH=0` → **8 项红**（7 条语义依赖用例 + accuracy gate），证明门禁首次具备判别力 |

**云端部署（代码 `31d5db1b94`）**

| 检查项 | 实测 |
|---|---|
| 模型文件 | `~/.cache/huggingface/hub/models--BAAI--bge-base-zh-v1.5`，`pytorch_model.bin` 409,138,989 B，sha256 与本地完全一致；补齐了缺失的 `tokenizer.json`（439,124 B） |
| 加载 | `HF_HUB_OFFLINE=1` + `HOME=/home/luke` 下 `is_inproc_available()=True`，embed 向量 **768 维**、L2 norm 1.0 |
| 向量 | 17 个中文意图向量均为 768 维（4 个无例句意图为空），与查询维度一致，维度守卫不触发 |
| 意图命中 | `有啥新动静吗` / `最近市场都在聊什么` / `这两天有什么值得关注的` / `币圈最近有啥大事` → `event_listing`（0.670–0.842）；负例 `帮我总结一下这篇文章` 0.646 被 0.66 挡住 |
| 服务重启 | `dreambuddy-worker-launcher`（常驻进程，模块级持有旧代码与旧 512 维 embedder）15:03:05 重启；`dreambuddy-frontend` 15:16:43 重启（`next build` 后） |
| 生产 API | `POST /api/data/query`：`有啥新动静吗`→`event_listing` 12.8s、`今天新闻`→`event_listing` 2.8s、`BTC现在什么价格`→`price_query` 4.0s、`帮我总结一下这篇文章`→`unknown` 11.5s，全部 HTTP 200 |

**新增硬约束：前端脚本超时必须 ≥30s**

SentenceTransformer 冷启动是**既有的 10–12s 成本，与模型大小关系不大**（同机实测：bge-base 10.15s / bge-small 12.60s），因为前端 API 是**每次请求 spawn 一个新 python 进程**。原 `SCRIPT_TIMEOUT_MS=15000` 余量不足，语义类问法会被 kill 并**静默返回空 `data`**（`success=true` 但无内容，最难排查的失败形态）。已改为 **30000**（`3.1-FRONTEND/src/app/api/data/query/route.ts`，commit `31d5db1b94`），改后上述语义问法全部可用。

**遗留风险**

1. ~~**内存**：每请求常驻约 900MB RSS，并发放大~~ → **已解决（§8.8 常驻向量服务，压测 +312MB）**
2. ~~**延迟**：语义类问法端到端 11–13s~~ → **已解决（§8.8，端到端 2.1–2.8s）**
3. **部署顺序**：必须先装模型再同步 768 维向量；反序会让维度守卫跳过全部向量而静默降级。
4. **新单点**：常驻服务是新的关键依赖。云端两个调用方已置 `L1_EMBED_LOCAL_FALLBACK=0`，
   服务挂掉时语义通道降级为纯正则（不报错、不 OOM），需纳入健康检查巡检。

### 8.8 常驻向量服务（根治冷启动与并发内存放大，2026-11-15）

**问题**：前端 `/api/data/query` 每次请求 spawn 新 python 进程，SentenceTransformer 冷启动
10–12s、RSS ~900MB；并发 N 个语义请求 = N×900MB。

**方案**：`41-文件索引系统/scripts/embed_server.py`（stdlib HTTP，仅监听 127.0.0.1:8099）

| 设计点 | 实现 |
|---|---|
| 模型只加载一次 | 进程内按语言缓存 embedder，启动后台线程预热 |
| 接口 | `POST /embed {"texts":[..],"lang":"zh"}` → `{"vectors":[[..]]}`；`GET /health` → ready/dim/rss/pid |
| 客户端优先级 | 常驻服务 → in-process → subprocess（`embedder_bridge.embed_batch`） |
| 内存兜底 | systemd `MemoryMax=2G`，超限由 systemd 重启而非拖垮整机 |
| 故障策略 | 服务不可用 + `L1_EMBED_LOCAL_FALLBACK=0` → 返回空向量，调用方 FAIL-OPEN 到纯正则 |
| 部署 | `41-文件索引系统/deploy/dreambuddy-embedder.service`（User=luke、HF_HUB_OFFLINE=1） |

**本地实测**

| 项 | 结果 |
|---|---|
| golden 全量 | 408 条 **6.3s** 跑完（此前每个用例各自加载模型，分钟级） |
| 单测 | `test_embed_server.py` 4 项 + `test_intent_matching.py` 18 项全绿 |

**云端实测（`b3fb473939`）**

| 项 | 结果 |
|---|---|
| 服务 | `dreambuddy-embedder` active/enabled，`/health` ready=true、zh_dim=768、RSS 883.9MB |
| 单请求延迟 | `有啥新动静吗` **12.76s → 2.75s**；`帮我总结一下这篇文章` **11.49s → 2.76s**；`今天新闻` 2.11s；`BTC现在什么价格` 4.15s |
| 10 并发压测 | 10/10 HTTP 200（14.7–21.0s，4 核串行编码），系统内存 5413MB → **5725MB（+312MB）**，embedder MemoryCurrent 661MB |
| 配置下发 | `dreambuddy-frontend` / `dreambuddy-worker-launcher` drop-in `L1_EMBED_LOCAL_FALLBACK=0` 已生效 |

**注**：`SCRIPT_TIMEOUT_MS=30000` 保留——常驻服务是优化，不是契约；服务重启窗口内仍需兜底余量。

---

## 9. 测试与验收门禁

| # | 门禁 | 内容 | 阈值 |
|---|---|---|---|
| T1 | 34 golden 全量 | 377 + 30 = 407 条精确匹配 | 407/407 |
| T2 | 冲突项核验 | §4.4 前三行改判生效，且其他意图无回退 | 其余 377 条差异 = 0 |
| T3 | 41 `test_intent_matching` | `event_listing` 纯语义 top1 命中 | A 组 ≥10/12 |
| T4 | 3.1 注册表测试 | `event_listing` 前后端模式一致 | 通过 |
| T5 | 执行器单测 | 0 命中编造 / topic=other 不过滤 / FAIL-OPEN / 窗口三级 | 全绿 |
| T6 | embedder 健康断言 | 34 域新增 `is_inproc_available()` + 余弦下限 | 通过 |
| T7 | 无匹配话术 | `以太坊相关的新闻` 返回条目或显式空 + coverage | 不可编造 |

**验收组合**：T1–T7 全绿 + 手动验证 3 条 query（最新/默认/30 天）答案中的 `window_h` 与 `coverage_note` 正确。

---

## 10. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| topic=other 79% → 过滤后空 | 用户体验 | `other` 不参与过滤 + 回显未分类占比 |
| 日覆盖空洞（11-09 仅 19 条） | 30 天窗口失真 | `coverage` 透出 + 低命中话术 |
| 意图划界改动引发回退 | 现有 377 条 | T2 强制"其余差异 = 0" |
| 语义阈值误拒新正例 | 假绿 | §8.3 强制前置阈值重扫 |
| 深度产物过大 | 运行时慢 | items ≤8000 / ≤4MB，超出按 importance 截断并标注 |
| 标签双轨混用 | 口径不一致 | `od_event_type` 仅降级输出，禁止反向 |

**回滚开关**：
- `NEWS_INTENT_ENABLED=0` → `event_listing` 退回 `l1_no_executor`（原行为）
- `L1_SEMANTIC_MATCH=0` → 关闭语义通道（A 组将全部 `unknown`，可用作对照）
- golden 新增 30 条统一 `variant=news_v1`，可整组移除

---

## 11. 实施顺序

| 批次 | 内容 | 产出 |
|---|---|---|
| P0 | 30 条探针入库 + 阈值重扫 | 附录 A 定稿 + 阈值数值登记 |
| P1 | 意图与槽位（TS + Python 对齐） | B 组 8/8、C 组无回退 |
| P2 | `gen_news_digest.py` | `news_digest.json` + coverage |
| P3 | `exec_news_search` + 窗口三级 + legacy 标记 | T5/T7 |
| P4 | embedder 健康断言（34 域） | T6 |
| P5 | 云端部署与端到端验收 | 云端 41/34 域全绿 + 3 条手动 query |

> P0 未通过（A 组召回不足或负例放行 > 0）则**不得进入 P1**。

---

## 12. 实施进度与剩余项（2026-11-15 对齐核对）

> 核对口径：以**仓库实际代码/产物**为准，不以文档自述为准。P2/P3/P4 逐项查文件与注册表。

| 阶段 | 内容 | 代码现状（证据） | 状态 |
|---|---|---|---|
| P0 | 30 条探针入库 + 阈值重扫 | 探针已入 golden（`variant=news_v1`），阈值数值见 §8.6 | ✅ 完成 |
| P0′ | 换 `bge-base-zh-v1.5` | `core/embedder_bridge.py` 主模型 bge-base；17 个意图向量 768 维；云端权重 sha256 与本地一致（§8.6/§8.7） | ✅ 完成 |
| P1 | 意图与正则前移 | `l1_route_signal.py:236-246` 的 `event_listing` 正则位于 `contradiction_insight`/`data_query` 之前；golden **408/408**（§8.7） | ✅ 完成 |
| P2 | `gen_news_digest.py` | `39-金融语义蒸馏系统/scripts/gen_news_digest.py` 已建；`news_digest.json` 5,439 条 / 1.75MB / coverage 30 天；已接入日更链路 | ✅ 完成 |
| P3 | `exec_news_search` + 窗口三级 + legacy 标记 | `exec_news_search` 已实现并注册 `EXECUTORS["event_listing"]`（18→19）；`exec_event_listing` 两条 return 均带 `legacy: True` | ✅ 完成 |
| P4 | embedder 健康断言（34 域） | `34-前端应用训练系统/tests/test_l1_embedder_health.py`：768 维 + 余弦下限 + 可用性 | ✅ 完成 |
| P5 | 云端部署与端到端验收 | 云端 `b31be616`：41 域 EXIT=0、34 域 L1 门禁 EXIT=0；4 条 query 窗口与 `coverage_note` 全部核对 | ✅ 完成 |

**计划外已完成（本 SPEC 之外的性能根治）**

§8.8 常驻向量服务：`scripts/embed_server.py` + `deploy/dreambuddy-embedder.service` + `tests/test_embed_server.py`（commit `b3fb473939`），关闭了 §8.7 遗留风险 ①②。它不在 P0–P5 里，但 P3 的执行器将直接受益（语义槽位抽取不再有 10–12s 冷启动）。

**执行过程中发现的额外缺陷（已修）**

常驻向量服务原单请求上限 64 条，`build_intent_vectors` 等批量调用收到 400 后静默退回 in-process，
在云端小机型上把 41 域测试拖到 20 分钟以上（表现为「卡在 test_intent_matching 第 12 项」）。
已改为「单请求上限 4096 + 服务内部按 `ENCODE_CHUNK=64` 分片编码」（commit `b31be61699`），
实测 200 条一次请求 200 向量 / 9.8s，41 域全量恢复秒级完成。

**门禁现状**

| 门禁 | 状态 |
|---|---|
| T1 34 golden 全量 | ✅ 408/408（本地与云端均绿） |
| T2 冲突项核验 | ✅ 其余 377 条差异 = 0（§8.7） |
| T3 41 `test_intent_matching` | ✅ A 组语义命中（bge-base，18 项单测全绿） |
| T4 3.1 注册表测试 | ✅ 前后端 `event_listing` 模式一致 |
| T5 执行器单测 | ✅ `test_l1_news_search.py` 11 项全绿 |
| T6 embedder 健康断言 | ✅ `test_l1_embedder_health.py` 3 项全绿 |
| T7 无匹配话术 | ✅ 空库场景输出「未检索到」+ 覆盖数，不编造 |

---

## 13. 执行清单（逐项勾选，就地回写）

> 规则：完成一项即在本节打勾，并在行尾补「证据」（产物路径 / 测试输出 / commit）。
> 未打勾项即当前遗留工作；状态变化同步 §12 与 INDEX。

### P2 — 数据产物 `news_digest.json`（39 域）

- [x] **P2-1** 新建 `39-金融语义蒸馏系统/scripts/gen_news_digest.py`（复用 `normalize_title`，不改 `build_hot_news` 签名）｜证据：文件已建，复用 `gen_semantic_events` 的 `normalize_title`/`importance`/`_sentiment_block`
- [x] **P2-2** 产出 `news_digest/v1`（`coverage` 逐日补 0、`items`≤8000、单 title≤200、≤4MB、原子 rename）｜证据：实测 5,421 条 / 1.75MB / coverage 30 天（9 天为 0，暴露采集空洞）/ 高影响 352
- [x] **P2-3** 幂等可重跑 + `--window-days` / `--out` 参数｜证据：`tests/test_news_digest.py` 4 项全绿（含幂等 + 原子 rename 无残留 .tmp）

### P3 — 执行器 `exec_news_search`（3.1 前端）

- [x] **P3-1** `data_query_executor.py` 新增 `exec_news_search`（标题子串匹配 + 标签过滤 + importance/ts 排序）｜证据：`data_query_executor.py` §L1 新闻检索段
- [x] **P3-2** 槽位解析：`topic` / `sentiment` / `importance_min` / `keyword` / `limit`｜证据：topic 复用 39 `TOPIC_RULES`+`TOPIC_LABELS`（同源零映射误差），keyword 复用 `entity_aliases.json`
- [x] **P3-3** 窗口三级：24h（榜单）/ 168h（默认）/ 720h（上限）+ 回显 `window_h`｜证据：实测 `今天…`→24/hot_news、`最近…`→168、`上周…`→720
- [x] **P3-4** 注册 `l1_route_signal.EXECUTORS["event_listing"]`｜证据：`l1_route_signal.py:151`，EXECUTORS 18→19
- [x] **P3-5** `exec_event_listing` 标 `legacy=true`（保留可调用）｜证据：两条 return 均带 `legacy: True`，docstring 标【legacy】
- [x] **P3-6** T5 单测：0 命中不编造 / `topic=other` 不过滤 / FAIL-OPEN / 窗口三级｜证据：`34-前端应用训练系统/tests/test_l1_news_search.py` 11 项全绿
- [x] **P3-7** T7 无匹配话术：`以太坊相关的新闻` 不编造｜证据：真实产物命中 1 条；空库场景断言「未检索到」而非编造

### P4 — 健康断言（34 域）

- [x] **P4-1** 新增 embedder 健康断言（`is_inproc_available()` + 768 维 + 余弦下限）→ T6｜证据：`34-前端应用训练系统/tests/test_l1_embedder_health.py` 3 项全绿（768 维、同义 0.6745 ≥ 0.60、同义-无关差 0.34 ≥ 0.25）

### P5 — 云端收口

- [x] **P5-1** 云端 41 域全量 pytest｜证据：云端 `b31be616` 上 `41-文件索引系统/tests/` 全绿（EXIT=0，6 项 skip 因 PostgreSQL fis 库不可用，属环境缺省）
- [x] **P5-2** 云端 34 域 L1 门禁（news_search + embedder_health + route_signal + golden）｜证据：EXIT=0
- [x] **P5-3** 3 条窗口核验 query（最新 / 默认 / 30 天）核对 `window_h` 与 `coverage_note`｜证据：`今天有什么新闻`→24h/hot_news、`最近有什么新闻`→168h/news_digest（5,439 条）、`上周的新闻`→720h（"近 30 天检索到 5439 条"）、`以太坊相关的新闻`→168h 命中 1 条且回显「9 天无数据（采集异常）」

---

## 附录 A：30 条 golden 探针（实测现状已核）

| # | message | 目标意图 | 现状（实测） | 组 |
|---|---|---|---|---|
| 1 | 帮我盯一下这两天有没有什么值得注意的事 | event_listing | unknown | A 语义 |
| 2 | 有啥新动静吗 | event_listing | unknown | A |
| 3 | 币圈今天闹什么了 | event_listing | unknown | A |
| 4 | 这两天有什么大事 | event_listing | unknown | A |
| 5 | 有没有关于美联储的新东西 | event_listing | unknown | A |
| 6 | 今天消息面怎么样 | event_listing | unknown | A |
| 7 | 有什么值得关注的 | event_listing | unknown | A |
| 8 | 市场最近都在聊什么 | event_listing | unknown | A |
| 9 | 这两天发生了什么值得关注的事 | event_listing | unknown | A |
| 10 | 给我看看最近的热点 | event_listing | unknown | A |
| 11 | 这两天币圈有啥风吹草动 | event_listing | unknown | A |
| 12 | 有什么我该知道的事 | event_listing | unknown | A |
| 13 | 最近有什么新闻 | event_listing | unknown | B 正则 |
| 14 | 最新的监管新闻 | event_listing | event_line_query（需改判） | B |
| 15 | 以太坊相关的新闻 | event_listing | unknown | B |
| 16 | 今天有哪些利好新闻 | event_listing | unknown | B |
| 17 | 帮我找几条高影响的新闻 | event_listing | unknown | B |
| 18 | 24小时新闻情绪怎么样 | event_listing | unknown | B |
| 19 | 通胀主题的新闻 | event_listing | data_query（需改判） | B |
| 20 | 列出最近三条地缘政治消息 | event_listing | unknown | B |
| 21 | 美联储加息这件事后续怎么演变 | event_line_query | event_line_query | C 演化 |
| 22 | 地缘局势最近有什么新进展 | event_line_query | event_line_query | C |
| 23 | 加密监管的动态和趋势 | event_line_query | event_line_query | C |
| 24 | 这个事件后面会怎么发酵 | event_analysis | event_analysis（容忍） | C |
| 25 | 监管政策的演变过程 | event_line_query | event_line_query | C |
| 26 | 巨鲸动向最近的变化 | whale_flow | whale_flow（确定性优先） | C |
| 27 | 比特币是什么 | unknown | unknown | D 负例 |
| 28 | 帮我写一首诗 | unknown | unknown | D |
| 29 | 以太坊的RSI是多少 | technical_indicator | technical_indicator | D |
| 30 | 美股和加密最近哪个强 | asset_class_trend | asset_class_trend | D |

**已排除的候选**（实测不可用，记录以免重复踩坑）：

| message | 实测 | 原因 |
|---|---|---|
| 最近市场在交易什么消息 | event_line_query | 已被演化意图命中，作语义样本会制造歧义 |
| 最近都出了些什么事 | event_line_query | 同上 |
| 最近有点什么新鲜事 | event_line_query | 同上 |
| 最近出了什么值得关注的事 | event_line_query | 同上 |

---

## 附录 B：实测证据快照（2026-11-15）

| 项 | 值 |
|---|---|
| `l1_intent_golden.jsonl` | 377 条；`pytest` 计 378（含 1 条 accuracy gate） |
| golden 语义开/关差异 | **0 条**（两种模式均 378 passed） |
| 正则未命中 | 40 条，全部 `unknown` |
| 负例语义 top1 上界 / 正例中位数 | 0.6462 / 0.7392 |
| 语义阈值 | zh 0.65 / en 0.5，余量 0.0038 |
| `hot_news.json` | 853 事件 / top50 / window 24h / cluster 48h / 40KB |
| `semantic_events.jsonl` | 27,427 行 / 11.4MB / 30 天 / canonical 事件 6,500 行 |
| 近 24h 关键词命中 | 美联储 33 / 比特币 14 / 黄金 8 / 加密 5 / 以太坊 1 |
| `event_lines.json` | 本地缺失（gitignored 运行时产物）；源 `newsflash_%`，`limit=1500` ≈1.8 天 |
| 41 意图单元 | 21 个，4 个无 examples/vector |
| 34 域全量测试 | 1,535 项，当前 2 红（worker_roles 期望 8 实际 12，由 `58ddeae1a4` 引入，与本 SPEC 无关） |
