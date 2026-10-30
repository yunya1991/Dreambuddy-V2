# L0 三层架构 · 本地多视角评审（第 1 轮）

> 日期：2026-10-30　评审对象：[l0-three-layer-SPEC-C.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.trae/documents/l0-three-layer-SPEC-C.md) v0.2
> 评审方式：架构 / 工程 / 风险 三个独立视角并行，只读评审（不改代码、不改文档）
> 基线：两端代码已对齐 `4d6837f880`；云端 Ubuntu 24.04.5（4C8G/120G）为交付目标
> 结论：**三方均为「有条件通过」**，合并后有 **12 项 P0** 必须在 P0 段开工前关闭

## 一、三视角结论

| 视角 | 结论 | 一句话理由 |
|---|---|---|
| 架构 | 有条件通过 | P/I/S 分层方向成立，但 port 契约不足以兑现"换库不波及上层"，且 C7 与"新代码必须建在门面上"自相矛盾 |
| 工程 | 有条件通过 | C3/C10 在非包化仓库不可执行；C1/C2/C9/C13 验收口径不可测；部署身份分裂 + 密钥内联会直接放大云端故障 |
| 风险 | 有条件通过 | "run_id 幂等"在现有 `record()` 上不成立；C4 切库在 19-DAL 无 PG 后端；新增记账/检索会与实盘争 4C8G |

## 二、P0 合并清单（必须关闭才能开工）

| # | 问题 | 证据（已核实） | 处置 |
|---|---|---|---|
| P0-1 | **C7 绕过 port 且非"零依赖"**：`unified_search` 设计为直接路由既有窄接口，等于永久旁路；41 实为 `/home/ubuntu/fis-p0` 独立 venv 外部部署，带 `FIS_AGENT_TOKEN` 权限、索引靠每小时 cron 刷新；三源分数不可比、去重键未定义 | `l0_foundation.py:162`；`41-文件索引系统/api/search_api.py:11-14`；SPEC §3.2 组件③ | C7 必须经 C2 的 `Search` port 分发（仅实现 3 个 backend adapter）；min-max 归一化 + `source` 分层；去重键=规范化路径；41 探活失败必须显式报"全降级"而非返回空 |
| P0-2 | **C1 基线错误**："仅 34 使用、原路径不动"不成立——3.1-FRONTEND 3 个脚本、39 已在调用，L2 还用了私有 `_load_cle` | `3.1-FRONTEND/scripts/data_query_executor.py:26`、`l1_route_signal.py:41`、`l2_cognitive_settle.py:42`、`39-金融语义蒸馏系统/scripts/gen_spacetime_events.py:58` | C1 增"调用方清单 + 唯一入口声明"；私有方法冻结（`_load_cle`→公有 `load_cle()` 并设弃用期） |
| P0-3 | **契约缺关键语义**：信封无 `version/trace_id/idempotency_key/error_code`；port 无事务边界、分页、身份/权限、错误枚举 → C8/C12 只能往 meta 塞字段 | SPEC §3.1 信封；`41/api/search_api.py` 的 `user_id/token` 权限模型 | 信封加 4 字段；每个 port 补 4 类语义，权限作为入参显式化 |
| P0-4 | **安全：明文口令 + 硬编码路径 + 模块级 sys.path 注入；部署身份分裂（脚本 `luke` / 门面 `ubuntu`）** | `l0_foundation.py:41-42,162-165`（含 `FIS_PG_PASSWORD` 默认值）；`31-分布式计算部署/phase1/update.sh:10-13` | 新增 G0 门禁：密钥外置 + **立即轮换已入库口令** + 配置注入 + 路径注册表化；先清理再谈 C1 |
| P0-5 | **CI 不阻断**：所有 pytest job `continue-on-error: true`，新契约测试不会让流水线红 | `.github/workflows/ci.yml:81,86,91,96,106,113` | G0：新增独立阻断 job `l0-contracts`（不动既有 job，避免零回归冲突） |
| P0-6 | **C3/C10 不可执行**：仓库非包化（中文目录 + 大量 `sys.path.insert`/importlib），import-linter 分层契约覆盖不到 | SPEC §6 C3/C10；`l0_foundation.py:41`、`di.py` 相对导入 | C3/C10 降级为 grep 门禁 + 白名单；包化（`dreambuddy_l0/`）列为 P1 前置 |
| P0-7 | **"run_id 幂等"不成立**：`record()` 无幂等入参，记忆 ID 含毫秒 → 同一 run 会写多条记忆，verify 反复升级置信度 | `4-MEMORY/9-工具与接口/.../cognitive_loop_entry.py:439,941`（ID 生成）；SPEC §6 C8 | C8 前置：认知表加 `external_id` 唯一索引 + `record(idempotency_key=...)` |
| P0-8 | **C4 无法落地**：19-DAL 合法后端只有 `json_legacy / dual_write / sqlite_unified`，**没有 PG 后端** | `19-数据访问层/dreambuddy_dal/di.py:15-17,46-48` | 拆为 C4a（先建 PG adapter + 契约测试）→ C4b（再搬 `dc_pg` 能力），C4b 才允许"调用方零改动" |
| P0-9 | **切库判据会假 MATCH**：`DualWrite` 新库写失败仅 `warning`，影子比对只比 `len()` | `di.py:177`（`MATCH if len(a)==len(b)`）、`di.py:220,239` | C5 前先补字段级 diff + diff 率门槛 + per-repo 读开关（现 `READ_SOURCE` 是全局 env） |
| P0-10 | **`job_runs` 会静默停摆**：`logical_window` 未定时区（host `+0800` vs PG 容器 UTC）；回收后同窗重跑被 unique 拒；`_last_run` 在内存、重启齐发、长任务跨窗 | `update.sh:233`（`+0800`）；SPEC §3.3 | 定义 `logical_window` = UTC 门控时刻 + 迟到容忍窗；跨窗拆 run；记录 `missed_run`；**连续 N 窗无 run 必须告警** |
| P0-11 | **资源争抢打断实盘**：每次 `record()` 都可能 `Popen` 触发 41 重建；JSONL 无轮转；磁盘写满会打断实盘写仓 | `cognitive_loop_entry.py:1062`；云端 disk 120G | G0：logrotate + 磁盘水位告警；C8 前置批量/去抖；非实盘 unit 限 CPU |
| P0-12 | **部署回滚误触发**：`update.sh` 用 `--dry-run` 调健康检查、未 `--record-good`，失败计数不清零 | `phase1/update.sh:231`；`37-一键启动脚本/health-check.sh:8,86`；`rollback-last-good.sh:115-117` | G0：部署末尾改 `--record-good`；回滚需人工确认（连续 3 次失败不自动 `reset --hard`） |

