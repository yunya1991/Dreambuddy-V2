# SPEC 评审报告 — 54-L1 架构能力聚合层 v0.1

- **评审对象**: `54-L1架构能力聚合层/SPEC-54-L1架构能力聚合层.md` v0.1
- **评审日期**: 2026-11-14
- **评审方式**: 代码事实核验 + 架构/契约/可验证性/风险四维评审（Devil's Advocate）
- **评审结论**: 🟡 **有条件通过** —— 架构方向成立，但存在 **5 个 P0 阻断项**，修订后可进入 P0 实施。

---

## 一、结论摘要

| 维度 | 评分 | 说明 |
|---|---|---|
| 架构合理性 | 4.0 / 5 | 「只聚合不采集」「L1 与前端同源」方向正确，层级边界清晰 |
| 契约严谨度 | 3.0 / 5 | 存在字段位置矛盾、统计口径可误删真实极值 |
| 可验证性 | 3.5 / 5 | 有验收指标，但缺性能实测、负样本回归、部署验证 |
| 风险控制 | 3.0 / 5 | 绕过记忆门禁缺防误路由设计；无索引与查询上限 |
| 兼容性 | 4.0 / 5 | 新增层不动既有执行器，回滚路径明确 |
| **综合** | **3.5 / 5** | 有条件通过 |

**已核验为真的关键事实**（无夸大）：
1. `mm_metrics` 实测 348,543 行 / 5,304 sub_category / 455 指标，`DGS10` 回溯 1962 —— 成立。
2. 前端 `timeseries` **硬编码为空数组**：`src/app/api/fundamental/[...path]/route.ts` 第 69 行 `timeseries: []` —— 比 SPEC 描述的「无生产者」更严重，属确定性缺陷。
3. 9-基本面 `_make_timeseries()` 为随机游走合成 —— 成立，必须替换。
4. `mm_metrics` **没有** `(sub_category, metric_name, timestamp)` 索引 —— SPEC 未覆盖，属 P0 遗漏。
5. PyYAML 6.0.3 可用且 34 系统 core 已在用 —— `capability_manifest.yaml` 方案可行，无需改 JSON。

---

## 二、P0 阻断项（必须修订后才能开工）

### B1｜前端序列替换路径不完整（§1.2 / §4 / §7-P1.8）
**问题**：SPEC 只写「删除 `_make_timeseries` 调用」，但该函数仍被 `ml_trade_service_v2` 等其他消费方调用；且 `route.ts:69` 是硬编码 `[]`，不是「无生产者」。
**风险**：按此实施会破坏 ML 交易服务的序列输入。
**修订要求**：
- 明确「**不改 9 的 `generate_timeseries` 实现**，只在 54 内新增 `series_aggregator`，前端路由改调 54」；
- 增加过渡期开关（`FUNDAMENTAL_TIMESERIES_SOURCE=54|legacy`），默认 54、可一键回退；
- 把 `route.ts:69` 列为显式改造点（含行号）。

### B2｜ADR-5 绕过记忆门禁缺防误路由设计（§0.2 / §5.4）
**问题**：`metric_*` 全部 `deterministic`，一旦意图识别把「CPI 的文档在哪」识别成 `metric_series`，会绕过一切门禁直接作答。
**修订要求**：
- 明确**能力命中三条件**：`指标别名命中` AND `查询类型词命中` AND `非文档/事件意图`；
- 固定 fallback 顺序：`doc_search → event_line_query → metric_* → data_query/price_query`；
- golden set 必须新增**负样本**（≥10 条），例如「CPI 文档在哪」→ `doc_search`、「CPI 数据什么时候发布」→ `calendar`；
- 显式声明「`deterministic` 不等于无校验」，校验项 = 别名 + 参数完整性 + 数据质量。

### B3｜缺索引与查询上限（§5.1 / §6）
**问题**：`query_metric_by_time` 在 34.8 万行无索引表上做区间扫描；`sub_category` 无白名单，可构造超长区间查询。
**修订要求**：
- P0 增加索引迁移：`CREATE INDEX IF NOT EXISTS idx_mm_metrics_lookup ON mm_metrics(sub_category, metric_name, timestamp)`；
- 契约增加 `max_days`（默认 1825）与 `sub_category` 白名单/字符校验；
- 验收补「P95 ≤ 800ms」的实测方法与样本量（≥20 次，冷/热各半）。

