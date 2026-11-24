# SPEC — 内容优化引擎（content-optimizer）P0 可行性验证 v0.1

> **更新日期**：2026-11-24 ｜ **版本**：v0.2 ｜ **状态**：已确认；P0-A 抖音滚动采集补齐 1-50 排名分层，**G0 复核恢复通过**（抖音去重后 103 条、适用覆盖 63.4%）；P0-B 去重后 137 条（小红书 34 + 抖音 103）探索性分析 → **No-Go**（G1/G2/G5 未达标）
> **v0.2 变更（2026-11-24）**：① G0/G1/G2/G5 从「功能上线门禁」降级为「**权重启用门禁**」——功能（建议/打分/留痕）先上线，证据未达标时权重全为 `prior`、`gate_status=no_signal`，输出自报证据不足；② 新增 §17 目标架构与闭环（S0 重训 → S1 发布前优化 → S2 发布回流 → S3 每日反思）；③ 新增 §18 CLI 契约层决策（不注册 59 组件，走路径注入）。
> **上游**：[SPEC-B 59 域全生命周期 · 框架与操作流程](./SPEC-20261121-59域全生命周期-框架与操作流程-v0.1.md)
> **关联**：[33-REA 逆向解析工程](../../33-REA逆向解析工程/README.md)、[手机内容发布参考](../components/mobile-reservation-assist/skill/references/xiaohongshu-publishing.md)、[抖音发布参考](../components/mobile-reservation-assist/skill/references/jianying-douyin-publishing.md)
> **一句话**：用“行为级逆向 + 自身账号实验闭环”验证小红书/抖音的内容可控特征是否存在稳定、可复现、可行动的信号；P0 只做验证，不建组件、不改生产代码。

---

## 0. 决策记录（用户已确认）

| 日期 | 决策 | 口径 |
|---|---|---|
| 2026-11-24 | 接受结论口径 | **行为级逆向 + 实验闭环**；不追求解析平台推荐算法本体 |
| 2026-11-24 | 数据边界 | **仅公开信息流 + 自己账号后台**；不做服务端逆向、反编译、批量爬虫、多账号矩阵 |
| 2026-11-24 | 推进顺序 | 先 SPEC → 再 P0 可行性验证 → Go 后才正式建 `content-optimizer` |
| 2026-11-24 | 账号与赛道 | 小红书 + 抖音各 1 个自有账号；沿用现有 5 个赛道（财经/经济/时事/AI Agent/数据服务） |
| 2026-11-24 | 浏览器自动化边界 | **仅允许自己账号后台**；公开信息流仍走手机端只读浏览，不用浏览器自动化抓公开页 |
| 2026-11-24 | 开工确认 | 认可 G0–G5 门禁；P0-A 采集通道验证启动 |

本 SPEC 的 P0 结论只有三种：`Go`（建组件）、`Conditional-Go`（补样本后复审）、`No-Go`（不建，保留报告）。

---

## 1. 结论与口径

### 1.1 能做什么、不能做什么

| 目标 | 判定 | 理由 |
|---|---|---|
| 拿到小红书/抖音排序模型或权重 | **不可行** | 排序在服务端，闭源；客户端不含模型 |
| 反编译客户端拿特征/接口参数 | **低价值、高风险，不采用** | 拿不到权重；违反平台规则与合规红线 |
| 观测公开爆款并提取内容特征 | **可行** | 现有 `xhs/douyin scout` 已能只读浏览与读取卡片 |
| 推断“内容特征 ↔ 流量表现”的关联 | **可行（探索性）** | 公开样本无曝光分母，只能产生假设，不能宣称因果 |
| 在自己账号做随机对照实验 | **可行（唯一因果路径）** | 需要人工发布 + 后台数据回流；P1/P2 落地 |
| P0 直接证明“改标题就能涨流量” | **不可行** | 单账号样本量与混杂因素不支持；P0 只做信号筛选 |

### 1.2 REA 的准确定位

REA 是“本地只读、静态 AST 分析”，只分析可读源码，不执行目标程序（[README 定位](../../33-REA逆向解析工程/README.md)、[能力表](../../33-REA逆向解析工程/README.md)）。因此：

- **不作为主路径**：不能解析平台推荐算法。
- **可选辅助**：若后续确需理解客户端推荐理由文案、入口参数或埋点字段，可在 P2 做一次性取证；结论必须标注 `inference`，不得作为验收证据。
- **本 SPEC 不包含任何反编译、破解签名、服务端接口逆向任务**。

---

## 2. 目标与非目标

### 2.1 P0 目标

回答一个问题：**在“公开信息流 + 自己账号后台”的数据边界内，内容可控特征与流量表现之间是否存在足够稳定、可复现、可行动的信号，值得投入建组件？**

P0 必须产出：

1. 一套可复用的样本 schema 与采集日志；
2. 一份带置信区间、效应量、时间切分复现与负对照的分析报告；
3. 一份机器可读的 `go_no_go.json`，逐门禁给出通过/不通过与理由。

### 2.2 非目标

- 不建 `content-optimizer` 组件、不改 `components/`、`contracts/`、`tools/dreambuddy.py`；
- 不自动发布、不接 `publish_note`、不做多账号矩阵；
- 不承诺流量、不输出“保证爆款”类结论；
- 不做平台算法本体逆向、不反编译、不爬取非公开接口；
- 不在 P0 做因果结论；因果验证放在 P1 的自身账号随机对照实验。

---

## 3. 现状取证

### 3.1 已有能力（可直接复用）

