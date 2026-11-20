# Agent 服务优化实验记录

追加式记录。每轮只改一个变量，只记"变量 → 指标 → 结论"，不复述过程。

## 汇总

| 轮次 | 日期 | 变量 | coverage_hit_rate | ours_selection_rate | wrong_our_tool | false_positive_rate | 结论 |
|---|---|---|---|---|---|---|---|
| R0 | 2026-11-21 | 基线（内部术语描述） | 36.4%（8/22） | 26.7%（8/30） | 0 | 0% | quote / filings / reservation 全败给竞品的描述 |
| R1 | 2026-11-21 | 仅改动作描述为用户实体词 | **100%（22/22）** | **73.3%（22/30）** | 0 | 0% | 纯文案 +63.6 个百分点，无需改架构 |
| R2a | 2026-11-21 | full 模式改工具名 | 100%（22/22） | 73.3%（22/30） | 0 | 0% | **无效对照**：R1 已到 100% 天花板，无 headroom，不能据此判定名字无效果 |
| R2b | 2026-11-21 | name-only（去掉描述）旧名 vs 新名，10 条改名意图 | 60% → **80%** | 60% → **80%** | 0 | — | **名字有独立信号 +20pp**，但在强描述下会被淹没 |
| R6 | 2026-11-21 | name-only 细化命名（`sec_filing_reader` / `ticket_reservation`） | 80% → **100%** | 80% → **100%** | 0 | — | 动作+能力对象命名优于单一实体命名；同族回归通过 |
| R7 | 2026-11-21 | 全量 name-only（30 条）回归 | **81.8%（18/22）** | 63.3%（19/30） | 1 | 0% | 已改名族全部 100%；短板在 facts / event / reservation 监控族 |
| R8 | 2026-11-21 | 补改 4 族名（`a_share_index_facts` / `official_fed_sec_event_search` / `ticket_monitor_list` / `ticket_monitor_report`） | 81.8% → **95.5%** | 63.3% → 73.3% | 1 | 0% | facts / reservation 100%；event 剩 e02 为随机边界 |
| R9 | 2026-11-21 | 新增 `when_to_use` / `not_for`，guidance 模式（名字+边界，无描述） | 95.5% → **100%** | 73.3% | **0** | 0% | 边界成组加才有效；语义重叠需先改名划边 |
| R10 | 2026-11-21 | 换弱模型 `qwen3.6-flash` 复测（name / guidance / full） | name 95.5% / guidance 95.5% / full **100%** | 70.0% / 73.3% / 73.3% | 0 / 1 / **0** | 0% | 命名结论可复现；guidance 单独不够，描述+边界最稳 |
| R11 | 2026-11-21 | SkillHub 上架字段（description / tags / summary / displayName） | —（无平台曝光数据） | — | — | — | 4 个免费 Skill 预检通过；转化需平台数据 |
| R12 | 2026-11-21 | 同一配置（full / 强模型）复跑 3 次 | 100% × 3 | 73.3% × 3 | 0 × 3 | 0% × 3 | 选择 0 翻转；时延 σ≈2.2s，单次时延差异不可作结论 |
| R14 | 2026-11-21 | 压力集 15 条（超短意图 + 看似相关越界） | 90%（9/10） | 60.0% | 0 | 0%（0/5） | 仅 p08 失败，属能力边界：无实时余票查询 |
| R15 | 2026-11-21 | 实际发布 4 个免费 Skill 到 SkillHub | —（待审核） | — | — | — | 4/4 上架成功；审核 pending，搜索索引 0 |

## R1 明细

- 改动范围：`market-data` / `market-facts-daily` / `event-context` / `mobile-reservation-assist` / `reservation-assist` 的 `component.yaml`，只改 `actions[].description`。
- 未改：工具名、参数 schema、脚本、MCP 注解、SkillHub 上架字段。
- 复跑命令：

