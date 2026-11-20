---
name: agent-service-optimization
description: Improve how agents discover and choose DreamBuddy skills and MCP tools. Use when tuning skill descriptions, tool names, SkillHub listings, or routing benchmarks. Not for tool implementation.
---

# Agent 服务优化

优化"用户装了一堆 skill 时，agent 为什么首选我们"。适用于新增/修改 Skill、MCP 工具、SkillHub 上架文案，或评估某次命名/描述改动是否真的提升了路由。

## 第一原则

1. **选择是检索 + 排序，不是能力比拼**：先能被召回，再被选中，最后被复用。
2. **每次只改一个变量**：同一套意图集前后对照；没有数据不改。
3. **可发现性是构建产物**：描述、触发词、工具名从 `component.yaml` 单一源生成，不手写散落文档。
4. **假阳性比漏选更伤**：越界误选必须保持 0；选错动作必须保持 0。

## 五步闭环

### 1. 跑基线

先测，不先改。

```bash
cd 59-通用组件管理
make bench-dry     # 只校验夹具，秒级，已并入 make check
make bench         # 真实模型，30 条意图，输出指标并写报告
```

需要存档时加 `--json /tmp/routing-baseline.json`。

### 2. 看失分

- 按 `category` 看命中率，找出 0% 的类别，而不是看总分。
- 逐条看未命中明细里的 `期望 vs 实选`，判断是"实体没写进描述"还是"能力真没有"。
- 只看两类失败：没选我们（漏选）、选了我们但选错动作（误选）。竞品赢在描述上，就改描述。

**先检查 headroom**：若基线覆盖命中 ≥ 90%，说明测试太容易，变量效果会被天花板掩盖。改用 `--catalog-fields name`（去掉描述）或加难例，制造区分度后再测。

### 3. 只改一个变量

按 ROI 从高到低，一次只做一项：

1. **动作描述**（最高 ROI）：写用户原话里的实体，不写内部术语。
2. **工具名**：意图词优先（`a_share_quote`），品牌词放 displayName。
3. **`when_to_use` / `not_for`**：压低难例误选。
4. **SkillHub 上架字段**：标题、tags、示例、图标、更新日志。
5. **免费入口 / 技能集 pack**：降低用户装竞品的概率。

### 4. 复跑并判定

```bash
python3 59-通用组件管理/platform/bench/routing/run_bench.py \
  --router qwen --json /tmp/routing-after.json \
  --compare /tmp/routing-baseline.json

# 制造 headroom：只给名字、不给描述；--name-style legacy 用于旧名 A/B
python3 59-通用组件管理/platform/bench/routing/run_bench.py \
  --router qwen --catalog-fields name --ids q01,f01,r01

# 验证 when_to_use / not_for：名字 + 边界，不含描述
python3 59-通用组件管理/platform/bench/routing/run_bench.py \
  --router qwen --catalog-fields guidance

# 真实 MCP 面 + 弱模型复测（描述 + 边界）
python3 59-通用组件管理/platform/bench/routing/run_bench.py \
  --model qwen3.6-flash --catalog-fields full
```

基准默认对单条失败重试 1 次并自动补 certifi 证书；整轮大量 `error` 时先修环境再判读，不要把网络问题算成路由退化。

基准默认对单条失败重试 1 次，并自动补 certifi 证书；若整轮出现大量 `error`，先修环境再判读，不要把网络问题算成路由退化。

判定标准（全部满足才算通过）：

- `coverage_hit_rate` 上升；
- `false_positive_rate` 仍为 0；
- `wrong_our_tool` 不上升；
- 平均时延没有明显恶化（参考 ±20%）；单次差异小于 2σ 视为噪声，本仓实测 σ≈2.2s；
- **稳定性**：准确率指标至少复跑 2 次（推荐 3 次）；本仓 full 模式 3 次逐条选择 0 翻转。
- **同族回归**：只改了一个工具的命名/描述时，同分类其它意图不能掉。
- **全量回归**：每轮结束跑一次全量 name-only；只测改动过的族会漏掉仍用模块名的族（R7 就暴露了 facts / event / reservation 监控族）。
- **跨模型**：至少换一个更弱的宿主模型跑 full 模式；guidance-only 失败不算方案失败，描述才是兜底。

任一条不满足就回滚该变量，不要叠加解释。

### 5. 固化

- 把本轮变量、前后指标、结论追加到 `references/experiment-log.md`；
- 同步 `59-通用组件管理/docs/RESEARCH-20261121-59域接入SkillHub与AI宿主-v0.1.md` 与 `INDEX.md`；
- 若是结构性问题（夹具缺失、schema 不完整），补进 `run_bench.py` 或 `make check`，让下一轮自动发现。

## 描述写法

模板：**能力 + 用户原话实体 + 边界**。

好例（实测把 quote 从 0% 拉到 100%）：

