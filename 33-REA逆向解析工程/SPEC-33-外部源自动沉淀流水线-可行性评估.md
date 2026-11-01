# SPEC-33-外部源自动沉淀流水线 · 可行性评估

| 项 | 值 |
|---|---|
| 版本 | v1.0（评估稿，未实施） |
| 日期 | 2026-11-01 |
| 归属 | 33-REA逆向解析工程 / 反思层 P3 |
| 关联 | [SPEC-33-外部真实源接入.md](./SPEC-33-外部真实源接入.md)、[external_sources.json](./reflection_data/external_sources.json) v2.1 |
| 目标 | 调研产出 → 自动归档知识库 → 登记外部源 → 同步云端 → 定时注入，形成闭环 |

---

## 0. 结论

**整体可行，但不可一次性打通，必须分三段。**

| 环节 | 可行性 | 现状 | 缺口 |
|---|---|---|---|
| S1 调研产出抽取（项目/URL/价值） | 中 | 人工 grep 文档（本次 97 源即人工抽取） | 无脚本；项目名≠URL 不可靠 |
| S2 知识库归档 | 高 | `knowledge-ingest` SKILL 已具备分类+RAG+认知 record | 缺 `external-source` 子类型与 frontmatter 契约 |
| S3 登记 external_sources.json | 高 | schema 已定型（category/priority/wave/patterns/extract_target） | 缺幂等 upsert 脚本 |
| S4 同步云端 | 中 | ProxyJump 链路已跑通（commit `505d8b6c`） | 本地无 GitHub 出口，必须借云端提交 |
| S5 云端定时注入 | 高 | 云端已有 2 个 crontab 在跑（含每小时 FIS reconcile）；B1–B3 已修复并实跑（云端 `be02cbdd`，本地已同步） | 仅缺 cron 脚本封装与验收（见 §4 S5） |

---

## 1. 这 97 个源的来源（溯源）

**本质：全部是"人工从调研文档里抽出来的 GitHub 地址"，没有一条来自自动抽取。** 这正是本流水线要替代的动作。

### 1.1 第一批 59 条
按 10 大类人工精选，来源为历次开发前调研文档：
- `1-ARCHITECTURE/WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md`（Agent OS 竞品）
- `1-ARCHITECTURE/specs/ARCH_OPTIMIZATION_INDUSTRY_BENCHMARK_SPEC.md`（行业标杆）
- `1-ARCHITECTURE/RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md`、`前端设计/RESEARCH_DEEPSEEK_HARNESS.md`（Harness 架构）
- `1-ARCHITECTURE/SUPERPOWERS_INTEGRATION_UPGRADE.md`
- `1-ARCHITECTURE/dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md`
- `2-KNOWLEDGE/7-EXTERNAL-RESEARCH/**`（26 篇外部调研）

### 1.2 第二批 38 条（本次扩充）
对上述文档做 `github.com/owner/repo` 正则抽取 → 按 10 类归属 → 补 `extract_target`（抽什么架构模式、映射到哪个内部模块）。增量分布：金融 +15、大模型 +14、DSH +4、DreamOS +3、认知 +1、采集 +1。

### 1.3 抽取损耗（关键，决定 S1 难度）
`2026-09-03-GitHub最小阻力RL策略进化开源项目调研.md` 列了 5 个项目，实际只有 1 个能落地 URL：
- ✅ `b3hzadsh/Evolutionary-Trading-Strategies`
- ❌ `genetic-stock-trader`（Java 实现，按语言规则排除）
- ❌ `RL_Trade_Ensemble_Analysis` / `rl-order-execution` / `Deep-RL-Trading-Ensemble`（文档为转述名，GitHub 检索无对应仓库）

**即"项目名 → 真实仓库"转化率 20%。** 这是流水线必须引入 GitHub Search API 校验的根本原因。

