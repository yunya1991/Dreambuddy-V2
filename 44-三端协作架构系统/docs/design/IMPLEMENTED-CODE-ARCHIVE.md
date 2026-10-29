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

## 三、未实现（按 SPEC 计划待办）

| 项 | 内容 |
|---|---|
| P1-1 | G5/G6 自动回滚 + systemd watchdog（人为造故障 → 自动回滚演练） |
| P1-3 | 本地辅训 GitHub Release 通道（1 例端到端） |
| P1-4 | 风控独立线在门禁链文档中显式登记 |
| P2-1 | SKILL 冲突检测（category+role 互斥）与依赖环校验（validate_registry 扩展 W4/E7） |
| P2-2 | Postmortem 模板 + GitHub 归档流程 |
| P2-3 | 首次灾备演练（记 RTO/RPO） |
| P2-4 | 季度 SKILL 审计自动化 |
| 八维 | D1/D4/D5/D7/D8 脚本化与固定周期（当前仅 D2/D3/D6 有 `cloud-review.sh`） |

## 四、云端评审提交记录（2026-10-30 00:08 CST）

已按 44 README 流程提交到云端 `/home/luke/dreambuddy/44-三端协作架构系统`：

| 云端路径 | 大小 | sha256 |
|---|---|---|
| `docs/tech/SPEC-three-tier-collab-management.md` | 20,770 B | `6f4c9b379acd1d8c75ae38cd7d1066c7fbe3376e660e92187b7876640f9b6156` |
| `docs/tech/three-tier-collab-qwen-research.md` | 13,059 B | `df3f4a66c922cf730bc531aff92ff5202bd215ca9246772ce2a5f2c9c738dd68` |
| `docs/tech/dream-three-tier-collab-SKILL.md` | 9,613 B | `30cd9ab6bc5a3938add73be988646a0327046e3076aa71705447fb5ffe13144e` |
| `review/pending/SPEC-three-tier-collab-management.md`（评审副本） | 20,770 B | 同上 |

与本地文件逐一对齐（sha256 一致 3/3）。**云端评审执行体尚未落地**（`cloud/scripts` 为空、无 review 相关 timer）。

## 五、归档说明

- 本清单与 `docs/tech`、`docs/design` 下的文档副本同批提交，使技术文档脱离本地 `.trae/`（gitignored）成为版本库资产。
- 代码本体不复制：清单只登记路径与提交号，避免出现第二套实现。
- 运行时状态文件（`backtest_cache/*.json`、`signal_pool/pool.json`、`architecture_health_report.json`）不入归档。