| 能力 | 现状 | 证据 |
|---|---|---|
| 小红书爆款侦察 + 图文填稿 | 浏览信息流、读前 N 篇、可选点赞/收藏；填稿停在发布前 | `components/mobile-reservation-assist/skill/scripts/phone_adapters/xiaohongshu.py` |
| 抖音图文/视频侦察 + 填稿 | 搜索赛道、读卡片互动量；填稿停在发布前 | `components/mobile-reservation-assist/skill/scripts/phone_adapters/douyin.py` |
| 内容链路命令 | `xhs/douyin scout/trends/collect/data/compose/cover/post/chain` | 59 副本 `component.yaml` actions |
| 内容生产管线 | 研究文档、博文草稿、社媒物料包、指标记录/汇总 | `tools/content.py`（`render/blog/social/metrics`） |
| 业务闭环定义 | S0 数据快照 → S1 研究 → S2 博文 → S3 物料 → S3.5 手机填稿 → S4 回流 | SPEC-B §5 |
| 合规闸门 | 荐股/收益/导流词硬阻断；发布保持人工 | SPEC-B §5 |

### 3.2 关键缺口

| 缺口 | 影响 | P0 处理 |
|---|---|---|
| `ops/metrics.csv` 当前不存在，回流靠人工补录 | 没有稳定的效果分母，闭环断裂 | P0 先建“样本表 + 采集日志”，不依赖生产 CSV |
| 公开样本只有点赞/收藏/评论，没有曝光 | 无法算点击率/完播率，只能做代理指标 | 公开样本只做探索性排序；自己账号后台提供曝光/完播 |
| 现有 scout 默认读“前 N 篇爆款” | 幸存者偏差，只看到被推流样本 | P0 改为按 rank 分层抽样，纳入中低排名样本 |
| scout 回传格式未实测 | 适配器当前只生成 `read_note(index=0)` 步骤，能否回传 N 条结构化样本未知 | P0-A 先做采集通道验证；不足则人工录入 |
| 组件族与输出契约受限 | `family` 是枚举，`output_contract` 只允许 4 个 profile | P0 不注册组件；Go 后再扩展 schema |

契约限制证据：`contracts/component.schema.json` 的 `family` 枚举与 `output_contract` 白名单；`contracts/data-sources.yaml` 规定“未登记源一律不可商用，新增源先登记再写代码”。

---

## 4. 数据边界（硬约束）

### 4.1 允许

| 来源 | 方式 | 限制 |
|---|---|---|
| 公开信息流 | 手机端人工可见页面、现有 `scout` 只读浏览 | 限频；不登录他人账号；不抓评论用户信息 |
| 自己账号创作者后台 | 人工导出 CSV/截图，或仅登录自己账号的浏览器自动化 | 凭据只存本地 Keychain/受限文件，不上云 |
| 自己账号发布记录 | 现有 `metrics` 记录 + 后台导出 | 需要 `content_id/platform/published_at` 可对齐 |

### 4.2 禁止

- 反编译 APK、破解签名、调用非公开服务端接口；
- 批量爬虫、代理池、验证码绕过、多账号矩阵；
- 刷量、控评、自动评论、搬运他人图文/视频；
- 采集他人私信、评论者身份、非公开数据；
- 把凭据、原始样本、账号数据上传云端或写入对外商品。

### 4.3 数据最小化与留存

- 公开样本：本地只存 `url_hash + 标题（≤100 字）+ 派生特征 + 互动计数`，**不存图片/视频/正文全文**；
- 自己账号：可存全文与指标，仅本地；
- 原始样本留存 **180 天**，到期删除；报告只保留聚合结果与匿名样例；
- 出现账号警告、限流、验证码升级等风控信号：**立即停采**，写入 `collection_log.jsonl`，P0 暂停并回报。

---

## 5. 研究假设

| 编号 | 假设 | 验证方式 | 失败含义 |
|---|---|---|---|
| H1 | 公开样本中，内容可控特征与表现存在稳定关联 | 分层 + 时间切分 + bootstrap | 无稳定关联 → No-Go |
| H2 | 同一账号随机化改变单一特征可产生可测差异 | Go 后的 P2 随机对照实验 | P0 不验证，只输出实验设计 |
| H0 | 不存在可行动信号 | 全部门禁 | 不建组件 |

**负对照**：加入 2 个与内容质量无关的特征（如标题字数奇偶、发布时间分钟奇偶）。若负对照也显著，判定模型过拟合或存在时间混杂，结论降级。

---

## 6. P0 样本与字段设计

### 6.1 抽样设计

| 项 | 设计 |
|---|---|
| 样本单位 | 一条笔记 / 一条视频 |
| 平台 | 小红书、抖音（分别建模，不混池） |
| 赛道 | 沿用现有 5 个：财经 / 经济 / 时事 / AI Agent / 数据服务 |
| 时间窗 | 连续 4 周；同一查询至少在 3 个不同日期、2 个时段采集 |
| 排名分层 | 每个查询按信息流/搜索结果位置分 3 层：1–10、11–30、31–50；每层都要有样本 |
| 作者去重 | 同一作者最多 2 条，降低作者权重混杂 |
| 公开样本量 | 每平台 ≥150，合计 ≥300 可用样本 |
| 自己账号样本 | 全部历史发布 ≥30 条，其中 ≥20 条有曝光/播放数据；不足 30 条按实际量运行并降级为 `Conditional-Go` |
| 排除 | 广告/带货、搬运、非目标赛道、发布不足 7 天（指标未稳定） |

**关键修正**：不得只采“爆款”。必须同时采中低排名样本，否则无法区分“内容特征”与“平台已推流”。

### 6.2 字段表（P0 最小集）

