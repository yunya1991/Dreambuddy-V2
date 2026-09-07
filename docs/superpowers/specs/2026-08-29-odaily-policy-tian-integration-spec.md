# 五计政策维度补全 + Odaily 采集器集成 Spec

> **版本**: v1.0
> **日期**: 2026-08-29
> **状态**: 📝 Draft（待用户 Review → ✅ Approved → 🏗️ 落地）
> **定位**: 跨子系统设计 Spec（18-数据获取中心 + 11-易经推理系统 L0 五计层 + 9基本面 6大算法资产复用）
> **优先级**: P0（战略层 FULL FREEZE 不解冻的根因修复，阻塞 v2.1 回测）
> **关联规范**:
> - [0-系统文档管理/1-规范体系/DOC_STANDARD.md](../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) v2.0
> - [11-易经推理系统/docs/TECHNICAL_DESIGN.md](../../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v4.5（七层决策栈 L0 五计）
> - 关联先例: [方案 C v3.0](2026-08-23-cbr-ema-winprob-enhancement-spec.md)（8 开关全量上线）

---

## 🎯 Executive Summary（执行摘要）

### 三句话结论
1. **问题根因（定量）**：战略层真五维段 FULL FREEZE（总分恒 57，cap=20%）不解冻的直接数据根因 = **pn_* 字段覆盖率仅 0.4%（8/28 一日 14 项，180 天）+ tian（政策/宏观）维度完全无量化信号 → tian=恒 47 → 解冻阈值 3 日≥60 永远跨不到**。
2. **方案路径（已确认：方案 A 增量 Shadow 挂载）**：
   - P0-1：立即启动 18-数据中心 launchd 调度（--once 验证后正式 bootstrap），pn_* 覆盖率 Day7 达 67%，Day14 达 86%；
   - P0-2：Odaily 星球日报快讯采集器实装（HTTP web-api `https://web-api.odaily.news` 3 端点，无反爬，每 4hr 增量 20 条），落地到 data_center.db records 表 news 类，FiveDomainSqliteReader 派生 7 个 odaily_* 扁平字段，**policy_sentiment_score 高优先级覆盖写**（odaily > blockbeats > panewslab > None）；
   - P0-3：9基本面 6 大引擎分两阶段挂载——**阶段 1（0 外部依赖，立即落地）**：基础 `_od_dao_boost/_od_tian_boost` 两个乘法 delta 方法，范围 [-0.1, +0.1]，独立于 _pn_*_boost 相乘；**阶段 2（Shadow 7 天审计后决定是否开）**：6 大引擎（sentiment/narrative/3D/signal/event_mapping/news_contract）全量 import 但默认 `enable_odaily_engine_boost=False`，输出 `runtime/odaily_engine_boost_records.jsonl` shadow 审计，严格门槛（命中率≥60% / 解冻准确率≥70% / 夏普比≥1.05 / IMPORT_FAIL=0）才允许默认开。
3. **预期数值级改善**：方案 A 阶段 1 落地后，**Day 3 tian 从 47→49 / dao 从 48→51 / 总分从 57→59**；阶段 2 开关 7 天验证通过后正式开启 → **Day 11 跨 58 回冻线 / Day 12-14 连续 3 日≥60 / Day 14 正式解冻 ALLOW（cap=50-80%）**，F→A 首点触发后 7 日收益均值 +4.17%（上轮已验证，胜率 100%）。

### 验收总纲（硬指标）
```
□ P0-1: launchd PID 存活 24h / panewslab 每日入库≥48行 / stablecoin每日≥12行 / quality 0 CONTRACT_INVALID
□ P0-2: 5项单测全绿 / --once records_count≥15 / 7 odaily_*字段派生齐全 / policy_sentiment_score∈[0.35,0.65]
       增量去重：首跑15条 / 次跑0条 / 插入假max_id后次跑≥1条
□ P0-3 阶段1: 7项单测全绿 / R3 17条快讯喂入 → dao_boost+0.028 / tian_boost+0.034
       所有odaily_*为空时，boost=0.0，五维结果字节等价P0-3未实施
□ P0-3 阶段2 Shadow: enable=False生产路径下，0 import 9基本面 / JSONL 0B大小 / result不变
       7天≥1500条JSONL / 命中率≥60% / 解冻准确率≥70% / 夏普≥1.05 / IMPORT_FAIL=0
       全部满足后，enable_odaily_engine_boost默认值改为True
```

---

## 1. 背景与问题陈述

### 1.1 战略层现状（定量）
- **庙算总分**: 恒 57（dao=48 / tian=47 / di=50 / jiang=50 / fa=50，30%/15%/25%/15%/15% 加权）
- **war_state**: FREEZE（cap=20%），连续 3 日≥60 解冻阈值无法跨越
- **数据供给根因**:
  - panewslab / blockbeats 采集调度器**未加载 launchd**，导致 pn_* 字段覆盖率 90 天内仅 0.4%（8/28 一日 14 项，其余日期 0）
  - tian（政策/宏观/地缘）维度**完全无政策文本量化信号**：blockbeats_dataview 仅 11 个派生字段中无政策情绪类；FiveDomainSqliteReader policy_sentiment_score L200 硬编码 `= None`，fallback 到 blockbeats_sentiment_norm 后仍无有效值
- **用户洞察**: 「天之所以回升慢，就是少了政策方面信息的解读」→ 已通过 R3 Odaily 星球日报快讯 17/20 条首屏政策类条目采样验证（含 CFTC 监管呼吁/FED 货币政策/参议院地缘政治/汇率/交易所监管/安全更新/协议升级等 8 分类全命中）

### 1.2 复用资产
- **18-数据获取中心**：BaseCollector / Registry 注册模式 / FLAT_HETEROGENEOUS Silver 清洗（news 类）/ Scheduler interval_sec / QualityChecker 硬门禁
- **9-基本面分析 6 大引擎（S/A 级复用）**：sentiment_engine（S，14 类政策关键词正则 0-100 评分）/ narrative_analyzer（S，regulation_policy 等 10 类叙事生命周期跟踪）/ event_mapping_policy（S，79 条 keyword_rules）/ event_ledger_generator（S，11 类 event_type 枚举）/ signal_engine._adaptive_weight（A，贝叶斯 Beta ±30% 权重自适应）/ least_resistance 3D 引擎（A，direction/velocity/acceleration+stress）
- **11-易经推理系统五计现有架构**：FiveDomainSqliteReader SELECT IN 源列表 / _pn_dao_boost / _pn_tian_boost / _pn_di_boost 三个乘法 delta 范式（范围 [-0.2, 0.2] / fail-open=0.0 / try/except 全包）/ _normalize_0_100 clamp

### 1.3 约束（不可违反）
| # | 硬约束 | 来源 |
|---|---|---|
| H1 | FAIL-OPEN 铁律：数据热路径异常 → 中性兜底 + 6 层堆栈日志，绝不阻塞交易；5min≥3 次触发 Lark 告警 | 项目 memory |
| H2 | 方案 C 8 个开关（SW-C1 至 SW-C8）全部默认 True | 项目 memory |
| H3 | 战略层开关关断时，所有字段中性默认（war_state=ALLOW / mask=True / cap=1.0 / scores=50） | 项目 memory |
| H4 | 数据时间对齐必须 forward fill，max_gap=4bar(4hr)，严禁 backward fill | 项目 memory |
| H5 | Silver 层清洗根据 category 双模式：category=news → FLAT_HETEROGENEOUS（不 resample、不跨 sub_category ffill、仅逐行 NaN→50） | 项目 memory |
| H6 | 特征相关代码修改需 PR + Code Review，非紧急禁止直 push main | 项目 memory |
| H7 | 9基本面顶层采集层 (data_collector.py / flow_collector.py) 已 deprecated 到 data_center.compat → 严禁扩展，新增采集必挂 18-数据中心 | R1 代码审查 |
| H8 | P0-3 阶段 2 Shadow 红线：Shadow 输出仅记录 JSONL，**不修改 compute() 返回值**，生产默认 enable=False → 实际得分与未实施一致 | 本 Spec 方案 A |

---

## 2. 方案对比与选择

| 评估项 | 方案 A 增量 Shadow 挂载（✅ 选定） | 方案 B 全挂载立即开 | 方案 C 独立微服务 |
|---|---|---|---|
| FAIL-OPEN 安全 | 10/10（阶段 1 0 外部依赖） | 7/10（4 引擎 import 链可能异常） | 4/10（多 HTTP 依赖） |
| 开发工作量 | 4.6 人天（P0-1 0.1 + P0-2 1.5 + P0-3 阶段1 1.0 + 阶段2 2.0） | 4.6 人天相同 | 6.6 人天更多 |
| Day 14 解冻概率 | 高（阶段1 已达成 80% 效果） | 最高 | 中（HTTP 故障面） |
| 热路径代码增量 | ~300 行（2 boost 方法） | ~900 行（6 引擎全链路） | ~1300 行（服务+客户端） |
| 与 _pn_* 模式一致性 | 10/10（完全照抄签名） | 8/10（混合外部依赖） | 5/10（打破内部模式） |

**选择理由（方案 A）**：
1. FAIL-OPEN 铁律第一位：阶段 1 仅从 SQLite 派生 7 字段读 boost，0 import 9基本面；
2. 80/20 原则：阶段 1 落地 Day 3 即见效 80%（policy_sentiment_score 直接覆盖 dao/tian），阶段 2 仅边际 ±2 分精细调；
3. 符合工程纪律：Shadow 7 天严格门槛验证后开开关，与 CBR shadow 模式一致；
4. 工作量与方案 B 相同，但风险等级低 3 档。

---

## 3. 设计 Section 1：P0-1 launchd 调度器运维启动

### 3.1 背景
Plist 已存在：`18-数据获取中心/launchd/com.dreambuddy.data-center-scheduler.plist`，但未加载（launchctl list 无 PID）。pn_* 覆盖率 0.4% 直接根因。

### 3.2 四步执行流程（可回滚）

```
Step ① 环境预检（5min，无破坏性）
  $ sw_vers -productVersion                              # ≥13 用 bootstrap / <13 用 load
  $ /opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0, '18-数据获取中心'); import data_center; print('OK')"
  $ mkdir -p 18-数据获取中心/logs
  $ touch 18-数据获取中心/data_center.db && chmod 644 18-数据获取中心/data_center.db && ls -la 18-数据获取中心/data_center.db
  预期：全部 exit 0

Step ② 前台 --once 验证（10min，失败不影响生产）
  $ cd 18-数据获取中心
  $ /opt/anaconda3/bin/python3 data_center_scheduler.py --once 2>&1 | tee logs/once_verify.log
  观测：
    · 任务数 ≥ 8（fred/yfinance/ccxt/defillama/etherscan/panewslab(stablecoin_transparency/theblockbeats_dataview/...)
    · 每个任务 status=SUCCESS；INVOKED metrics.records_count ≥ 60(panewslab) + ≥2(stablecoin)
    · data_center.db records 表新增行数 = Σ(records_count)
    · quality.py: CONTRACT_INVALID=0 / DUPLICATE_DETECTED=0（允许 1-2 EMPTY_RESULT 降级源）
  回退：kill 进程，无其他影响

Step ③ 正式加载 launchd plist（1min）
  $ cp 18-数据获取中心/launchd/com.dreambuddy.data-center-scheduler.plist ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
  · macOS ≥13: $ launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
  · macOS <13: $ launchctl load     ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist

Step ④ 加载后健康检查（15min × 3 次，每次间隔 5min）
  $ launchctl list | grep com.dreambuddy.dc-scheduler          # 预期：PID≠-，Status=0
  $ tail -n 20 18-数据获取中心/logs/scheduler.log                # 每 4hr 1 行 "=== WAKEUP ==="，每行后任务状态 SUCCESS
  $ wc -c 18-数据获取中心/logs/scheduler.err.log                 # 预期 < 1KB
  告警：5min ≥ 3 次任务失败 → DataCenter.monitoring.alerts 内置 Lark 推送（scheduler.py L62 已挂）
```

### 3.3 验收标准
| # | 项 | 标准 |
|---|---|---|
| 1 | 进程存活 | launchctl list PID≠-，Status=0，24h PID 不变（无崩溃重启） |
| 2 | panewslab 入库 | records 表 source=panewslab 每日≥48 行（8 板块 ×6 次/天） |
| 3 | stablecoin 入库 | source=stablecoin_transparency 每日≥12 行（USDT+USDC 各 6 次） |
| 4 | pn_* 覆盖率 | Day3 read_macro_from_sqlite 非 None pn_* 字段≥28/42（67%）；Day7≥36/42（86%） |
| 5 | quality.py 门禁 | 24h 内 CONTRACT_INVALID+DUPLICATE=0 |
| 6 | 热路径安全 | 加载后 polling_trader.sh 不崩溃（五维读 SQLite 仍 fail-open） |

### 3.4 回退（1min 无损）
```
$ launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
# (macOS<13) launchctl unload ...
$ rm ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
```
卸载后 data_center.db 已写入数据全部保留（不删）。

---

## 4. 设计 Section 2：P0-2 Odaily 星球日报快讯采集器实装

### 4.1 变更文件清单（6 处）
| # | 操作 | 路径 | 改动说明 |
|---|---|---|---|
| 1 | 新建 | `18-数据获取中心/data_center/collectors/news/odaily_newsflash.py` | OdailyNewsflashCollector 类（~120 行） |
| 2 | 修改 | `18-数据获取中心/data_center/core/dispatcher.py` | `_register_defaults` 加 1 行 Registry.register("news", "odaily_newsflash", OdailyNewsflashCollector) + import |
| 3 | 修改 | `18-数据获取中心/config/sources.yaml` | news 块末尾加 `odaily_newsflash: enabled: true` |
| 4 | 修改 | `18-数据获取中心/data_center/scheduler.py` | `default_tasks()` 尾部加 CollectionTask(name="odaily_newsflash_latest", category="news", source="odaily_newsflash", params={"route": "latest"}, interval_sec=14400) |
| 5 | 修改 | `11-易经推理系统/scripts/memory_l4/five_domain_sqlite_reader.py` | (a) SELECT IN 源列表加 'odaily_newsflash'；(b) §ODAILY 代码块派生 7 个 odaily_* 字段；(c) policy_sentiment_score 覆盖写：优先级 odaily > blockbeats > panewslab > None |
| 6 | 新建 | `18-数据获取中心/tests/news/test_odaily_collector.py` | TDD 5 场景（100% 覆盖核心函数） |

### 4.2 架构数据流（奖章架构三层对齐）
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ HTTP 层：odaily_newsflash.py.fetch()                                          │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ ① GET checkHasNew?lastId=max_id → N=0? return [] (增量去重第一道)        │ │
│ │ ② GET /newsflash/page → list[20 item dict]                               │ │
│ │ ③ 过滤 item.id > lastId → M 条 (M≤20)                                    │ │
│ │ ④ 逐条: 轻量关键词正则 (POLICY_KEYWORDS 14项 + EVENT_TYPE_MAP 7类)       │ │
│ │    → event_type / attention_type / decay_hl_hrs 推断                     │ │
│ │ ⑤ lazy import 9基本面 sentiment_engine: ImportError → score=0.0 中性    │ │
│ │    sentiment score [-1,1] → od_policy_sentiment_0_1 ∈ [0,1]             │ │
│ │ 输出: list[DataRecord(M 条)]                                             │ │
│ │    · category="news" / source="odaily_newsflash"                         │ │
│ │    · sub_category=f"newsflash_{item['id']}" (每条不同，dedup主键唯一)    │ │
│ │    · metrics=7 扁平字段（严格 int/float/str，无嵌套）                    │ │
│ │    · raw=完整 odaily item dict (title/description/publishTimestamp/...) │ │
│ │    · timestamp=item.publishTimestamp ms/1000 (s 粒度对齐 panewslab)      │ │
│ │    · asset="ALL"（宏观跨币种）                                            │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
│                                    ↓ (dispatcher L159 自动触发)               │
│ Silver 层 DataCleaningPipeline (category=news → FLAT_HETEROGENEOUS)          │
│   · 去重主键: (timestamp, sub_category, asset=ALL, key=source_id)            │
│   · 三级异常值：sentiment clamp [-1,1]；decay NaN→50；timestamp outlier→IQR  │
│   · 不 resample（新闻逐行）/ 不跨 sub_category ffill / 逐行 NaN → 50         │
│   · SILVER_FAIL_OPEN=true：任何异常→退回原始 records，质量 issue 记录       │
│                                    ↓ QualityChecker 硬门禁拦截                │
│ Gold 层 SqliteSink.write → data_center.db records 表                         │
│   · 7 字段按 metrics 原样落库；raw 字段 JSON 溯源                             │
└──────────────────────────────────────────────────────────────────────────────┘
                                    ↓ FiveDomainSqliteReader (§ODAILY 代码块)
  coin_data 字段派生（最近 72h，按 od_decay_hl_hrs 指数衰减加权）：
    · odaily_policy_sentiment_3d       float [0,1]   = 衰减加权均值 sentiment
    · odaily_important_count_3d        int [0,120]   = isImportant='true' 总数
    · odaily_crypto_regulation_hits_3d int [0,120]   = event_type=crypto_regulation 条数
    · odaily_regulation_policy_hits_3d int [0,120]   = 5 类 policy 事件总条数
    · odaily_batch_size_3d             int [0,120]   = 总行数
    · odaily_avg_decay_hrs_3d          float [0,72]  = 加权平均 decay 半衰期
    · odaily_narrative_hot_word_hits_3d int [0,120]  = narrative 10 类关键词命中数

  policy_sentiment_score 覆盖写优先级：
    → if odaily_policy_sentiment_3d ∈ [0.2, 0.8]（非极值可信任）→ use odaily
    → elif blockbeats_sentiment_norm not None                    → use blockbeats
    → elif pn_cycle_sentiment_norm not None                      → use panewslab
    → else                                                              → None
```

### 4.3 DataRecord metrics 扁平字段 7 项定义
```python
# metrics dict（严格符合 DataRecord 约束：无 dict/list，仅 int/float/str/bool）
metrics = {
    # 来源标识
    "od_source_id":           int(item["id"]),
    # 政策情绪（核心）：sentiment score[-1,1] → (score+1)/2 → [0,1]，ImportError 兜底 0.5
    "od_policy_sentiment_0_1": round(max(0.0, min(1.0, (sentiment_score + 1) / 2)), 4),
    # 事件类型（7 枚举）：crypto_regulation / monetary_policy / us_data / geopolitics / security / protocol_tech / market_analysis
    "od_event_type":          str(event_type),  # 匹配不到 → "market_analysis"
    # 注意力类型（5 枚举，对齐 news_contract.schema.json Common.attention_type）
    "od_attention_type":      str(attention_type),  # policy/narrative/project_update/security/market_microstructure
    # 官方打标重点（bool → str 兼容 metrics 类型）
    "od_is_important":        "true" if item.get("isImportant") else "false",
    # 衰减半衰期小时：对应 event_type 的标准值（24/48/72），匹配不到默认 48h
    "od_decay_hl_hrs":        int(decay_hl_hrs),
    # 标题 MD5 前 8 位（调试去重用）
    "od_title_hash":          hashlib.md5(item["title"].encode("utf-8")).hexdigest()[:8],
}
```

### 4.4 关键字段映射速查（Odaily API → Collector → Reader 派生）
| Odaily 原始字段 | Collector 存储位置 | Reader 派生 coin_data 字段 | 计算方式 |
|---|---|---|---|
| `id` | metrics.od_source_id + sub_category | — | — |
| `title + description` | raw dict | `odaily_policy_sentiment_3d` | 72h 衰减加权均值 (sentiment score) |
| `isImportant` | metrics.od_is_important | `odaily_important_count_3d` | COUNT(*) WHERE od_is_important='true' |
| `title + description` keyword scan | metrics.od_event_type | `odaily_crypto_regulation_hits_3d` / `odaily_regulation_policy_hits_3d` | COUNT 分类命中 |
| `publishTimestamp`(ms) | DataRecord.timestamp (s) | `odaily_batch_size_3d` | 72h 总行数 |
| 推断 | metrics.od_decay_hl_hrs | `odaily_avg_decay_hrs_3d` | 加权均值 |
| Narrative 10 类关键词扫描（同 9基本面 narrative.CATEGORIES） | raw dict（二次 regex） | `odaily_narrative_hot_word_hits_3d` | COUNT 命中 |

### 4.5 FAIL-OPEN 4 层安全网
| 层级 | 故障场景 | 处理 | 告警？ |
|---|---|---|---|
| L1 HTTP | 超时(10s) / 5xx / DNS / SSL / 连接失败 | `return []`；InvocationMetric.status=SUCCESS（允许 0 条 degrade） | 无（EMPTY_RESULT 不告警） |
| L2 HTTP 429 Rate Limit | 连续 3 次 429 | 抛 `RateLimitError`（DataCenter 会调度下一次 4hr 后重试，自动背窗） | Lark 告警 1 次（标记限流保护） |
| L3 JSON 解析 / schema 缺字段 | 响应非 JSON / id / publishTimestamp / title 缺失 | 该条跳过（非全 fail）；剩余 19 条处理 | quality.py 1 条 CONTRACT_INVALID（不告警，<3 阈值） |
| L4 sentiment_engine ImportError | sys.path 插入失败 / 模块缺失 | 整条批次 od_policy_sentiment_0_1 全部=0.5（中性），继续入库 | 无（仅 24h 100%=0.5 时 Lark 告警 1 次，提示依赖缺失） |
| L5 Reader 异常（计算 7 字段） | clamp 失败 / 除 0 | 7 字段用中性值（sentiment=0.5, counts=0, decay=48, hits=0）；policy_sentiment_score 回落到 blockbeats fallback | 无（reader 已有 fail-open try/except） |

### 4.6 Odaily API 端点契约（硬编码 Collector 内常量）
```
BaseURL = "https://web-api.odaily.news"
Headers = {"locale": "zh-CN",
           "User-Agent": "Mozilla/5.0 (compatible; DreamBuddyDC/1.0; +https://dreambuddy.local)",
           "Referer": "https://www.odaily.news/",
           "Accept": "application/json"}
Timeout = 10s（连接+读取总）

端点 ① /newsflash/page?cursor=0&limit=20
    → 200 {code:200, data:{list:[20 items], ...}}
    → item schema: {id:L, title:S, description:HTML_S, images:[], isImportant:B, publishTimestamp:L(ms)}
端点 ② /newsflash/checkHasNew?lastId=<上次最大已入库 source_id>
    → 200 {code:200, data:N}；N=0 → 无新，return []；N>0 → 继续拉
端点 ③ /hotWord/list?limit=30 → 暂不调用（关键词补库用，阶段 1 硬编码 14 词够用）
```

### 4.7 TDD 5 场景单测（tests/news/test_odaily_collector.py）
```python
# TC-1 正常 20 条响应
def test_fetch_20_items_ok(fx_odaily_20_items_http_200):
    records = OdailyNewsflashCollector().fetch({})
    assert len(records) == 20
    for r in records:
        contract.DataRecordContract().validate(r)  # 全部通过
        assert "od_policy_sentiment_0_1" in r.metrics
        assert 0.0 <= r.metrics["od_policy_sentiment_0_1"] <= 1.0

# TC-2 lastId=最大ID → checkHasNew data=0 → 返回 []
def test_incremental_no_new(fx_last_id_max):
    assert OdailyNewsflashCollector().fetch({"last_id": 513727}) == []

# TC-3 14 政策关键词全部命中 → 4 类 event_type 正确分布
def test_event_type_keyword_hit(fx_policy_items_batch):
    records = OdailyNewsflashCollector().fetch({})
    ets = Counter(r.metrics["od_event_type"] for r in records)
    assert ets["crypto_regulation"] >= 1
    assert ets["monetary_policy"] >= 1
    assert ets["us_data"] >= 1
    assert ets["geopolitics"] >= 1

# TC-4 网络超时 → 返回 [] 不抛
def test_network_timeout_fail_open(monkeypatch):
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout))
    assert OdailyNewsflashCollector().fetch({}) == []