```text
A 股实时行情快照：查贵州茅台、宁德时代、比亚迪等 A 股现价与涨跌幅（代码如 sh600519）
```

坏例：

```text
行情快照        # 没有实体，agent 无法映射用户原话
美股披露        # 没写 8-K/10-K/us-gaap，竞品写了就赢
查看作业清单    # 内部术语，用户不会这么说
```

要求：

- 至少包含 2–3 个用户会直接说出的实体（公司名、代码、表单类型、场馆名）；
- 用中文用户措辞，不用内部模块名、代号、缩写；
- 写清"不做什么"（如"不含币价"），减少越界误选；
- 描述不是说明书，控制在 60 字以内，参数细节交给 `params`。

## 工具命名

- 名字即检索信号：用"动词 + 实体"或"实体 + 能力"（`us_sec_filings`、`reservation_plan`）。
- 品牌放 `displayName`，不要放 slug/工具名。
- 一个工具只覆盖一个意图；不要用 `get_everything` 式大工具。
- 工具数量影响路由成本：超过 15 个时，提供一个 `route_intent` 入口工具。
- 名字用**动作 + 能力对象**，不要绑定单一实体：`ticket_reservation` 同时覆盖国博与演唱会；`museum_ticket_reservation` 修好国博却丢了演唱会。`sec_filing_reader` 比 `sec_filing_search` 更贴合"提取 10-Q 财务字段"。
- **本仓实测（name-only）**：R2b 旧名 60% → 新名 80%（+20pp）；R6 细化命名 80% → **100%**。名字有独立信号，但在强描述下会被淹没；有描述时优先改描述，无描述/弱描述环境再优先改名字。
- 改完一个难例，必须复测**同族其它意图**，防止"修好一个、丢了另一个"的泛化回退。
- 语义重叠的两个工具（都叫"监控任务"）先**改名划边**（`reservation_job_list` vs `ticket_monitor_list`），再写 `not_for`。
- `when_to_use` / `not_for` 必须**成组添加**：只给竞争中的一方加，会把流量吸走并制造新误选；验证用 `--catalog-fields guidance`。
- **边界是增强项、描述是兜底**：弱模型更字面，guidance-only 可能翻车（R10 的 e01），真实 MCP 面必须同时给描述 + 边界。
- 边界样本（如"美联储声明"同时像 macro 和 event）不要靠继续加长名字硬压；单次结果有方差，至少复跑 2 次，再用描述 / `when_to_use` 消歧。

## SkillHub 上架清单

- 标题含意图词，tags 中英双语，并放入用户会直接说出的实体词（公司名、表单类型、指数名）；
- description 前 80 字写"解决什么问题"，不是"我们有什么"；
- 至少 3 个可复制示例 + 输出样例；
- 图标、截图、分类、更新日志齐全；
- 上架前先 bump version，再跑 `skillhub publish <dir> --dry-run --json`，必须返回 slug + version；同版本更新会被拒；
- `skillhub verify` 通过，签名状态公开；
- 高频只读能力放免费层，做发现入口；
- 多能力组件用 `pack` 技能集一次装齐；
- slug 是安装入口，同族保持统一前缀；改 slug 前先评估已有链接与安装量，不轻易改。

## MCP 暴露

- MCP 工具描述就是新的触发器，和 SKILL.md 同等重要；
- 保留 `inputSchema` 简洁、默认值明确、错误码稳定；
- 写工具加 `readOnlyHint=false` + `confirm` + principal，避免被 agent 误当只读；
- 结果统一 envelope，字段名稳定，agent 才会复用。

## 指标口径

| 指标 | 含义 | 目标 |
|---|---|---|
| `coverage_hit_rate` | 覆盖意图里选对我们的比例 | ≥ 70%，现状 100% |
| `ours_selection_rate` | 全部意图里选我们的比例 | 越高越好 |
| `wrong_our_tool` | 选了我们但选错动作 | 0 |
| `false_positive_rate` | 越界意图仍选我们 | 0 |
| `avg_latency_ms` | 单次选择时延 | 不显著恶化；单次 <2σ 视为噪声 |

## 反模式

- 只堆关键词，导致误触发后被 agent 标记为坏工具；
- 一个 skill 塞多个不相关意图，描述变模糊；
- 同时改名字 + 描述，无法归因；
- 只改 SKILL.md 不改 MCP 工具描述，宿主内仍选不中；
- 拿竞品数据当结论，不跑自己的意图集；
- 用内部代号（D1/D5、59 域、M3）当用户可见词。

## 参考

- 历史实验记录：`references/experiment-log.md`
- 基准代码与夹具：`59-通用组件管理/platform/bench/routing/`
- 接入调研与基线：`59-通用组件管理/docs/RESEARCH-20261121-59域接入SkillHub与AI宿主-v0.1.md`
- MCP 投影：`mcp_shells/l0_components/server.py`