| 组 | 字段 | 说明 |
|---|---|---|
| 标识 | `sample_id/platform/source_type/url_hash` | `source_type ∈ {public, own}`；不存原始 URL |
| 采集 | `query/rank_bucket/collected_at/collector` | 记录抽样位置与时间，支持分层 |
| 作者 | `author_followers_bucket` | 分桶（<1k/1k–1w/1w–10w/≥10w），不存作者身份 |
| 时间 | `published_at/publish_hour/weekday` | 统一 Asia/Shanghai |
| 内容 | `title/title_len/title_pattern/body_len/topic_count/hashtag_count/cover_type/media_type/duration_sec/first3s_text_present` | 标题截断 100 字；其余为派生特征 |
| 公开表现 | `likes/saves/comments/shares` | 缺失记 `null`，不记 0；另记 `metrics_at` |
| 自有表现 | `impressions/views/cover_ctr/avg_watch_sec/completion_rate/two_sec_bounce/follows` | 后台有则填，无则 `null` |
| 质量 | `missing_flags/outlier_flags/is_censored` | 右删失（发布不足 7 天）标记 |

### 6.3 指标口径

**字段覆盖口径（2026-11-24 补充）**：

```text
raw_coverage        = 非空字段数 / 34                     # 含 7 个自有账号专属指标，公开样本必然偏低
applicable_coverage = 非空字段数 / 适用字段数(=27)          # 分母排除 impressions/views/cover_ctr/
                                                          # avg_watch_sec/completion_rate/two_sec_bounce/follows
```

- G0 门禁用 `applicable_coverage`；报告同时给出 `raw_coverage`，两者差值即“结构性不可得字段”；
- 分析阶段只用实际采集到的字段，禁止用缺失字段构造特征或用 0 填充。


```text
公开互动代理 = (likes + saves + comments + shares)
公开主指标   = 同平台×同粉丝桶×同排名层内的互动代理百分位（0–100）
自有 CTR     = views / impressions
自有互动率   = (likes + saves + comments + shares) / views
自有完播率   = avg_watch_sec / duration_sec（仅视频，后台有则用后台值）
自有涨粉率   = follows / views
```

公开样本没有曝光分母，**不得**把“互动代理”解释为点击率或完播率；报告必须显式标注该局限。

### 6.4 采集通道验证（P0-A，先于信号分析）

P0 分两段，避免在采集不可行时直接进入分析：

| 段 | 目标 | 通过标准 | 不通过处理 |
|---|---|---|---|
| P0-A 通道验证 | 确认现有 scout + 后台导出能稳定产出结构化样本 | 1 周内可获 ≥30 条/平台结构化记录；字段覆盖按**适用字段**口径 ≥70%（小红书）/ ≥40%（抖音，生产适配器仅回传 5 类字段）；无需改生产代码 | 改为人工录入模板；仍不可行则 `No-Go` |
| P0-B 信号验证 | 累积 ≥300 公开 + ≥30 自有样本并跑完整分析 | 通过 §9 门禁 | 按 §9 判定 |

采集入口（不改代码，直接调用现有命令）：

```bash
# 主仓/59 代理壳均可；具体路径以当前同步版本为准
python3 scripts/mra.py xhs scout --track "财经,经济,时事,AI Agent,数据服务" --limit 8 --json
python3 scripts/mra.py douyin scout --track "财经,经济,时事,AI Agent,数据服务" --limit 8 --json
```

若 scout 只回传少量详情，允许用手机截图 + 人工录入 ≥30 条作为 P0-A 的兜底；人工录入模板必须与 §6.2 字段一致。

---

## 7. 特征工程（确定性，不用 LLM 打标）

全部用正则/规则实现，保证同样输入多次运行结果一致：

| 特征 | 规则 |
|---|---|
| `title_pattern` | 数字开头 / 疑问句 / 对比句（vs、相比）/ 利益点（如何、3 步、避坑）/ 情绪词 / 陈述句 |
| `title_len` | 字符数（中文按 1，英文按单词） |
| `cover_type` | 文字封面 / 人像 / 图表 / 截图 / 纯色（人工抽检 50 条校准） |
| `topic_count` | `#` 话题数 |
| `body_len` | 正文字符数；公开样本只存长度不存正文 |
| `first3s_text_present` | 视频前 3 秒是否有字幕/口播文本 |
| `publish_hour/weekday` | 发布时间分桶 |
| `series_flag` | 标题是否含“第 N 期/系列/复盘”等 |

`cover_type` 若必须用视觉模型，只做离线小样本校准，不进入自动流水线；P0 以人工抽检为准。

---

## 8. 分析计划

### 8.1 数据质量

- 缺失率、重复率、取值范围、时间分布；
- 同一作者重复、同一内容跨平台重复；
- 公开样本的 `metrics_at` 与 `published_at` 间隔必须 ≥7 天。

### 8.2 单变量

- 按平台 × 体裁 × 粉丝桶 × 排名层分层；
- 效应量：Cliff's delta（连续）或率比（计数）；bootstrap 95% CI（≥1000 次）；
- 多重比较：Benjamini–Hochberg FDR，报告 q 值；
- 不把 `p<0.05` 单独当结论。

### 8.3 多变量

- 特征数 ≤8，避免小样本过拟合；
- 主模型：弹性网 Logistic（因变量：是否进入同层前 25%）或负二项回归（计数）；
- 敏感性：梯度提升树 + permutation importance；
- 验证：按时间切分（前 70% 训练、后 30% 测试）；嵌套交叉验证；
- 报告：out-of-sample AUC / Spearman、校准曲线、特征方向稳定性。

### 8.4 稳定性与负对照

- 200 次 bootstrap，统计特征方向一致率；
- 第二个时间窗或第二个赛道复现；
- 负对照特征必须不显著；若显著，结论降级并排查时间/账号混杂。

### 8.5 自己账号