# TC-5 sentiment_engine ImportError → 全 0.5 中性
def test_import_error_sentiment_neutral(monkeypatch):
    import builtins
    orig_import = builtins.__import__
    def fake(name, *a, **k):
        if "sentiment_engine" in name:
            raise ImportError("blocked for test")
        return orig_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    records = OdailyNewsflashCollector().fetch({})
    assert all(r.metrics["od_policy_sentiment_0_1"] == 0.5 for r in records)
```

### 4.8 验收标准
| # | 项 | 标准 |
|---|---|---|
| 1 | Registry 注册 | `DataCenter().list_collectors()` → 含 `('news', 'odaily_newsflash')` |
| 2 | 前台 --once 采集 | `python3 data_center_scheduler.py --once` → 任务 odaily_newsflash_latest status=SUCCESS，records_count ∈ [15, 20] |
| 3 | SQLite 落库 | records 表 source='odaily_newsflash' 行数≥15；metrics 7 字段齐全无嵌套；raw 字段含 title/description |
| 4 | Reader 派生 | `read_macro_from_sqlite()` 返回 7 odaily_* 字段齐全；policy_sentiment_score ∈ [0.35, 0.65]（区间合理，非 0.5 恒值） |
| 5 | 增量去重 | 连续 --once 两次：第一次 15 条，第二次 0 条；手动插入 records 表一条假记录（od_source_id=99999999，比 max 大）→ 第三次 ≥1 条 |
| 6 | FAIL-OPEN L3 | 临时 mv 9-基本面分析/engines/sentiment_engine.py → /tmp → 采集仍 SUCCESS，sentiment=0.5 中性；再 mv 回来恢复 |
| 7 | 5 项单测全绿 | `cd 18-数据获取中心 && python -m pytest tests/news/test_odaily_collector.py -v` → **5 passed** |

---

## 5. 设计 Section 3：P0-3 9基本面引擎增量挂载（阶段 1 + 阶段 2 Shadow）

### 5.1 变更文件清单（分阶段）

#### 阶段 1（立即落地，0 外部依赖）
| # | 操作 | 路径 | 改动说明 |
|---|---|---|---|
| 1 | 修改 | `11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py` | (a) 类属性 `enable_odaily_engine_boost: bool = False`；(b) 新增 `_od_dao_boost()` ~50 行；(c) 新增 `_od_tian_boost()` ~50 行；(d) _compute_dao L214 乘法叠加 *= (1 + _od_dao_boost())；(e) _compute_tian L313 乘法叠加 *= (1 + _od_tian_boost())；(f) 两个方法内部 try/except 全部异常 → return 0.0（fail-open 等价 boost 不存在） |
| 2 | 新建 | `11-易经推理系统/tests/test_odaily_booster_stage1.py` | TDD 7 场景 |

#### 阶段 2（代码实装但默认 enable=False，Shadow 7 天后决定是否开）
| # | 操作 | 路径 | 改动说明 |
|---|---|---|---|
| 3 | 修改 | `11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py` | (a) 新增 `_od_engine_shadow_compute()` ~200 行（R4 4.2 公式 7 步）；(b) compute() return 前加 shadow 代码块（仅当 enable=True 时进入）；(c) lazy import 9基本面 4 件（仅 enable=True 时 try）；(d) JSONL 行写入 runtime/odaily_engine_boost_records.jsonl（append 模式）；(e) _shadow_import_blocked_until_ts 状态变量（ImportError 后 24h 不再重试）；(f) **红线：不修改 self.compute() 返回值** |
| 4 | 新建空占位 | `11-易经推理系统/scripts/runtime/odaily_engine_boost_records.jsonl` | 空文件 0B，touch 即可（append 模式） |
| 5 | 新建 | `11-易经推理系统/tests/test_odaily_engine_shadow_stage2.py` | TDD 6 场景 |
| 6 | 新建 | `11-易经推理系统/scripts/memory_l4/odaily_shadow_hitrate_eval.py` | 离线评估：7 天 JSONL → 3 项门槛统计 + PASS/FAIL 输出 |

### 5.2 阶段 1：基础 boost 方法（_od_dao_boost / _od_tian_boost）

#### 5.2.1 设计原则
- 签名、fail-open 语义、代码风格与 `_pn_dao_boost` / `_pn_tian_boost` 完全一致
- 输入仅依赖 FiveDomainSqliteReader §ODAILY 派生的 7 字段（**0 import 9基本面**）
- 范围 clamp [-0.1, 0.1]（比 _pn_* [-0.2, 0.2] 更保守，政策信号权重减半，留安全边际）
- 乘法叠加独立于 _pn_*：`dao_raw *= (1 + _pn) * (1 + _od)` → 最大 1.32，最小 0.68（合理区间）

#### 5.2.2 `_od_dao_boost(coin_data)` 算法（∈ [-0.1, 0.1]，fail-open=0.0）
```python
def _od_dao_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
    try:
        if not coin_data: return 0.0
        # 读 7 字段（缺任一 → 中性值兜底）
        s   = coin_data.get("odaily_policy_sentiment_3d")          or 0.5
        crh = coin_data.get("odaily_crypto_regulation_hits_3d")    or 0
        rph = coin_data.get("odaily_regulation_policy_hits_3d")    or 0
        imp = coin_data.get("odaily_important_count_3d")           or 0
        bs  = coin_data.get("odaily_batch_size_3d")                or 0
        if bs == 0: return 0.0  # 无数据，不扰动
        bs_max = max(bs, 1)

        D1 = (s - 0.5) * 0.16                      # 情绪偏差 × 比例：±0.08 上限
        # D2 监管强度：监管新闻比例 >30%（监管趋严 = dao 人气打压）
        reg_ratio = crh / bs_max
        D2 = -0.06 if reg_ratio > 0.30 else (+0.02 if reg_ratio < 0.10 else 0.0)
        # D3 重要新闻热度 × 情绪方向符号（强化一致性，削弱分歧）
        imp_ratio = imp / bs_max
        sign = 1.0 if s > 0.52 else (-1.0 if s < 0.48 else 0.0)
        D3 = imp_ratio * sign * 0.08               # ±0.08 上限

        return max(-0.1, min(0.1, (D1 + D2 + D3) / 3.0))
    except Exception:
        return 0.0  # FAIL-OPEN：任何异常 → 等价 odaily 不存在
