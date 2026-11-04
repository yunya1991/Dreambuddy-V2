# INVENTORY:事件源盘点清单 v1.0

> **版本**: v1.0 ｜ **日期**: 2026-11-03 ｜ **状态**: ✅ 定稿——T1/T2/T3/T4/T6 全部实测完成;T5(A5 回放集)采样方案已备(§七),待立项
> **定位**: [SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2](SPEC-EVENT-DRIVEN-L1-GATEWAY.md) §3.1 任务 0 前置交付物
> **用途**: ①事件类意图从本清单导出(SPEC §3.1 任务 3) ②A5 回放集构造依据(n≥200,覆盖全部已盘点类型)
> **口径**: 交易热路径(polling_trader 开仓链路)**只盘点不接入**(SPEC §3.2 非目标 / DESIGN H5)

---

## 一、盘点维度定义

| 列 | 含义 | 取值说明 |
|---|---|---|
| 源 ID | 全局唯一标识 | kebab-case |
| 类别 | 定时器 / 行情阈值 / 文件落盘 / webhook / 消息渠道 | SPEC P0 适配器先支持前三类 |
| 载体 | launchd(本地) / systemd timer(远端) / 进程内循环 / 外部推送 | |
| 速率 | 触发频率 | 实测值;未知标 `待核` |
| 现处理方 | 事件当前流向(脚本/服务) | |
| 热路径 | 是否触及交易开仓链路 | ✅=禁接,只盘点 |
| 事件化价值 | 接入网关后的预期收益 | 高/中/低,初判待复核 |

---

## 二、本地事件源(launchd,已实测 2026-11-03)

本地 `~/Library/LaunchAgents/` 实测 27 个 `com.dreambuddy.*` 任务,按语义归类:

### 2.1 调度/采集类(候选:定时器事件源)

| 源 ID | plist | 速率(2026-11-03 实测) | 现处理方 | 热路径 | 价值 |
|---|---|---|---|---|---|
| `local.dc-scheduler` | com.dreambuddy.dc-scheduler.plist | **常驻**(KeepAlive+RunAtLoad) | 18 采集调度(本地副本) | ❌ | 中 |
| `local.datacenter` | com.dreambuddy.datacenter.plist | **常驻**(KeepAlive+RunAtLoad) | 数据中心 | ❌ | 中 |
| `local.dbsync` | com.dreambuddy.dbsync.plist | **600s** | 本地→云端上行同步 | ❌ | 低(单向管道,事件化收益小) |
| `local.etl-worker` | com.dreambuddy.etl-worker.plist | **常驻**(KeepAlive+RunAtLoad) | 7-产物中台 prisma ETL | ❌ | 中 |

### 2.2 监控/信号类(候选:行情阈值事件源,**优先**)

| 源 ID | plist | 速率(实测) | 现处理方 | 热路径 | 价值 |
|---|---|---|---|---|---|
| `local.signal-scanner` | com.dreambuddy.signal_scanner.plist | **常驻**(KeepAlive) | 信号扫描 | ⚠️ 近热路径 | **高**(阈值命中天然是事件) |
| `local.ab-monitor` | com.dreambuddy.ab_monitor.plist | **14400s(4h)** | ab-trading 监控 | ⚠️ | 高 |
| `local.yijing-monitor` | com.dreambuddy.yijing_monitor.plist | **14400s(4h)** | 易经监控 | ⚠️ | 中 |
| `local.screen-monitor` | com.dreambuddy.screen_monitor.plist | **14400s(4h)** | 屏幕监控 | ❌ | 中 |
| `local.trailing-stop` | com.dreambuddy.trailing-stop-runner.plist | **常驻**(KeepAlive:Crashed/!SuccessfulExit) | 移动止损 | ✅ **禁接** | —(只盘点) |

### 2.3 编排/训练类(候选:任务完成事件)