```bash
cd 59-通用组件管理
python3 platform/bench/routing/run_bench.py --router qwen \
  --json /tmp/routing-after.json --compare /tmp/routing-baseline.json
```

- 观察：quote 5/5、filings 3/3、reservation 4/4 全部从 0% 转正；越界误选仍为 0，说明提升来自匹配变准，不是"什么都往自己身上揽"。

## R2 明细

- R2a（full 模式）：`market-data.quotes` / `market-data.filings` / `mobile-reservation-assist.ask` 的 `mcp.name` 改为 `a_share_quote` / `us_sec_filings` / `reservation_plan`，描述与参数不动。结果与 R1 持平，但 R1 已是 100%，**天花板效应使该对照失效**。
- R2b（name-only 隔离）：候选只给名字、不给描述，只跑被改名的 10 条意图（q01–q05、f01–f03、r01–r02）。
  - 旧名（legacy）：60%（6/10）；filings 0/3、reservation 1/2。
  - 新名（current）：80%（8/10）；filings 2/3、reservation 1/2。
  - 差异 +20pp，证明名字在无描述/弱描述环境有独立贡献；剩下的 f02（10-Q 财务字段）仍输给 `sec_reader`，r01（国博预约）选 `none`。
- 环境：首轮 28 次 SSL 证书错误作废；基准已加 certifi 兜底与 `--retries` 单条重试。
- 方法论教训：**测变量前先检查 headroom**。基线贴近 100% 时，降低信息量（name-only）或加难例，否则会把"有效"误判为"无效"。

## R6 明细

- 起点：R2b name-only 80%，剩余两条为 f02（10-Q 财务字段败给 `sec_reader`）、r01（国博预约选了 `none`）。
- 第一次尝试：`museum_ticket_reservation` 修好了 r01，但 r02（演唱会）失败，净覆盖仍 80%。**发现：绑定单一实体的名字会牺牲同族泛化**。
- 第二次尝试：`ticket_reservation` + `sec_filing_reader`。定向 5 条 5/5；全量 10 条 **100%**，对比 R2b 提升 +20pp。
- 结论：命名用"**动作 + 能力对象**"（ticket_reservation / sec_filing_reader），不要绑定单一实体；每次改完一个难例，必须复测同族其它意图。

## R7 明细

- 范围：全部 30 条意图（22 覆盖 + 8 越界），name-only。
- 已改名族：quote 5/5、filings 3/3、macro 3/3、onchain 2/2，全部 100%。
- 未命中 4 条，全部落在尚未按"动作+能力对象"改名的族：
  - `n01` 指数涨跌幅/分位 → 竞品 `a_share_market`（我们的 `market_facts_daily_facts` 是模块名）；
  - `e01` 特斯拉 SEC 公告和事件 → 选了我们自己的 `sec_filing_reader`（动作错，`event_context_events` 太抽象）；
  - `r03` 在监控哪些余票任务 → 竞品 `ticket_monitor`；
  - `r04` 余票监控报告 → 竞品 `ticket_monitor`。
- 越界误选 0，说明命名细化没有带来"什么都答应"。
- 结论：**只回归改动过的族会高估效果**；每轮应跑一次全量 name-only 回归。

## R8 明细

- 改动：`a_share_index_facts`、`ticket_monitor_list`、`ticket_monitor_report`、event 工具名。
- event 命名迭代了 3 版：
  - `company_event_feed`：e02 修好，e01 仍输给 `sec_filing_reader`；
  - `official_event_search`：e01 输给 `sec_filing_reader`；
  - `official_sec_event_search`：e01 修好，e02 输给 `market_data_macro`；
  - `official_fed_sec_event_search`：定向 6/6；全量 21/22，e02 仍偶发输给 `market_data_macro`。
