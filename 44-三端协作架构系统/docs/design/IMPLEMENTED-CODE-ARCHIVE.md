# 三端协同 — 已实现代码归档清单

> 归档时间：2026-10-30
> 基线：`origin/main` = `f50b562a24`（44 系统初始化）+ 本地 P0/P1 两个提交
> 归档原则：**只登记现有资产，不复制第二套实现、不改变云端运行态**；本清单为唯一索引。

---

## 一、已实现（有提交、有验证证据）

| 门/项 | 实现文件 | 规模 | 提交 | 验证证据 |
|---|---|---|---|---|
| **P0-3 G2 pre-commit** | `.pre-commit-config.yaml`、`scripts/precommit_secret_scan.py` | 136 行 | `568c01582c` | 三钩子（ruff/black/secret-scan）在 `087bd645a6` 系列提交中全 Passed；仅查 staged |
| **P0-1 registry schema 1.1** | `1-ARCHITECTURE/skills/_registry/{registry.json, migrate_schema_1_1.py, validate_registry.py}` | 209 + 119 行，186 条 SKILL | `568c01582c` | `validate_registry.py` 0 硬错误；role 五类分布 operator35/coordinator58/researcher45/trader40/risk8；tier 三端齐全 |
| **P0-2 模型状态机 + G7 eval** | `12-三屏趋势系统/ml/version_manager.py`、`ml/models/registry.json` | 637 行 | `568c01582c` | 状态机 none→staging→production→rejected/archived；evaluate/promote/rollback + current.json 原子写；沙箱验证通过 |
| **P0-4 G4 部署窗口门** | `37-一键启动脚本/g4-volatility-gate.py` | 199 行 | `568c01582c` | ATR20 分位 >90% 或 \|资金费率\|>0.001 拒绝(exit 4)；hotfix 需确认人+原因并写 24h 补审；实跑 rc=0（数据过期 FAIL-OPEN 放行） |
| **P0-0 云端评审日检** | `37-一键启动脚本/cloud-review.sh`、`cloud-logs.sh` | 121 + 83 行 | 本次归档 | D2/D3/D6 一页摘要，产出 `.trae/documents/review-reports/YYYY-MM-DD-daily.md`；全只读 |
| **P1-2 模型热加载** | `experiments/ab-trading/ml_inference.py` | 372 行 | `db3cbcf1d2` | 读 `models/current.json`（version+checksum），版本变化立即 reload；加载失败保留旧模型（FAIL-OPEN）；沙箱验证 v1→v2→v3 失败回退 |
| **G4 接入部署** | `31-分布式计算部署/phase1/update.sh` | 236 行 | `db3cbcf1d2` | 步骤 1/5 调用 G4，exit 4 中止；`--skip-g4` / `--g4-hotfix "原因"`；`bash -n` 通过 |
| **双轨登记** | `.trae/documents/SPEC-three-tier-collab-management.md` §4.5、`version_manager.py` docstring | — | `db3cbcf1d2` | V15 实盘线(shadow→ab_eval→live) 与 12-ML 研究线状态映射；禁止跨轨写入 |
| **三端协同 SKILL** | `1-ARCHITECTURE/skills/dream-three-tier-collab/SKILL.md` | 180 行 | `db3cbcf1d2` | category `collaboration` / role `coordinator` / tier 三端；registry 已登记（第 186 条） |
| **P1-1 G6 健康检查 + 自动回滚** | `37-一键启动脚本/health-check.sh`、`rollback-last-good.sh`、`31-分布式计算部署/phase12/{dreambuddy-healthcheck.service,.timer,12-health-watchdog.sh}` | 健康 11 项检查（6 unit + 3 HTTP + PG/Redis），连续 3 次失败触发回滚 | `febd1ae7e4` | 沙箱：dry-run 11 项、回滚 reset+留痕通过并 FAIL-OPEN；**云端实检 HEALTHY（0/11，9 OK + 2 SKIP）**，timer 已安装（5min 巡检） |
| **P1-3 Release 辅训通道** | `12-三屏趋势系统/ml/{publish_release.sh, ingest_release.py}`、`ml/version_manager.py::register_external` | 4.3 KB + 5.7 KB + 新增 1 函数 | `816c4ff3e6` | `publish_release.sh --version vX` 校验 model.pkl+meta.json、算 sha256、生成 manifest.json、`gh release create ml-vX`；`ingest_release.py --release ml-vX` 下载+校验（checksum 不符 exit 3）→ `register_external` 落 versions/ 并登记 state=none；`bash -n` + `py_compile` 全通过 |
| **P1-4 风控独立线登记** | `.trae/documents/SPEC-three-tier-collab-management.md` §一之七、`1-ARCHITECTURE/skills/dream-three-tier-collab/SKILL.md` §零 | — | `816c4ff3e6` | `trailing-stop-runner --real`、组合风险熔断、`alpha_decay_gate`、`actr_activation`、G4 阈值归属统一归 D6；4 条硬约束（风控优先于策略信号、禁止为收益放宽风控等） |
| **P2-1 冲突/依赖环校验** | `1-ARCHITECTURE/skills/_registry/validate_registry.py` | +E7 DFS 三色标记 / +E8 互斥 | `816c4ff3e6` | 实跑 186 条：0 硬错误；E7 无环（26 节点/74 边）；E8 同 category+role+mutex_group 无冲突 |
| **P2-2 Postmortem 模板** | `44-三端协作架构系统/github/templates/POSTMORTEM.md` | 模板 | `816c4ff3e6` | 事件分级/时间线表/5Why/处置与回滚（引用 rollback-log.jsonl）/可验收改进项/只读证据；归档路径 `review/feedback/postmortem-YYYY-MM-DD-<slug>.md` |
| **P2-3 灾备演练** | `31-分布式计算部署/phase12/12-dr-drill.sh` | 100 行 | `816c4ff3e6` | 沙箱实跑 **PASS，RTO=15s**（造故障版本→真实 `rollback-last-good.sh --auto`→断言 HEAD 与内容回到 last_good）；`--cloud` 只读预检，`--cloud --yes` 才真实 reset |
| **P2-4 季度 SKILL 审计** | `1-ARCHITECTURE/skills/_registry/audit_registry.py` | 7.4 KB | `816c4ff3e6` | 输出 `audit-report.json`（总数/status/category/role/tier/同名/path 缺失/deprecated/缺元数据）；实跑 active 166 / proposed 14 / shadow 6，同名 34 组涉 70 条；`--json-only`，恒 exit 0 |
| **八维 D1/D4/D5/D7/D8 脚本化** | `37-一键启动脚本/review-extended.sh` | 166 行 | `816c4ff3e6` | `d1\|d4\|d5\|d7\|d8\|all [--no-save]`，只读 SSH + FAIL-OPEN；实跑：D1 本地 vs 云端 HEAD/DIRTY、D4 快照 00:44 落盘 + API 200、D5 v1 production wf_auc=0.7703/gap=0.2917（阈值内）、D7 ufw active/仅 22+80 端口、D8 内存 4.9/15Gi、磁盘 23%、timer 44 |
| **双端协作：模块租约** | `44-三端协作架构系统/shared/tools/{lease.py,test_lease.py}` | R1-R8（R8 终审权归云端） | 本次变更 | 17 项单测全通过；冲突 exit 2；`lease` / `hotfix:*` 豁免；本地申请 `review:approved/**` 返回 exit 2 |
| **双端协作：文档双向同步** | `44-三端协作架构系统/shared/tools/docs_sync.sh` | 103 行 | 本次变更 | `bash -n` 通过；同步判定 = HEAD vs origin/main（不设 ACK 文件）；云端 fetch→全量路径校验→整提交 `pull --ff-only`（不做路径级 checkout），不绕过 G4 |
| **G3.5 角色分离门 + 租约 CI** | `.github/workflows/lease-guard.yml` | 70 行 | 本次变更 | PR 事件触发；无租约阻断；lease/hotfix/`lease-waiver` 豁免；可选身份白名单 |
| **P1 文档秒级同步（Actions）** | `.github/workflows/docs-sync.yml`、`37-一键启动脚本/docs-sync.sh` | — | `87e77ec63c` | 实跑：push 文档 → Actions 11s → 云端 `SYNCED d9179a2002 → 87e77ec63c`，`status.json=synced`；代码变更一律跳过（交 update.sh + G4） |
| **main 分支保护** | GitHub 仓库设置（`branches/main/protection`） | — | 2026-10-30 | 必需检查 `lint` + `lease`；禁 force push/删除；`enforce_admins=false`（owner 可直推） |
| **双端协作 SPEC + 独立评审** | `44-三端协作架构系统/docs/tech/SPEC-dual-end-collab-governance.md`、`review/feedback/2026-10-30-dual-end-collab-review.md` | — | 本次变更 | 独立评审"有条件通过"；M1-M6 必改、S1-S4 建议全部处置并回写；M7（终审权归云端）→ R8 |