- 描述性统计 + 同星期/同时段配对；
- 估计基线方差与最小可检测效应，为 P2 随机化实验定样本量；
- P0 不宣称因果。

---

## 9. Go / No-Go 门禁

| 门禁 | 通过标准 | 测量 |
|---|---|---|
| G0 通道可行 | 现有 scout + 后台导出可稳定产出结构化样本；1 周 ≥30 条/平台；**字段覆盖按适用字段口径**：小红书 ≥70%、抖音 ≥40%（2026-11-24 用户确认分平台阈值）；不改生产代码 | P0-A 通道报告 |
| G1 数据充足 | 公开可用 ≥300；自有 ≥30 条且 ≥20 条有曝光/播放；关键字段缺失 <30%；重复 <5%（2026-11-24 用户确认：先按现有 72 条推进，G1 未达标时结论最高只能 `Conditional-Go`） | `samples.csv` + 质量报告 |
| G2 信号存在 | ≥2 个可控特征 out-of-sample `abs(rho)≥0.20` 或 `AUC≥0.60`；相关系数 95% CI 不含 0，AUC 的 95% CI 下界 >0.5；BH `q≤0.10`；bootstrap 方向一致率 ≥70% | 分析报告 |
| G3 可行动 | ≥1 个特征对应确定性改写规则，且最高/最低分位相对差 ≥10% | 改写规则清单 |
| G4 合规 | 0 违规、0 账号警告、采集在限频内 | `collection_log.jsonl` |
| G5 可复现 | 第二个时间窗或赛道中 ≥1 个特征方向一致 | 复现报告 |

**判定规则**：

- `Go`：G0–G5 全通过；
- `Conditional-Go`：G0/G1/G4 通过，G2 仅有 1 个特征或 CI 边缘 → 扩样后复审；
- `No-Go`：G0 失败、G2 失败、G3 失败、G4 失败，或负对照显著且无法解释。

任何 `No-Go` 都必须保留报告与数据 schema，供后续复用；不删除证据。

---

## 10. P0 交付物与工程约束

### 10.1 交付物

```text
platform/lab/content-optimizer-p0/
  schema.json                 # 样本字段与类型
  samples.csv                 # 本地样本（不入库、不上云）
  collection_log.jsonl        # 每次采集：query/rank/时间/结果/异常
  events/content_event.jsonl  # content_event.v1 事件流（埋点）
  raw/<run_id>.json           # scout 原始回执（本地）
  analysis/
    report.md                 # 数据质量、效应量、模型、局限、结论
    go_no_go.json             # 逐门禁结果与理由
    figures/                  # 可选图表
  scripts/                    # 一次性采集/分析脚本（不进入组件）
                              #   collect_p0a.py      通道自检 + 抖音 scout 采集
                              #   collect_xhs_u2.py   小红书只读 u2 采集（P0-A 兜底）
                              #   analyze_p0b.py      小样本探索性分析 → go_no_go.json
                              #   build_model.py      samples + 门禁 → model/optimizer_model.json
                              #   retrain_daily.py    幂等重训 → model/ + model/history/
  model/
    optimizer_model.json      # 优化模型（P0 结论 No-Go → gate_status=no_signal）
    history/YYYYMMDD.json     # 每日重训留档（drift + 模型快照）
  tests/                      # 采集器 / 分析 / 建模 / 重训单测（不进入组件）
```

### 10.2 工程约束

- **不改生产代码**：`components/`、`contracts/`、`tools/dreambuddy.py` 全部冻结；需要改动时先停并回报。
- P0 脚本只允许放 `platform/lab/content-optimizer-p0/scripts/`，不被任何组件 import。
- 采集优先用现有 `mra xhs|douyin scout`；后台数据优先人工导出，浏览器自动化仅用于自己账号。
- 所有数字可追溯：报告中的每个效应量必须能回指 `samples.csv` 的行与计算脚本。

### 10.3 埋点与监控点契约（P0-A 起生效）

**原则**：一个事件流、三层消费、最小集；埋点 FAIL-OPEN，写失败不影响主链路。

| 层 | 数据 | 消费方 | 留存 |
|---|---|---|---|
| 实验埋点 | 事件级 JSONL，高粒度，本地 | P0/P1 分析 | 180 天 |
| 监控点 | 按分钟/小时聚合的 SLI | 巡检/告警 | 长期指标表 |
| 审计点 | 写/发布事件，append-only | 发布台账 | 长期 |

**事件统一字段**：

```json
{
  "event_id": "sha256(trace_id|stage|job_id)",
  "ts": "2026-11-24T12:00:00+08:00",
  "trace_id": "note:scout:...",
  "run_id": "p0a-20261124-001",
  "stage": "collect.result",
  "action": "xhs.scout",
  "status": "requested|ok|degraded|done|timeout|error|empty",
  "error_code": "NO_DEVICE|GATEWAY_DOWN|AUTH|RATE_LIMIT|LAYOUT_CHANGED|TIMEOUT|PARSE_ERROR|",
  "duration_ms": 60250,
  "counts": {"in": 0, "out": 0, "dropped": 0},
  "schema_version": "content_event.v1",
  "refs": {"raw_sha256": "...", "trace_path": "..."},
  "detail": {}
}
```

**P0-A 只埋 4 类事件**：

| 事件 | 关键字段 | 监控用途 |
|---|---|---|
| `channel.check` | `gateway_ok/devices_count/adb_ok/token_ok` | 通道可用性 |
| `collect.request` | `platform/track/limit/run_id` | 采集请求基线 |
| `collect.result` | `status/duration_ms/items_returned/fields_present/error_code` | 成功率、样本产出率 |
| `collect.parse` | `rows_in/rows_valid/missing_fields/parse_errors` | 字段覆盖率、解析质量 |