| 源 ID | plist | 速率(实测) | 现处理方 | 热路径 | 价值 |
|---|---|---|---|---|---|
| `local.v15-light-poll` | com.dreambuddy.v15_light_poll.plist | **300s(5min)** | V15 轻量轮询 | ⚠️ | 中 |
| `local.v15-orchestrator` | com.dreambuddy.v15_orchestrator.plist | **900s(15min)** | V15 编排 | ❌ | 中 |
| `local.ab-orchestrator` | com.dreambuddy.ab_orchestrator.plist | **14400s(4h)** | ab-trading 编排 | ❌ | 中 |
| `local.continual-training` | com.dreambuddy.continual-training.plist | **1800s(30min)** | 持续训练 | ❌ | **高**(训练完成=天然事件) |
| `local.evolution-scheduler` | com.dreambuddy.evolution_scheduler.plist | **日历(整点 Hour)** | 进化调度 | ❌ | 中 |
| `local.agent-b-strategy` | com.dreambuddy.agent-b-strategy-update.plist | **日历(整点 Hour)** | 策略更新 | ❌ | 中 |
| `local.trend-executor` | com.dreambuddy.trend_executor.plist | **60s** | 趋势执行 | ⚠️ | 中 |

### 2.4 认知/系统类

| 源 ID | plist | 速率(实测) | 现处理方 | 热路径 | 价值 |
|---|---|---|---|---|---|
| `local.dreamos` | com.dreambuddy.dreamos.plist | **常驻**(KeepAlive) | DreamOS 调度 | ❌ | 中 |
| `local.cognitive-ttl` | com.dreambuddy.cognitive-ttl.plist | **日历(整点 Hour)** | 认知 TTL 清理 | ❌ | 低 |
| `local.memory-cleanup` | com.dreambuddy.memory_cleanup.plist | **日历(整点 Hour)** | 记忆清理 | ❌ | 低 |
| `local.yijing-data-server` | com.dreambuddy.yijing_data_server.plist | **常驻**(KeepAlive) | 易经数据服务 | ❌ | 低(服务型非事件型) |
| `local.yijing-live-300s` | com.dreambuddy.yijing_live_300s.plist | **常驻**(KeepAlive:!SuccessfulExit/NetworkState) | 易经实时 | ⚠️ | 中 |
| `local.yijing-trading` | com.dreambuddy.yijing_trading.plist | **常驻**(KeepAlive:!SuccessfulExit) | 易经交易 | ✅ **禁接** | —(只盘点) |
| `local.ranking-trigger` | com.dreambuddy.ranking-trigger.plist | **14400s(4h,curl)** | 排名触发 | ❌ | 中 |
| `local.screen-orchestrator` | com.dreambuddy.screen_orchestrator.plist | **600s** | 屏幕编排 | ❌ | 低 |
| `local.test-min` | com.dreambuddy.test-min.plist | **常驻**(KeepAlive) | 测试用 | ❌ | 低 |
| `local.v15-trader(停用)` | com.dreambuddy.v15_trader.plist.disabled | — | 已禁用 | — | — |
| `local.polling-trader` | dreambuddy.yijing.polling-trader.plist | **常驻**(KeepAlive:!SuccessfulExit/AfterInitialDemand/NetworkState) | **只盘点不接入** | ✅ **禁接** | —(只盘点) |

> **实测摘要(T1 完成)**:27 项中 **常驻型 11 项**(KeepAlive)、间隔型 8 项(60s~4h)、日历型 4 项(整点)、停用 1 项、余 3 项。事件化收益最高的是常驻循环类(信号/监控)——它们内部已有"每轮检查"逻辑,命中即事件,接入成本最低。

---

## 三、远端事件源(systemd,**2026-11-03 ssh 实测复核完成**)

> T2 解锁依据认知经验 VM-1793717552554:扫码横幅是噪音,命令照常执行(串行)。实测 **18 运行中服务 + 29 个 dreambuddy 相关 timer**。与 10-14 记忆快照差异:新增一批 `dreambuddy-*` 事件管道 timer;`hermes-gateway` 已在运行(快照称未部署);`continual-training.timer` **5 天未调度(疑似停用)**。

