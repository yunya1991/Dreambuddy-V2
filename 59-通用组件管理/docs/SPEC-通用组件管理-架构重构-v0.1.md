# SPEC — 通用组件管理架构重构 v0.1

> **版本**: v0.7（P0–P6 完成） | **日期**: 2026-11-20
> **范围**: `59-通用组件管理/` 全模块的目录结构、契约层、共享内核、分发构建与治理闸门
> **依据**: [INDEX.md](../INDEX.md) v0.7、[ARCH 评估结论](#1-背景)（2026-11-20 对话）
> **不改动**: 任何组件的对外输出契约语义（数值、字段、红线措辞），只改「代码与文档如何组织」
> **上游决策**: 用户已确认 ①先出 SPEC 再落地 ②分发变体采用「一份源码 + 构建生成」

---

## 1. 背景

`59-通用组件管理` 当前承载 4 个商品族、11 个 Skill 目录、1 个后端服务、1 套运维脚本，总量 114 个文件（全模块 git 零跟踪）。评估发现三个结构性错位：

| 错位 | 事实 |
|---|---|
| 组件单元不统一 | 认知管家在模块根，其余在 `skills/`；`services/`、`ops/`、`assets/` 与组件平级 |
| 文档归属错位 | `docs/` 4 篇 + 根目录 9 个 SPEC/REVIEW 全是认知管家专属，却登记为模块级文档 |
| 「独立」实现成复制 | `cloud.py`×2（112/113 行，diff 25）、`handoff.py`×2、`context.py`×2、`pay.py`×3、`metrics-contract.json`×3 |

**核心判断**：组件独立性应体现在「源码期零复制、依赖单向、契约唯一」，而不是「每个目录各抄一份」。交易域长期会新增大量通用组件，若不先修结构，第 2 个商品族就会拖垮维护面。

---

## 2. 目标与非目标

### 2.1 目标（验收对象）

1. **一个组件一个目录**，自包含 `component.yaml / skill/ / docs/ / specs/ / tests/`
2. **源码期零跨组件复制**：共享逻辑只存在于 `kernel/`，复制只发生在构建产物（`dist/`）
3. **契约唯一源**：指标口径、输出外壳、数据源授权、红线、禁用引用各一份
4. **分发变体不写第二份代码**：`products/*.yaml` 声明差异，构建期产出
5. **独立性可机器判定**：4 类边界规则由 `tools/check_boundaries.py` 拦截，不依赖人眼
6. **INDEX 不再手工双写**：组件登记表由 `component.yaml` 生成

### 2.2 非目标

- 不改任何组件的输出字段、方法 ID、评分权重、红线措辞
- 不合并 4 个商品族，不统一它们的业务语义
- 不引入第三方依赖（Skill 沙箱要求零依赖，沿用现状）
- 不改变现网已发布商品的商品 ID、价格、渠道

---

## 3. 目标结构

```
59-通用组件管理/
├── INDEX.md                      # 治理入口：生成式组件登记表 + 依赖图 + 生命周期
├── contracts/                    # ★ 全局唯一契约层（唯一源，不复制）
│   ├── component.schema.json     #   组件元数据必填项
│   ├── output.schema.json        #   统一输出外壳
│   ├── metrics-contract.json     #   九项指标口径（原三份副本的源头）
│   ├── data-sources.yaml         #   数据源授权台账（腾讯/新浪是否可用的唯一裁定）
│   ├── redlines.md               #   全局红线（禁方向性结论、禁分组排序…）
│   └── forbidden_refs.yaml       #   跨组件禁用引用黑名单
├── kernel/                       # ★ 共享内核（纯标准库，只被构建期使用）
│   ├── endpoint.py               #   cloud/local/auto 三通道
│   ├── handoff.py                #   可装配指针
│   ├── pay_gate.py               #   402/付费校验
│   └── headers.py                #   声明式 UA、超时、重试退避
├── components/                   # ★ 对外组件（一目录一商品族）
│   ├── cogsteward/
│   ├── market-data/
│   ├── event-context/
│   └── market-facts-daily/
├── products/                     # ★ 分发表（只声明差异，无代码）
│   ├── cogsteward.yaml
│   ├── market-data.yaml
│   ├── event-context.yaml
│   └── market-facts-daily.yaml
├── platform/                     # 内部工程，不对外分发
│   ├── services/skillhub-audit-api/
│   ├── ops/patrol/
│   └── tools-skills/             # skillpay-workflow / skillhub-publisher / skill-ops
├── tools/                        # 构建与闸门
│   ├── build_product.py
│   ├── check_boundaries.py
│   └── gen_index.py
├── docs/                         # 仅模块级：治理说明、演进记录、评估报告
├── assets/logo/
└── dist/                         # 构建产物（gitignore）
```

**依赖规则（硬约束）**

```
components/*  ──▶  contracts/  ──▶  （纯数据，无代码）
components/*  ──▶  kernel/     ──▶  标准库
platform/*    ──▶  contracts/
禁止：component A ──▶ component B（源码引用）
禁止：kernel ──▶ component（反向依赖）
禁止：任何源码写死绝对路径
```

**组件单元标准**

```
components/<name>/
├── component.yaml     # name / version / lifecycle / family / kernel_deps / outputs
├── skill/             # 唯一打包源：SKILL.md / scripts/ / references/ / templates/
├── docs/              # 技术设计、API、CHANGELOG、工程索引（不进包）
├── specs/             # SPEC / REVIEW / SPIKE / PRETEST 归档（不进包）
└── tests/             # 组件回归（不进包）
```

> `skill/` 与 `docs/` 分离的原因：平台只允许 `SKILL.md/references/scripts/templates` 进包（见 [TECHNICAL_DESIGN §10 D3](../components/cogsteward/docs/TECHNICAL_DESIGN.md)），开发文档与测试不能混进分发物。

---

## 4. 迁移映射（逐目录，P2 执行）

| 现状 | 目标 | 方式 |
|---|---|---|
| `cognition-manager/`（SKILL.md、scripts/、references/、templates/、manifest.yaml） | `components/cogsteward/skill/` | `git mv` |
| `cognition-manager/CHANGELOG.md` | `components/cogsteward/docs/CHANGELOG.md` | `git mv` |
| `docs/TECHNICAL_DESIGN.md` `API_SPEC.md` `ENGINEERING_INDEX.md` `CHANGELOG.md`（认知管家专属） | `components/cogsteward/docs/` | `git mv` |
| 根目录 `SPEC-…-v0.2~v0.5.md`、`REVIEW-…`×4、`PRETEST-…`、`SPIKE-…` | `components/cogsteward/specs/` | `git mv` |
| `skills/cogsteward-pro/` | 并入 `components/cogsteward/`（`products/cogsteward.yaml` 声明 pro 变体） | 删除目录，逻辑入 `variants/` 或 products |
| `skills/cogsteward-pro-pay/` | 同上（按次变体） | 同上 |
| `skills/market-data-hub/` | `components/market-data/skill/` | `git mv` |
| `skills/market-data-pro/` | 并入 `products/market-data.yaml` | 删除目录 |
| `skills/event-context/` | `components/event-context/skill/` | `git mv` |
| `skills/event-context-pro/` | 并入 `products/event-context.yaml` | 删除目录 |
| `skills/market-facts-daily/` | `components/market-facts-daily/skill/` | `git mv` |
| `skills/skillpay-workflow/` `skills/skillhub-publisher/` `skills/skill-ops/` | `platform/tools-skills/` | `git mv` |
| `services/skillhub-audit-api/` | `platform/services/skillhub-audit-api/` | `git mv` |
| `ops/patrol/` | `platform/ops/patrol/` | `git mv` |
| `docs/`（迁空后） | 改为模块级治理文档 | 保留目录 |
| `assets/logo/` | `assets/logo/` | 不动 |

**变体目录的处置**：`cogsteward-pro`（144 行）、`cogsteward-pro-pay`（82 行）、`market-data-pro`（89 行）、`event-context-pro`（86 行）都是薄封装（纯计算或调云端 API），不是独立实现。处置方式：

- 该变体独有的脚本 → `components/<name>/skill/variants/<variant>/`
- SKILL.md 差异（name / displayName / license / 命令表）→ 写在 `products/<name>.yaml` 的 `overrides`
- 构建期由 `build_product.py` 合并生成，源码不再保留第二份完整副本

---

## 5. 契约层（P1）

### 5.1 `contracts/component.schema.json`

必填字段：

| 字段 | 约束 |
|---|---|
| `name` | 唯一，小写连字符 |
| `version` | SemVer，与 `skill/SKILL.md` frontmatter 一致 |
| `family` | `cogsteward / market-data / event-context / market-facts` 之一 |
| `lifecycle` | `draft / active / deprecated / archived` |
| `entrypoints` | 命令列表（如 `cm_cli.py route`） |
| `kernel_deps` | 必填数组，只能取 `kernel/*` 中的模块名 |
| `output_contract` | `contracts/output.schema.json` 的 profile 名 |
| `tests` | 测试入口命令 |

### 5.2 `contracts/output.schema.json`

沿用现有最严的一份（`market-data-hub` 的 JSON 外层）：

```json
{"skill":"...","version":"...","generated_at":"...","data_date":"...",
 "rows":[],"missing":[],"method_ids":[],"sources":[],"limits":"..."}
```

各组件只声明 `profile`（可裁剪字段），不得新增不兼容字段。

### 5.3 `contracts/metrics-contract.json`

现三份副本（免费版 / Pro / 后端）收敛为一份，构建期注入到各产物。`release_check.py` 的职责从「比对三份副本 sha256」降级为「校验构建产物携带的契约版本号」。

### 5.4 `contracts/data-sources.yaml`

数据源授权台账，唯一裁定「某源能否用于对外商品」。当前必须落一条裁决：

| 源 | 现状 | 裁定 |
|---|---|---|
| FRED / SEC / 公共 RPC | 已登记 Public Domain | 保持 |
| 腾讯行情 `web.ifzq.gtimg.cn` | 数据服务默认不接，日报在用（`facts.py:25`） | **书面例外（DC-1）✅ 已落地**：日报保留前复权日线；台账写明用途仅限「已发布收盘价的统计描述」、不二次分发原始行情；`market-data-hub` 措辞已改为「默认不接，例外见授权台账」 |

### 5.5 `contracts/forbidden_refs.yaml`

禁用引用清单，初始内容：

- ~~`cogsteward/pack`（`handoff.py` 写死的跨组件目标）~~ → 已改为契约值 `cogsteward.pack@1.0`（P5 落地，`handoff.v1` 的 `target` 正则已允许）
- 绝对路径前缀 `/Users/`、`/opt/`、`/home/`
- 组件间包名互引（如 `import market_data_hub`）

---

## 6. 共享内核（P3）

| kernel 模块 | 取代 | 现有副本 | 关键约束 |
|---|---|---|---|
| `endpoint.py` | `cloud.py`×2 | event-context 112 行 / market-data-hub 113 行 | `--endpoint auto\|cloud\|local` 语义、`data_route` 字段、5s/30s 超时、失败不静默降级 |
| `handoff.py` | `handoff.py`×2 | 141 / 135 行 | 输出 `handoff_version/target/budget/items/total_tokens/read_only/limits`，`target` 改为契约引用 |
| `pay_gate.py` | `pay.py`×3 | 82–89 行 | 402 判定、金额、商品令牌读取顺序 |
| `headers.py` | 各组件内联 UA/重试 | 多处 | 声明式 UA、0.8/1.6s 退避、最多 2 次 |

**分发自包含约束**：SkillHub/WorkBuddy 包必须自包含，不能依赖已安装的 kernel。因此：

- `kernel/` 只在**源码期**存在，禁止任何组件 `import kernel`
- `build_product.py` 把 kernel 模块**内联注入**到产物 `scripts/_kernel/`，并在文件头写入生成标记与源 sha256
- 「复制」由此被限制在构建产物中，源码树保持零复制

---

## 7. 分发构建（P4）

`products/cogsteward.yaml` 示例：

```yaml
product: cogsteward
component: components/cogsteward
contract_profile: cogsteward.v1
variants:
  free:
    target: skill
    channel: workbuddy-local
    name: cognition-manager
    display_name: 认知管家
    license: MIT
    entrypoints: [scripts/cm_cli.py]
    metrics_contract: true
  pro:
    target: skill
    channel: skillpay-subscription
    product_id: P0806000213876724
    price: 2.99/月
    name: cogsteward-pro
    license: 商业授权（订阅制）
    overlay: variants/pro
    entrypoints: [scripts/report.py]
    metrics_contract: true
  pro-pay:
    target: skill
    channel: skillhub-pay
    price: 0.99/次
    name: cogsteward-pro
    backend: platform/services/skillhub-audit-api
    overlay: variants/pro-pay
    entrypoints: [scripts/pay.py]
```

构建行为：

```
python3 tools/build_product.py --product cogsteward --variant pro
  → 校验 component.yaml 与 skill/SKILL.md 版本一致
  → 复制 skill/ → 叠加 variants/<variant>/（该变体的 SKILL.md 为准）
  → 校验包名/许可与 SKILL.md frontmatter 一致
  → 按脚本实际引用内联 kernel/_kernel/（并在 kernel_deps 未声明时失败）
  → 注入 contracts/metrics-contract.json（按 variant 指定）
  → dist/<product>/<variant>/ + dist/<product>/<variant>.manifest.json

python3 tools/build_product.py --all   # 全量构建
```

**验收**：`dist/` 产物与现网已发布包功能等价（SKILL.md 与源码逐字节一致、命令表、入口可执行、退出码逐项比对）。

---

## 8. 独立性闸门（P5）

`tools/check_boundaries.py` 七条规则，任一失败退出 1：

| # | 规则 | 判定方式 |
|---|---|---|
| G1 | 组件内不得引用其他组件 | AST import + 字符串匹配组件名/路径（含目录名、`component.yaml` name、SKILL.md name/slug 别名） |
| G2 | 不得写死绝对路径 | 正则 `/Users/`、`/opt/`、`/home/`、`C:\\` |
| G3 | 不得出现 `forbidden_refs.yaml` 条目 | 文本匹配 |
| G4 | 依赖必须单向 | `kernel_deps` ⊆ `kernel/*`；kernel 不得 import 任何 components |
| G5 | `component.yaml` 必填字段齐全且版本与 SKILL.md 一致 | JSON Schema + frontmatter 比对 |
| G6 | 每个组件至少 1 份 golden 输出通过 `output.schema.json` | 运行 `tests/golden/` |
| G7 | 每个组件 `tests/` 非空且入口可执行 | 目录 + 命令存在性 |

接入：`gen_index.py`（由 component.yaml 生成 INDEX §3）与 `check_boundaries.py` 组成 `make check`，发版前必跑（`make release` = `check` + `build`）。`make check` 额外包含 `sync_kernel.py --check`，防止 `_kernel/` 注入副本过期。

---

## 9. 分阶段与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0 纳管** ✅ | `git add 59-通用组件管理/` + `.gitignore`（`__pycache__/`、`.cm/`、`dist/`、`node_modules/`、`.env`） | 基线 commit `a0f6dd4725`（109 文件 / 20460 行），tag `pre-restructure`；`__pycache__` 未入库 |
| **P0b 规范归一** ✅ | `ruff --fix` + `black` + 手工修复 E402 / B904 / B905 / F841 / B007 / C416；`zip` 统一 `strict=False` 保持原行为 | ruff 0 告警、black 38 文件通过、认知管家 84 通过 2 跳过（与基线一致） |
| **P1 契约层** ✅ | 5 份契约 + 3 个 tools 骨架 | `contracts/` 五份文件齐备，三份 schema 通过 Draft-07 自校验，合成正/负例均按预期通过/拦截，真实 `handoff --json` 与 `cm doctor --json` 分别通过 `handoff.v1` / `cogsteward.v1`；`check_boundaries.py` 基线：G2 PASS，G3 FAIL 2 处（`cogsteward/pack`），G1/G4–G7 SKIP（待 P2） |
| **P2 目录迁移** ✅ | 按 §4 映射 `git mv` | 映射表 100% 落地（4 组件 + platform + docs）；根目录只剩 INDEX/contracts/kernel/components/products/platform/tools/docs/assets；`git log --follow` 可见历史；`check_boundaries.py` G5/G7 由 SKIP 转为 PASS |
| **P3 kernel 抽取** ✅ | 4 个 kernel 模块（endpoint / handoff / pay_gate / headers）+ `tools/sync_kernel.py` 注入机制 | 重复实现 0 份：`cloud.py` 115→41 行（仅剩声明式配置）、`handoff.py` 与 `pay.py`×3 的共享逻辑全部入 kernel；`sync_kernel --check` 8 个 scripts 目录一致；四组件 94 项测试、沙箱 16/16、改造前后输出逐字段 diff 一致 |
| **P4 产品构建** ✅ | `products/*.yaml`（4 份）+ `build_product.py`（overlay 叠加、按引用注入 kernel、`--all`） | 4 个商品族 × 8 个变体全部可构建（`--all` 失败 0）；8 份产物 SKILL.md 与源码逐字节一致；入口脚本可执行、`report.py`/`pay.py` 实跑通过 |
| **P5 闸门接入** ✅ | `Makefile` 的 `check`（sync_kernel + G1–G7 + gen_index）/`release`；G1 增加 SKILL name/slug 别名；清零 G3、G6 存量违规 | 正常树 7/7 PASS、0 违规；`--all` 构建 8/8；负例注入（G1–G7 各 1 例）全部被拦 |
| **P6 红线收敛** ✅ | `data-sources.yaml` 裁定腾讯源；`handoff` target 改契约 | DC-1 复核记录在台账（`reviewed_at`/`review_result`）；数据服务措辞改为「默认不接，例外见台账」，日报免责声明与 DC-1 范围对齐；`handoff` target 已为 `cogsteward.pack@1.0`；`forbidden_refs` 0 命中 |

**回归基线（每个阶段结束必跑）**

```
python3 components/cogsteward/skill/scripts/cm_cli.py selfcheck
cd components/cogsteward && python3 -m unittest discover -s tests -v   # 88 项（2 跳过）
node platform/services/skillhub-audit-api/test/app.test.js             # 13 项
```

**P2 遗留（登记到 P4）**：`components/market-facts-daily/skill/scripts/facts.py` 的 `--json` 仍是文本主输出的辅助格式，未携带 `data.v1` 的 `version / data_date / limits / method_ids / sources` 外壳，故 G6 对该组件暂为 FAIL；金额与统计字段不在 P2 改动范围，P4 构建期统一补齐。

---

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 迁移期多组件并行开发冲突 | P0 基线 commit 后立刻打 tag `pre-restructure`；迁移按组件逐族合入，单族一个 commit |
| 打包规则被破坏（docs/tests 混入包） | 构建只读 `skill/`，`check_boundaries.py` G5 校验产物文件白名单 |
| kernel 抽取改变通道降级行为 | P3 只做「同逻辑搬迁」，先跑 golden 输出 diff（组件输出逐字段比对）再合并 |
| 已发布商品 ID 变更 | `products/*.yaml` 固化现有 8 个商品 ID，构建脚本禁止改写 |
| 目录大迁移导致 IDE/SKILL 引用失效 | 迁移后全仓 grep 旧路径，同步更新 `0-系统文档管理/INDEX.md` 与本模块 INDEX |

---

## 11. 决策记录（2026-11-20 用户确认）

| # | 决策 | 结论 | 落地动作 |
|---|---|---|---|
| DC-1 | 腾讯行情源 | **登记为书面例外**（保留 `web.ifzq.gtimg.cn` 前复权日线） | 写入 `contracts/data-sources.yaml`，标注 `exception: true` + 商用依据 + 复核责任人；`market-data-hub` 的「不接腾讯」措辞改为「默认不接，例外见授权台账」，避免两组件口径冲突 |
| DC-2 | `skill-ops` / `skillpay-workflow` / `skillhub-publisher` 归属 | **归 `platform/tools-skills/`，不按通用组件登记**（评估结论：三者服务于本模块自身的发版与运营，无外部分发形态，纳入组件登记会污染组件依赖图与 golden 输出校验） | INDEX §3 组件登记表移除三行，改由 §3.2「平台工具」表登记；§3.1 完整 Skill 清单保留（目录即登记单位），并标注 `平台工具` |
| DC-3 | P2 迁移粒度 | **按商品族分 4 个 commit**：cogsteward / market-data / event-context / market-facts-daily，另加 1 个 platform 迁移 commit | 每个 commit 独立可回滚；commit message 统一 `refactor(59): 迁移 <族> 至 components/<name>` |

---

## 12. 偏差记录

| # | 偏差 | 原因 |
|---|---|---|
| S1 | 组件目录内区分 `skill/` 与 `docs/` 两层 | 平台打包只允许 4 类目录，开发文档不能进包 |
| S2 | kernel 采用构建期内联而非运行时共享 | Skill 包必须自包含，沙箱无法安装共享库 |
| S3 | Pro/按次变体源码删除，改为 products 声明 | 薄封装不值得独立维护；口径漂移已发生过一次 |

---

**文档版本**: v0.2 | **状态**: 已确认，P0–P1 完成，P2 待执行 | **最后更新**: 2026-11-20