- 最终：覆盖 95.5%（21/22），越界 0，选错动作 1（e02 选了我们自己的 macro）。
- 结论：
  1. facts / reservation 通过"动作+能力对象"命名直接到 100%；
  2. e02 是**跨族歧义 + 模型随机性**边界（同配置定向 6/6、全量 2/3），不应靠继续加长名字硬压；
  3. 单次结果有方差，边界样本至少复跑 2 次再定论。

## R9 明细

- 实验模式：新增 `--catalog-fields guidance`，只给"名字 + 适用/不适用"，不给描述，用来隔离边界文案。
- 第一次：只给 event / macro 加边界，结果 95.5% → 86.4%——event 抢走 filings（f01/f03），facts 因无边界落选。**边界只加一方会吸走另一方流量**。
- 第二次：8 个热工具全部补齐边界，回到 90.9%；仍剩两处语义重叠：
  - n02 "一页市场数字事实" 输给 `global_assets`；
  - r03 "在监控哪些余票任务" 被 `mobile_reservation_assist_jobs` 抢走。
- 第三次：facts 的 `when_to_use` 改写为"生成 A 股一页数字事实…"；MRA jobs 改名 `reservation_job_list` 并与 `ticket_monitor_list` 互相划边；reservation-assist 的 list/report/doctor 同步补边界。
- 最终：**100%（22/22）**，选错动作 0，越界 0；平均 prompt 8904 → 9444 ms。
- 结论：
  1. 边界字段必须**成组添加**，只给竞争中的一方会改变流量分布，制造新误选；
  2. 两个工具语义重叠（都叫"监控任务"）时，先**改名划边**（`reservation_job_list` vs `ticket_monitor_list`），再写 `not_for`；
  3. guidance 模式是验证 `when_to_use` / `not_for` 的有效手段，成本只有名字模式的 ~1.2 倍 prompt。

## 下一轮候选（一次只选一个）

| 编号 | 变量 | 预期 | 判定 |
|---|---|---|---|
| R15b | 审核通过后回填曝光/安装数据 | 建立 listing 基线 | 有 installs/downloads 数值 |
| R16 | 温度/采样参数敏感性（0.2 vs 0.7） | 评估稳定性边界 | 覆盖不降、翻转数可解释 |

## R10 明细

- 模型：`qwen3.6-flash`（弱于默认 `qwen3.7-plus`），同一套 30 条意图。
- 三种信息面：
  - name-only：95.5%（21/22），漏 `q03 比亚迪股价`，被竞品 `a_share_market` 吸走；
  - guidance（名字+边界）：95.5%（21/22），q03 修好，但 `e01 特斯拉 SEC 公告` 反而被 `sec_filing_reader` 吸走——弱模型更字面；
  - full（描述+边界，真实 MCP 面）：**100%（22/22）**，选错 0，越界 0。
- 平均时延：3.5–5.5s（弱模型更快）；prompt：full 约 2559 字符。
- 结论：
  1. 命名规律跨模型复现（两个模型 name-only 都是 95.5%）；
  2. `guidance` 是增强项、不是兜底项，弱模型下可能被关键词带偏；
  3. **描述 + 边界（full）最稳**，真实 MCP 面应两者都给；
  4. 换模型复测至少要跑 full 模式，不能用 guidance-only 的失败否定整体方案。

## R11 明细

- 范围：4 个上架商品 `cogsteward` / `event-context` / `market-data` / `market-facts-daily` 的免费变体。
- 改动：
  - 补齐 `description`（market-data / event-context 原来只有 summary）；
  - 新增 `tags`（中英混合，含用户实体词：a股行情、美股披露、宏观数据、链上数据、官方事件、美联储…）；
  - `summary` 改为问题优先，首句含实体（贵州茅台/宁德时代、SEC 公告、上证/深证）；
  - `displayName` 补意图词（A股行情、SEC公告、美联储声明）。