**与现有链路的关系**：手机侧已有 `phone_monitor.record()` 的 `traces/YYYYMMDD.jsonl`（字段 `ts/trace_id/stage/action/ok/state/duration/page_text/screenshot/error/detail`）。本契约不复制这些字段，只通过 `trace_id/job_id` 关联；`page_text` 与截图不进入监控指标。

**后期转监控点（聚合口径，不在 P0 设阈值）**：

| 监控点 | 计算 | 阈值时机 |
|---|---|---|
| `channel_availability` | `channel.check.gateway_ok` | P0 基线后 |
| `collect_success_rate` | `done / request` | P0 基线后 |
| `sample_yield` | `items_returned / request` | 连续 3 次为 0 告警 |
| `field_coverage` | `fields_present / 34`（不含 3 个元字段） | <70% 触发 G0 不通过 |
| `parse_success_rate` | `rows_valid / rows_in` | <80% 告警 |
| `timeout_rate` | `timeout / request` | 连续 2 次告警 |
| `model_auc_oos/psi` | P1 模型事件 | P2 起 |

**硬约束**：

- 事件写失败必须吞掉异常并继续主流程；不允许因为埋点导致采集中断。
- 监控指标不得使用 `content_id/title/url` 作为标签；原文只进本地事件明细。
- 同一 `event_id` 重复写入由消费端去重，不依赖写入端事务。
- 错误码必须使用上表枚举，新增错误码先改契约再写代码。
- 阈值不在 P0 拍定；先积累基线，再由监控投影任务配置。

---

## 11. 若 Go：P1 组件设计草案（不在本 SPEC 实施）

### 11.0 阶段划分

| 阶段 | 范围 | 前置 |
|---|---|---|
| P0 验证 | 采集通道 + 信号筛选 + Go/No-Go | 本 SPEC 评审通过 |
| P1 组件 MVP | `ingest/features/score/advise`，规则卡 + 可解释模型 | P0 = Go |
| P2 实验闭环 | 自身账号随机对照 + `feedback` 回流 + 统计检验 | P1 可用 |
| P3 自动化 | 自动回流、漂移监控、定时报告 | P2 证明有效 |

### 11.1 组件元数据

```yaml
name: content-optimizer
display_name: 内容优化引擎
family: content-optimizer        # 需扩展 contracts/component.schema.json 枚举
version: 0.1.0
lifecycle: draft
entrypoints: [scripts/content_optimizer.py]
kernel_deps: []
output_contract: data.v1         # 首版复用 data.v1，不新增 profile
tests: {dir: tests, entry: "python3 -m unittest discover -s tests -v"}
```

若确需独立 `content.v1`，必须先在 `contracts/output.schema.json` 增加 profile，再改组件；不得私自定义。

### 11.2 动作边界

| 动作 | safety | 作用 | MCP |
|---|---|---|---|
| `ingest` | write（本地） | 标准化 scout/后台导出为样本表 | extended |
| `features` | read | 确定性特征提取 | extended |
| `fit` | write（本地模型） | 训练/更新评分模型与漂移基线 | extended |
| `score` | read | 草稿打分 + 缺失项 | hot |
| `advise` | read | 输出标题/封面/话题/时段改写 patch | hot |
| `experiment-plan` | read | 生成随机化发布计划与样本量 | extended |
| `feedback` | write（本地） | T+1/T+7 指标入库 | extended |
| `report` | read | 周报 + 漂移告警 | extended |

### 11.3 与手机 AGENT 的集成

```text
mra xhs chain / douyin chain
  → 生成 pack.json
  → dreambuddy content-optimizer advise --draft pack.json
  → 返回 patches[]（标题备选/封面建议/话题/时段）
  → mra xhs|douyin post（停在发布前）
  → 人工点发布
  → feedback 导入 T+1/T+7
```

组件只消费本地文件，不直接抓取平台；采集仍由手机 AGENT 承担。`publish_note` 永不暴露。

### 11.4 契约与治理改动（Go 后）

1. `contracts/component.schema.json`：`family` 增加 `content-optimizer`；
2. `contracts/data-sources.yaml`：登记平台公开信息源为 `commercial_use: forbidden`，注明“仅本地内部研究、不进入对外输出、不二次分发”；自己账号后台数据单独登记为内部源；
3. `tools/gen_index.py --write` 更新 INDEX；
4. `make check` 全绿；
5. 测试覆盖：契约、确定性、无网络、缺失数据、合规词阻断、发布禁止。

---

## 12. 风险与缓解

| 风险 | 后果 | 缓解 |
|---|---|---|
| 幸存者偏差 | 只看到已推流样本，模型学成“平台偏好” | rank 分层抽样；纳入中低排名；作者去重 |
| 公开样本无曝光分母 | 只能做代理指标，结论易误读 | 报告显式降级；自有账号后台补分母 |
| 单账号样本少 | 统计功效低，假阴性/假阳性 | P0 只做信号筛选；P0 扩样 + P2 随机化 |
| 作者/时间混杂 | 把账号权重当内容特征 | 分层、配对、时间切分、负对照 |
| 算法漂移 | 模型过期 | 规则卡兜底 + 滚动重训 + 漂移告警 |
| 平台风控/规则 | 限流、封号 | 限频、只读公开页、不做互动诱导；风控信号即停 |
| 隐私/版权 | 合规风险 | 不存他人图片/正文；只存 hash + 派生特征；180 天删除 |
| 多重比较/过拟合 | 假发现 | BH-FDR、时间切分、bootstrap、负对照 |
| LLM 建议幻觉 | 错误改写 | P0/P1 建议以确定性模板 + 证据为主；LLM 只做润色 |

---

## 13. 待确认事项