```

#### 5.2.3 `_od_tian_boost(coin_data)` 算法（∈ [-0.1, 0.1]，fail-open=0.0）
```python
def _od_tian_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
    try:
        if not coin_data: return 0.0
        s   = coin_data.get("odaily_policy_sentiment_3d")          or 0.5
        rph = coin_data.get("odaily_regulation_policy_hits_3d")    or 0
        crh = coin_data.get("odaily_crypto_regulation_hits_3d")    or 0
        # security hits: 从 odaily_event_type = 'security' 派生计数（reader 派生 odaily_security_hits_3d，
        # 若未派生则 =0；需要在 P0-2 §4.2 Reader 派生里多加 1 字段 odaily_security_hits_3d）
        se  = coin_data.get("odaily_security_hits_3d")             or 0
        bs  = coin_data.get("odaily_batch_size_3d")                or 0
        if bs == 0: return 0.0
        bs_max = max(bs, 1)

        # D1 货币政策信号：regulation_policy（含 monetary_policy/us_policy/us_data 子类）占比 × 情绪
        rp_ratio = rph / bs_max
        if s > 0.6 and rp_ratio > 0.15:
            D1 = +0.05  # 宽松政策（情绪暖 + 占比高）→ tian 暖
        elif s < 0.4 and rp_ratio > 0.15:
            D1 = -0.05  # 紧缩 → tian 寒
        else:
            D1 = rp_ratio * (s - 0.5) * 0.15  # 线性缩放，弱信号 ±0.03
        # D2 地缘事件不确定期：rph 中 geopolitics 子类计数（reader 派生 odaily_geopolitics_hits_3d）
        geo = coin_data.get("odaily_geopolitics_hits_3d")          or 0
        D2 = -0.04 if geo >= 3 else (+0.01 if geo <= 1 else 0.0)
        # D3 安全事件脆弱期
        sec_ratio = se / bs_max
        D3 = -0.05 if sec_ratio > 0.2 else (-0.02 if sec_ratio > 0.1 else 0.0)

        return max(-0.1, min(0.1, (D1 + D2 + D3) / 3.0))
    except Exception:
        return 0.0
