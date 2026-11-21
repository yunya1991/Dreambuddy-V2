# 架构升级后的弃用清单（云端实测版）

> **版本**: v1.0 | **调研日期**: 2026-11-18
> **调研方式**: 云端 `43.160.201.117` 只读实测（systemd / 进程 / 端口 / cron / PostgreSQL / 磁盘 / git） + 本地仓库代码与文档交叉核验
> **定位**: 一次性盘点，回答「升级后哪些东西已经不该再被当作现状」。清理动作需二次确认后执行。
> **权威口径**: 架构 `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` v4.2；交易契约 `49-交易框架协议/SPEC.md`；执行权 `47-MCP管理系统/registry/execution_rights.json`
> **决策记录（2026-11-18）**: 本轮仅交付清单，**不执行任何清理**；11 域实盘进程（DP-02/03/17）定为「先观察，暂不处理」，不得擅自停用或改动。

---

## 一、结论先行

1. **升级本身基本落地，但「弃用」只落在代码和文档里，没有落到运行时与配置里**。最典型的证据是云端健康检查连续 25 次失败，唯一失败项是一个已经不存在的 unit 名（`yijing-polling-trader`）。
2. **11 域交易并未真正退场**：下单出口已收口到 22（代码层实现），但 11 域仍有一个**不受 systemd 管理的实盘进程**在跑（`OKX_DRY_RUN=false`，01:58 仍在开仓 ARB）。这是当前最大的架构-运行时不一致。
3. **数据库迁移是「半迁移」**：18 已用 PostgreSQL，19-DAL 仍以 SQLite 为唯一主库（`dreambuddy_core.db` 1.1G，今日仍在写）。文档里的「DB 集中化」不能按已完成理解。
4. **文档错漏集中在三处**：全局索引（`DEBT_INDEX` / `SYSTEM_MAP` / `ARCHIVE_INDEX`）停更于 10 月中；31-分布式计算部署仍在描述已消失的部署形态；49 与 47 对「11 是否还有执行出口」表述互相矛盾。
5. **可清理的确定性垃圾约 8-9GB**（19 的 `backups/` 7.3G、4-MEMORY 的 WAL 2.5G、deploy-backups 多份），且备份轮转服务本身是停用状态。

---

## 二、现状口径（以实测为准）

| 维度 | 升级后应有形态 | 云端实测 |
|---|---|---|
| 系统分层 | L0 数据/认知 → L1 零 token → L2 大模型编排 | 运行中的服务与之一致（18/19/39/42/23/50/22） |
| 交易决策 | 23 唯一决策权威；50 走 paper/live:50-bypass；11 仅信号源 | 23 `entry_runner`/`exit_runner` 常驻；50 每 5min 影子 + live chain；11 仍在跑实盘 |
| 下单出口 | 唯一出口 22 `TradeExecutionGateway` | 代码已收口；11 域进程仍为手动启动，未经 systemd |
| 战略层 | 43 `strategic_extension` | `dreambuddy-43-strategic-publish.timer` enabled，正常 |
| 数据库 | PostgreSQL 集中（38 方案 4） | PG 有 `fis` 2.2G / `data_center` 239M / `dreambuddy` 10M；19 仍写 SQLite |
| 前端 | 3.1-FRONTEND，nginx 双实例滚动 | 3001/3002 均在 nginx upstream 中，属设计内 |
| 文档 SSoT | v4.2 + 归档横幅 | 横幅已加；但导航索引与债务清单未同步 |

---

## 三、弃用清单

风险级别：**R0 立即修（影响告警/资金/可运维性）** · **R1 本周期（架构漂移/资源浪费）** · **R2 计划清理（确定性冗余）** · **R3 待确认（先取证再动）**

### A. 运行时与服务层（云端）

