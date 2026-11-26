# 变更记录 — 15-监控告警系统

> **版本**: v2.28 | **更新日期**: 2026-11-26

---

## 版本变更记录

| 版本 | 日期 | 变更内容 | 影响范围 |
|------|------|----------|----------|
| v2.28 | 2026-11-26 | 新增 TD §14「主神经网络监控模块（main-nn）」并归档原 SPEC-MAIN-NN-MONITOR v0.1：M0–M14 节点表（48 保持 B 类、作为 M0 上游门禁）、`chain_event.v1` 扩展（`source/mode/reason_category`）、指标族、告警复用映射 + 3 条新增规则（`MainNNStrategicFallbackDominant` 三条件由 `main_nn_strategic_fallback_dominant` 一次判定、`MainNNConstraintDegraded`、`MainNNExecutionRightsMismatch`）；导出器新增 `main_nn_metrics()`；`monitoring.yaml` 新增 3 个 artifacts + `signals.main_nn`/`execution.main_nn`；`domains.yaml` L1.trade 登记 main-nn + 4 探针 | 文档+代码+配置+规则 |
| v2.27 | 2026-11-26 | `SltpReconcileFailed` P1 误报治理：11-26 19:24–19:30 CST 每轮 `failed=1` 实为 AMZN 的 `50011 Too Many Requests` 查询失败（保护状态未知 ≠ 缺保护）。22 `reconcile_sltp` 拆分 `failed`（下单/去重失败）与 `query_failed`（algo 查询失败，落 `kind=algo_query_fail` 明细）；导出器新增 `sltp_reconcile_query_failed_1h` 并新增 P2 `SltpAlgoQueryFailed`（>0 for 30m）；P1 只看真实补挂失败。TD §13.8.3/§13.8.5/§13.9.2 同步，新增 2 项单测 | 代码+规则+测试+文档 |
| v2.26 | 2026-11-25 | `ArtifactStale` 二次口径纠偏（11-25 实测 19h 无 submit 误报：OP 已持仓被 `duplicate_position` 拦下，其余 525 条决策全 WAIT）：① 新增 `decision_flow_23` 产物探针，直接取 `chain_events-*.jsonl` 中 `pipeline.decision` 最新 ts（WAIT 也算决策），1800s/P1 真正判"决策沉默"；② `execution_decisions_23` TTL 43200→172800（仅粗粒度兜底零下单）；③ 导出器 artifact 指标补 `severity` 标签，修复规则 `{{ $labels.severity }}` 恒空、卡片"级别 -"、P2 误路由到 P1 通道；新增 3 项单测，TD §10.5 同步 | 代码+配置+测试+文档 |
| v2.25 | 2026-11-25 | `CrossValidationDegraded` 误报治理：① 23 `CrossValidationGate` 在 SPRT `accept_h1` 时改标 `degraded_mode=no_reliable_link`（A 链路仍可用、仅判不可信），`both_none` 仅保留给两路均无输出；② 导出器 `semantic_metrics` 增加决策时效窗口（`signals.state_window_seconds`，默认 43200s），超窗旧决策不再产生 `cv_degraded_mode`/`cv_present_ratio`，避免告警永不恢复；③ 同步 TD §10.5/§13.9.5 与告警 summary，新增 2 项单测 | 代码+配置+规则+测试+文档 |
| v2.24 | 2026-11-22 | `ArtifactStale` 口径纠偏：`execution_decisions.jsonl` 仅在真实 submit 时追加、WAIT 不写（近 24h 实测最长自然间隔 6.6h），原 1800s/P1 在 43 `war_state=FREEZE` 期间必然误报。新增 `entry23_heartbeat`（`23/runtime/event_driven_state.json`，900s/P1）作为存活心跳；决策审计改为 43200s/P2 仅兜底决策沉默。TD §10.5 同步 | 配置+文档 |
| v2.23 | 2026-11-20 | `GhostPositionCleaned` 归因纠偏：复盘发现 24h 内 12 次 `ghost_exchange_flat` 全部是 50-nn 实盘 1.5%/3% 交易所 OCO 成交后的正常回填（回填发生在成交同一分钟），24h 滚动计数恒 >0 导致 P2 自 11-17 长期 firing。改为 23 `exit_loop._resolve_ghost_exit()` 回填时归因：真实成交价 → `exchange_sltp`（新增 `ledger_exchange_sltp_24h`，仅观察不告警）；无成交/脏价 → `ghost_exchange_flat`（保留 P2）。规则表达式不变；另修复 close/reduce 成交索引延迟导致落账 px=0（2 次重试 + camelCase 字段兜底） | 代码+规则+测试+文档 |
| v2.22 | 2026-11-18 | 补齐最后两项任务打点：① `bus_42` 在 `48/bus/run_shadow_probe.py` 每轮成功后 `push_job.sh bus_42 success`（FAIL-OPEN）；② 核查 `shadow-driver.timer` active+enabled（每 10min、exit 0，未退役），补 `ExecStopPost` → `shadow_50`。至此 5 个 job 全部有 series | 代码+配置+文档 |
| v2.21 | 2026-11-18 | 补任务打点：Pushgateway 原有 0 条 `dreambuddy_job_*` series，导致 6 条 JobFailed/*Stale 规则静默失效。新增 40 日更 cron 包装器（退出码→`push_job.sh 40_daily`），并为 publish_43/live_50 增加 `ExecStopPost` 打点（`deploy/systemd/install-job-push.sh`）；bus_42/shadow_50 待定（常驻/疑似退役）；TD §13.9.6 记录维护约定 | 配置+脚本+文档 |
| v2.20 | 2026-11-18 | 告警降噪四项：① `GhostPositionCleaned` 改用 `ledger_ghost_exchange_flat_24h`，新增 `GhostStaleBulkCleanup`（stale>20/24h），导出器拆分 ghost 指标；② `CrossValidationDegraded` 只对 `both_none` 触发（attention_only/granger_only 属设计内降级）；③ Watchdog(meta) 路由到 blackhole 不进飞书；④ TD §13.9.5 记录 ArtifactStale 根因（运行时产物被 git 跟踪，pull 覆盖新鲜产物，部署后需重跑 40 流水线）；新增 ghost 指标单测 | 代码+规则+文档 |
| v2.19 | 2026-11-18 | 修正链路完成率口径：N11 `blocked`（如 `duplicate_position`）属策略主动终止，从 `chain_completion_ratio` / `chain_missing_stage_total` 分母中剔除，新增 `chain_blocked_total{gate}`；避免正常拦截长期压低完成率触发 `ChainBroken`/`ChainCompletionLow` 误报；新增 1 项单测 | 代码+测试 |
| v2.18 | 2026-11-18 | 新增模型用量告警：`scripts/model_usage_check.py` 每小时抓取 DeepSeek 余额，推算 24h/7d 消耗与可用天数，覆盖余额下限、可用天数、消耗突增、凭证失效 4 类告警（receiver 推送 + 6h 去重）；新增 `config/model_usage.json`、云端 hourly systemd timer、10 项单测 | 代码+配置+运维 |
| v2.17 | 2026-11-18 | 新增信号口径校准监控：`signal_calibration_metrics()` 导出 11 个指标（dstar 口径/翻转、ri 中性、ESS 方向空、放量门槛、reflection 样本）；新增 5 条告警 `DstarCalibratedModeOff/DstarCalibratedAllWait/EssDirectionEmpty/RippleVolThresholdOutOfRange/ReflectionSampleStarved`；daily_insight 新增 `23_REFLECTION_STARVED` 并更新 `23_DSTAR_WAIT` 处置口径；TD 新增 §13.9.4 | 代码+规则+文档 |
| v2.15 | 2026-11-18 | 新增每日 09:00 监控日报：23 核心链聚合 + 规则异常识别 + DeepSeek 归因 + 飞书推送；40 神经链预留（`enabled_chains` 未启用）；新增 launchd/systemd 定时与单测 | 代码+配置+运维 |
| v2.14 | 2026-11-18 | ri/tier 恒值诊断：N9 事件与指标表补充 `ri/tier/ess_top_direction/vol_ratio/ripple_is_source`；§13.9.1 N9 行增加「ri 恒定」首查路径 | 代码+文档 |
| v2.13 | 2026-11-18 | 接入 N3 高阶因子调制到实盘路径（`EngineRouter.run_path_discovery` 内、路径发现前），新增开关 `EVOLUTION_N3_HIGH_ORDER` 默认 off：关闭时只做影子对比（`n3_compare.before/after`、`direction_flip`），不改决策 | 代码+文档 |
| v2.12 | 2026-11-18 | 可观测补齐：N0/N2/N3/N4/N9/N15/E2/E3 落地 `chain_events`；`trace_id` 由 N0 生成并在推理段贯穿（G1 关闭）；22 SLTP 补挂审计新增 `source=22-sltp_reconcile`；同步 §13.2 节点表「现状可观测/关联键」 | 代码+文档 |
| v2.11 | 2026-11-18 | 新增 TD §13.9 监控点↔链路节点锚定索引（告警→N/E 节点→指标→证据→命令，含四步定位法）；修正 §13.2/§13.3 平仓链旧口径 | 文档 |
| v2.10 | 2026-11-18 | 11 交易循环退役后的监控对齐（TD §13.8）：停用 universe 三条误报规则；导出器新增 `entry23_active/exit23_active/ledger_*/sltp_*`；新增 6 条执行链告警；watchdog 增 exit23 日志与账本检查；本地 `monitor_config.json` 的 yijing 置 disabled | 代码+配置+文档 |
| v2.9 | 2026-11-17 | 修复 blackbox 探针误报 TargetDown：探针改 `network_mode: host` + targets 统一 `127.0.0.1`（云端业务端口只绑回环，`host.docker.internal` 打不通）；新增 `deploy/DEPLOY-CHECKLIST.md` 部署检查清单 | 配置+运维 |
| v2.8 | 2026-11-17 | 落地 §13 链路监控：chain_events 事件流；修复 G1–G7；导出器新增 chain_*/exit_* 指标；新增 ChainBroken/ChainCompletionLow/ChainWaitBroken/ExitSizeUnknown/ExitCloseFailed 规则 | 代码+配置 |
| v2.7 | 2026-11-17 | 技术设计新增第 13 章：A/B 分类监控原则；23 交易链路 N0–N15 逐节点监控方案；`chain_event.v1` 链路汇总与复盘；确认 6 个链路缺口（无 trace_id、pc/cv 旁路、regime/ri 退化、审计仅 submit、双 decision_id） | 文档 |
| v2.6 | 2026-11-17 | 23 契约补齐 v1.2（payload 12 字段 + 顶层执行扩展）；审计携带完整 signal；导出器按 payload 校验并消除无信号误报 | 代码+契约 |
| v2.5 | 2026-11-17 | 上线业务指标导出器(:9101)与 Prometheus/Alertmanager 栈；23 信号/发件箱/产物/单元指标已入库，端到端联调 am=200 | 代码+运维 |
| v2.4 | 2026-11-17 | 告警通道接通：复用 hermes-gateway 飞书应用凭证，部署 receiver(:9098) + watchdog(5min)；联调消息已送达 Trading-Desk | 代码+运维 |
| v2.3 | 2026-11-17 | 23 切实盘（移除 `--dry-run`、开关置 on）；监控进入 14 天 alert_only（至 2026-12-01）；记录切换前权益/持仓预检 | 配置+运维 |
| v2.2 | 2026-11-17 | 一期收敛为 23 推理信号链（TD 第 12 章）：23 模块全景、v1.1 契约差异、8 步生命周期、10 条信号告警、落地审计；`monitoring.yaml` 增 signals 段、`domains.yaml` 分期调整 | 文档+配置 |
| v2.1 | 2026-11-17 | 新增 3+3 全景监控架构（TD 第 11 章）与 `config/domains.yaml` 域注册表：三层×三链矩阵、四期覆盖、M0–M5 成熟度、一格一 owner | 文档+配置 |
| v2.0 | 2026-11-17 | 新增云端全链路监控目标架构（TD 第 10 章）、调研 v0.2、API v1.1 草案；建立代码骨架 `exporter/ receiver/ deploy/ scripts/`；新增 12 条告警规则与 Pushgateway 接入模板 | 文档+骨架 |
| v1.0 (文档补建) | 2026-09-30 | 补建 `docs/API_SPEC.md`、`docs/CHANGELOG.md`，完善模块文档体系 | 文档 |
| v1.0 | 2026-08-02 | 补建 `docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`，对齐 DOC_STANDARD L3 模块文档建设规范 | 文档 |
| — | 2026-07-27 | 模块运行中，产生首个故障事件记录 `INC-20260727111511.json` | 运行数据 |

---

## 详细变更

### v2.18 — 2026-11-18

**动机**：模型用量（余额/消耗）此前无告警，余额耗尽或凭证失效会让 23 推理链、日报归因等 LLM 调用静默断供；2026-11-18 云端就出现过 `1-ARCHITECTURE/dreamos/.env` 的 DeepSeek key 失效（401）而无人感知。

- 新增 `scripts/model_usage_check.py`：按 `config/model_usage.json` 遍历启用的供应商，抓取余额并落快照
- DeepSeek 走 `/user/balance`（权威消耗口径，无需在每个调用点埋点）；key 按 环境变量 → `env_files` 顺序回退，401 自动跳过失效 key
- 用量推算：24h 消耗、按自然日末余额的 7 日均消耗、可用天数、24h 折算消耗 vs 基线（充值日不计消耗）
- 4 类告警：`*_unavailable`(P1)、`*_balance_low`(P1)、`*_balance_warn`/`*_days_remaining`/`*_burn_spike`(P2)
- 推送复用 receiver，失败直连飞书；同一告警 6h 去重，状态存 `~/.cache/dreambuddy-model-usage.json`
- 云端 `dreambuddy-model-usage.timer` 每小时执行；快照保留 14 天
- 单测 `tests/test_model_usage_check.py`（10 项）：余额解析、凭证回退、充值不计消耗、阈值判定、快照读写

### v2.15 — 2026-11-18

**动机**：23 链存在 `ri` 长期集中于 0.5、`d_star` 恒 WAIT、N2 全量降级等隐性退化，人工巡检难以及时发现；需要每日自动汇总并借助大模型做归因。

- 新增 `scripts/daily_insight.py`：聚合 `chain_events-*.jsonl`（N1–N14/E*）、`execution_decisions.jsonl`、发件箱、22 账本与 SL/TP 审计
- 规则引擎：`ri` 恒定/高度集中、ESS 方向为空、tier 恒 probe、d_star WAIT、N2 降级、信号静默、CV 降级、chain_id 不贯通、发件箱积压、账本/补挂异常
- 大模型：DeepSeek JSON 模式输出健康分、归因、建议；失败自动退化为规则报告（先生成报告，不阻塞）
- 报告落盘 `logs/daily-insight/`；推送优先 receiver，失败直连飞书 management 群
- 定时：生产在云端 systemd timer 09:00 Asia/Shanghai；本地仅手动验证，不装 launchd
- 40 周期神经网络链路预留：`config/daily_insight.json` 的 `enabled_chains` 仅含 `23`，采集/TTL 接口保留
- 单测：`tests/test_daily_insight.py`（8 项）

**实测**：对最近 24h 数据运行，识别 7 项 P1（ri 0.5 占 82.9%、ESS 空方向 85.7%、d_star WAIT 100%、N2 降级 100% 等）并成功推送飞书。

### v2.11 — 2026-11-18

**动机**：节点编号由 23 SSoT 定义、指标/告警由 15 定义，此前只能人工对照；11 退役与 22 承接公共执行后，排查易对错节点。

- TD 新增 §13.9：N0–N15 / E0–E6 / 进程 / SLTP 的「指标 → 告警 → 证据 → 首查命令」一页索引，加四步定位法
- 23 SSoT §6.3 增加指向 §13.9 的反向链接，并声明不复制映射（单一维护点）
- 修正 §13.2 平仓表 E0/E4 代码入口、§13.3 E0/E6 指标名与告警名（`LedgerDriftFrequent`、`ledger_last_write_age_seconds` 等）

### v2.10 — 2026-11-18

**背景**：11 `polling_trader` 停用，23 `entry23/exit23` 成为唯一交易 owner；22 承接 SL/TP 补挂、账本对账、幽灵仓清零。

**停用误报规则**
- `EvolutionScanStalled` / `EvolutionScanFailed` / `EvolutionPoolShrunk`：数据源 `runtime/universe_snapshot.json` 由 11 写入，23 无写入点，11 退役后永久误报
- `monitoring.yaml` 新增 `universe.enabled=false`，导出器 `universe_metrics()` 按开关短路

**新增执行链指标（`execution_metrics()`）**
- `entry23_active` / `exit23_active`（systemd）
- `ledger_positions` / `ledger_last_write_age_seconds` / `ledger_reconcile_updated_1h` / `ledger_ghost_closed_24h`（22 `position_ledger.db`）
- `sltp_reconcile_age_seconds` / `sltp_reconcile_patched_1h` / `sltp_reconcile_failed_1h`（22 `sltp_reconcile.jsonl`）

**新增告警（`execution` group）**
- `Entry23Down`(P1)、`Exit23Down`(P0)、`LedgerDriftFrequent`(P2)、`GhostPositionCleaned`(P2)、`SltpReconcileFailed`(P1)、`SltpReconcileStale`(P2)

**watchdog**
- 新增 `exit23.log` 10min 新鲜度、`position_ledger.db` 24h 写入检查

**本地 v1**
- `monitor_config.json` 的 `yijing` 置 `enabled=false`（heartbeat 随交易循环停止，避免永久 CRITICAL）；`yijing-data-server:8765` 由 Prometheus blackbox 覆盖

### v2.8 — 2026-11-17

**链路事件（23）**
- 新增 `execution/chain_events.py`：`emit_stage()` / `new_trace_id()`，写入 `runtime/chain_events-YYYYMMDD.jsonl`，按 UTC 日轮转，全异常 FAIL-OPEN
- 开仓：N1 trace、N5 主矛盾、N6 交叉验证、N7 统计验证、N8 决策（含主动 WAIT 归因）、N10 信号构造、N11 闸门、N12 最终信号、N13 发件箱、N14 网关
- 平仓：E0 持仓同步、E1 离场决策、E4 平仓信号（含 SIZE_UNKNOWN）、E5 执行、E6 落账

**缺口修复**
- G1：推理段 trace_id 贯穿到 `payload.trace_id`
- G2：pc/cv 优先取本次 `path_info`，未通过验证时也保留；私有属性仅兜底
- G3/G4：`regime/ri/l4_v` 透传；入口 `ri` 以 confidence 兜底
- G5：WAIT/拦截/失败均落事件，不再只有 submit 审计
- G6：`payload.chain_id` + `upstream_decision_id` 串联双 decision_id
- G7：平仓链补 `d_star/regime`，平仓失败与数量未知可告警

**监控**
- `business_metrics_exporter.py` 新增 `chain_metrics()`：`chain_stage_total`、`chain_completion_ratio`、`chain_missing_stage_total`、`chain_wait_total`、`wait_vs_broken_ratio`、`chain_broken_total`、`exit_size_unknown_total`、`exit_close_failed_total`
- 规则新增 `ChainBroken`、`ChainCompletionLow`、`ChainWaitBroken`、`ExitSizeUnknown`(P0)、`ExitCloseFailed`(P0)

### v2.7 — 2026-11-17

**分类监控原则（TD §13.1）**
- A 类交易链路：沿信号传递逐节点监控 + 链路汇总/复盘（价值最高），每节点四态 `enter/pass/blocked/failed/skip`
- B 类其他模块：结果导向，存活 + 产物新鲜度 + 核心计数，允许粗糙、允许抽样，不参与 P0 路由

**23 链路逐节点方案（TD §13.2–13.3）**
- N0 数据就绪 → N15 回报反馈，共 16 节点：代码入口、输入输出字段、关联键、现状观测、静默失败模式
- 平仓并行支链 E0–E6（持仓同步/离场决策/RL 覆盖/信号构造/提交/清理），共用 N12–N15
- 每节点指标、告警规则、级别、SLO；统一 `samples_recent>0` 与 `for:` 降噪约束
- 确认 6 个链路缺口：G1 推理段无 trace_id、G2 pc/cv 私有属性旁路、G3 regime 未透传、G4 二次构造 ri/l4_v 退化、G5 审计仅 submit、G6 双 decision_id；平仓另有 `sz=0`/`d_star/regime` 为空缺口

**链路汇总与复盘（TD §13.4）**
- `chain_event.v1` 事件模型与 `trace_id → chain_id → upstream_decision_id → decision_id → order_id` 串联规则
- `chain_completion_ratio`、`chain_missing_stage_total`、`chain_latency_seconds`、`wait_vs_broken_ratio` 等链路级指标
- 落盘、留存、`chain_summary` 查询与复盘视图定义

### v2.6 — 2026-11-17

**契约补齐（选项 A）**
- 新增 `final_decision_signal.v1.2.json`：登记顶层执行扩展（decision_id/action/pos_side/sz/sl_px/tp_px/reason/tier），并扩展 action 枚举（open/close/reduce/stop_loss/take_profit）
- 23 生产器输出 `ts/horizon/risk_exposure_hint/mode` 与 payload 12 字段；缺省值显式为 unknown/0/{}，不伪造结论
- 入口透传 `d_star/ri/l4_v/regime/primary_contradiction/...`，出口补齐同构字段
- 审计记录新增完整 `signal`；22 `from_dict` 支持 payload 回退

**监控修正**
- 导出器改为同时校验 payload 12 字段；无样本时不再输出 `ratio=0`
- `SignalSchemaViolation` 增加 `samples_recent > 0` 门槛

### v2.5 — 2026-11-17

**业务指标导出器**
- `exporter/business_metrics_exporter.py`（127.0.0.1:9101，只读）：信号产出/契约一致率/置信度、发件箱状态、产物新鲜度、entry23 模式、3+3 单元成熟度
- 已上线 systemd `dreambuddy-metrics-exporter`；Prometheus `dreambuddy-business` target 为 up

**监控栈**
- 启动 Prometheus 2.55 / Alertmanager 0.28 / node_exporter / blackbox / pushgateway（Grafana 暂缓，节省资源）
- Prometheus/Alertmanager 改 host 网络，仅监听 127.0.0.1；31 条规则加载成功
- Alertmanager 关闭 gossip（9094 冲突），P0→Risk、P1/P2→Desk、P3→Management
- 端到端：POST `/api/v2/alerts` 返回 200，E2EProbe 进入 active 并经 receiver 转发

### v2.4 — 2026-11-17

**告警通道**
- 复用 `hermes-gateway` 使用的飞书应用凭证（`~/.hermes/.env`），写入 `/etc/dreambuddy-monitoring/monitoring.env`（600 root）
- 新增 `receiver/feishu_receiver.py`：`/alert`（Alertmanager v4）、`/notify`（watchdog）、`/healthz`；按 P0/P1/P2/P3 路由到 RiskControl/Desk/Management，30min 去重
- 新增 `scripts/watchdog.py` + 5min timer：entry23/exit23 存活、entry23 日志 10min 新鲜、审计文件 24h、磁盘 90%
- 联调：`POST /notify` 返回 `{"sent": true}`，消息已送达 Trading-Desk
- 全部为 alert_only，无任何自动冻结或阻断

### v2.3 — 2026-11-17

**23 切实盘**
- `23/deploy/dreambuddy-entry23.service`：移除 `--dry-run`，`EVOLUTION_ENTRY23_ENABLED=off → on`
- 预检：权益 2118.10 USDT / 可用 919.05 / 冻结 1200.19 / 永续持仓 0；凭据库 `simulated=false,dry_run=false`
- 切换后 `expected_mode: live`；`DryRunMismatch` 语义由"实盘未开"转为"实盘被意外关闭"

**监控策略**
- 2026-11-17 至 2026-12-01 为 `alert_only`：只告警，不自动冻结/阻断
- 到期复核误报率与信号质量后，再启用 §10.7 D2 的自动动作

### v2.2 — 2026-11-17

**一期范围**
- 一期由「交易列三层」收敛为「23 推理信号链」；40 主神经网络闭环顺延二期，只保留 L0 存活探针
- `config/domains.yaml` 分期改为：一期 23 → 二期 40 → 三期训练链 → 四期产品链 → 五期横切

**23 信号监控（TD 第 12 章）**
- 模块全景、v1.1 契约字段与实测差异（23 缺 `horizon/risk_exposure_hint/mode` 及 payload 12 字段）
- 8 步生命周期：数据→生成→契约→审计→发件箱→网关→风控成交→回报反馈
- 10 条信号告警：Schema/Silence/Expired/DryRunMismatch/OutboxStuck/RejectSpike/RiskGateEmpty/Duplicate/FillJoin/ConfidenceDegenerate
- 落地审计：22 无 JSON Schema 校验、云端 entry23 为 dry-run、23 审计仅 submit 阶段、outbox 为 SQLite

**配置**
- `config/monitoring.yaml` 新增 `signals` 段；`execution_decisions_23` TTL 24h→30min
- `docs/API_SPEC.md` 增加 13 个信号级指标

### v2.1 — 2026-11-17

**架构**
- `docs/TECHNICAL_DESIGN.md` 第 11 章：3+3 全景监控架构（L0/L1/L2 × 交易/训练/产品），四期覆盖，一期只要求交易列 ≥M3、其余 ≥M1
- 管理机制：`config/domains.yaml` 单点注册（owner/phase/maturity/probes/slo/runbook）、统一 `chain/layer/cell/module` 标签、3×3 热力图、月度覆盖评审

**配置**
- 新增 `config/domains.yaml`：9 格 + 横切治理，含状态机 `draft→active→paused→retired` 与命名约定

### v2.0 — 2026-11-17

**架构与调研**
- `docs/TECHNICAL_DESIGN.md` 升级 v2.0：新增第 10 章「云端全链路监控目标架构」，含云端实测基线、五层探针、TTL 矩阵、P0–P3 治理、D1–D6 决策、实施验收；第 1–9 章降级为本地 v1.0 现状
- 新增 `docs/RESEARCH-全链路监控体系调研-v0.2.md`：40 链 12 节点、23 链 9 节点、SRE/金融监控框架、GitHub 选型、云端证据

**代码骨架（未实现）**
- `exporter/`：业务只读指标导出器（probes/tests 占位）
- `receiver/`：Alertmanager→飞书 webhook 接收器（占位）
- `config/monitoring.yaml`：TTL、任务节奏、链路阈值、域名义上限、告警治理参数
- `deploy/`：Compose、Prometheus、12 条规则、Alertmanager、Grafana provisioning、blackbox、systemd unit
- `scripts/push_job.sh`：cron/systemd 任务末尾推送运行/成功/耗时/记录数

**文档**
- `docs/API_SPEC.md` v1.1：新增 §6 监控接口草案（`/metrics`、`/alert`、`/healthz`）

### v1.0 (文档补建) — 2026-09-30

**文档建设**
- 新建 `docs/API_SPEC.md`：覆盖核心层（UnifiedMonitor/MonitorAdapter/MonitorResult/MonitorStatus）、适配器层（5 个 MonitorAdapter 子类）、告警层（send_alert + 13 个 notify_* 业务函数）、持仓同步层（PositionSyncService/PositionSyncAdapter + 3 个 SyncAdapter 子类）、调度层（run_monitor/run_position_sync/main/shadow_resistance_gene_mvp）、记忆层（OpsMemoryInterface 14 个方法）的全部公开接口签名、参数表、示例、错误处理
- 新建 `docs/CHANGELOG.md`：本文件

### v1.0 — 2026-08-02

**文档建设**
- 新建 `docs/ENGINEERING_INDEX.md`：模块定位、目录地图、6 层文件清单（调度/核心/适配器/告警/持仓同步/记忆）、核心流程索引、配置参数索引、测试体系、技术债务、快速导航
- 新建 `docs/TECHNICAL_DESIGN.md`：概述、6 层架构、5 个核心算法（告警路由/健康检查优先级短路/BCRM2.0 双维度自检/双层调度/外部平仓二次确认）、数据流、接口设计、状态管理、配置管理、错误处理、扩展性设计

---

## 代码能力清单（按模块）

> 以下为当前代码已实现的能力清单，供变更追溯参考。

### 核心层（monitor_core.py）
- `MonitorStatus` 四级状态枚举（healthy/warning/critical/unknown）
- `MonitorResult` 结果对象（to_dict / is_healthy）
- `MonitorAdapter` 适配器基类（check_health + 4 个可选维度方法）
- `UnifiedMonitor` 统一管理器（三级配置回退 / 5 适配器实例化 / monitor_all / get_all_metrics / send_alerts）

### 适配器层（adapters/__init__.py）
- `YijingAdapter`：心跳 + 风控 + 性能 + BCRM2.0 双维度自检（日志扫描 6 关键字 + 模型缓存 48h 新鲜度）
- `V15Adapter`：心跳超时 + 连续亏损 ≥5 警告
- `ScreenAdapter`：心跳超时 + 三屏趋势指标
- `AgentAAdapter` / `AgentBAdapter`：日志时间戳心跳 + 记忆指标

### 告警层（feishu_alert.py）
- `send_alert` 通用入口 + 飞书 schema 2.0 卡片构建
- 13 个业务告警函数（heartbeat/process_error/trading_halted/consecutive_losses/model_error/position_close/system_error/performance_degrade/status_summary/trade_execution/system_start/system_stop）
- 四级路由（critical/error→risk, warning→trading, info→management）
- 凭证缺失降级（FEISHU_CREDENTIALS_VALID）

### 持仓同步层（position_sync.py）
- `PositionSyncService`：OKX 客户端延迟加载、外部平仓二次确认（窗口 + 次数）、API 故障保护、自动备份
- 3 个同步适配器（V15/Yijing/Screen）
- dry_run 只读模式

### 调度层（scheduler.py）
- 双层调度（60min 完整监控 + 5min 持仓同步）
- dreambuddy-v2 MVP L1×L2 影子调度（UTC 00:05，FO-7 熔断 ≥5 次失败）

### 记忆层（memory/app_memory_interface.py）
- `OpsMemoryInterface`（AM-OPS-001）：incident/playbook 增删改查、蒸馏候选、健康检查、相似案例检索

---

**文档版本**: v2.6
**最后更新**: 2026-11-17
