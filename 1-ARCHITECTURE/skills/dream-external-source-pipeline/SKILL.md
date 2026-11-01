---
name: dream-external-source-pipeline
description: Orchestrates 8-step external source sediment pipeline: extract URLs from research docs → dedup by location → cloud verify (exists/license/Q2) → value scoring & category → knowledge archive → JSON upsert → cloud sync → cognitive record. Local only emits inbox；cloud is the single writer of external_sources.json. Invoke when research SKILL completes, or user says 外部源归档/同步外部源/更新外部源清单/外部源注入.
version: 1.0.0
created: 2026-11-01
updated: 2026-11-01
license: Internal
status: active
category: orchestration
triggers: [外部源归档, 同步外部源, 更新外部源清单, 外部源注入, 外部源流水线, external source pipeline, inbox 合并]
depends_on: [sync_external_sources.py, merge_external_inbox.py, verify_external_sources.py, external_source_weekly.py, core/reflection/harvest.py]
provides: [external-source-sediment, external-source-merge, external-source-verify, external-source-weekly]
cognitive_links: []
apply_count: 0
---
## Autonomy Boundary

可自主执行：
- 抽取/去重/归类/归档/报告生成
- 写 inbox 提案（本地）与主清单合并（云端）
- 云端增量校验与可选注入（受内存门禁约束）

需用户确认：
- 单次新增 > 50 条（触发截断告警）
- 开启真实注入（`--inject-max > 0` 首次启用）
- 删除/下线任何源（本流水线只标 retired，不删）

禁止：
- 本地直接写 `reflection_data/external_sources.json`（唯一写者是云端）
- license ∈ {unknown, GPL/AGPL} 的源进入注入
- 跳过内存门禁继续校验/注入


# Dream External Source Pipeline — 外部源自动沉淀流水线 SKILL

> 把「调研产出 → 外部源清单 → 云端校验/注入」固化为可复用闭环：本地只提案，云端统一合并与校验，避免双写冲突。

## 一、何时调用

1. 调研类 SKILL 完成（`dream-research-workflow` / `dream-science-*` / `knowledge-ingest`）→ 自动沉淀新发现的外部仓库
2. 用户说「外部源归档 / 同步外部源 / 更新外部源清单 / 外部源注入」
3. 每周云端定时任务（cron 周日 04:00）→ 直接跑 `external_source_weekly.py`

不触发：纯代码变更、无 GitHub 链接的文档。

## 二、八步流水线

| # | 步骤 | 执行端 | 命令/产物 | 门禁 |
|---|---|---|---|---|
| 1 | 抽取 | 本地 | `sync_external_sources.py --dry-run`（扫 `*.md`，排除 node_modules/site-packages/dist 等） | 占位符/自引用仓库过滤（Q1） |
| 2 | 去重 | 本地 | 幂等键 `location` 小写去尾斜杠 | 已存在 → skip |
| 3 | 云端校验 | 云端 | `verify_external_sources.py --limit N`（ls-remote/API 存在性 + license/stars/language Q2） | 内存门禁；并发固定 1 |
| 4 | 价值评分/归类 | 本地/云端 | `sync_external_sources.py` 的 `classify()` 关键词打分 → 10 大类 | Q2 通过才升 `qualified`；Q3 通过才升 `priority` |
| 5 | 知识库归档 | 本地 | `2-KNOWLEDGE/7-EXTERNAL-RESEARCH/external-sources/<category>/<id>.md` | 只新增不修改 |
| 6 | JSON upsert | 云端 | `merge_external_inbox.py`（§8.4 协议） | `content_hash` 不变则不写 |
| 7 | 同步云端 | 本地→云端 | `scp` inbox + 报告；主清单回传本地 | 双端 hash 一致 |
| 8 | 认知记录 | 本地/云端 | `record(tags="external-source-pipeline,...")` | — |

## 三、双路径与单写者（核心约束）

```
本地                                     云端（唯一写者）
sync_external_sources.py --emit-inbox    sync_external_sources.py（无 --emit-inbox）
  → reflection_data/inbox/                 merge_external_inbox.py
     external_sources.local.json  ─scp─▶   → reflection_data/external_sources.json
                                            → inbox/archive/<ts>/
```

- 本地**禁止**直接改主清单；只写 inbox 提案
- 云端自己调研时直接写主清单（无冲突）
- 合并协议：幂等键 location；两侧同源并集 1 条（`also_seen_in[]`）；category 冲突取 priority 更高者、同级取云端；id 冲突后来者 `-2/-3`；元数据冲突云端校验值优先、本地值进 `local_hint`；一律不删，只标 `retired`

## 四、内存门禁（硬门禁，不可跳过）

- 阈值：`MemAvailable ≥ 800MB` **且** `≥ 10%`（`REA_MEM_MIN_FREE_MB` / `REA_MEM_MIN_FREE_PCT`）
- 检查点：运行开始 + 每源前后；越线 → 写 `reflection_data/reports/ALERT_mem_<ts>.json` → `exit 3`（本周暂停，已完成结果保留）
- 单源体量：`size_cap_mb=50`；并发固定 1
- 验收模拟：`REA_MEM_FAKE_AVAILABLE_MB=100 python3 scripts/external_source_weekly.py --dry-run` → 必须 exit 3 且主清单不变

## 五、分级与注入

| 级别 | 通过 | 去向 |
|---|---|---|
| `candidate` | 仅 Q1 | 只进 inbox，不进主清单、不注入 |
| `qualified` | Q1+Q2（stars≥300 / Python·TS / MIT·Apache·BSD） | 进主清单 `wave=4`，不自动注入 |
| `priority` | Q1+Q2+Q3（LLM 判定可映射我方模块） | 进主清单，允许 `--inject-max` |

注入只对 `verified && admissible && level∈{qualified, priority}` 且池中不存在的源，单次 ≤5（`--inject-max`）。

## 六、CLI 速查（在 `33-REA逆向解析工程` 目录下）

```bash
# 本地
python3 scripts/sync_external_sources.py --dry-run
python3 scripts/sync_external_sources.py --emit-inbox      # 只写 inbox
# 云端
python3 scripts/merge_external_inbox.py --dry-run
python3 scripts/merge_external_inbox.py                    # 合并 + 归档 inbox
python3 scripts/verify_external_sources.py --limit 5 --dry-run
python3 scripts/external_source_weekly.py --inject-max 5   # 周任务全流程
```

## 七、失败策略（FAIL-OPEN）

- 步骤 1/2/6 失败：只写报告，不污染主清单（临时文件 + 原子替换）
- 步骤 3 失败：部分成功保留，失败项不更新 `last_checked_at`（下周重试）
- 步骤 0/内存门禁失败：**硬退出**（exit 3），不改主清单
- 任一步失败都不阻断调研主流程

## 八、输出与验收

- 报告：`reflection_data/reports/{merge,verify,weekly}-<date>.json`、`sync_reports/<date>.json`
- 验收 G1–G5：三脚本单测通过 / dry-run 与人工核对一致 / 注入 ≤5 且 V 增量为正 / 低内存 exit 3 / inbox 重复合并 hash 不变
- 运维手册：`33-REA逆向解析工程/docs/EXTERNAL_SOURCE_PIPELINE_RUNBOOK.md`
- 规格：`SPEC-33-外部源自动沉淀流水线-可行性评估.md` §8–§10