| 编号 | 问题 | 建议默认 |
|---|---|---|
| Q1 | 用哪些账号/平台？ | 小红书 + 抖音各 1 个自有账号 |
| Q2 | 主 KPI 优先级？ | 自有：收藏率 + 涨粉率；公开：互动代理百分位 |
| Q3 | 后台数据获取方式？ | 先人工导出；稳定后再评估仅自己账号的浏览器自动化 |
| Q4 | 采集频率与总量？ | 每平台每日 ≤3 次查询、每次 ≤8 条；4 周累计 ≥300 |
| Q5 | 留存与删除？ | 原始样本 180 天；报告长期保留 |
| Q6 | 是否需要独立复评？ | 建议 P0 报告完成后做一次三视角评审（架构/统计/合规） |

---

## 14. 验收清单

- [x] 用户确认本 SPEC 与数据边界；
- [x] P0-A 外挂埋点落地（`platform/lab/content-optimizer-p0/scripts/collect_p0a.py`，4 类事件 + 7 项单测）；
- [x] P0-A 采集通道实测（2026-11-24：小红书 38 条 / 适用字段覆盖 82.6%；抖音首轮 34 条 / 55.6%；G0 首轮通过，见 `platform/lab/content-optimizer-p0/analysis/P0A-通道验证报告-v0.1.md`）；
- [x] G0 复核（2026-11-24 22:05）：清理解析重复行后抖音唯一卡片 23 < 30，覆盖 53.1% 仍达标 → **G0 未通过（仅条数子项）**，待补样本；
- [x] G0 覆盖门禁分平台化（小红书 70% / 抖音 40%，适用字段口径，2026-11-24 用户确认）；
- [ ] 自有账号样本 ≥30 条（含 ≥20 条有曝光/播放），用于 G1；
- [x] P0-B 首轮探索性分析（去重后 68 条，非 300）：`analysis/P0B-信号验证报告-v0.1.md` + `analysis/go_no_go.json`，判定 **No-Go**（G1/G2/G5 未达标）；
- [x] P0-B 数据复核（2026-11-24 22:05，去重后 57 条 = 小红书 34 + 抖音 23）：占位标题清零、日期型点赞置空；重跑后 G0 转 FAIL、结论仍 **No-Go**；
- [x] 抖音卡片解析修复（2026-11-24）：`phone_flows/douyin.py::parse_scout_cards` 排除点赞按钮 content-desc（「未点赞，喜欢X，按钮」）与日期型点赞（「09.05」），标题与点赞量按最近距离一对一配对；真机复采 `p0a-20261124-215253-douyin` 已无占位标题；
- [x] 抖音滚动采集补齐 rank 分层（2026-11-24 22:22）：新增 `scripts/collect_douyin_u2.py`（双列卡片 x 轴配对、按钮 desc 点赞折叠、相关搜索/博主卡过滤、搜索框关键词回填校验），5 赛道共写入 114 条；财经单赛道 50 张卡覆盖 1-50 连续排名；
- [x] G0 复核恢复通过（2026-11-24 22:24，去重后 137 条 = 小红书 34 + 抖音 103）：抖音条数 103 ≥30、适用字段覆盖 63.4% ≥40%；rank_bucket 分布 1-10 / 11-30 / 31-50 = 36 / 30 / 14，另有 23 条历史 scout 行为 unknown；结论仍 **No-Go**（G1/G2/G5）；
- [ ] 修补结构缺口后重跑：自有账号样本接入、第二时间窗复现（rank 分层已补齐）；
- [ ] 样本 schema 冻结，字段口径无歧义；
- [ ] 采集日志完整，无合规事件；
- [ ] 分析报告含效应量、CI、FDR、时间切分、负对照；
- [ ] `go_no_go.json` 逐门禁可复核；
- [ ] 结论明确为 `Go` / `Conditional-Go` / `No-Go`；
- [ ] `No-Go` 或 `Conditional-Go` 时保留 schema 与报告，不删证据。

---

## 15. 自评审记录（v0.1，2026-11-24）

| 视角 | 发现 | 处理 |
|---|---|---|
| 统计 | AUC 的零假设不是 0；`abs(rho)` 原先写成带竖线形式会破坏表格 | 统一为 `abs(rho)`；相关系数 CI 不含 0、AUC CI 下界 >0.5 |
| 统计 | 公开样本无曝光分母，容易把互动代理当点击率 | §6.3 显式禁止该解释；结论降级为探索性 |
| 统计 | 多重比较、时间漂移、作者混杂 | 增加 BH-FDR、时间切分、作者去重、负对照 |
| 工程 | 现有 scout 只生成 `read_note(index=0)`，回传条数未证实 | 新增 P0-A 采集通道验证与 G0 门禁；允许人工录入兜底 |
| 工程 | 新增组件需改 `family` 枚举与 `output_contract` | P0 不注册；Go 后按 §11.4 改契约并跑 `make check` |
| 合规 | 平台公开内容可能涉及版权与 ToS | 只存 hash + 标题 + 派生特征；不存图片/正文；180 天删除 |
| 合规 | 自己账号后台凭据风险 | 仅本地保存；不上云；浏览器自动化仅限自己账号 |
| 产品 | P0 可能“做了很多但不可行动” | 增加 G3 可行动门禁与确定性改写规则要求 |

**未关闭**：独立三视角复评（架构/统计/合规）待 P0 报告完成后执行，见 Q6。

---

## 附录 A：与现有架构的关系

- 本 SPEC 是 [SPEC-B](./SPEC-20261121-59域全生命周期-框架与操作流程-v0.1.md) §5 业务闭环的“优化层”扩展：不改变 S0–S4 的数据流，只在 S3（物料）与 S4（回流）之间增加“评分/建议/实验”能力。
- P0 不新增组件、不改契约；Go 后才进入 59 组件登记流程。
- 手机 AGENT 仍是唯一执行源；本 SPEC 不复制手机业务逻辑。