## 二、本次一并归档的运维脚本（此前未入版本库）

| 文件 | 行数 | 用途 |
|---|---|---|
| `37-一键启动脚本/start-cloud-all.sh` | 76 | 云端全量服务恢复（分层暂停的逆操作） |
| `37-一键启动脚本/start-local-all.sh` | 61 | 本地 LaunchAgents 全量恢复 |
| `37-一键启动脚本/status-cloud.sh` | 30 | 云端服务状态速查（只读） |
| `37-一键启动脚本/status-local.sh` | 57 | 本地服务状态速查（只读） |
| `37-一键启动脚本/stop-cloud-layered.sh` | 85 | 云端分层暂停（保留训练/数据/反思/治理链） |
| `37-一键启动脚本/stop-local-layered.sh` | 104 | 本地分层暂停（进入"仅训练"模式） |
| `31-分布式计算部署/phase11/11-cloud-safety-overrides.sh` | 57 | 云端实盘安全覆盖（凭据到位 ≠ 云端实盘，强制 dry-run） |
| `31-分布式计算部署/phase11/11-full-migrate.sh` | 129 | 面板 8765 数据本地→云端全量同步（首次） |

全部通过 `bash -n` 语法检查；均不含写云端运行态的非预期动作（status/logs 只读）。

## 三、待办（非未实现：P1/P2 全部落地，余下为周期执行与实机验证）