| ID | 对象 | 证据 | 判定 | 风险 | 建议动作 |
|---|---|---|---|---|---|
| DP-01 | `dreambuddy-healthcheck.service` 中的 `yijing-polling-trader` 检查项 | 连续 25 次 CRITICAL，唯一失败项为 `unit:yijing-polling-trader → not-found`；13 项检查中其余全 OK | **配置漂移**（检查项指向已消失 unit） | R0 | 改检查项为实际进程/新 unit；不要为了让它变绿而重建旧 unit |
| DP-02 | 11 域实盘进程 `scripts.memory_l4.polling_trader`（PID 2269352） | 运行于 `session-87170.scope`（**非 systemd**），cwd `11-易经推理系统`，参数 19 币、`--confidence 0.7955`，`OKX_DRY_RUN=false`，日志 01:58 仍有「ARB 开仓」 | **未纳管实盘**，与「11 域退场」目标冲突 | R0 | 先不动进程；确认是否继续跑，再决定「纳管为 systemd」或「按新流程停用」。任何停用需先核持仓与 SL/TP |
| DP-03 | 11 域 `.env` 中 `OKX_DRY_RUN=false` | 云端 env 实测 | 与「11 仅信号源」口径不符 | R0 | 变更前必须先确认 11 是否仍承担 live 执行职责 |
| DP-04 | `dreambuddy-nn-live-chain.service` 描述 | 描述含「→ 11 live order」，实际 ExecStart 为 `50-NN.../run_live.py` + `22-执行引擎中心/x1_live_executor.py` | **过期描述** | R2 | 改描述为「50 → 22」，避免误导排障 |
| DP-05 | 37-一键启动脚本 6 个脚本 + 31 文档中的 `yijing-polling-trader` | `health-check.sh:43`、`cloud-logs.sh:17,46`、`cloud-review.sh:16,21,89`、`start-cloud-all.sh:14`、`stop-cloud-layered.sh:20`、`status-cloud.sh:11`；31 文档 8 处 | **过期拓扑** | R1 | 统一改为实际纳管方式（见 DP-02 决策） |
| DP-06 | PM2 | `/usr/bin/pm2` 存在，`pm2 list` 零进程 | **已弃用工具链**（前端早已 systemd 化） | R2 | 卸载或明确标注不用于生产 |
| DP-07 | `deploy-backups/` 8 份前端备份（含 11-14/15 的 `pre-*`） | `ls /home/luke/deploy-backups` | 无保留策略 | R2 | 保留最近 2-3 份，其余归档/删除 |
| DP-08 | `19-数据访问层/data/backups` 7.3G | `du` 实测；`dal-rotate.service` 为 `inactive dead` 且未 enabled | **备份轮转实际停摆** | R1 | 恢复轮转 timer；按保留策略清理（磁盘已 63%） |
| DP-09 | `4-MEMORY/data/cognitive_memory.db-wal` 2.1G、`evidence_ledger.db-wal` 428M | `du` 实测 | WAL 长期未 checkpoint | R1 | 低峰执行 checkpoint/truncate，并核查写入频率 |
| DP-10 | `dreambuddy-redis` 容器 | `dbsize=0`，仅 1 个连接、累计命令 27 万（无业务键） | **疑似未使用** | R3 | 先全仓取证是否引用；确认后停容器并移除健康检查里的 SKIP 项 |
| DP-11 | `dreambuddy-minio` 容器 | 桶：`backtest-results` / `data-cache` / `models` | 用途待确认 | R3 | 取证后定去留 |
| DP-12 | `/home/luke/tmp/group_poller.py`（root 运行）、`/home/ubuntu/fis-p0/vector_bridge_daemon.py` | 进程实测，均在仓库外 | **仓库外漂移进程** | R2 | 确认归属后迁入仓库并纳管，或停用 |
| DP-13 | 云端工作区脏文件（37 项） | 多为 `40-*/*.json`、`42-*/runtime/*.json`、`.deploy/health-state` 等运行态 | 运行态入库（对应 D094/D096/D097 未还） | R1 | 运行态目录进 `.gitignore`；云端不提交运行态 |
| DP-14 | 云端 HEAD 落后本地 1 个提交 | 云 `1cbe1301`(01:54) vs 本地 `34bc950d8c`(02:00) | 发布窗口差 | R3 | 按部署流程快进，不做 reset |