---

## 16. 反思模块调研（顺风车 `content_reflect`）

> 调研日期：2026-11-24 ｜ 结论：**可复用，但只能作为“建议生成层”，不能替代 P0 的统计层**。

### 16.1 现状（已存在，不新建）

| 项 | 事实 |
|---|---|
| 位置 | 主仓 `mobile-reservation-assist/skill/scripts/content_reflect.py` |
| 输入 | `published.load()` 台账（最近 10 条，含标题/平台/发布时间）+ `fixed/runs/*/run.json`（近 12 次运行）+ `fixed/metrics.json`（按标题索引的流量） |
| 处理 | `brain.chat()` 单次调用，固定 prompt 要求输出 `{wins, issues, suggestions, next_actions, confidence}`；LLM 不可用时走确定性 `_fallback()` |
| 产物 | `fixed/reflections/YYYYMMDD.json/.md` + `latest.json` |
| 消费 | `latest_text()` 取 3 条 suggestions + 2 条 next_actions，注入下一次 `compose` 的提示词（“昨日反思建议”） |
| 调度 | `fixed` 定时任务 `reflect_hours=[10]`，每日 10 点跑一次 |
| 无数据处理 | `metrics_missing=True` 时禁止编数字，`confidence ≤ 0.5` |

### 16.2 与本 P0 的关系

- **互补**：P0 产出“特征 ↔ 表现”的可复核统计结论；`content_reflect` 产出面向次日的可执行建议。前者是证据，后者是行动。
- **可复用点**：① `metrics.json` 按标题索引，可直接作为 P0 `source_type=own` 样本的指标来源；② `latest.json` 的 `suggestions` 可作为 G3“可行动”的候选规则；③ 已有的“无数据禁编造 + confidence 上限”纪律与 P0 的负对照要求一致。
- **不能替代**：它没有统计检验、没有分层抽样、没有负对照，`confidence` 是 LLM 自评，不能当作 G2 证据。

### 16.3 接入建议（P1 再做，P0 不落地）

1. P0 结论（特征方向 + 效应量）作为 `content_reflect` 的**只读输入**，让建议由统计结论支撑，而不是纯 LLM 生成；
2. `content_reflect` 的 `published` 台账补 `content_id/url_hash`，与 `samples.csv` 的 own 行对齐，形成“发布→回流→反思→改写”闭环；
3. 反思建议进入改写规则前，必须先过 P0 的 G3 判据（最高/最低分位相对差 ≥10%），否则只作参考不作执行。

---

## 17. 目标架构与闭环（v0.2 新增）

> 目标：顺风车业务在**发布前**对小红书笔记 / 抖音视频做算法优化；**发布后**回流数据；**每天反思**并按积累数据重训；重训产物回注优化入口，形成闭环。

### 17.1 一句话架构

```text
samples.csv ──build_model──▶ optimizer_model.json ──load_model──▶ content_optimize.score()
      ▲                                    │                                  │
      │                                    │                         发布前建议（不阻断）
      │                                    │                                  ▼
      │                              retrain_daily                     mra fixed optimize
      │                                    ▲                          compose 注入规则
      │                                    │                                  ▼
      └── published 台账 + metrics.json ── content_reflect（每日反思） ◀── 发布 + 回流
```

### 17.2 闭环四段（S0–S3）

| 段 | 名称 | 入口 | 产物 | 生效边界 |
|---|---|---|---|---|
| S0 | 模型构建 / 每日重训 | `scripts/build_model.py`、`scripts/retrain_daily.py` | `model/optimizer_model.json`、`model/history/YYYYMMDD.json` | **只写模型文件**，不直接改线上打分逻辑 |
| S1 | 发布前优化 | `skill/scripts/content_optimize.py`、`mra fixed optimize`、`compose` 规则注入 | `{score, grade, findings, suggestions, evidence_status}` | **只建议不阻断**；发布仍人工确认 |
| S2 | 发布 + 回流 | `skill/scripts/published.py` 台账 + `fixed/metrics.json` | 发布记录、按标题索引的流量 | 不自动发布 |
| S3 | 每日反思 | `skill/scripts/content_reflect.py`（`reflect_hours=[10]`） | `fixed/reflections/YYYYMMDD.json` | 反思建议只作参考，需过 G3 才可执行 |

**闭环判定**：S0 产物被 S1 读取 → S1 建议影响 S2 发布 → S2 数据进入 S3 反思 → S3/S0 重训回注，四段缺一即为断链。当前断链点：**S2 自有样本 0 条、`metrics.json` 为空**，因此 S0 只能产出 `prior` 权重，S3 的 `confidence` 是 LLM 自评而非统计证据。

### 17.3 门禁降级：从「功能上线门禁」到「权重启用门禁」

P0-B 结论为 `No-Go`（G1/G2/G5 未达标）。v0.2 明确：**No-Go 否决的是"证据权重"，不是"功能"**。

| 门禁 | v0.1 含义 | v0.2 含义 |
|---|---|---|
| G0 通道可行 | 功能上线前置条件 | 采集通道可用性；不影响功能上线 |
| G1 数据充足 | 功能上线前置条件 | **权重启用**前置条件：样本不足 → 权重全 0 |
| G2 信号存在 | 功能上线前置条件 | **权重启用**前置条件：无稳定信号 → 权重全 0 |
| G3 可行动 | 功能上线前置条件 | 规则是否可执行；规则始终输出，但标注 `prior` |
| G4 合规 | 硬门禁 | **仍为硬门禁**：违规即停采、停用 |
| G5 可复现 | 功能上线前置条件 | **权重启用**前置条件：未复现 → 权重全 0 |