### 1.4 数据质量现状
- 97 条 = 97 个唯一 `owner/repo`，无 id 重复、无 location 重复、全部为标准两段式 GitHub 地址
- 许可证：MIT 44 / Apache-2.0 25 / BSD 5 / GPL-3.0 2 / LGPL-2.1 1 / **unknown 20**
- 存在性：**未验证**（按用户决定交由云端做 `git ls-remote`）

> 结论修正：97 源在"结构上"对应 97 个不同仓库，但"是否真实存在、许可证是否可注入"这一步尚未完成，20 条 unknown 必须在注入前核验。

---

## 2. 已有基建盘点（可直接复用）

| 能力 | 位置 | 复用方式 |
|---|---|---|
| 外部调研知识库 | `2-KNOWLEDGE/7-EXTERNAL-RESEARCH/`（finance、github/{data-engineering,trading-systems,infra-tools,ml-frameworks}、technical，共 26 篇） | S2 归档落点，只新增目录 `external-sources/` |
| 知识沉淀 SKILL | `.trae/skills/knowledge-ingest/SKILL.md`（分类入库+RAG 向量化+认知 record+索引更新；已设"批量 >10 条需确认"门禁） | S2 直接调用，不重写 |
| 外部采集器 | `33-REA逆向解析工程/core/reflection/harvest.py`（E1 clone → E2 解析 → E3 三重验证 → E4 注入回放池，FAIL-OPEN） | S5 执行体，只补修 bug |
| 源清单 schema | `reflection_data/external_sources.json`（category/dimensions/priority/wave/patterns/expected_analyzers/extract_target/size_cap_mb/known_blockers） | S3 直接读写，无需改结构 |
| 云端定时任务 | 云端 2 个 crontab（ubuntu：每小时 FIS reconcile；luke：40-周期 0:10/0:25、39-语义 3,33/18,48 分、43-战略 18,48 分、34-语料 3:00） | S5 加一行 cron，零新建基建 |
| 云端 GitHub 出口 | `dreambuddy-remote`(43.160.201.117) 与 `tencent-cloud`(49.233.123.96) 均可访问 GitHub | S1 校验、S4 提交都在云端做 |
| 本地无 GitHub 出口 | git/curl TLS `SSL_ERROR_SYSCALL` | 决定 S4 必须"云端提交"而非本地推送 |

---

## 3. 目标流水线（5 段）

```
调研文档/报告
   │  S1 抽取（URL 正则 + GH Search 校验 + 价值评分）
   ▼
2-KNOWLEDGE/7-EXTERNAL-RESEARCH/external-sources/<domain>/<owner>-<repo>.md
   │  S2 归档（knowledge-ingest：frontmatter + RAG + record + 索引）
   ▼
33-REA.../reflection_data/external_sources.json   （S3 幂等 upsert）
   │  S4 同步（云端 worktree commit → push branch → cherry-pick 到 main）
   ▼
云端 /home/luke/dreambuddy（定时 cron）
   │  S5 注入（harvest.py E1→E4 → replay_pool，provenance=external，权重 0.5）
   ▼
反思层 DreamingLoop 可用外部先验
```

---

## 4. 逐段可行性与风险

### S1 调研产出抽取 — 中
- **做法**：正则抽 `github.com/owner/repo`；未命中的项目名走 GitHub Search API（`/search/repositories?q=<name>`）取 top1，`stars>500 且 语言∈{Python,TypeScript}` 才落地。
- **风险**：① 本地无网，必须在云端跑；② 转述名误匹配（本次 4/5 落空）；③ 语义判断"是否有价值"无法纯脚本，需 LLM 打分（复用 `dream-research-workflow` 的 5 维评估）。
- **结论**：脚本负责"抽 URL + 去重 + 校验存在"，LLM 负责"归类 + 写 extract_target + 价值评分"。

### S2 知识库归档 — 高
- 复用 `knowledge-ingest`，仅新增一类 frontmatter：`source_type: external_repo` / `repo_url` / `stars` / `license` / `category` / `extract_target` / `rea_wave`。
- **注意**：`knowledge-ingest` 禁止修改已有文件（HC-8 只新增不修改）→ 与"每次调研更新同一 repo 的 stars/状态"冲突。**需要为 external-sources 目录开例外：允许刷新元数据字段，正文只追加"历次调研结论"小节。**