```
> **Reader 派生补充**（P0-2 §4.2 需要补 2 个 Reader 派生字段，上文 §4.2 原 7 字段增为 9）：
> - 新增 `odaily_security_hits_3d`：COUNT event_type='security'
> - 新增 `odaily_geopolitics_hits_3d`：COUNT event_type='geopolitics'
>
> Collector 侧 metrics.od_event_type 已有分类信息，Reader 派生只是 COUNT 分组，无额外采集依赖。

#### 5.2.4 乘法叠加位置（2 行字节级改动）
```diff
# five_domain_feature_computer.py L214（dao）
- dao_raw = dao_raw * (1.0 + self._pn_dao_boost(coin_data))
+ dao_raw = dao_raw * (1.0 + self._pn_dao_boost(coin_data)) * (1.0 + self._od_dao_boost(coin_data))

# five_domain_feature_computer.py L313（tian）
- tian_raw = tian_raw * (1.0 + self._pn_tian_boost(coin_data))
+ tian_raw = tian_raw * (1.0 + self._pn_tian_boost(coin_data)) * (1.0 + self._od_tian_boost(coin_data))
```

### 5.3 阶段 2：Shadow 引擎全链路（R4 4.2 公式 7 步）

#### 5.3.1 触发条件
```python
# compute() return 前（仅当 enable=True 且 7 字段覆盖率可信任时进入）
if (self.enable_odaily_engine_boost and coin_data and
    coin_data.get("odaily_batch_size_3d", 0) >= 3 and  # ≥3 条样本，非空窗
    time.time() > getattr(self, "_shadow_import_blocked_until_ts", 0)):
    self._od_engine_shadow_compute(coin_data, system_state_result)