## 三、P1 采纳项（并入 SPEC，不阻断开工）

| # | 问题 | 处置 |
|---|---|---|
| P1-1 | port 数量矛盾：§3.1 说 7（含 Facade），C2/§9 只写 6 | 明确 **Facade = 门面本体，不计为 port** → 上限 6；Event 只保留"跨能力通知"，落库一律走 Store |
| P1-2 | 方言能力集只声明操作符，漏类型映射（datetime/jsonb/numeric）、隔离级别、连接上限；DDL 无归属（`init_db_schema` 在 DI 里） | 能力集分"操作符 + 类型语义映射"两层；新增 schema registry，**迁移只有唯一 owner**，业务禁止建表 |
| P1-3 | `L0-S` 与 SACG 的 S 同字母；v1.3 明确"L0 不直接对外路由" | 保留命名但强制写 `L0-S(调度)`；检索入口标注"L0 供给 + L1 聚合"，调用者限 L1/L2 |
| P1-4 | `job_runs` / observability 无保留期与归档（4C8G/120G） | C9 附保留期与归档，复用 38 冷热分层；C12 health 增"表增长/最老滞留" |
| P1-5 | C13 验收自相矛盾（2 个不同任务却要求"同一任务两端可见"） | 改为"每端各 1 个任务在 `job_runs` 可见"；health 探测不依赖 `systemctl` 内部状态 |
| P1-6 | C4 薄壳若保 `dc_pg` 的裸 dict/list，与 DAL repo 契约不同 | 薄壳保返回结构 + 保 FAIL-OPEN；抽样比对定为"字段级 + 样本量 + 阈值" |
| P1-7 | C5 开关粒度未到文件级；11 是实盘宿主（`yijing_trading`） | 只读查询先行、写路径暂缓；开关按文件/进程；改后需重启实盘的批次单列窗口 |
| P1-8 | C11/C12 缺默认值 | C11：去重窗口 10min、并发 2、单次 ≤20 job；C12：`health_cmd` 2s 超时 + 60s 缓存 + 并发探测 |
| P1-9 | 缓存语义未进 port（Redis 在栈内） | Store/Search port 增 `cache_policy`（默认不缓存 + TTL 语义） |
| P1-10 | 无 consumer-driven 契约测试 | 五能力对外接口加 golden schema 快照，防 MCP/前端双端漂移 |

## 四、三方共同指出的三条"最危险路径"

1. **C4/C5 切库**：无 PG adapter + 只比长度的影子比对 + 新库写失败静默 → 一开开关就读空/读旧，"换库出事"原样重演。
2. **C9 调度**：时区错位 + unique 键 + 内存态 `_last_run` → 重启齐发或同窗被拒，采集停摆而表上无痕。
3. **C7/C8/C11 与实盘争资源**：检索与每次 record 触发的 41 重建子进程抢 4 核，止损/轮询线程被拖慢。

## 五、处置结果

- 全部 P0 已回写为 **SPEC-C §5.1「G0 开工前置门禁」** 与 C1/C2/C4/C5/C7/C8/C9/C13 的修订验收口径；
- P1 已并入 §3.1/§3.2/§3.3/§5/§6/§9；
- 待用户确认后，方可进入云端阶段 4 评审（D1-D8）。