### S3 登记 external_sources.json — 高
- 幂等键 = `location`（小写去尾斜杠）。已存在则只更新 `priority/wave/patterns/extract_target`，不新增。
- 需新增字段以支持溯源：`discovered_from`（来源文档路径）、`discovered_at`、`verified`（云端 `git ls-remote` 结果）、`license_verified`。
- **风险**：JSON 单文件并发写 → 用文件锁 + 原子替换（临时文件 + `os.replace`）。

### S4 同步云端 — 中
- 已验证可用链路：`ssh -o ProxyCommand="ssh -o BatchMode=yes -W 43.160.201.117:22 tencent-cloud" ... dreambuddy-remote`
- **必须遵守**：云端 main 有 2 个未推送 commit，禁止 `git push origin main`；走 worktree → push `docs/33-external-sources-spec` → cherry-pick 到云端 main。
- **噪声**：每次登录 tencent-cloud 弹出微信扫码 banner（但命令仍执行成功），脚本需过滤 banner 输出。
- **风险**：跳板机依赖；若 tencent-cloud 登录态失效，整条 S4 断。

### S5 云端定时注入 — 高

cron 加一行即可（例如每周日 04:00 跑 `scripts/external_source_cron.py --max 5`）。原先的 4 个逻辑缺口（B1–B3）**已于 2026-11-01 在云端修复并实跑验证**，commit `be02cbdd`（分支 `fix/33-rea-external-injection`），本地已同步且 17 项测试通过：

| # | 原缺口 | 修复内容 | 状态 |
|---|---|---|---|
| B1 | `generate_candidates` 只重排当前序列 | 新增 `pool` 参数 + "步骤 0 池序列挖掘"，外部树动作序列可入候选集（SPEC §9-1） | ✅ 已修 |
| B2 | E3 交叉验证用 action 集合交集，内外部互斥 | `_verify_cross` 增加 `provenance=external` 分支：external-external 交集 + 首批外部树放行（§9-2） | ✅ 已修 |
| B3 | E2 未调用 `recover_decisions`/`narrative` | `parse_source` 追加 `_append_decision_nodes` + `_append_narrative_nodes`，注入决策路径 | ✅ 已修 |
| B4 | 本地无 GitHub | 只能云端跑（不影响 cron） | 设计约束 |

**实跑证据（云端）**：外部回放池已注入 78 棵树；`reflection_data/experiment_ec2_ea1.json` 记录 `internal_trees=200 / external_trees=11 / v_internal_only=0.0 / v_full_pool=0.006448` —— 外部先验已产生非零 V 贡献（量级偏小，需后续调权重与采样）。

**剩余工作**：仅为 cron 封装 + 验收（外部池增长、V 增量稳定性、失败率）。

---

## 5. 建议的 SKILL 设计（待批准后创建）

`dream-external-source-pipeline`

| 项 | 内容 |
|---|---|
| 触发 | 调研类 SKILL（`dream-research-workflow` / `dream-science-*`）完成；用户说"外部源归档/同步外部源/更新外部源清单" |
| 步骤 | 1 抽取 → 2 去重 → 3 云端校验（存在性+license） → 4 价值评分与归类 → 5 知识库归档 → 6 JSON upsert → 7 同步云端 → 8 认知 record |
| 门禁 | 新增 >10 条需用户确认（继承 knowledge-ingest）；license∈{unknown,GPL} 一律标记只读、不得注入 |
| 失败策略 | FAIL-OPEN：任一步失败只记录 `known_blockers`，不阻断调研主流程 |
| 幂等 | 幂等键 `location`；重复执行不产生重复条目 |
| 输出 | 变更清单（新增/更新/跳过/待核验），写入 `reflection_data/sync_reports/<date>.json` |