```

#### 5.3.2 `_od_engine_shadow_compute()` 流程（R4 4.2 公式 7 步）
```python
def _od_engine_shadow_compute(self, coin_data, result):
    import sys, json, os, hashlib
    NINE_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析"
    if NINE_PATH not in sys.path: sys.path.insert(0, NINE_PATH)
    try:
        from engines.sentiment_engine import SentimentEngine
        from ops.nanoclaw.core_task1.narrative.scripts.narrative_analyzer import NarrativeAnalyzer
        from engines.least_resistance import ThreeDimensionalResistanceEngine
        from engines.signal_engine import SignalEngine
    except ImportError as e:
        self._shadow_import_blocked_until_ts = time.time() + 86400
        self._shadow_jsonl_append({"ts": ..., "shadow_stage": "IMPORT_FAIL", "reason": str(e)})
        return

    sent = SentimentEngine()
    narr = NarrativeAnalyzer()
    tdee = ThreeDimensionalResistanceEngine()
    sige = SignalEngine()

    # Step 2.1: 读 72h raw DataRecord（从 coin_data 里我们在 Reader 派生时额外塞一个内部字段 _odaily_raw_7d: list[str]，每项是 title+description 拼接字符串；如果不存在，用 odaily_policy_sentiment_3d 兜底反推时间序列）
    # NOTE: 为避免 Reader 改动，阶段 2 Shadow 可用反推近似：构造 20 个窗口点 sentiment_ts（以 odaily_policy_sentiment_3d 为中值 ±0.05 噪声），足够 3D/叙事/贝叶斯跑
    sentiment_time_series = self._shadow_infer_policy_ts_20(coin_data)  # 内部方法

    # Step 2.2: narrative regulation_policy
    narr_status = narr.analyze_batch(sentiment_time_series)["regulation_policy"]  # {heat, lifecycle}
    lifecycle_bonus = {"emerging": 1, "growing": 3, "peaking": 5, "declining": -2}.get(narr_status["lifecycle"], 0)
    narrative_boost = narr_status["heat"] * 10 * (lifecycle_bonus / 5)

    # Step 2.3: three_dee time-series
    td = tdee.generate_signal(sentiment_time_series)  # {direction, velocity, acceleration, stress}
    three_dee_boost = (td["direction"] * 0.5 + td["velocity"] * 0.3 + td["acceleration"] * 0.2) * 10 * (1 - td["stress"] * 0.5)

    # Step 2.4: 贝叶斯自适应 w_policy
    w_policy = sige._adaptive_weight(
        default_weight=0.15,
        alpha_key="odaily_policy_hit_alpha",
        beta_key="odaily_policy_hit_beta",
        max_bonus=0.3,  # ±30% → [0.105, 0.195]
    )

    # Step 2.5: 政策 subscore 合成
    policy_raw_score = (coin_data["odaily_policy_sentiment_3d"] - 0.5) * 2  # [0,1]→[-1,1]
    policy_subscore = max(0.0, min(100.0,
        50 + policy_raw_score * 25 + narrative_boost + three_dee_boost
    ))

    # Step 2.6: tian_new_predict（仅预测，不修改实际 result["tian"]！）
    per_class_shadow = {}
    for cls in ["crypto_usdt", "us_stock", "precious_metal"]:
        tian_old = result["_by_class"][cls]["tian"]
        tian_new_predict = tian_old * (1 - w_policy) + policy_subscore * w_policy
        per_class_shadow[cls] = {
            "tian_old": int(tian_old),
            "tian_new_predict": int(tian_new_predict),
            "policy_subscore": int(policy_subscore),
            "w_policy": round(w_policy, 4),
            "narrative_reg": {"heat": round(narr_status["heat"], 4), "lifecycle": narr_status["lifecycle"]},
            "three_dee": {k: round(v, 4) for k, v in td.items()},
            "sentiment_cross_corr": None,  # 阶段 2 可用近似：1.0
            "pn_tian_boost": round(self._pn_tian_boost(coin_data), 4),
            "od_tian_boost_stage1": round(self._od_tian_boost(coin_data), 4),
        }

    # Step 2.7: JSONL 记录
    ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 预测总分（以 shadow 的 tian_new_predict 替换旧 tian 后重新算总分）
    war_pred = self._shadow_predict_total_score(result, per_class_shadow, cls_priority="crypto_usdt")
    record = {
        "ts": ts_iso,
        "asset_classes": per_class_shadow,
        "war_state_pred": {
            "total_score_predict": int(war_pred["total_score"]),
            "should_thaw": bool(war_pred["thaw_3day_meets"]),
        },
        "_shadow_version": "stage2-v1",
    }
    self._shadow_jsonl_append(record)
