# SPEC — SkillHub 产品优化引擎 v0.1

> 模块：`59-通用组件管理/platform/optimizer/`
> 状态：P0/P1/P2 已落地（v0.1.0）

## 1. 为什么要有它

R0–R14 已经证明：agent 选不选我们，主要由**描述里有没有用户原话实体**决定，其次是工具命名、
边界声明与上架字段。但这套方法一直是手工动作，且只覆盖 SKILL.md 文案。

本引擎回答一个问题：**发布前，这个 SKILL / MCP 工具 / 商品页 / 定价包装，够不够容易被 agent 发现并选中？**

## 2. 定位与非目标

| 是 | 不是 |
|---|---|
| 内部发布门禁工具 | 对外售卖的优化服务 |
| 离线确定性代理评分 | 模型真实选择率的替代品 |
| 合规链的补充（可发现性） | 合规链的重复（frontmatter/402/密钥/体积） |

分工：

- `contracts/skill-quality-rules.yaml` → 能不能上架；
- `contracts/product-scorecard.yaml` → agent 会不会选你；
- `platform/bench/routing/run_bench.py` → 真实模型上的选择率真值（只由 `ab` 子命令调用）。

## 3. 架构

```
contracts/product-scorecard.yaml   评分卡单一源（5 维 20 规则）
platform/optimizer/
  loaders.py     四类对象 → Surface（component.yaml / dist SKILL.md / products yaml）
  evidence.py    实体、双语、跨字段重复词（纯文本，确定性）
  rules.py       8 类 check.type 解释器
  score.py       维度加权 + blocker / warn 聚合
  advise.py      Finding → before/after 建议
  gate.py        profile 门禁与退出码
  ab.py          复用 run_bench 的单变量 A/B
  report.py      Markdown 报告
  cli.py         card / score / advise / gate / ab / report
```

### 3.1 四类评分对象（Surface）

| kind | 来源 | 说明 |
|---|---|---|
| `skill_md` | `dist/<component>/<variant>/SKILL.md` | 发布态产物；缺失时回落 `components/<c>/skill/SKILL.md` |
| `mcp_tool` | `components/<c>/component.yaml` 的 actions | 只取 `mcp.expose && safety=read && output=json`，描述按 server 投影规则拼接 |
| `product_page` | `products/<p>.yaml` + 同名 dist SKILL.md | 标题/副标题/关键词/价格/模式 |
| `packaging` | `products/<p>.yaml` 的 variants | channel / price / trial / entrypoints |

### 3.2 五维与权重

| 维度 | 权重 | 回答的问题 |
|---|---|---|
| retrievability 可召回 | 30 | 描信号里有没有用户会说的实体与触发短语 |
| distinctiveness 可区分 | 25 | 有没有边界声明、同族工具名是否重叠 |
| trust 可信任 | 20 | 示例可复制、输出样例、许可证、版本 |
| conversion 转化 | 15 | 标题/副标题/关键词不浪费检索位、定价模式明确 |
| operability 可用 | 10 | 首跑命令、错误语义、输出契约 |

### 3.3 check.type

`entity_hit / intent_term / bilingual / boundary_declared / cross_field_dup /
length_range / field_present / evidence_present / family_distinct`

全部为纯文本或正则实现，保证同一输入多次运行结果逐字节一致。

## 4. CLI 契约

| 子命令 | 关键参数 | 输出 | 退出码 |
|---|---|---|---|
| `card` | `--check` | 评分卡结构校验 | 0/1 |
| `score` | `--all/--component/--product --profile --json [--include-draft]` | 五维分、总分、findings、证据 | 0/2 |
| `advise` | 同上 + `--min-severity` | 按严重度排序的改写建议 | 0/2 |
| `gate` | `--all --profile --offline --audit --include-draft` | blocker 清单 + 总分告警 | 0 通过 / 1 阻断 / 2 环境 |
| `ab` | `--ids --catalog-fields --repeats --dry-run` | 均值、2σ 噪声带、headroom 提示 | 0/1/2 |
| `report` | `--in --out` | Markdown 报告 | 0/2 |