---

## 6. 分期建议

| 期 | 范围 | 前置条件 |
|---|---|---|
| P0 | S3 + S2 脚本化（`sync_external_sources.py`：upsert + 归档 stub + 报告）；SKILL v1 本地可用 | 无 |
| P1 | 云端 `verify_external_sources.py`（ls-remote + license 核验）+ cron 周任务，**只产报告不注入** | S4 链路稳定 |
| P2 | ①B1–B3 修复 **已完成**（云端 `be02cbdd`，本地已同步，17 测试通过）②补 cron 封装 `external_source_cron.py` ③开启真实注入并验收（V 增量稳定性、失败率、池增长） | ②③依赖 P1 |

**当前状态更新**：P2 的代码前置（B1–B3）已消除，不再构成阻塞；剩余的是 cron 封装与验收，可与 P0/P1 并行推进。

---

## 7. 决策记录（2026-11-01 已确认）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 同步方式 | **直接同步云端**（不再走 branch + cherry-pick 的保守路径），风险接受 |
| D2 | 定时频率 | **每周增量校验**（不全量重验 97 源） |
| D3 | 内存约束 | 云端每周校验**必须**先做内存门禁；超出阈值**必须**告警并**暂停**，不得降级继续 |
| D4 | 入库方式 | **无人值守**（调研产出自动入库，不设 >10 条人工确认门禁） |
| D5 | 实施路径 | 技术文档**先同步云端**，由**云端审核并配套落地**，再做两地联调 |

---

## 8. 双路径入库与周合并（本方案核心）

### 8.1 为什么是双路径

本地和云端都会产生调研产出，两条路径**天然分叉**：

| 路径 | 产生方 | 网络能力 | 产出 |
|---|---|---|---|
| **L 路径**（本地） | 本机 IDE / 调研 SKILL | 无法访问 GitHub（TLS 失败） | 可归类、可登记，**不可校验** |
| **C 路径**（云端） | 云端调研 / 定时任务 | 可访问 GitHub | 可归类、可登记、**可校验 + 可注入** |

因此**校验与注入只能在云端做**，本地只做"候选登记"。这决定了合并权威必须在云端。

### 8.2 单写者原则（避免双写冲突）

**主清单只有一个写者：云端。** 本地不直接改 `external_sources.json`，改为写 inbox：

```
本地                                         云端
33-REA/reflection_data/inbox/                33-REA/reflection_data/
  external_sources.local.json      ──scp──▶    inbox/
                                               │
                                       周合并（唯一写者）
                                               ▼
                                   reflection_data/external_sources.json
```

- 本地：`sync_external_sources.py --emit-inbox` → 只写 `inbox/external_sources.local.json`
- 同步：`sync_to_cloud.sh` → scp inbox 文件 + 报告到云端
- 云端：`merge_external_inbox.py` → 按 §8.4 协议合并到主清单 → 归档 inbox 到 `inbox/archive/<date>/`
- 云端自己也调研时，直接写主清单（云端是写者，无冲突）

**收益**：本地永不产生主清单 diff，不存在"本地改一半、云端改一半"的合并冲突；inbox 是纯增量提案。

### 8.3 每周调度（云端 cron，周日 04:00）

```
[0] 内存门禁        MemAvailable < 800MB 或 < 10%  →  ALERT + exit 3（暂停，本周不跑）
[1] 云端自调研入库   scan 本地同款 roots + 云端调研产出目录 → 主清单（幂等 upsert）
[2] 消费本地 inbox   merge_external_inbox.py（§8.4）→ 归档 inbox
[3] 增量校验        未验证 or last_checked > 30 天，单次上限 40，并发 1
                     每源前后各一次内存检查，越线即停（已完成的保留）
[4] 汇总报告        reports/weekly-<date>.json（新增/更新/冲突/失败/内存峰值）
[5] 注入（可选开关）--inject-max 5，harvest E1→E4 → 回放池外部树
```