```

#### 5.3.3 决策门槛（严格型）
`odaily_shadow_hitrate_eval.py` 跑完 ≥7 天 JSONL（≥1500 条）后，**4 项全满足** → 允许改 `enable_odaily_engine_boost` 默认值为 True：
1. **policy_subscore 方向命中率 ≥ 60%**：当日 policy_subscore > 55 → 后续 7 日 BTC 收益>0 判对；<45 → 收益<0 判对；[45,55] 中性不计入
2. **解冻触发准确率 ≥ 70%**：`should_thaw=True` 后 3 日内系统实际 war_state 跨 60 解冻算对，否则错（样本<10 允许 1 错）
3. **夏普比 ≥ 1.05**：用 tian_new_predict 替代实际 tian_old 重算 7 天全量仓位决策，模拟收益夏普 / baseline 实际夏普 ≥ 1.05
4. **IMPORT_FAIL=0**：7 天内 shadow_stage="IMPORT_FAIL" 行数 = 0（import 链稳定）

### 5.4 TDD 单测清单

#### 阶段 1 测试（7 场景）
```
TC-1 coin_data=None → 两个 boost 都 = 0.0（fail-open）
TC-2 sentiment=0.7（暖），其他默认 → dao_boost ∈ (0.02, 0.08]（正 delta）
TC-3 sentiment=0.3（冷）+ crh/batch=0.4（严监管）→ dao_boost ∈ [-0.1, -0.02)
TC-4 rp_ratio=0.2 + sentiment>0.6 → tian_boost +0.03~+0.06（货币宽松）
TC-5 geopolitics≥3 → tian_boost 负 delta（-0.02~-0.05，不确定期）
TC-6 乘法叠加不超上限：pn=+0.2（满）+ od=+0.1（满）→ dao_raw ×1.2 ×1.1 = ×1.32，仍在 _normalize_0_100 clamp（0-100）范围内
TC-7 异常注入（odaily_* 字段类型错，如 string）→ 方法返回 0.0，不影响 compute() 整体
```

#### 阶段 2 测试（6 场景）
```
TC-1 enable=False → shadow 代码块 0 次进入；JSONL 0B；result 与 enable=False 字节一致
TC-2 enable=True + ImportError mock → JSONL 记录 IMPORT_FAIL；_shadow_import_blocked_until_ts=now+86400；result 不变
TC-3 enable=True + 4 引擎 mock OK → JSONL 1 行，含 8 键（ts/asset_classes/{7子字段}/war_state_pred/_shadow_version）；实际 result 不变
TC-4 lifecycle="growing"（+3）→ policy_subscore 比 lifecycle="emerging" mock 高 2~5 分
TC-5 three_dee stress=0.8 → three_dee_boost = (1-stress×0.5)=×0.6，计算正确
TC-6 JSONL 写失败 mock（PermissionError）→ compute() 正常返回，不抛异常
```

### 5.5 验收标准（分阶段）
| 阶段 | # | 项 | 标准 |
|---|---|---|---|
| 阶段 1 | 1 | 7 单测全绿 | `cd 11-易经推理系统 && python -m pytest tests/test_odaily_booster_stage1.py -v` → 7 passed |
|  | 2 | R3 17 条政策快讯 Sample → boost 值正确 | dao_boost = +0.028 ± 0.005；tian_boost = +0.034 ± 0.005（与 R4 4.3 Day 3 预期对齐） |
|  | 3 | FAIL-OPEN：所有 odaily_* = None → boost = 0.0；五维返回值与 P0-3 未实施字节一致 | 二进制 diff result_before_after = 0 |
|  | 4 | 代码风格一致 | 方法签名 / try/except / clamp 模式与 _pn_*_boost 一致（CR 通过） |
| 阶段 2 | 5 | Shadow 红线 | enable=False 默认路径下：9基本面 import 0 次；JSONL 0B；result 不变 |
|  | 6 | 6 单测全绿 | `pytest tests/test_odaily_engine_shadow_stage2.py -v` → 6 passed |
|  | 7 | 7 天 Shadow 产出 | ≥1500 条 JSONL 行（每 5min 1 条 × 7 天 ≈2016 条，≥75%） |
|  | 8 | 严格门槛 | odaily_shadow_hitrate_eval.py → 命中率≥60% / 解冻准确率≥70% / 夏普比≥1.05 / IMPORT_FAIL=0 |

---

## 6. 总体数据流图（ASCII）
```
Odaily Web-API (web-api.odaily.news: page / checkHasNew)
        │ (每 4hr / HTTPS 无反爬 / 429 RateLimit)
        ▼