### B. 交易链路（11 域交易 / 11 域战略层）

| ID | 对象 | 证据 | 判定 | 风险 | 建议动作 |
|---|---|---|---|---|---|
| DP-15 | 11 域独立下单出口 | `polling_trader.py:1016-1087` 已接 `TradeExecutionGateway`，失败即 `FailClosedOkxClient`；`11/docs/ENGINEERING_INDEX.md` v3.5 记录「11 不再存在独立下单出口」 | **代码层已弃用** | — | 无需动作 |
| DP-16 | 「11 只保留 live 执行网关」的表述 | `49/SPEC.md:233` 与 `47/registry/execution_rights.json:321`（「11 域不再有独立执行出口」「11 不再持有下单客户端」）互斥 | **文档口径冲突** | R1 | 以 47 为准统一 49 表述；这是 11 域退场判定的关键依据 |
| DP-17 | `11-strategy` 战略层 | `49/SPEC.md:1146,1407` DEC-01 明确废弃，战略层归 43；11 配置 `enable_five_domain=False`、`shadow_mode=True` | **已弃用（保留为信号源）** | R1 | 清理 11 内残留 strategic 分支与开关，保留 bcrm/bdsm/event_arbitrage/washout 四子池 |
| DP-18 | 6-TRADING 两条 OKX 直连 | `6-TRADING/scripts/dream_trade_exec.py`、`trade_exec_api.py`；DEC-25 要求「降为调试/回放并移除生产凭证」「仅 demo」 | **判定已弃用但未执行完** | R2 | 核验是否仍有 live 凭证；按 DEC-25 收口 |
| DP-19 | `31-分布式计算部署` | cloud-ops SKILL 明确「已过时，不要照旧文档执行」；其 `update.sh`/PM2 流程与现状不符 | **文档/流程层已弃用** | R2 | 整目录加「已归档」横幅并指向 44/37 现行流程 |
| DP-20 | 12-三屏 / 16-调控 / 14-V15 的在线性 | `signal-scanner`（300s）、`trailing-stop-runner --real`（300s）、`v15-api:8771`/`v15-capital-api:8770` 均 enabled 且 nginx 有路由 | **未弃用，仍在生产链路** | — | 不要误清；16 的 trailing stop 是实盘 |

### C. 数据库与存储

| ID | 对象 | 证据 | 判定 | 风险 | 建议动作 |
|---|---|---|---|---|---|
| DP-21 | 「数据库已迁移 PostgreSQL」的认知 | 19-DAL README 仍写 `DB_BACKEND=json_legacy` 默认；`dreambuddy_core.db` 1.1G 今日仍在写；38 仅有 `migrate_to_postgres.py` | **半迁移** | R1 | 文档改为「PG 仅覆盖 18 联邦/评测域；19 主库仍 SQLite」；迁移收尾单独立项 |
| DP-22 | `19/data/core.db`（0 字节） | `du` 为 0 | 空占位 | R2 | 删除 |
| DP-23 | `3.1-FRONTEND/.env.production.bak.20261115`、`.bak.202611130225` | grep 到 postgres DSN | **含凭据的历史备份** | R1 | 立即删除（先确认已有正式备份） |
| DP-24 | `11-易经推理系统/.env.bak.20261031` | find 实测 | 同上 | R2 | 删除 |
| DP-25 | `4-MEMORY/data/` 4.4G、`9-基本面分析/` 1.7G、`3.1-FRONTEND/` 1.7G | du 实测 | 体量集中点 | R3 | 逐项核查（venv / .next / 历史产物）后再清 |

### D. 文档