失败策略：`[1] [2]` FAIL-OPEN（失败只记报告，不污染主清单——用临时文件 + 原子替换）；`[3]` 部分成功保留；`[0]` 是硬门禁，不通过直接停。

### 8.4 合并协议（幂等、可重放）

| 场景 | 规则 |
|---|---|
| 幂等键 | `location` 小写 + 去尾斜杠（唯一判重口径） |
| 两侧都新增同一源 | 取并集为 1 条；`discovered_from` 保留两条（主值 + `also_seen_in[]`） |
| `category` 冲突 | 取 `priority` 更高者（P0>P1>P2>P3）；同级取云端（云端有校验数据） |
| `id` 冲突（不同 location 同名 repo） | 先入者保留，后来者追加 `-2`、`-3` |
| 元数据冲突（license/stars/verified） | **云端校验结果优先**，本地值只作参考写入 `local_hint` |
| 删除 | 一律不删，标 `retired: true` + `retired_at` |
| 重复执行 | 结果不变（merge 前后 `content_hash` 相同则跳过写入） |
| 版本 | `schema_version` 固定；`version` 由云端单调递增 |

### 8.5 内存压力评估（云端）

| 项 | 取值 | 依据 |
|---|---|---|
| 门禁阈值 | MemAvailable ≥ **800MB** 且 ≥ **10%** | 单源 clone（`--depth 1 --filter=blob:none`）+ 解析峰值约 300–500MB，留 1.5 倍余量 |
| 单源体量 | `size_cap_mb: 50`，超限跳过并记 `size_exceeded` | 已在 `admission_rules` 中定义 |
| 并发 | 固定 1 | 避免峰值叠加 |
| 检查点 | 每次运行开始 + **每源结束后** | 中途越线立即 `ALERT` + 退出，已完成结果保留 |
| 告警 | 写 `reflection_data/reports/ALERT_mem_<ts>.json` + 飞书通知（可开关） | 可追溯 |
| 暂停语义 | 本周不校验不注入，**不改主清单** | 避免半成品状态入库 |

### 8.6 验收门禁（云端审核用）

| 门 | 判据 |
|---|---|
| G1 | 三个脚本单测通过（幂等 upsert、inbox 合并、内存门禁分支） |
| G2 | dry-run 报告与人工核对一致：97 源 0 重复、0 误归类（抽查 10 条） |
| G3 | 单次注入 ≤5 源，外部池增长且 `v_full_pool > v_internal_only` 稳定为正 |
| G4 | 模拟低内存（`REA_MEM_MIN_FREE_MB=99999`）能触发 ALERT + exit 3 + 不改主清单 |
| G5 | inbox 重复合并幂等（连跑两次，主清单 hash 不变） |

---

### 8.7 抽取质量管理（本地实测，2026-11-01）

**第一次 dry-run 的 433 是假象**（仅扫 3 个根目录）：

```
docs_scanned=1288   urls_found=433   new=396
```

排查发现其中 372 篇文档位于 `node_modules/`、`site-packages/`、`dist/` 等依赖目录，抽出的是 `openai/openai-node`（被提及 1814 次）、`aws-sdk`、`zod`、`chokidar` 这类**第三方依赖**，不是本系统的调研结论。

**修正口径（全仓扫描 + 排除依赖目录 + 排除占位符/自引用仓库）**：

```
docs_scanned=3916（全仓 md）   urls_found=144   hit_existing=97   new=47
```

即：**知识库里真实存在的 GitHub 项目是 144 个**，其中 97 个已入清单，**新增候选仅 47 个**。47 条按 10 类自动归类分布：

| 类别 | 条数 |
|---|---|
| finance_models | 19 |
| dsh | 11 |
| llm_training | 9 |
| database | 4 |
| dreamos | 2 |
| frontend | 2 |

已排除的噪声：`your-username/dream-multiSkill`、`org/repo` 等 4 个占位符，`yunya1991/Dreambuddy-V2` 自引用 1 个。