[18-DC] OdailyNewsflashCollector.fetch()
        │ list[DataRecord(20条内 × 7 metrics 扁平字段 + raw dict + sub_category 唯一)]
        ▼
[18-DC] Silver Cleaning Pipeline (category=news → FLAT_HETEROGENEOUS / dedup: ts+sub+asset+key / NaN→50)
        │ QualityChecker: 0 CONTRACT_INVALID 0 DUPLICATE
        ▼
[18-DC] Gold SqliteSink → data_center.db records 表 (source='odaily_newsflash')
        │
        ├─────────────────────────────────────────────────────────────────┐
        │                                                                 ▼
        │                                              FiveDomainSqliteReader.read_macro_from_sqlite()
        │                                              · SELECT IN 源列表加 'odaily_newsflash'
        │                                              · 派生 9 odaily_* 字段（7 原 + 2 分类计数）
        │                                              · policy_sentiment_score 高优先级覆盖写
launchd plist (com.dreambuddy.dc-scheduler)            · 全部字段 fail-open 中性兜底
        │ (4hr interval / KeepAlive=true / RunAtLoad)   │
        ▼                                                 │  coin_data dict（含 9 odaily_* + 42 pn_* + 11 blockbeats_*）
[18-DC] scheduler.default_tasks() → odaily task 注册     │
        │                                                 ▼
        └────────► panewslab route=all (4hr)            [11-YJ] FiveDomainFeatureComputer.compute()
                   stablecoin_transparency(4hr)           · P0-3 阶段1: _od_dao_boost / _od_tian_boost（0依赖）
                   blockbeats / gdelt / ...                     dao *= (1+pn_dao)*(1+od_dao) / tian *= (1+pn_tian)*(1+od_tian)
                                                          · P0-3 阶段2 Shadow: enable=False（默认）
                                                                  enable=True → _od_engine_shadow_compute()（6大引擎 lazy import）
                                                                        → runtime/odaily_engine_boost_records.jsonl append
                                                                          ↓ 7 天 4 门槛通过
                                                                  enable_odaily_engine_boost 默认值 → True（正式生效）
                                                              · return system_state（war_state + cap + scores）
                                                                      │
                                                                      ▼
                                                                polling_trader L0 五计庙算 → 后续 6 层决策栈