判定口径：

```text
gate_status = "evidence"    # G1 ∧ G2 ∧ G5 全通过 → 允许使用统计权重
            | "no_signal"   # 任一未通过（当前状态）→ 全部特征 weight=0、source=prior
```

**硬约束**：`gate_status="no_signal"` 时，任何输出**禁止**声称"该特征能提升流量"，必须显式返回 `evidence_status="insufficient"`。

### 17.4 No-Go 默认行为（功能上线后的表现）

| 能力 | No-Go 时行为 |
|---|---|
| 打分 `score()` | 仍返回 0–100 分，但分值只由**先验规则**决定，与统计权重无关 |
| 建议 `suggestions[]` | 只输出确定性改写建议（标题长度、问句/数字开头、话题数、前 3 秒字幕、发布时段），全部标注 `source=prior` |
| 证据 `evidence_status` | 固定 `"insufficient"`，附带未通过门禁列表 |
| 发布阻断 | **不阻断**；`mra composed` 只在提示词中追加规则，不改变发布流程 |
| 重训 | 照常运行并按幂等写 `history`，但因权重全 0，产物与线上一致 → 记 `no_change` |

### 17.5 模型文件契约（`optimizer_model.json`）

```json
{
  "schema_version": "1.0",
  "version": 1,
  "generated_at": "2026-11-24T23:00:00+08:00",
  "gate_status": "no_signal",
  "verdict": "No-Go",
  "source": {"rows": 175, "deduped": 137, "by_platform": {"xiaohongshu": 34, "douyin": 103}},
  "platforms": {
    "xiaohongshu": {"n": 34, "features": [{"name": "title_len", "n": 19, "rho": null, "status": "insufficient", "weight": 0.0, "source": "prior"}], "rules": []},
    "douyin": {"n": 103, "features": [], "rules": []}
  },
  "rules": []
}
```

字段口径：

- `gate_status ∈ {no_signal, evidence}`；`evidence` 才允许 `weight ≠ 0`；
- `source ∈ {prior, evidence}`；`no_signal` 时强制全 `prior`；
- `rules[]` 与 `platforms.<p>.rules[]` **始终存在**，与统计权重解耦；
- 缺失特征记 `null`，禁止用 0 填充（沿用 P0 §6.3）。

### 17.6 每日重训口径

| 项 | 口径 |
|---|---|
| 输入 | `samples.csv`（公开）+ 台账/`metrics.json`（自有，P1 接入后） |
| 确定性 | 同输入必得同输出（忽略 `generated_at`）；禁止随机种子漂移 |
| 幂等 | 与现模型比对（忽略 `generated_at` / `version`）；相同 → `no_change` 不写盘 |
| 有变化 | `version += 1`，写 `model/optimizer_model.json` + `model/history/YYYYMMDD.json` |
| drift 记录 | 新增/删除规则、权重变化、样本增量，写入 history 便于回溯 |
| 生效方式 | **只记录不生效**：权重要求 `gate_status="evidence"` 才被 `score()` 使用；否则仅留档 |

### 17.7 与 P0 / 生产代码的边界

- P0 目录（`platform/lab/content-optimizer-p0/`）仍是**验证与离线脚本**，新增 `build_model.py` / `retrain_daily.py` 只写 `model/` 与 `analysis/`，不被任何组件 import；
- 生产侧改动只在顺风车仓库（`mobile-reservation-assist/skill/scripts/`），不进主仓 `components/`、`contracts/`、`tools/dreambuddy.py`；
- 抖音视频的 `first3s_text_present` / `duration_sec` 在公开样本中结构性缺失，因此抖音打分**不得**复用小红书的图文权重，必须按平台独立给规则。

---

## 18. CLI 契约层决策：不注册 + 路径注入（v0.2 新增）

### 18.1 问题

是否要先把内容优化能力注册到 `59-通用组件管理` 的 CLI 契约层（`contracts/` + `tools/dreambuddy.py`），再实现顺风车两域打通？

### 18.2 结论：**不注册**

| 判断维度 | 事实 | 结论 |
|---|---|---|
| 组件族枚举 | `family` 为封闭枚举，内容优化无对应族 | 注册需改契约 schema |
| 输出契约 | `output_contract` 只允许 4 个白名单 profile | 打分结果无匹配 profile |
| 复用范围 | 目前只有顺风车一个业务域使用 | 不满足跨域复用前提 |
| 现状约束 | P0 SPEC §2.2 明确 P0 不改 `components/`、`contracts/`、`tools/dreambuddy.py` | 注册与 P0 约束冲突 |
| 收益/成本 | 注册需改枚举+契约+CI `make check`，收益仅"统一入口" | 成本高于收益 |

### 18.3 采用方案：路径注入

```text
mra.py（顺风车）
  └── import skill/scripts/content_optimize.py
        └── load_model(state_dir) 优先级：
              1. env CONTENT_OPTIMIZER_MODEL
              2. config  p0_model_path
              3. state_dir/fixed/optimizer_model.json
```

- 主仓 59 域**不新增组件、不改契约**；
- 模型文件由 P0 离线脚本生成，顺风车通过本地路径读取；
- 跨域调用（如未来其他业务域需要）再走注册流程。

### 18.4 未来触发注册的条件（满足任一）

1. ≥2 个业务域需要同一份内容优化能力；
2. 需要被 `tools/dreambuddy.py` 统一编排或写入 `output_contract`；
3. 需要跨机器/跨语言调用（此时才值得付出契约改造成本）。

届时按 §11.4 扩展 `family` 枚举与 `output_contract` 白名单，并跑 `make check` 验收。
