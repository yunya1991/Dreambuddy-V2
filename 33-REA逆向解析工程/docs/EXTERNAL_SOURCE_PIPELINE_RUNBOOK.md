# 外部源沉淀流水线 RUNBOOK

> 规格：`SPEC-33-外部源自动沉淀流水线-可行性评估.md` §8–§10
> SKILL：`.trae/skills/dream-external-source-pipeline/SKILL.md`

## 1. 角色分工

| 端 | 职责 | 写者 |
|---|---|---|
| 本地 | 抽取/去重/归类/归档 + 写 inbox 提案 | 否（只写 inbox） |
| 云端 | inbox 合并 + 增量校验 + 可选注入 | **唯一写者** `reflection_data/external_sources.json` |

## 2. 目录

```
33-REA逆向解析工程/reflection_data/
├── external_sources.json          # 主清单（云端唯一写者）
├── inbox/external_sources.local.json   # 本地提案（同步到云端 inbox/）
├── inbox/archive/<ts>/            # 合并后归档
└── reports/                       # merge-*/verify-*/weekly-*/ALERT_mem_*
```

## 3. 本地每周

```bash
cd 33-REA逆向解析工程
python3 scripts/sync_external_sources.py --dry-run          # 先看抽取结果
python3 scripts/sync_external_sources.py --emit-inbox       # 写 inbox（不碰主清单）
# 同步到云端
scp reflection_data/inbox/external_sources.local.json <云端>:/home/luke/dreambuddy/33-REA逆向解析工程/reflection_data/inbox/
```

## 4. 云端每周（cron 周日 04:00）

```bash
cd /home/luke/dreambuddy/33-REA逆向解析工程
python3 scripts/external_source_weekly.py                  # 报告 + 合并，不注入
python3 scripts/external_source_weekly.py --inject-max 5   # 额外注入 ≤5 源
```

退出码：
- `0` 全部成功
- `3` 内存门禁触发（本周暂停，不改主清单）
- `1` 部分步骤失败（FAIL-OPEN，已写报告）

## 5. 内存门禁

- 阈值：`MemAvailable ≥ 800MB` 且 `≥ 10%`（`REA_MEM_MIN_FREE_MB` / `REA_MEM_MIN_FREE_PCT`）
- 检查点：开始 + 每源前后；越线写 `reports/ALERT_mem_<ts>.json` 并暂停
- 验收模拟低内存：

```bash
REA_MEM_FAKE_AVAILABLE_MB=100 python3 scripts/verify_external_sources.py --limit 5
# 期望：ALERT + exit 3 + 主清单 hash 不变
```

## 6. 校验与分级

| 级别 | 条件 | 去向 |
|---|---|---|
| candidate | 仅 Q1 结构过滤 | inbox |
| qualified | Q1 + Q2（stars≥300、Python/TS、MIT/Apache/BSD） | 主清单，不注入 |
| priority | Q1+Q2+Q3（LLM 相关性） | 主清单，可注入 |

`GITHUB_TOKEN` 可选（未设置时 60 次/小时限流，单次上限 40 源）。

## 7. 故障处理

| 现象 | 处理 |
|---|---|
| `ALERT_mem_*` 出现 | 停用本周注入；确认实例内存后手动补跑 `verify_external_sources.py --limit 20` |
| merge 报告 `changed=false` 但存在 inbox | 主清单已含这些源；检查后可手动归档 inbox |
| verify 出现大量 `api_fail` | 检查网络/限流；失败项不更新 `last_checked_at`，下周自动重试 |
| 注入后池未增长 | 查 `weekly-*.json` 的 `inject.rejected`（空壳门 `MIN_EFFECTIVE_NODES=3`） |
| 双端 hash 不一致 | 以云端为准：回传主清单到本地，勿本地改主清单 |

## 8. 回滚

主清单为纯 JSON：`git checkout -- reflection_data/external_sources.json` 即可；注入产物在 `reflection_data/replay_pool/external/`，按 `source_label` 删除对应目录即可。