### B4｜契约字段位置自相矛盾（§5.1 vs §5.3）
**问题**：§5.1 把 `quality` 放在 `data` 内，§5.3 放在顶层；§5.3 约束文字写「`data.answer` 禁止为空串」但示例里 `answer` 在顶层。
**修订要求**：统一为**顶层 `quality` + 顶层 `answer`**，`data` 只承载业务字段（now/past/stat/meaning/cross），并补一份 `contracts/capability_result.schema.json` 作为唯一事实源。

### B5｜统计口径会误删真实极值（§6）
**问题**：`>10×IQR 剔除` 会删掉 VIX 尖峰、清算瀑布、恐惧贪婪 0/100 等**最有信息量**的点。
**修订要求**：
- 离群值**只标记不删除**（`outlier_flag`），仅 `z-score` 计算时使用 winsorize（p1/p99）；
- `cagr` 仅适用于正值的指数型/存量型序列（CPI 指数、M2、TVL），对费率/多空比/涨跌幅禁用并返回 `null`；
- 明确 `volatility` 定义（日收益率标准差 × √365，还是原始值标准差），二者不可混用。

---

## 三、P1 重要建议

| # | 章节 | 问题 | 建议 |
|---|---|---|---|
| I1 | §5.3 | 缺 L1 收尾约定 | 新执行器必须注册进 `EXECUTORS` 并走 `settle_to_cognitive`；`degraded_reason` 建枚举字典（与 `route_confidence.reasons` 对齐），禁止自由文本 |
| I2 | §3.2 | 缺可运行性约定 | 54 需 `__init__.py`；`l1_route_signal.py` 的 `sys.path` 注入方式写明；云端需 `git pull` + `black/ruff` 门禁 |
| I3 | §5.4 | 未评估 golden 门禁影响 | +5 意图 × ≥20 条会稀释总体阈值，需同步更新 `test_l1_intent_golden.py` 阈值说明与 TS jest 用例 |
| I4 | §4.2 | `predict` 易被误读为结论 | 固定 `caveat` 模板（来源/期限/置信度/不可外推声明），缺任一字段则 `quality.status=partial` |
| I5 | §5.1 | 无查询上限 | 见 B3：`max_days` + 白名单 + 参数长度校验 |
| I6 | §5.5 | 前端无法区分「空/无」 | `timeseries` 增 `unit` 与 `data_quality`；空数组时必须给出 `reason` |

---

## 四、P2 优化

- **O1**：§4.1 中 `calendar` 的 `predict ✅` 应改为 `—`（fedwatch 概率归 `macro`，日历是事件表）。
- **O2**：§3.2 目录未包含 `reports/`，与 §6 交付物路径不一致。
- **O3**：§10 Q5 需明确别名表位置（建议 `meaning/metric_aliases.yaml`）与维护责任人。

---

## 五、可执行性判断

| 项 | 判断 |
|---|---|
| P0 工作量是否可控 | ✅ 可控：1 个聚合器 + 1 个 L0 scope + 1 个执行器 + 索引迁移 + 体检脚本 |
| 是否依赖未就绪能力 | ❌ 无：DAL 区间查询、PyYAML、L1 注册机制均已就绪 |
| 最大实施风险 | B2（误路由）与 B3（性能/查询失控） |
| 建议开工顺序 | 索引 → 覆盖体检 → `datacenter.series` → `exec_metric_series` → golden 负样本 → 前端开关 |

---

## 六、修订清单（对应 SPEC 章节）

| 编号 | 目标章节 | 动作 |
|---|---|---|
| R1 | §1.2 / §7-P1 | 按 B1 补「不改 9、只换前端来源、加开关、route.ts:69」 |
| R2 | §0.2 ADR-5 / §5.4 | 按 B2 补三条件、顺序、负样本要求 |
| R3 | §5.1 / §6 / §7-P0 | 按 B3 补索引迁移、`max_days`、白名单、性能实测 |
| R4 | §5.1 / §5.3 | 按 B4 统一 `quality`/`answer` 位置，补 schema 文件 |
| R5 | §6 | 按 B5 改离群处理、`cagr` 适用范围、`volatility` 定义 |
| R6 | §3.2 / §4.1 / §5.5 / §10 | 按 O1–O3、I6 小修 |

**结论**：完成 R1–R5 后版本升为 v0.2，可进入 P0 实施；R6 可随 P0 一并提交。