| 项 | 内容 | 触发条件 |
|---|---|---|
| ~~P1-3 端到端 1 例~~ | **已完成（2026-10-30）**：v1 发布 `ml-v1`（GitHub asset digest == 本地 sha256 `2231ef7f…`）；**云端侧也已打通**：已装 gh 2.103.3（复用 luke `.git-credentials` 中已有 token，未新引入凭据，hosts.yml 权限 600），云端重复守卫 exit 1 且 registry 未改动 ✓，临时注册表正向链路 checksum 一致 → 登记 state=none ✓。注意：云端 ingest 必须用 `/home/luke/venv-trading/bin/python`（系统 python3 缺 pandas 会 FAIL-OPEN exit 2） | — |
| **P2-3 云端真实演练** | `12-dr-drill.sh --cloud --yes` 会真实 reset + 重启，需本人明确授权且在低波动窗口（G4） | 季度或重大变更后 |
| **D1/D4/D5/D7/D8 定期执行** | 建议 crontab/timer：D1 每次部署后+每周、D4/D8 每周、D5 每次训练后、D7 每月 | 周期 |
| **D7 发现的小项（P1 级，需走门禁链修复）** | 云端多个 `.env` 权限为 644/664（`.env.production`、`10-经典指标系统/.env`、`12-三屏趋势系统/.env`、`11-易经推理系统/.env`），应统一 `chmod 600`；SSH `permitrootlogin without-password` 建议改 `no`；云端 gh token 为个人全 scope token（admin:enterprise 等），建议后续换 fine-grained PAT 仅 repo scope | 下次部署窗口 |
| **采集源残余（P2）** | ① ~~theblockbeats 云端不可达~~ **已修复（1863f8e761）**：`DC_DISABLED_SOURCES` 环境级禁用，云端 drop-in 已配；② ~~coingecko 429~~ **已修复**：scheduler 启动错峰（90s 线性铺开）+ 源级节流 8s/次，云端实测 metrics status=ok、间隔 8-9s、零 429。残余观察项：yfinance crumb 429（有优雅降级，继续无 crumb 运行） | 每日 D3 巡检确认 |

> 说明：评审通道只读，上表 D7 问题不在评审时直接改云端，须经门禁链（本地改脚本 → G2 → 部署）修复。

## 四、云端评审提交记录（2026-10-30 00:08 CST）

已按 44 README 流程提交到云端 `/home/luke/dreambuddy/44-三端协作架构系统`：

| 云端路径 | 大小 | sha256 |
|---|---|---|
| `docs/tech/SPEC-three-tier-collab-management.md` | 22,885 B | `98c815166cda628c58b93408830d9c9ebbf4f4e3ddfd12f31794f23d2711ce89` |
| `docs/tech/three-tier-collab-qwen-research.md` | 13,059 B | `df3f4a66c922cf730bc531aff92ff5202bd215ca9246772ce2a5f2c9c738dd68` |
| `docs/design/dream-three-tier-collab-SKILL.md` | 9,846 B | `64e1008e64efeda17968f6546dd8b158d4ee38e814e272c20d28a38b8ca4e162` |
| `review/pending/SPEC-three-tier-collab-management.md`（评审副本） | 22,885 B | 同上 |

与本地文件逐一对齐（sha256 一致 3/3）。**云端评审执行体尚未落地**（`cloud/scripts` 为空、无 review 相关 timer）。

**云端评审反馈（2026-10-30）**：结论"有条件通过"。必改 M1（D5 报告时效）、M2（G4 参数来源/周期）、M3（budget-baseline 落盘）、M4（脚本缺失）与建议 S2（hotfix 留痕）、S3（SSH 前置检查）已回写 SPEC 与 SKILL；M4 因三个脚本已入库而关闭；S1（yijing-polling-trader 静默悬案）保留为 D3 待办。闭环表见 SPEC §一之六。

**副本刷新（2026-10-30 01:00 CST）**：SPEC 增加 §一之七「风控独立线」（P1-4）后，`docs/tech/` 与 `review/approved/` 两份副本同步至 `d966018a…`（sha256 `d966018a953595ec358dabbb354a0dde39b566fcf310dcb1162ee14cecda017a`）；SKILL 同步至 `ebb1f3ea…`（sha256 `ebb1f3eab7278a0b53c9e1b0f6f5173fbb21a4e20e2a0d1b829bbbcfff491558`）。三份 SPEC 与两份 SKILL 逐字节一致。

## 五、归档说明

- 本清单与 `docs/tech`、`docs/design` 下的文档副本同批提交，使技术文档脱离本地 `.trae/`（gitignored）成为版本库资产。
- 代码本体不复制：清单只登记路径与提交号，避免出现第二套实现。
- 运行时状态文件（`backtest_cache/*.json`、`signal_pool/pool.json`、`architecture_health_report.json`）不入归档。