### 3.0 重大发现:云端已有事件管道雏形(事件化价值重估,T6)

| timer | 速率(实测) | 说明 |
|---|---|---|
| `dreambuddy-atomic-events.timer` | **10min** | 39 原子事件增量采集,产出 → `39-金融语义蒸馏系统/atomic_events.jsonl`(**现成事件流载体**) |
| `dreambuddy-aggregate-events.timer` | 10min | 聚合事件 |
| `dreambuddy-semantic-events.timer` | 10min | 语义事件 |
| `dreambuddy-event-lines.timer` | 30min | 事件线 |
| `dreambuddy-healthcheck.timer` | **5min** | G6 健康检查,**journal 输出结构化 JSON**(status/fails/checks 数组,11 项检查) |

**含义**:事件网关 shadow 期的"事件判定信号"无需自建——`atomic_events.jsonl`(文件落盘,天然适配 P0 首选模拟源)+ healthcheck JSON 行即为现成事件源。

### 3.1 timer(实测,按速率排序;* = 高价值)

| 源 ID | timer | 实测速率 | 热路径 | 价值(T6 校准) |
|---|---|---|---|---|
| `remote.v15-poll-light` | v15-poll-light.timer | 5min | ⚠️ | 中 |
| `remote.healthcheck`* | dreambuddy-healthcheck.timer | **5min,JSON 输出** | ❌ | **高**(异常=告警事件,信号已结构化) |
| `remote.shadow-driver` | dreambuddy-shadow-driver.timer | 10min | ❌ | 中 |
| `remote.atomic-events`* | dreambuddy-atomic-events.timer | 10min | ❌ | **高**(现成事件流) |
| `remote.aggregate-events` | dreambuddy-aggregate-events.timer | 10min | ❌ | 中 |
| `remote.semantic-events` | dreambuddy-semantic-events.timer | 10min | ❌ | 中 |
| `remote.snapshot` | dreambuddy-snapshot.timer | 10min | ❌ | 中 |
| `remote.v15-orchestrator` | v15-orchestrator.timer | 15min | ❌ | 中 |
| `remote.windowed-collect` | dreambuddy-windowed-collect.timer | ~30min(23:07→00:07) | ❌ | 中 |
| `remote.event-lines` | dreambuddy-event-lines.timer | 30min | ❌ | 中 |
| `remote.trade-cases` | dreambuddy-trade-cases.timer | 30min | ⚠️ | 中 |
| `remote.datacenter-backfill`* | datacenter-backfill.timer | 每小时(:15) | ❌ | **高**(回填完成/失败=事件) |
| `remote.index-reconcile` | index-reconcile.timer | 1h | ❌ | 中 |
| `remote.job-runs-audit`* | job-runs-audit.timer | 1h | ❌ | **高**(job 审计异常=事件) |
| `remote.docs-sync` | docs-sync.timer | ~1h | ❌ | 低 |
| `remote.yijing-monitor` | yijing-monitor.timer | 4h | ⚠️ | 中 |
| `remote.ranking-trigger` | ranking-trigger.timer | 4h | ❌ | 中 |
| `remote.case-stats` | dreambuddy-case-stats.timer | 6h | ❌ | 中 |
| `remote.newsflash-weights` | dreambuddy-newsflash-weights.timer | 6h | ❌ | 中 |
| `remote.contradiction` | dreambuddy-contradiction.timer | 6h | ❌ | 中 |
| `remote.dal-integrity`* | dal-integrity.timer | 6h | ❌ | **高**(完整性异常=告警事件) |
| `remote.l3-synthesis` | dreambuddy-l3-synthesis.timer | 24h(01:05) | ❌ | 中 |
| `remote.memory-cleanup` | memory-cleanup.timer | 24h(02:05) | ❌ | 低 |
| `remote.dal-backup` | dal-backup.timer | 24h(04:00) | ❌ | 中 |
| `remote.evaluator-restart` | dreamos-evaluator-daily-restart.timer | 24h(04:00) | ❌ | 低 |
| `remote.auto-archive` | datacenter-auto-archive.timer | 24h(04:30) | ❌ | 低 |
| `remote.dal-rotate` | dal-rotate.timer | 24h(05:00) | ❌ | 低 |
| `remote.complex-semantics` | dreambuddy-complex-semantics.timer | 24h(06:00) | ❌ | 中 |
| `remote.spacetime` | dreambuddy-spacetime.timer | 24h(07:00) | ❌ | 中 |
| `remote.continual-training` | dreambuddy-continual-training.timer | 30min(timer)→ 常驻 daemon(PID 684148,自 10-25 运行) | ❌ | **高**(2026-11-03 复核:**未停**,list-timers 显示为假象——daemon 常驻使 timer 触发成 no-op;`l1_case_store.jsonl` 当日 23:16 仍在写入,CPU 9 天均 11%) |