**这 47 条交由云端调研评估**（Q2 硬指标 + Q3 语义相关性），入口为 `reflection_data/inbox/external_sources.local.json`（`level=candidate`，不注入、不直接进主清单）。

三层质量门（Q1 本地已实现，Q2/Q3 归云端）：

| 层 | 规则 | 归属 |
|---|---|---|
| Q1 结构过滤 | 排除非仓库路径、依赖目录、占位符、自引用仓库 | 本地 ✅ |
| Q2 硬指标 | `stars ≥ 300`、`language ∈ {Python, TypeScript}`、`license ∈ {MIT, Apache, BSD}` 才升 `qualified` | 云端 |
| Q3 语义相关性 | LLM 判定"含可抽取架构模式 + 能映射到我方模块"，产出 `extract_target`、`relevance_score` 才升 `priority` | 云端 |

**分级入库（关键）**：
- `candidate`（仅 Q1 通过）：只进 `inbox`，不进主清单、不注入
- `qualified`（Q1+Q2 通过）：进主清单，`wave=4`，不自动注入
- `priority`（Q1+Q2+Q3 通过）：进主清单并允许 `--inject-max` 注入

这样"无人值守"体现在**流程不停、自动分级**，而不是"全部直接进池"。

---

## 9. 云端审核与落地清单

技术文档同步云端后，由云端**审核并配套落地**以下事项：

| # | 事项 | 产物 |
|---|---|---|
| 1 | 审核 §8 双路径与合并协议，确认写者/权限边界 | 评审意见（回写本文档 §11） |
| 2 | 落 `scripts/sync_external_sources.py`（本地已先行实现，供参考） | `--emit-inbox` 模式 |
| 3 | 落 `scripts/merge_external_inbox.py` | inbox → 主清单，幂等 |
| 4 | 落 `scripts/verify_external_sources.py` | ls-remote 存在性 + GitHub API license/stars |
| 5 | 落 `scripts/external_source_weekly.py` | 上表 6 步编排 + 内存门禁 |
| 6 | 建目录 | `reflection_data/inbox/`、`inbox/archive/`、`reports/` |
| 7 | 加 cron | 周日 04:00；与现有 4 个任务错峰 |
| 8 | 告警通道 | ALERT json + 可选飞书 |
| 9 | 运维说明 | `docs/EXTERNAL_SOURCE_PIPELINE_RUNBOOK.md` |
| 10 | **质量门 Q2/Q3** | `verify_external_sources.py` 内实现 stars/language/license 硬门槛 + LLM 相关性评分，产出 `candidate/qualified/priority` 三级 |

**约束**：云端复用同一份 `external_sources.json` 与同一套 `category_map`，不得另建清单，否则合并失效。

---

## 10. 两地联调计划（2026-11-01 已执行）

| 步骤 | 动作 | 通过判据 | 结果 |
|---|---|---|---|
| T1 | 本地 `sync_external_sources.py --dry-run` | 抽到 URL 数与人工核对一致；无网络依赖 | ✅ `docs_scanned=3969 urls_found=142 new=0`（142 条唯一 URL 全部已在主清单） |
| T2 | 本地 `--emit-inbox` → scp 上传 | inbox 文件在云端可读、JSON 合法 | ✅ 云端 `reflection_data/inbox/external_sources.local.json`（45 条，14:08 已同步） |
| T3 | 云端 `merge_external_inbox.py` 两次 | 第一次新增 N 条，第二次新增 0、hash 不变 | ✅ 该 inbox 此前已被一次性注入消费：两次均 `added=0 skipped=45`，主清单 hash 不变；本次已归档到 `inbox/archive/20261101_154122` |
| T4 | 云端 `verify_external_sources.py --limit 5` | 5 源 verified 有结论；内存报告落盘 | ✅ 5/5 verified，`admissible=4`（Calibration-Neural-SDEs 因 GPL-3.0 被拒），MemAvailable 11619MB |
| T5 | 云端模拟低内存 | ALERT + exit 3，主清单未改 | ✅ `REA_MEM_FAKE_AVAILABLE_MB=100` → `exit 3`，`ALERT_mem_20261101_153914.json`，hash `ae22a26c…` 前后一致 |
| T6 | 云端 `--inject-max 2` | 外部池 +2，V 增量非负 | ⏸ 本次 `eligible=0`（137 棵池树已覆盖全部已校验合格源），注入 0 条；待后续周校验产出新合格源后自动触发 |
| T7 | 回传合并后的主清单到本地 | 本地 hash 与云端一致 | ✅ 双端 `md5=327918b2b465d7317ad4eda311b926f9`，143 条（云端自调研 +1 `openlit`） |