## 5. 门禁策略

- `make check`：`card --check` + `gate --all --profile legacy --offline`；
- `make release`：`gate --all --profile new --offline`；
- `legacy`（存量）：只阻断 blocker，总分低只告警；
- `new`（新增商品）：blocker 阻断，总分告警线 75；
- `gate` 默认只评 `lifecycle: active` 组件，`--include-draft` 才纳入草稿；
- `score` / `advise` 的 `--all` 与 `gate` 同口径（默认 active，`--include-draft` 才含草稿）；
- `--product` 按字面取商品页与包装，不会被同名组件截走（如 `market-data`）；
- `--audit` 可选复用 `skillhub-audit-api` 的 `auditSkill`，补齐合规阻断项。

当前 blocker 集合（刻意收窄，避免存量商品被历史问题卡死）：

- `RET001` 描述里 0 个用户实体；
- `DIS004` MCP 工具描述为空/过短；
- `CON004` 收费渠道缺价格或售卖模式。

## 6. 验收

```bash
cd 59-通用组件管理
python3 -m unittest discover -s platform/optimizer/tests -v
python3 platform/optimizer/cli.py card --check
python3 platform/optimizer/cli.py score --all --profile legacy --json /tmp/s.json
python3 platform/optimizer/cli.py advise --component market-data --min-severity warn
python3 platform/optimizer/cli.py gate --all --profile legacy --offline; echo $?
python3 platform/optimizer/cli.py ab --dry-run --repeats 2
make check
```

## 7. 边界与风险

1. 离线分是**代理指标**：能判断"信号够不够"，不能判断"模型实际选谁"；最终结论必须由 `ab` 给出。
2. 实体词表是领域相关的：新增领域必须同步 `entity_lexicon`，否则会出现"描述没问题但 0 命中"的误报。
3. 阈值与权重全部在 YAML，代码零魔数；新增规则必须 bump version。
4. `make check` 只跑 legacy + active + 离线，秒级；不要把它扩成全量联网基准。
5. 规则与实验结论的 SSoT 仍是 `agent-service-optimization` SKILL 与 `experiment-log.md`，本 SPEC 只定义实现。

## 8. 校准记录（评分卡 v3，2026-11-21）

用 4 个在售商品（market-data / event-context / market-facts-daily / cogsteward）端到端跑分，按 rule_id 归因后修正 4 类引擎缺陷：

| 类型 | 现象 | 归因 | 修正 |
|---|---|---|---|
| 取数口径 | `--product market-data` 只出组件面，商品页/包装永远评不到 | 商品名与组件同名，`target_surfaces` 先命中组件 | `--product` 直接取商品面；`score/advise --all` 默认与 gate 同口径（排除 draft） |
| 误报 | CON002 报出「据服 / 件上 / 次付 / 场事 / 美联」等重复词 | 中文 2 字滑窗把跨词碎片当词 | 传 `entity_lexicon` 后只按整词比对，无词表才回退滑窗 |
| 误报 | 商品页因描述缺「当用户」被判 D 级 | RET002 是 SKILL.md 召回规则，却套到商品页 | RET002 只约束 `skill_md`；触发词补 适合/面向/覆盖/帮你 |
| 漏报 | 描述写了「美股 / A股 / 财报 / 分位」却算 0 实体 | `entity_lexicon` 只覆盖公司/代码/表单 | 新增 market / metric 词族与 体检 |

校准结果（4 商品 31 个发布面，profile=legacy）：平均分 91.53 → **96.34**，blocker 0，warn 20 → **11**；残余告警全部指向真实内容缺口（pro 变体缺 tags、pro 描述缺意图短语、商品页标题/副标题/关键词重复同一实体），不再是引擎噪声。随后按这 11 条告警修源文件（pro 补 tags 与意图短语、免费版补英文 tag、商品页 tags/summary 改长尾）并重建 dist，四商品 31 个发布面归零（100 分 / 0 warn）。

已知未覆盖（刻意不做，避免过度工程）：商品页没有检索维度规则；CON002 只认词表内整词，词表外的新词重复不会报警。