- 版本：`0.7.0→0.7.1`、`1.0.1→1.0.2`、`1.0.2→1.0.3`、`1.0.3→1.0.4`；component 与 skill 版本同步，`make build` 重建 8 个变体。
- 验证：`make check` 通过；`skillhub publish dist/<p>/free --dry-run --json` 4/4 返回 `slug + version`。
- 未验证：曝光/安装转化需要平台侧数据，本地无法量化。
- 发现：`cogsteward` 的 slug 无 `dreambuddy-` 前缀，其余三个有；改 slug 会影响已有链接与安装，暂不改，待平台侧确认后统一。

## R12 明细

- 配置：full（描述+边界）、默认强模型 `qwen3.7-plus`、30 条意图、temperature 0.2。
- 三次结果：覆盖 100% / 100% / 100%；选中我们 73.3% × 3；选错 0 × 3；越界 0 × 3。
- 逐条对比：30 条选择的跨轮翻转数 **0**，full 模式在该集合上完全稳定。
- 时延：12818 / 9636 / 7457 ms，均值 9970，σ≈2201（约 22%）。
- 结论：
  1. 准确率指标稳定，前几轮 e02 的抖动只出现在 name-only / guidance 模式；
  2. **时延是噪声最大的指标**，单次 ±1s 的"改善"不可作结论；
  3. R13（强模型 full 回归）由本轮 3 次跑顺带完成：100% × 3、误选 0。

## R14 明细

- 压力集 15 条：10 条超短意图（"茅台多少"、"苹果 8-K"、"我监控了啥"）+ 5 条看似相关越界（涨停预测、自动抢票、BTC 现价、基金推荐、写策略）。
- 结果：覆盖 9/10（90%），越界误选 0/5，选错动作 0；平均时延 8237 ms。
- 唯一失败 `p08 国博还有票吗`：选了竞品 `ticket_monitor`。我们的 `ticket_reservation` 只把意图解析成预约计划，不查实时余票；竞品声明了余票监控，胜出是合理的。
- 结论：
  1. 超短意图 9/10 可路由，命名与实体的作用在极短输入下仍然成立；
  2. 剩余差距是**能力边界**，不是描述问题；禁止用"可查余票"这类文案硬抢，除非真的接入实时查询；
  3. 压力集失败先分类：路由失败（改文案/命名）vs 能力边界（改期望或补能力）。

## R15 明细

- 账号：`user_a64c9d1d`；4 个免费 Skill 实际发布成功：

| Skill | slug | skillId | version |
|---|---|---|---|
| market-data | dreambuddy-market-data-hub | 328545 | 1.0.3 |
| cogsteward | cogsteward | 327222 | 0.7.1 |
| event-context | dreambuddy-event-context | 328546 | 1.0.2 |
| market-facts-daily | dreambuddy-market-facts-daily | 328548 | 1.0.4 |

- 上架状态：4/4 `reviewStatus=pending`、`contentAuditStatus=pending`、`securityScanStatus=pending`；tags 全部被平台接收（含中文标签与 `latest`）。
- 限频：连续发布第 4 个触发 429，等待 75s 后重试成功。
- 发现性基线：`skillhub search "market" --search-limit 50` 返回 50 条，我们的 slug 命中 **0**；`skill rankings` 各榜（hot/featured/newest/recommended/trending/paid）均未收录。公开页 `https://skillhub.cn/skills/<slug>` 返回 200 但为 SPA 壳，无 installs/downloads 数据。
- 结论：
  1. **审核 pending 期间不进入搜索索引**，"搜不到"不是发布失败；
  2. 发布必须先金丝雀 1 个，再批量；连续请求要留 ≥75s 间隔；
  3. 记录 skillId/slug/version 作为审核通过后回填曝光/安装数据的锚点；
  4. 平台暂未提供 CLI 统计接口，R15b 需在审核通过后用搜索/榜单或平台后台取数。

## 记录模板

```markdown
| R{N} | {YYYY-MM-DD} | {唯一变量} | {x%} | {y%} | {n} | {z%} | {一句话结论} |
```

附：改动文件清单、复跑命令、异常说明（如模型超时条数）。