### 3.2 运行中服务(18 个,实测)

| 源 ID | 服务 | 事件信号(T3) | 热路径 |
|---|---|---|---|
| `remote.polling-trader` | yijing-polling-trader.service(300s 轮询 18 币对) | 日志 append | ✅ **禁接**(只盘点) |
| `remote.signal-scanner`* | signal-scanner.service(`scanner.py --daemon --interval 300`) | 日志 append | ⚠️ |
| `remote.trailing-stop` | trailing-stop-runner.service | — | ✅ **禁接** |
| `remote.cognitive-daemon` | cognitive-daemon.service | — | ❌ |
| `remote.datacenter-scheduler` | datacenter-scheduler.service | — | ❌ |
| `remote.hermes-gateway` | hermes-gateway.service(**已在运行**,快照过期) | — | ❌ |
| `remote.v15-api`/`:8771` / `v15-capital-api` / `yijing-data-server` / `fundamental` / `m25~m28` / `dreambuddy-frontend` / `product-hub` / `dreamos-dynamic-evaluator` | HTTP/常驻服务 | healthcheck 已覆盖其存活检查 | — |

### 3.3 事件判定信号(T3,2026-11-03 实测)

| 源 | 信号载体 | 事件形状 |
|---|---|---|
| atomic-events | `39-金融语义蒸馏系统/atomic_events.jsonl`(文件落盘) | JSONL 增量,本轮产出 0 条也留日志 |
| healthcheck | journal 结构化 JSON 行 | `{ts,status,fails,checks:[{check,result,detail}...]}`,status≠HEALTHY 即事件 |
| systemd 全量 | `systemctl show -p ExecMainStatus` / journal | timer 退出码≠0 = job_failed 事件(**通用兜底信号,覆盖全部 29 timer**) |
| backfill/integrity 等 | journal append 日志 | 关键字/退出码 |

**通用判定规则**:所有 timer 型源以「本次运行退出码 + 预期产出校验」为事件信号,无需逐源定制。

---

## 四、渠道/外部事件源(SPEC P0 预留接口,先模拟)

| 源 ID | 类别 | 现状 | P0 处理 |
|---|---|---|---|
| `ext.github-webhook` | webhook | **已实测:仓库 webhook 数 = 0**(gh api 2026-11-03) | 适配器接口预留,文件模拟 |
| `ext.feishu-event` | 消息渠道 | lark-cli event consume 可监听(NDJSON) | 适配器接口预留,P0 不接真实渠道 |
| `ext.file-drop` | 文件落盘 | 无统一监听 | **P0 首选模拟源**(A3 端到端验证用) |
| `ext.cron-file` | 定时器 | launchd/systemd 本身即定时器 | P0 模拟源 |

---

## 五、事件类意图导出(T6 校准版,基于 2026-11-03 实测)

从价值=高 的源导出初值意图(SPEC §3.1 任务 3 初值仅 2 个,此处为扩展池):