| ID | 对象 | 证据 | 判定 | 风险 | 建议动作 |
|---|---|---|---|---|---|
| DP-26 | `DEBT_INDEX.md` v2.5（2026-10-11） | 一个多月未更新；期间新增 22/49/50/51/53/54/56 等模块 | **过期索引** | R1 | 至少补一次增量评审，或明确降级为「历史债务快照」 |
| DP-27 | `0-系统文档管理/2-文档地图/SYSTEM_MAP.md` v2.3（2026-10-16） | 仍写「7 顶层 + 8 子系统」，未收录 22/35/38/44/46/47/49/50/51-56 | **导航过期**，会把 AI 带偏 | R1 | 按现目录重建；这是最高性价比的文档修复 |
| DP-28 | `ARCHIVE_INDEX.md` v1.0（2026-10-11） | 只记录 7 月归档 | 过期 | R3 | 并入 DP-27 的治理批次 |
| DP-29 | SSoT 内部版本号不一致 | §16.2 横幅模板写「v4.1」，文档本身 v4.2；§16.1 冲突裁定也写 v4.0/v4.1 | 版本漂移 | R2 | 统一为 v4.2，横幅模板改为不带版本号 |
| DP-30 | 49 与 47 交易契约口径 | 见 DP-16 | 双口径 | R1 | 一次修正，避免「11 是否还能下单」被反复误判 |
| DP-31 | `1-ARCHITECTURE` 归档横幅 | 实测 6 份旧文档横幅均已加 | **已处理** | — | 无需动作（避免重复治理） |

---

## 四、清理顺序（按风险递增，可独立回滚）

**Batch 0 — 只修漂移，不删东西（建议立即）**
1. DP-01 健康检查检查项 → 让 `dreambuddy-healthcheck` 恢复有意义（当前是「永久红」，等于告警失效）。
2. DP-16 / DP-30 统一 11 域执行出口唯一口径（47 为准）。
3. DP-04 / DP-05 修正 unit 描述与 6 个脚本 + 31 文档中的失效 unit 名。
4. DP-27 / DP-26 重建导航地图与债务索引增量。

**Batch 1 — 低风险确定性清理（先备份后删）**
1. DP-08 恢复 `dal-rotate` 并清 `19/data/backups` 存量（7.3G）。
2. DP-09 WAL checkpoint（2.5G）。
3. DP-23 / DP-24 删除含凭据的 `.env.bak*`。
4. DP-07 / DP-06 / DP-22 / DP-13 备份收敛、PM2 下线、空库删除、运行态出库。

**Batch 2 — 需要业务决策**
1. DP-02 / DP-03：11 域实盘进程「纳管」还是「停用」；停用前必须核对持仓、SL/TP、以及 22 链路接管情况。
2. DP-10 / DP-11：Redis / MinIO 去留（先全仓取证）。
3. DP-18：6-TRADING 直连凭证核验与收口。
4. DP-21：19-DAL → PG 的收尾排期（不要与 Batch 1 混做）。

**Batch 3 — 高风险/大改**
1. 删除 11 域交易代码前，先完成 DP-02 决策 + 至少一个完整交易日观察。
2. 31 目录整体归档替换。

**回滚原则**：Batch 0 全部为文本/配置类，`git revert` 即可；Batch 1 删除前先 `du` 记录清单 + 保留 24h 回收；Batch 2/3 一律先做快照（PG dump + 关键 `.db` `.backup`）。

---

## 五、验收标准（每批完成后）

- Batch 0：`dreambuddy-healthcheck.service` 的失败原因不再是「unit not-found」；全仓 `grep -r "yijing-polling-trader"` 只剩历史归档文档。
- Batch 1：`df -h /` 释放 ≥8G；`dal-rotate.timer` 为 enabled；`4-MEMORY` WAL < 256M。
- Batch 2：`ps` 中不再有 session-scope 的实盘进程；或该进程已由 systemd 纳管且 `Restart=` 生效。
- Batch 3：`11-易经推理系统` 仅剩信号源职责；`49/SPEC.md` 与 `47/execution_rights.json` 对 11 的表述一致。

---

## 六、本次未下结论的项（需业务/持仓信息）

- 11 域实盘是否属于「有意保留的 live 执行器」——文档互斥，运行时又在真实下单，必须由人裁定。
- Redis / MinIO 是否有外部消费者。
- `/home/ubuntu/fis-p0` 与 `/home/luke/tmp` 的归属。