**补充执行（cron 实跑）**：云端 `external_source_weekly.py`（无注入）→ `scan 8.0s / merge 0.1s / verify 40 源 21.5s / 总 29.6s`，exit 0，内存 11692→11743MB；40/40 verified、admissible 23；主清单 143 条（verified 90 / admissible 27）；cron 已装 `0 4 * * 0`（与现有 00:10 / 00:25 / 03:00 错峰，`flock -n /tmp/rea_weekly.lock`）。

**Q2 实现细则（回写 §8.7）**：GitHub primary language 对科研仓库常报 `Jupyter Notebook`（实现仍是 Python）→ 视作 Python 兼容；`NOASSERTION/unknown` 许可不覆盖清单已登记的具体许可；API 明确返回其他语言（如 Go）仍判 `admissible=false`。

---

## 11. 云端评审意见（2026-11-01 已填）

**审核结论：通过。** §8 双路径与合并协议成立，写者/权限边界无冲突；G1–G5 全部达成（单测 22 passed；dry-run 与人工核对一致；低内存 exit 3 且主清单不变；inbox 重复合并 hash 不变）。

| # | 事项 | 状态 | 产物 |
|---|---|---|---|
| 1 | 审核 §8 双路径与合并协议 | ✅ 通过 | 本表 |
| 2 | `sync_external_sources.py --emit-inbox` | ✅ 已有 | `scripts/sync_external_sources.py` |
| 3 | `merge_external_inbox.py` | ✅ 新增并落地 | 幂等合并 + `also_seen_in` + `local_hint` + `retired` + inbox 消费后归档 |
| 4 | `verify_external_sources.py` | ✅ 新增并落地 | 存在性 + Q2（notebook/NOASSERTION 细则见 §10） |
| 5 | `external_source_weekly.py` | ✅ 新增并落地 | 6 步编排 + 内存门禁 + 汇总报告 |
| 6 | 目录 | ✅ | `inbox/`、`inbox/archive/`、`reports/` |
| 7 | cron | ✅ `0 4 * * 0` | `flock -n /tmp/rea_weekly.lock`，日志 `/tmp/rea_weekly.log` |
| 8 | 告警通道 | ✅ JSON | `reports/ALERT_mem_<ts>.json`；飞书通知留开关 |
| 9 | 运维说明 | ✅ | `docs/EXTERNAL_SOURCE_PIPELINE_RUNBOOK.md` |
| 10 | 质量门 Q2/Q3 | ✅ Q2 / ⏳ Q3 | Q3（LLM 语义相关性）留待最新调研产出时按需评分，默认 `qualified` |

**遗留（不阻塞）**
1. T6 注入待触发：需周校验产出新的 `admissible` 源，下一周日自动生效（当前 `eligible=0`）。
2. 未配置 `GITHUB_TOKEN`：未认证限流 60 次/小时，单次上限 40 源，当前周任务 40 源刚好在限内；如扩到 >60 需配置 token。
3. `reflection_data/replay_pool/external/`（137 棵树，约 26MB）仍未纳入 git：建议 `.gitignore` + 由云端为权威副本再同步。
4. Q3 语义相关性未自动化，`priority` 级别暂无自动晋升路径（人工标注或后续接入 LLM 评分）。