| 意图 ID | 来源事件 | L1 闭环动作(零 token) | 升级 L2 条件 |
|---|---|---|---|
| `alert_confirm`(P0) | 监控阈值命中(signal-scanner/ab-monitor) | 告警卡直发 | 连续命中/新型阈值 |
| `event_triage`(P0) | 通用事件分类(atomic_events.jsonl 新增条目) | 归类+记录 | 未知类型 |
| `health_alert`**新增** | healthcheck JSON `status≠HEALTHY` | 告警卡+异常 check 明细 | 连续 3 次异常/新 check 失败 |
| `job_failed` | timer 退出码≠0(通用兜底,29 timer) | 重试建议卡+飞书通知 | 重试仍失败 |
| `job_completed` | 长任务完成(backfill/training) | 记录+摘要卡 | 产出异常指标 |
| `integrity_alert` | dal-integrity 异常 | 告警卡 | 连续异常 |

**T6 校准结论**:
1. `health_alert` 升为第一优先意图——信号已结构化(JSON),判定零成本,覆盖 11 项检查
2. `job_failed` 通用兜底规则成立(systemd 退出码),不必逐源定制
3. `remote.continual-training` 经 2026-11-03 复核**未停用**(常驻 daemon 使 timer 显示成假象,案例库当日仍在写入),`job_completed(training)` 维持;但 models/ 产物最近更新 10-30,训练产出节奏可另案观察
4. atomic_events.jsonl 是 P0 事件网关 shadow 的**首选真实事件源**(文件落盘 + 10min 增量 + 现成)

---

## 六、待办(完成本盘点的剩余工作)

| # | 待办 | 状态(2026-11-03) |
|---|---|---|
| T1 | 全部 launchd plist 速率实测回填 | ✅ 完成(§二,27 项全实测) |
| T2 | 远端 timer/服务复核 | ✅ 完成(§三,18 服务 + 29 timer;经验 VM-1793717552554:扫码横幅是噪音) |
| T3 | 日志位置与事件判定信号 | ✅ 完成(§3.3,通用规则=退出码+产出校验;atomic_events.jsonl/healthcheck JSON 现成) |
| T4 | GitHub webhook 配置现状 | ✅ 完成:webhook 数 = 0,无现存配置 |
| T5 | A5 回放集构造(从本清单分布采样 n≥200) | ⬜ **可立项**:采样分布已具备(§七) |
| T6 | 事件化价值复核 | ✅ 完成(§五校准版,health_alert 升一优) |

> **盘点完成**:T1-T4+T6 全部完成,本清单可升 v1.0 定稿。剩余 T5(A5 回放集)立项条件已具备。

---

## 七、T5:A5 回放集采样分布方案(立项输入)

> 依据 SPEC-EVENT-DRIVEN-L1-GATEWAY A5:n≥200,覆盖全部已盘点事件类型。

| 事件类型 | 来源 | 采样方式 | 目标 n | 占比 |
|---|---|---|---|---|
| 原子事件(各类) | 云端 `atomic_events.jsonl` 历史段 | 直接抽取 | 100 | 50% |
| healthcheck 正常/异常 | journal 历史(含 HEALTHY 与故障段) | journalctl 导出按 status 分层 | 40 | 20% |
| timer job 成功/失败 | systemd journal 退出码记录 | 按源 ID 分层抽样 | 30 | 15% |
| 本地 launchd 事件 | 本地 plist 日志/状态 | 对应云端类型配比 | 20 | 10% |
| 模拟边界事件(未知类型/畸形/重复) | 合成 | 手工构造 | 10 | 5% |
| **合计** | | | **200** | 100% |

**实施要点**:①回放集落 `46-DSH架构/replay/`(或网关测试目录);②每条标注期望意图与期望分流(L1 闭环/升级 L2/丢弃);③atomic_events 拉取走 ssh 单次 scp,避免频繁连接;④未知类型样本用于验证 `event_triage` 升级路径。