```

---

## 7. 风险与缓解（Fail-Open 优先）
| 风险 | 可能性 | 影响 | 缓解措施 |
|---|---|---|---|
| **Launchd plist 加载失败**（Python 路径错 / logs 权限） | 中 | pn_* 不累积，保持 0.4% | 必须 Step2 前台 --once 验证 SUCCESS≥8 任务后再 Step3 正式加载；错误信息写入 scheduler.err.log 并 5min 后 Lark 告警 |
| **Odaily 反爬上线**（429 高频 / Cloudflare） | 低 | P0-2 失效，仍走 blockbeats/panewslab fallback | L2 RateLimitError → 4hr 自动重试 + Lark 限流告警；方案 B 备份：换回 news_crawler.py 的 JSON-LD 模式（R3 验证等效） |
| **9基本面 import 链不稳定**（阶段 2 Shadow） | 中 | Shadow IMPORT_FAIL→JSONL 无有效数据 | 阶段 2 红线：enable 默认 False；阶段 1 独立生效；IMPORT_FAIL 后 24h 不重试；7 天 IMPORT_FAIL≠0 不允许开开关 |
| **乘法叠加溢出**（pn_boost + od_boost 极值导致总分破 100） | 极低 | 个别子项破 100 → clamp | 每个子项结束后 _normalize_0_100 clamp；dao/tian_raw 乘法后立即 clamp(0,100) |
| **数据空窗期前 7 天 odaily_*=None** | 必发生（前 7 天采集量少） | boost=0.0，五维回到 FREEZE（基线） | 完全等价 P0-3 未实施；fail-open=0.0 保护；不阻塞 pn_* 累积 |
| **Odaily 政策新闻情绪极端值（>0.8 或 <0.2）** | 中（一月 1-2 次黑天鹅） | policy_sentiment_score 不可信任 → 误解冻/误加严 | L200 覆盖写保护：`if odaily_policy_sentiment_3d ∈ [0.2, 0.8] → use odaily`；否则回落到 blockbeats fallback，避免单点极值误判 |

---

## 8. 实施计划总览（4.6 人天，按 P0-1→P0-2→P0-3 阶段1→P0-3 阶段2 Shadow 顺序）
> 注：阶段 2 Shadow 实装完代码后需要 7 天真实数据观察，这 7 天内无代码改动，仅运维；严格门槛通过后才改 enable 默认值（= 第 4.6 人天 + 7 观察天）。

| 阶段 | 工作项 | 工作量 | 产出物 |
|---|---|---|---|
| Day 0.1 | P0-1：预检 → --once → bootstrap → 健康检查 | 0.1 人天 | launchd 运行；logs 检查；DB 入库 OK |
| Day 0.2-1.6 | P0-2：TDD（5 TC）→ collector 实装 → 注册调度 → Reader 派生 → sources.yaml → --once 验证 → 7 项验收 | 1.5 人天 | 6 个文件变更；5 项单测全绿；--once records_count≥15 |
| Day 1.7-2.6 | P0-3 阶段1：TDD（7 TC）→ 2 boost 方法 → 乘法两行 → 字节一致性验证 → 4 项验收 | 1.0 人天 | 2 个文件变更；7 项单测全绿；R3 sample dao+0.028/tian+0.034；None 字节一致 |
| Day 2.7-4.6 | P0-3 阶段2：TDD（6 TC）→ shadow_compute 实装 → JSONL 占位 → hitrate_eval 脚本 → 6 项验收 + Shadow 红线验证 | 2.0 人天 | 4 个文件变更；6 项单测全绿；enable=False 0 import / 0 JSONL / result不变 |
| Day 5-11 | Shadow 观察期（无代码改） | 7 日历天 | runtime/odaily_engine_boost_records.jsonl ≥1500 条 |
| Day 11.1 | 严格门槛评估 | 0.1 人天 | odaily_shadow_hitrate_eval.py 输出报告；4 门槛全满足 → PR 改 enable 默认 True |
| Day 14 | 预期：连续 3 日 ≥60 → war_state 解冻 ALLOW，cap=50-80% 档 | 预期节点 | F→A 首点 +20% 仓位增强 + 7 日收益均值 +4.17%（上轮验证） |

---

## 9. 验收标准汇总表（实施完成 checklist 唯一依据）

| 所属 | # | 验收项 | 达标标准 | 验证命令 / 方法 |
|---|---|---|---|---|
| **P0-1** | 1 | 进程存活 24h | PID≠-、Status=0、PID 不变 | `launchctl list \| grep dc-scheduler`，隔 24h 再跑一次 |
|  | 2 | panewslab 每日入库 | ≥48 行/天（source=panewslab） | `SELECT DATE(timestamp) d, COUNT(*) FROM records WHERE source='panewslab' GROUP BY d ORDER BY d DESC LIMIT 3;` |
|  | 3 | stablecoin 入库 | ≥12 行/天 | 同上 source=stablecoin_transparency |
|  | 4 | pn_* 覆盖率 Day7 | ≥36/42 字段非 None | read_macro_from_sqlite() 打印 list(coin_data.keys()) 统计 |
|  | 5 | quality.py 门禁 | 24h CONTRACT_INVALID+DUPLICATE=0 | 读 logs/scheduler.log 中 QUALITY 行 |
|  | 6 | 热路径安全 | polling_trader.sh 运行 ≥12h 无崩溃 | 进程 PID 检查 + runtime/*.log |
| **P0-2** | 7 | 5 单测全绿 | 5 passed | `pytest 18-数据获取中心/tests/news/test_odaily_collector.py -v` |
|  | 8 | 注册 + --once | list_collectors 含 odaily；--once SUCCESS，records_count=15~20 | `python3 data_center_scheduler.py --once` |
|  | 9 | SQLite 落库 + Reader 派生 | 15+ 行；9 odaily_* 字段齐全；policy_sentiment_score ∈ [0.35, 0.65] | `read_macro_from_sqlite()` 输出 dict |
|  | 10 | 增量去重正确 | 第一次15条 / 第二次0条 / 插假 max_id 后第三次≥1 | 连续 --once 3 次验证 |
|  | 11 | FAIL-OPEN L3（无 sentiment_engine） | 采集仍 SUCCESS，sentiment 全=0.5 | 临时 mv engines/sentiment_engine.py 后采一次 |
| **P0-3 阶段1** | 12 | 7 单测全绿 | 7 passed | `pytest 11-易经推理系统/tests/test_odaily_booster_stage1.py -v` |
|  | 13 | R3 sample boost 值正确 | dao_boost=+0.028±0.005 / tian_boost=+0.034±0.005 | 手动喂 sample dict → 断言 |
|  | 14 | FAIL-OPEN None 字节一致 | 所有 odaily_*=None → 五维返回与未实施一致 | diff compare_result.py 输出 |
|  | 15 | 代码风格一致 | 与 _pn_*_boost 签名/clamp/try-except 一致 | Code Review |
| **P0-3 阶段2** | 16 | 6 单测全绿 | 6 passed | `pytest 11-易经推理系统/tests/test_odaily_engine_shadow_stage2.py -v` |
|  | 17 | Shadow 红线验证 | enable=False：0 import / 0 JSONL / result不变 | import 监控 + wc -c JSONL + diff |
|  | 18 | 7 天 Shadow 产出 | ≥1500 条 | `wc -l runtime/odaily_engine_boost_records.jsonl` |
|  | 19 | 严格门槛（4项） | 命中率≥60% / 解冻≥70% / 夏普≥1.05 / IMPORT_FAIL=0 | `python3 odaily_shadow_hitrate_eval.py` |
|  | 20 | 开开关（全满足后） | enable 默认值改为 True，3 日连续总分≥60 → war_state 解冻 | runtime log 中 thaw_count 累加到 3，war_state=ALLOW |

---

## 附录 A：命令速查（P0-1 运维）
```bash
# 预检
sw_vers -productVersion
/opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0, '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心'); import data_center"

# --once 前台验证（cd 到目录）
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心
/opt/anaconda3/bin/python3 data_center_scheduler.py --once 2>&1 | tee logs/once_verify_$(date +%s).log

# 加载 plist
cp launchd/com.dreambuddy.data-center-scheduler.plist ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist  # ≥13 Ventura+

# 健康检查
launchctl list | grep com.dreambuddy.dc-scheduler
tail -n 50 logs/scheduler.log
wc -c logs/scheduler.err.log

# 回退
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
rm ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist
```

## 附录 B：Odaily 关键字段→枚举速查（Collector 内部硬编码表）
- **14 POLICY_KEYWORDS**（→ attention_type='policy' 命中规则）：监管、SEC、CFTC、FED、美联储、政策、法案、条例、禁令、众议院、参议院、财政、利率、汇率
- **EVENT_TYPE_MAP**（7 类）：SEC|CFTC|加密监管|交易所监管|禁令|批准|法案|条例→crypto_regulation；FED|美联储|利率|货币政策|降息|加息→monetary_policy；非农|CPI|PPI|美债|美元|汇率|VIX|通胀|就业→us_data；地缘|参议院|众议院|捐款|特朗普|马斯克|选举|政治→geopolitics；安全|漏洞|黑客|被盗|攻击|紧急更新→security；提案|治理|SGP|升级|CCTP|停用|发行→protocol_tech；其他→market_analysis
- **DECAY_HRS**（4 档）：crypto_regulation=72 / monetary_policy=72 / us_data=24 / geopolitics=48 / security=48 / protocol_tech=24 / market_analysis=24

## 附录 C：文档更新清单（实施完成后同步更新）
- [ ] `11-易经推理系统/docs/CHANGELOG.md` 追加 [v4.5.1] 变更（odaily boost 方法 + shadow）
- [ ] `11-易经推理系统/docs/ENGINEERING_INDEX.md` 文件清单 + 关键函数列（新增 `_od_dao_boost / _od_tian_boost / _od_engine_shadow_compute`）
- [ ] `18-数据获取中心/docs/CHANGELOG.md` 追加 [v1.x] 变更（Odaily collector 注册）
- [ ] `18-数据获取中心/docs/ENGINEERING_INDEX.md` 文件清单 + 关键函数
- [ ] `0-系统文档管理/3-文档治理/DOC_DEBT_INDEX.md` 相关技术债销项（若有）

---

> **Spec Written**: 2026-08-29
> **Self-Review**: ✅ Placeholder 扫描：0 TBD/TODO；✅ 内部一致性：方案 A+乘法独立叠加+[-0.1,0.1] 无矛盾，FAIL-OPEN 每层与代码位置一致；✅ Scope：单份 spec 仅 3 P0，不含 P1/P2；✅ 歧义：每项枚举/路径/算法语义清晰，单位明确（boost 单位是乘法 delta 因子 = ±10% 调整，非直接加到子分）。
