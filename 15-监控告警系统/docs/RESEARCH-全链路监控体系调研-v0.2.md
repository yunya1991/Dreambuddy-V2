# RESEARCH · 全链路监控体系调研 v0.2

> 日期：2026-11-17 ｜ 状态：调研稿 v0.2（只含结论、链路梳理与选型决策，不含实现）
> 范围：40 主神经网络闭环链路、23 四层自进化链路、交易/资金监控、告警治理
> 方法：仓库代码与运行时产物取证（以代码为准）+ 计算机工程监控框架 + 传统金融交易监控框架交叉对照
> **v0.2 增补（2026-11-17）**：云端 43.160.201.117 实测校正（§2.3）、GitHub 成熟项目选型（§3.4）、六项决策（§7）。**架构以云端为准，本地产物陈旧不代表云端陈旧。**

---

## 0. 结论摘要（先看这 10 条）

1. **监控系统本身已停摆**：`15-监控告警系统` 最后一次运行日志为 2026-08-07，且只覆盖 5 个老系统（yijing/v15/screen/agent_a/agent_b），完全没有覆盖 40/42/43/50/23/48。监控缺失的第一层不是"指标不够"，而是"监控自己没人看"。
2. **本地 40 日更无排程证据，云端有**：本地 `40/logs/` 只有 11-09/10/13 三天且无 launchd 条目；**云端已证实 cron `02:00` 每日运行**（§2.3）。因此云端风险不是"没排程"，而是"失败后无飞书通知、只靠 exit code"。
3. **产物陈旧无告警（本地实测）**：本地 `cycle_state.json` 的 `generated_at=2026-11-10T16:02Z`，同名产物 mtime 为 11-14；按 72h TTL 已 stale。**云端按 cron 持续运行，需以云端实测为准**；但"产物超 TTL 不告警"这一机制缺口在两端都存在。
4. **总线指标自相矛盾**：`42/runtime/bus_state.json` 显示 46 条信号、8 类 source（含 40-cycle/40-divergence/strategic_extension），而 `42/runtime/metrics.json` 停留在 11-12 且写 `signal_count=1, source_counts={11-washout:1}`。**监控数据本身不可信**，必须纳入"指标一致性"校验。
5. **降级事件在"静默刷屏"**：`42/runtime/degraded_events.jsonl` 已达 171KB，典型内容 `bridge_closed_using_defaults: strategy_mapping.json missing`。系统把"缺输入用默认值"当正常路径，但这是监控最该抓的**软故障**。
6. **50 决策账本混入测试数据**：`50/runtime/decisions.jsonl` 最新一条是 `symbol="BTC-FLAP-PAYLOAD"`。生产账本与测试夹具未隔离，会污染绩效统计与后续训练样本。
7. **23 的放量门禁停在原地**：`43/runtime/shadow_gate_state.json` 为 `consecutive_days=0, last_qualifying_date=null`；同时 `23/.../architecture_health_report.json` 报 `health_level=critical`（file_size 维度）。**门禁不推进、健康度 critical，但无人被告知**。
8. **风控口径不统一**：50 域 live 单笔名义上限默认 100 USDT（指数类 150–300），而 23 在 11-14 出现 `notional_usdt=1600` 的 open 决策。两条链上限不同本身可以，但**必须监控"实际下单名义 vs 该域声明上限"的越界**。
9. **业界成熟做法可直接借用**：Google SRE 四黄金信号 + SLO burn-rate 告警；Prometheus `absent()`/Watchdog 死手开关（监控"没有数据"）；数据可观测性五支柱（新鲜度/量/分布/Schema/血缘）；ML 监控（PSI/KS 漂移 + champion-challenger）；金融侧 MiFID II RTS 6 的交易前控制与 kill functionality、SEC 15c3-5、T+1 对账、TCA/implementation shortfall、SR 11-7 持续模型监控。
10. **建议的落地顺序**：先补"活着没 + 产出没 + 一致没"三类**静默失败**（1 周内可完成），再上契约/模型监控，最后接交易与资金监控；监控自身必须有死手开关与独立告警通道。

---

## 1. 调研范围与方法

| 维度 | 做法 | 取证对象 |
|---|---|---|
| 架构口径 | 读唯一事实源 | `49-交易框架协议/SPEC.md` §0.6 双决策链、§1–§5 |
| 链路节点 | 节点级代码+产物核对 | 40/42/43/48/50 目录、scripts、runtime |
| 自进化链路 | 四层编排与状态机 | 23 `evolution_pipeline.py`、`shadow_activation_gate.py`、`outbox.py` |
| 现有监控 | 适配器/调度/告警/日志 | `15-监控告警系统/`、`8-FEISHU/README.md` |
| 外部框架 | 公开规范与工程实践 | SRE/Prometheus/数据可观测性/MLOps/MiFID II/SEC/SR 11-7（见 §8） |

> 口径声明：文档与代码冲突时以代码和运行时产物为准；本稿引用的时间戳均取自实际文件。

---

## 2. 现状诊断

### 2.1 已有能力（可复用的地基）

| 能力 | 位置 | 评价 |
|---|---|---|
| 四类状态文件读取（heartbeat/risk/perf/state）+ 优先级短路判定 | `15-监控告警系统/adapters/__init__.py` | 模式正确，可复制到新链路 |
| 飞书卡片 + 四级路由（risk/trading/management/research 群） | `15-监控告警系统/feishu_alert.py` | 通道可用，缺去重/升级/静默 |
| 60min 全量 + 5min 持仓同步双节奏 | `15-监控告警系统/scheduler.py` | 只覆盖老系统 |
| 40 流水线步骤失败即告警并中止 | `40-周期神经网络系统/scripts/run_daily_pipeline.sh` | 只防"跑错"，不防"没跑/跑空" |
| 42 链式过滤器（新鲜度/置信度/冲突/数据健康/归一化）+ TTL | `42-神经网络交易协调层/SPEC.md` §2.2/§3 | 已有"消费侧防陈旧"，缺"生产侧可观测" |
| 50 决策前置三条件 + 幂等 + trigger flap 锁 | `50-NN主矛盾评估器/SPEC.md` §3、`runtime/trigger_flap.jsonl` | 机制健全，缺"拒绝原因聚合告警" |
| 43 fail-open + 时效校验 + shadow 门禁 | `43-战略承接推演层/SPEC.md` §9.1、`runtime/shadow_gate_state.json` | fail-open 正确，但"降级次数"未上报 |
| 飞书群组/审批/多维表格 | `8-FEISHU/README.md` | 可作为告警路由与事件留痕的底座 |

### 2.2 已证实的监控盲区（按风险排序）

| # | 现象 | 证据 | 后果 | 级别 |
|---|---|---|---|---|
| F1 | 监控系统停摆 | `15/logs/monitor.log` 最后 2026-08-07 | 所有"下游以为有人看"的假设失效 | P0 |
| F2 | 监控覆盖面缺失 | `15/config/monitor_config.json` 仅 5 个老系统 | 新主链路零监控 | P0 |
| F3 | 40 流水线无排程 | `40/logs/` 仅 3 天；LaunchAgents 无 40 条目 | 日更断更静默 | P0 |
| F4 | 无"没跑"告警 | 流水线只在 exit≠0 时告警 | 进程/调度器死了也"全绿" | P0 |
| F5 | 无死手开关 | 全仓库无 Watchdog/`absent()`/心跳外发 | 监控与被监控同时死 → 无人知 | P0 |
| F6 | 产物陈旧无告警 | `cycle_state.generated_at=11-10`，今日 11-17 | 用陈旧周期状态继续决策 | P1 |
| F7 | 指标不一致 | `bus_state` 46 条 vs `metrics.json` 1 条（11-12） | 看板/告警判断失真 | P1 |
| F8 | 降级刷屏无聚合 | `degraded_events.jsonl` 171KB，`bridge_closed_using_defaults` | 软故障被当常态，真正的断点被淹没 | P1 |
| F9 | 测试数据入生产账本 | `decisions.jsonl` 含 `BTC-FLAP-PAYLOAD` | 统计/训练污染，审计不可信 | P1 |
| F10 | 门禁卡死不告警 | `shadow_gate_state.consecutive_days=0` 长期不变 | 进化停摆但以为"在验证中" | P1 |
| F11 | 健康度 critical 无人知 | `architecture_health_report.health_level=critical` | 结构性风险累积 | P2 |
| F12 | 双告警路径 | `15/feishu_alert.py` 与 `6-TRADING/scripts/feishu_notify.py` | 口径/去重/级别不一致，告警风暴或漏报 | P2 |
| F13 | 名义上限跨域不一致 | 50 默认 100 USDT vs 23 实际 1600 USDT | 需按域监控越界，否则资金风险敞口不可解释 | P1 |
| F14 | 告警无治理 | 无去重/冷却/静默/确认/升级/runbook | 告警疲劳，P0 被 P2 淹没 | P1 |

---

### 2.3 云端现状实测（2026-11-17，架构与监控的唯一基准）

> 结论先行：**云端已有"调度 + 健康检查 + 自动回滚"的骨架，缺的是"指标时序 + 业务新鲜度 + 告警路由"。** 不需要重建调度，只需要在现有 systemd/cron 上加一层标准监控。

| 项 | 实测事实 | 对监控的含义 |
|---|---|---|
| 主机 | `VM-0-5-ubuntu`，4 vCPU / 15.6GB（已用 5.1GB）/ 178GB（61%），up 31 天，load ≈7 | 可承载轻量监控栈；资源不是瓶颈，需关注 4 核上的 CPU 竞争 |
| 运行时 | nginx + 前端 `3001/3002`；Docker：`dreambuddy-pg`(PG16)、`dreambuddy-redis`(Redis7)、`dreambuddy-minio`；约 40 个 systemd 服务 | 监控应覆盖"主机 + 容器 + systemd + 业务产物"四层 |
| 40 日更 | cron `02 0 * * *` 跑 `run_daily_pipeline.sh`；`00:10` 跑 `x0_pipeline.py`；`00:25` 跑 `x1_metrics.py` | 新鲜度 TTL ≈ 26h；凌晨 03:00 未成功即 P1 |
| 42 总线 | cron `*/15` 跑 `run_bus.py` | 信号 TTL ≈ 45min；每轮校验 source 覆盖与 metrics 一致性 |
| 43 承接 | systemd timer `dreambuddy-43-strategic-publish` 每 30min，`CYCLE_STATE_BRIDGE=1` | 产物 TTL ≈ 90min |
| 50 影子 | cron `7,22,37,52 * * * *` 跑 `tools/run_shadow.py` | 决策 TTL ≈ 60min |
| 50 live + 22 | systemd timer `dreambuddy-nn-live-chain` 每 5min（`run_live.py` + `x1_live_executor.py --limit 20`） | 最新一轮：`executed=0, skipped=20`，1 条 `symbol_already_open`；**"跑通但零动作"必须可区分于故障** |
| 健康检查 | `dreambuddy-healthcheck.timer` 每 5min 跑 `37-一键启动脚本/health-check.sh`；11 项检查；连续 3 次失败触发回滚 | **没有任何飞书通知**；只证明"进程/端口活着"，不证明"业务产出是新的" |
| 已知健康检查缺口 | Redis 检查恒为 `SKIP`（宿主机无 `redis-cli`）；未覆盖 40/42/43/50/23 的产物与决策 | 需要补容器内探测 + 业务探针 |
| 监控组件 | 9090/9093/9100/9115/3000 **均未监听**；无 Prometheus/Grafana/Alertmanager 容器；`15-监控告警系统` 未在云端部署 | 监控栈是从 0 到 1，但宿主与调度已成熟，落地成本低 |
| 本地 vs 云端 | 本地 `40/42/50` 产物 last write 为 11-14；云端按 cron 持续运行 | **§2.2 中"产物陈旧/未排程"类结论仅适用于本地**；云端对应风险是"任务失败但无通知" |

**云端已具备、可直接复用的三件事**
1. 调度：cron + systemd timer 已覆盖主链路，不需要另造调度器。
2. 探活：`health-check.sh` 已有"连续失败→回滚"逻辑，可扩展而不是重写。
3. 通道：`15/feishu_alert.py` + 6 个飞书群已存在，可作为 Alertmanager 的唯一出口。

**云端真正缺的三件事**
1. **指标时序**：没有 Prometheus/时序库，无法回答"过去 7 天这条链路稳不稳"。
2. **业务新鲜度**：健康检查只看进程，不看 `cycle_state/bus_state/decisions` 是否更新。
3. **告警路由**：健康检查失败只回滚、不通知；回滚本身也可能静默失败。

---

## 3. 外部框架调研

### 3.1 计算机工程侧

| 框架 | 核心内容 | 对本系统的直接用法 |
|---|---|---|
| 四黄金信号（Latency/Traffic/Errors/Saturation）| Google SRE 提出的最小可用指标集 | 每条链路统一用四类指标定义：决策延迟、信号/决策量、步骤失败/拒单、队列/仓位/风险预算饱和度 |
| SLI/SLO + 错误预算 + burn-rate 告警 | 按"预算消耗速率"报警，而非单点阈值；如 14.4x/1h 与 6x/6h 两级 | 给"40 日更成功率""50 决策可用率""对账一致率"定义 SLO；用"连续 2 天未产出"≈ 高 burn-rate 触发 P1 |
| Watchdog / Dead man's switch | 永远触发的告警外发到外部心跳服务；心跳停止即报警；`absent()` 监控"指标消失" | 监控系统每 5min 向飞书/外部发心跳；15 自己停摆必须 P0；任何"应该周期性出现"的产物用 `absent` 语义 |
| 元监控（monitor the monitor） | 黑盒探针：PushGateway→Prometheus→Alertmanager→邮件 全链路 | 每类告警做"端到端自检"，而不是只监控各组件存活 |
| 数据可观测性五支柱 | Freshness / Volume / Schema / Distribution / Lineage | 为每个产物定义：最大陈旧度、期望记录数区间、必填字段 Schema、字段分布突变、上下游血缘 |
| 告警治理 | 去重指纹、冷却窗口、静默期、确认/升级、runbook 强绑定 | 每条告警必须带 `fingerprint`、`runbook_url`、`owner`；无 runbook 不允许 page |
| MLOps 模型监控 | PSI/KS/JS 漂移、训练-服务偏差、延迟标签下的性能衰减、shadow/champion-challenger | 40 的 P5/P6、50 的权重 W6、23 的 Shadow-RL 都要有"漂移 + 影子一致率 + 回滚"监控 |
| 事件管理 | MTTD/MTTR、事故分级、复盘（postmortem） | 告警→事件→复盘→playbook 回写；对应本仓库 `15/memory/`（已实现未接入） |

### 3.2 传统金融侧

| 框架 | 核心要求 | 对本系统的映射 |
|---|---|---|
| 交易前控制（MiFID II RTS 6 Art.15 / SEC 15c3-5）| 价格 collar、最大单笔/单量、最大消息速率、重复自动执行节流、信用/市场风险限额、受限标的拦截；自动、交易前生效 | 下单前校验：`price_deviation`、`notional ≤ 域上限`、`symbol ∈ 白名单`、`重复单`、`频率节流`、`13 风控不得放宽` |
| Kill functionality（RTS 6 Art.12）| 紧急情况立即撤单/停止某策略或全部交易 | 50 的 `50_KILL_SWITCH`、13 fail-closed 需做**可用性监控 + 定期演练**，不能只写在文档里 |
| 实时监控与年度自评（RTS 6 Art.16/9）| 实时监控算法行为、异常交易；年度自评与变更治理 | 监控"决策异常率、方向翻转、触发源抖动"；变更（参数/权重/模型）需带影响评估与回滚 |
| 实时风险监控 | 未实现盈亏、保证金、敞口、集中度、回撤、kill switch；盘中而非盘后 | 每 1–5min：净值、日回撤、保证金率、强平距离、单标的/单类集中度 |
| 交易后对账 | drop copy / 成交回报 vs 内部账本；break 分类、T+1 内清零；仓/现金/订单三方对账 | 50/23 决策 → 订单 → 成交 → 持仓 全链 join；未成交、部分成交、重复成交必须分类告警 |
| TCA（Implementation Shortfall）| 显性费用 + 价差 + 市场冲击 + 延迟 + 机会成本；基准用 arrival/VWAP | 每笔按 `decision_id` 计算滑点、延迟成本、未成交机会成本；按策略/标的/时段聚合 |
| 模型风险管理（SR 11-7 / SR 26-02）| 持续监控、结果分析（outcomes analysis）、回测、独立验证、触发复审 | 40/50/23 模型：IC/准确率/校准度滚动窗口、PSI、回测例外数、性能衰减触发复审 |
| 加密市场特有 | 交易所 API 延迟/断流（2021-05-19 Binance 案例）、资金费率异常、OI 骤变、清算级联、标记价/指数价偏离、稳定币脱锚 | 独立一组"市场结构告警"，与策略性能告警分开 |

### 3.3 可迁移结论（框架 → 本系统落点）

```
SRE 四黄金信号        → 每条链路统一指标骨架（延迟/流量/错误/饱和）
SLO burn-rate         → 40 日更成功率、50 决策可用率、对账一致率
Watchdog/absent       → 所有"应周期产出"的产物 + 监控系统自身
数据五支柱            → 40/42/43/50/48/23 的每个 json/jsonl 产物
ML 漂移/影子          → 40 P5/P6、50 W6、23 Shadow-RL 与基因晋升
RTS 6 / 15c3-5        → 交易前六项硬校验 + kill switch 可用性
实时风险 + 对账 + TCA → 交易中/交易后监控与归因
SR 11-7               → 模型持续监控与复审触发器
```

---

### 3.4 GitHub 成熟项目选型（按"云端最小改动 + 行业标准"筛选）

> 选型原则（借用 `harness-reverse-engineering` 的三线取证法）：**静态线**看项目定位/维护活跃度，**运行时线**看部署足迹与资源占用，**交互线**看值班/排障体验。只选"标准件"，不自研监控底座。

| 项目 | Stars | 角色 | 决议 | 理由 |
|---|---:|---|---|---|
| [prometheus/prometheus](https://github.com/prometheus/prometheus) | 67.7k | 指标采集与时序库、告警规则 | **采用** | 云原生事实标准；单二进制；规则文件可版本化 |
| [prometheus/alertmanager](https://github.com/prometheus/alertmanager) | 8.7k | 告警分组/去重/静默/升级 | **采用** | 直接提供去重、抑制、静默、repeat_interval，正好补 F14 |
| [grafana/grafana](https://github.com/grafana/grafana) | 78.0k | 可视化与排障面板 | **采用（只做展示）** | 告警唯一源仍在 Prometheus，避免双告警引擎 |
| [prometheus/node_exporter](https://github.com/prometheus/node_exporter) | 13.9k | 主机 CPU/内存/磁盘/负载 | **采用** | 4 核 load≈7，需持续观测资源饱和 |
| [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter) | 5.9k | HTTP/TCP 黑盒探针 | **采用** | 覆盖 3001/3002/8093-8099/8771/8765 与 PG/Redis 端口 |
| [prometheus/pushgateway](https://github.com/prometheus/pushgateway) | 3.4k | oneshot 批任务指标接收 | **采用** | 云端大量 `Type=oneshot`/cron，Pushgateway 是标准解法；配 `push_time_seconds` 做"没跑"告警 |
| [healthchecks/healthchecks](https://github.com/healthchecks/healthchecks) | 10.5k | Cron/定时任务死手开关 | **暂缓** | 能力与 Pushgateway+absent 告警重叠；单栈优先，避免第二套调度 |
| [louislam/uptime-kuma](https://github.com/louislam/uptime-kuma) | 94.5k | 外部黑盒可用性 | **暂缓** | 若需要"站外视角"再加；当前 blackbox_exporter 已够 |
| [netdata/netdata](https://github.com/netdata/netdata) | 81.4k | 一体化主机可观测 | **不采用** | 与 Prometheus 标准栈重复；避免两套指标口径 |
| [evidentlyai/evidently](https://github.com/evidentlyai/evidently) | 8.1k | 数据/模型漂移报告 | **Phase 3 采用** | 40 P5/P6、50 W6、23 Shadow 的 PSI/漂移需要它；先手工跑报告，再定时 |
| [great-expectations/great_expectations](https://github.com/great-expectations/great_expectations) | 11.9k | 数据质量断言 | **暂缓** | 重；先用 exporter 做新鲜度/条数/Schema 三件套 |
| [OpenLineage/OpenLineage](https://github.com/OpenLineage/OpenLineage) | 2.8k | 血缘标准 | **暂缓** | 单机 30+ 任务规模，血缘先用静态配置表维护 |
| [prometheus-community/node-exporter-textfile-collector-scripts](https://github.com/prometheus-community/node-exporter-textfile-collector-scripts) | 618 | textfile collector 示例 | **参考** | 若不想跑 Pushgateway，可用 textfile 方式落地业务指标 |
| Alertmanager→飞书 桥接（多个仓库） | 0–1 | 飞书通知桥 | **不自研、不选用** | 生态项目均不成熟；直接用现有 `feishu_alert.py` 写一个 ~100 行 generic webhook 接收器 |

**不选"创新方案"的边界**：不引入 Service Mesh、不引入 eBPF、不自研时序库、不做多集群联邦；单机 + 标准栈足够覆盖当前规模。

---

## 4. 完整闭环链路梳理

### 4.1 40 主神经网络闭环（NN 链）

```text
18/19/20/21/38 数据 → 39 语义 / 9 基本面 ─┐
                                          ├→ 48 涌现网关（训练/度量/相变）
                                          │        ↓ 主供体
                                   40 周期神经网络（P1–P6）
                                          ↓ cycle_state / strategy_mapping / fund_flow
                                   43 战略承接（弹性约束，fail-open）
                                          ↓ strategic_extension_signal
                                   42 协调层（8 源总线 + 链式过滤器）
                                          ↓ bus_state
                                   50 主矛盾评估器（evidence→path→决策）
                                          ↓ FinalDecisionSignal(source=50-nn)
                              13 风控 → 16 定容 → 22 执行 / 11 执行器
                                          ↓ 成交/PnL/拒单
                                   48（train_*/feedback）→ 40 再训练
```

**节点表**（TTL 为建议监控阈值；`2×周期` 是下限，硬 TTL 按 42 SPEC 冻结值）

| # | 节点 | 入口/脚本 | 关键产物 | 时间戳字段 | 建议 TTL | 已有门禁 | 最可能的静默失败 |
|---|---|---|---|---|---|---|---|
| N1 | 数据采集 | `18-数据获取中心/data_center_scheduler.py` | 行情/FRED/yfinance 落地 | 各表 `updated_at` | 2×采集频率 | 20 清洗质量门禁 | API 断流但进程活；缺失率上升 |
| N2 | 语义输入 | 39 系统 | `l3_synthesis.json`、`semantic_events.jsonl`、`contradiction_events.jsonl` | `generated_at`/行 `ts` | 24h | — | 事件流停更；条数骤降 |
| N3 | 48 网关 | `40/scripts/refresh_48_feedback.py`、`consume_48_feedback.py` | `48/events/nn_feedback/40_feedback.json`、`training_samples/*.jsonl` | `generated_at` | 26h | G13 双读一致 | 双读不一致未上报 |
| N4 | 40 日更 | `40/scripts/run_daily_pipeline.sh`（17 步） | `cycle_state/asset_rotation/sector_transmission/fund_flow/washout_verdicts/strategy_mapping/stovall_breadth/meme_platform/factor_contradiction_priors` | 各文件 `generated_at` | 26h（硬 72h） | 步骤失败即停 | 只跑一半；`data_coverage=partial` 仍出结论 |
| N5 | P5/P6 门禁 | `p5_gate.py`、`p6_gate.py`、`p6_e2_train_encoder.py` | `p5_gate_status.json`、`p6_gate_status.json`、`e2_training_report.json` | `generated_at` | 7d | X1/X2 门槛 | 报文陈旧但 PASS 被继续引用 |
| N6 | 40 执行层 | `execution/x0_pipeline.py`、`x1_metrics.py` | `execution_state.json`、`portfolio_executions.jsonl`、`x1_metrics_status.json` | 行 `ts` | 24h | 独立风控红线 | "无成交"被当健康；准确率/IC 衰减 |
| N7 | 43 承接 | `strategic_extension/cycle_state_adapter.py` | `runtime/strategic_extension_signal.json`、`strategic_elements_history.jsonl` | `generated_at` | 7d | `CYCLE_STATE_BRIDGE` 开关、过期不注入 | fallback 静默接管；`shadow_gate_state` 卡死 |
| N8 | 42 总线 | `adapters/*`、`bus_state.json` | `runtime/bus_state.json`、`bus_history.jsonl`、`metrics.json`、`degraded_events.jsonl`、`params_active.json` | `generated_at` | 信号 24h/参数 72h/表现 7d | F1–F5 过滤器、TTL | 某 source 消失；`metrics` 与 `bus_state` 不一致；degraded 刷屏 |
| N9 | 50 评估 | `tools/run_live.py`、`core/*` | `runtime/decisions.jsonl`、`runtime/live/outbox.jsonl`、`runtime/live/latest.json`、`audit/decisions.jsonl`、`trigger_flap.jsonl` | `ts`/`expires_at` | 24h | live 三前置、幂等、flap 锁、证据 TTL | 无决策；测试数据混入；constraint_degraded；live 前置不满足静默转 paper |
| N10 | 执行/对账 | 22 `x1_live_executor.py`、11 执行器 | 订单、成交、持仓 | `ts` | 实时 | 13 风控、SL/TP 校验 | 拒单不上报；重复下单；SL/TP 缺失；持仓漂移 |
| N11 | 反馈回流 | `48 train_50_decisions`、`40_feedback` | `events/train_50_decisions.jsonl`、`events/nn_feedback/40_feedback.json` | `ts` | 24h | — | 成交未 join 到决策 → 学习饥饿 |
| N12 | 前端/中台 | 3.1-FRONTEND `/api/cycle/*` | 只读视图 | — | — | — | 展示陈旧数据却无"stale"标识 |

**链路级静默失败 Top 8（40 链）**
1. 调度器/流水线未启动或半途退出（N4）。
2. 产物存在但 `generated_at` 超 TTL（N4/N5/N7）。
3. 42 某 source 长期缺席，但总线"照常工作"（N8）。
4. `metrics.json` 与真实 `bus_state` 不一致（N8）。
5. 50 无新决策，或决策全部因前置条件降级为 paper（N9）。
6. 决策到成交没有闭环 join，PnL 无法归因（N10/N11）。
7. `constraint_degraded` 持续出现却无人处理（N9）。
8. 前端展示 stale 数据，人类误以为系统在跑（N12）。

### 4.2 23 四层自进化闭环

```text
L1 状态空间（行情/矛盾/案例）
   ↓ 高阶因子阻力调制
L2 路径发现（多路径竞争→最小阻力→统计验证→决策）
   ↓
L3 Shadow-RL（(s,a,R,s') 样本、Phase3 激活、影子门禁）
   ↓
L4 Bellman V(s) + 反思（CS/ESS）+ 权重自动调整
   ↓ 回馈
进化寻优（基因库三层准入）→ 回到 L1/L2
   旁路：决策 → outbox(pending→submitting→submitted→filled/failed) → 执行网关
```

**节点表**

| # | 节点 | 入口/模块 | 关键产物 | 时间戳字段 | 建议 TTL | 已有门禁 | 静默失败 |
|---|---|---|---|---|---|---|---|
| E1 | L1 状态空间 | `evolution_pipeline.py`、`core/*` | `data/contradiction_samples.json`、`gene_data/shadow_rl_samples.jsonl` | 行 `ts` | 24h | — | 样本流停更；reward 大量占位 0（历史 92.9%） |
| E2 | L2 路径/裁决 | `path_discovery_service.py`、`core/contradiction.py`、`dominance.py`、`w6.py` | 决策对象、`runtime/decisions.jsonl`（23 侧） | `ts` | 24h | 矛盾阈值/共振 | `path_count=1` 成常态；W6 从不更新 |
| E3 | L3 Shadow-RL | `core/shadow_rl.py`、`shadow_rl_trainer.py` | `gene_data/shadow_rl_samples.jsonl`（108MB）、Phase3 状态 | 行 `ts` | 24h | Phase3 自动激活 | FAIL-OPEN 吞异常；样本只增不训 |
| E4 | Shadow 放量门禁 | `core/shadow_activation_gate.py` | `43/runtime/shadow_gate_state.json` | `last_qualifying_date` | 每日应推进 | 一致性达标才放量 | `consecutive_days=0` 长期卡死 |
| E5 | L4 反思/权重 | `engines/reflection_engine.py`、`engines/auto_weight_adjuster.py`、`core/weight_store.py` | `data/ess_reflection.jsonl`、`ess_gmax_history.jsonl`、权重文件 | 行 `ts` | 7d | CS 四维奖惩、权重上下限 | CS 恒为中性 0.0；权重从不调整 |
| E6 | 进化快照 | `run_evolution_snapshot.py` | `gene_data/evolution_snapshots.json` | 行 `ts` | 24h | — | 快照重复/停更 |
| E7 | 决策发件箱 | `execution/decision_signal.py`、`execution/outbox.py` | `runtime/execution_decisions.jsonl`、outbox | `ts`/stage | 实时 | `pending→…→filled/failed` | 卡在 submitting；重复决策；失败不重试 |
| E8 | 基因治理 | 基因库三层准入 | `gene_data/registry.json`、`architecture_health_report.json` | `generated_at` | 7d | 影子/灰度 | 健康度 critical；基因只增不淘汰 |
| E9 | 交易索引/反馈 | `.workbuddy/trade_index/all_trades_index.jsonl` | 成交索引 | `ts` | 24h | — | 索引与真实成交不一致 |

**链路级静默失败 Top 6（23 链）**
1. 影子门禁"永远差一天"（E4）。
2. Shadow-RL 样本持续写入但训练/Phase3 从未触发（E3）。
3. 反思/权重调整因 FAIL-OPEN 恒走中性分支（E5）。
4. outbox 卡在 `submitting`，资金侧无成交、系统侧无告警（E7）。
5. 基因库健康度 critical 与晋升流程并行且互不知情（E8）。
6. 交易索引与交易所持仓不一致，导致 reward 失真（E9）。

### 4.3 跨链共享风险点

| 风险点 | 说明 | 监控动作 |
|---|---|---|
| 双链对照失效 | 49 SPEC 要求 23 作为 NN 链的对照实验 | 两条链的"同标的同窗口"决策/绩效对照指标必须持续产出；对照断更=P1 |
| 执行出口互斥 | `source=50-nn` 与 `23-evolution` 不得同标的同时 live | 每次下单校验 `execution_rights` + 同标的互斥；冲突=P0 |
| 上限口径 | 50 默认 100 USDT，23 出现 1600 USDT | 按域声明上限监控越界；越界=P0 阻断 |
| 反馈污染 | 测试 symbol、未 join 成交 | 生产账本 symbol 白名单 + join 覆盖率监控 |

---

## 5. 监控体系设计建议

### 5.1 五层监控模型

| 层 | 目标 | 监控对象 | 典型探针 | 告警 |
|---|---|---|---|---|
| L0 存活/调度 | "该跑的在跑" | 进程、launchd/systemd、流水线、cron | 心跳文件、`absent()`、启动日志、退出码 | P0/P1 |
| L1 数据/产物 | "产出的是新的、对的、全的" | 每个 json/jsonl 产物 | 新鲜度、记录数、Schema、分布、血缘 | P1/P2 |
| L2 契约/链路 | "上下游接上了" | 42 source 覆盖、43 注入、50 决策、TTL | source 覆盖率、degraded 计数、决策产出率 | P1 |
| L3 模型/进化 | "还准、还在进化" | 40 P5/P6、50 W6、23 Shadow-RL | IC/准确率/校准、PSI、影子一致率、门禁推进 | P1/P2 |
| L4 交易/资金 | "钱是安全的、账是对的" | 下单、成交、持仓、PnL | 交易前六校验、实时风险、对账、TCA | P0/P1 |
| L5 告警治理 | "报警有人管" | 告警自身 | 去重、冷却、确认、升级、runbook、复盘 | P0（元告警） |

### 5.2 指标字典（最小集，先做 26 个）

| 类别 | 指标 | 定义/阈值建议 | 级别 |
|---|---|---|---|
| 存活 | `job_heartbeat_age` | 超过 3×周期 → 告警 | P0/P1 |
| 存活 | `pipeline_last_success_age` | 40 日更 >26h → P1；>48h → P0 | P0 |
| 存活 | `monitor_self_heartbeat` | 15 系统 >10min 无心跳 → P0 | P0 |
| 新鲜度 | `artifact_age_seconds` | 按 §4 表 TTL | P1 |
| 完整性 | `artifact_record_count` | 低于 7 日均值 50% → P2 | P2 |
| Schema | `artifact_schema_violations` | >0 → P1 | P1 |
| 分布 | `field_distribution_psi` | PSI>0.2 → P2；>0.25 → P1 | P1 |
| 血缘 | `feedback_join_coverage` | 成交 join 决策 <95% → P1 | P1 |
| 链路 | `bus_active_sources` | <6 → P2；缺 40-cycle/43-strategic → P1 | P1 |
| 链路 | `bus_signal_count_24h` | 为 0 或较 7 日均值降 >70% → P1 | P1 |
| 链路 | `metrics_consistency_mismatch` | `metrics` 与 `bus_state` 不一致 → P1 | P1 |
| 链路 | `degraded_events_rate` | >N/小时 → P2；同 reason 连续 3 天 → P1 | P1 |
| 链路 | `constraint_degraded_ratio` | >30% 决策带降级 → P1 | P1 |
| 决策 | `decision_count_24h` | 有证据但 0 决策 → P1 | P1 |
| 决策 | `decision_to_paper_ratio` | live 前置不满足比例突增 → P2 | P2 |
| 决策 | `trigger_flap_lock_rate` | 锁定率 >10% → P2 | P2 |
| 模型 | `model_ic_rolling` | 20 日 IC<0 → P2；连续 3 期 → P1 | P1 |
| 模型 | `model_calibration_slope` | 超出 [0.85,1.15] → P2 | P2 |
| 模型 | `shadow_consistency_rate` | <85%（43 P3 阈值）→ P1 | P1 |
| 进化 | `gate_consecutive_days` | 连续 7 天为 0 → P2；14 天 → P1 | P1 |
| 进化 | `shadow_samples_growth` | 24h 增量为 0 → P2 | P2 |
| 进化 | `weight_adjust_count_7d` | 0 次且样本充足 → P2 | P2 |
| 交易 | `order_reject_rate` | >2% → P2；>5% → P1 | P1 |
| 交易 | `notional_over_domain_cap` | >0 → P0 | P0 |
| 交易 | `position_reconciliation_break` | >0 且 15min 未清 → P0 | P0 |
| 交易 | `slippage_vs_arrival_bps` | 按策略分位，>P95 持续 → P2 | P2 |
| 资金 | `daily_drawdown_pct` | 50 域 50 USDT / 全局阈值 → P0 | P0 |
| 资金 | `margin_ratio / liq_distance` | 低于预注册安全线 → P0 | P0 |

### 5.3 告警分级、路由与治理

| 级别 | 语义 | 例子 | 路由 | 响应 | 升级 |
|---|---|---|---|---|---|
| P0 | 资金/合规/失控，需立即人工 | 未授权 live、重复下单、对账不平、kill switch 不可用、日亏损超限、监控自身死亡 | Trading-RiskControl + @all + 电话 | 5min 内确认 | 10min 未确认→第二责任人；30min→电话 |
| P1 | 链路断点，决策能力受损 | 40 日更失败/超 TTL、bus 缺关键源、50 无决策、影子门禁卡死、模型 IC 转负 | Trading-Desk + RiskControl | 30min | 2h 未处理→升级 |
| P2 | 降级/漂移/趋势 | degraded 率上升、PSI 漂移、拒单率升高、滑点恶化 | Trading-Desk | 4h/当日 | 次日复盘 |
| P3 | 摘要/趋势 | 每日健康摘要、周报、门禁进度 | Trading-Management | 无需即时 | 周会 |

治理规则（必须写进配置，而不是口头约定）：
1. **指纹**：`hash(layer, node, reason, symbol, window)`；同指纹 30min 内只发一次。
2. **重复**：未恢复则每 6h 复报一次，并在标题标 `[未恢复 N 次]`。
3. **恢复通知**：同一指纹发"已恢复"，避免只报坏消息。
4. **静默窗口**：发布/回滚/预定维护可静默 P2/P3，**P0 永不禁默**。
5. **Runbook 强绑定**：无 `runbook_url` 的规则不得进 P0/P1 路由。
6. **元监控**：15 系统自身每 5min 外发心跳；无心跳=P0。
7. **单一权威通道**：统一走 `15/feishu_alert.py`，`6-TRADING/scripts/feishu_notify.py` 降级为业务通知，不承担告警。

### 5.4 与门禁/风控的联动

| 场景 | 自动动作 | 边界 |
|---|---|---|
| 对账不平 / 重复下单 / 未授权 live | 立即 kill switch，撤挂单，冻结该域 live | 只收紧不放宽；恢复需人工双确认 |
| 40/43 产物 stale | 下游按既有 fail-open 降级，但必须发 P1，并在决策 `payload` 标 `degraded` | 不因监控自身异常阻断交易（FAIL-OPEN） |
| 模型 IC/校准连续恶化 | 自动把域 `execution_rights` 降为 paper（建议） | 需先评审再启用自动降级 |
| 影子门禁推进 | 达阈值仅"提议"，人工/审批放量 | 不放宽 13 风控与 48 门禁 |

---

## 6. 实施路线（建议）

> 本节是通用能力路线；**云端具体落地以 §7.1 为准**（标准栈 + 只读 exporter + 不改交易代码）。

### Phase 0 · 止血（1 周，先把"静默"变"有声"）

1. 给 40 日更、42 总线刷新、50 run_live、23 pipeline、48 指标各加**心跳文件**（`runtime/heartbeat/<job>.json`）。
2. 15 系统新增 6 个适配器（40/42/43/50/23/48），先只做三件事：**进程/心跳、产物新鲜度、关键产物存在性**。
3. 增加**"没跑"规则**：TTL 超时、`absent` 语义、连续 2 周期无产出。
4. 加 **15 自身死手开关**：每 5min 外发心跳；心跳缺失由独立脚本告警。
5. 告警治理最小版：指纹去重 + 30min 冷却 + 恢复通知 + P0/P1/P2 路由。
6. 隔离测试数据：生产账本 symbol 白名单校验（先告警，不阻断）。

**验收**：人为停掉 40 流水线与 15 自身，均能在 10min 内收到 P0/P1；恢复后收到恢复通知。

### Phase 1 · 链路可观测（2–3 周）

1. 建立统一指标落盘（建议 SQLite/单文件 JSONL，字段固定：`ts, layer, node, metric, value, labels, severity`），替代散落 metrics。
2. 补齐 §5.2 的链路指标：`bus_active_sources`、`metrics_consistency_mismatch`、`degraded_events_rate`、`decision_count_24h`、`feedback_join_coverage`。
3. 解析 `degraded_events.jsonl` 做原因聚合与趋势；`constraint_degraded` 进决策摘要。
4. 43 `shadow_gate_state`、23 `architecture_health_report`、23 outbox 状态机纳入监控。
5. 每日 08:00 健康摘要（P3）+ 周报（趋势与 Top 原因）。

**验收**：任一 source 被人为移除、任一产物被改旧、任一决策被改成测试 symbol，均能在 1 个周期内触发 P1/P2。

### Phase 2 · 模型与交易监控（3–4 周）

1. 模型监控：40 P5/P6 指标、50 W6 权重、23 CS/ESS 与影子一致率；PSI/KS + 滚动 IC/校准。
2. 交易前六校验监控：价格偏离、名义上限（按域）、白名单、重复单、频率、13 风控不放宽。
3. 交易中：净值/回撤/保证金/强平距离/集中度，按 1–5min。
4. 交易后：决策→订单→成交→持仓→PnL 全链 join；对账 break 分类；TCA（arrival/VWAP/IS）。
5. Kill switch 可用性巡检与季度演练（含"监控系统挂掉时"的降级路径）。

**验收**：单笔实盘可完整归因（decision_id → fill → PnL → slippage）；对账 break 30min 内可见；kill switch 演练 RTO 达标。

---

## 7. 决策（基于云端现状 + 成熟标准，最小改动）

> 决策原则：**标准件优先、单栈优先、只读优先、告警单出口**。不为监控改造交易主链，不引入第二套调度/告警引擎。

### D1 监控运行形态：云端单机标准栈（不做自研底座）

- **采用**：Docker Compose 部署 `Prometheus + Alertmanager + Grafana + node_exporter + blackbox_exporter + Pushgateway`（镜像固定版本，全部绑 `127.0.0.1`；Grafana 经 nginx 子路径 + 认证暴露）。
- **职责边界**：Prometheus 是唯一告警判定源；Alertmanager 只做分组/去重/抑制/静默/升级；Grafana 只做展示，不配告警规则（避免双引擎口径不一致）。
- **不采用**：Netdata（与标准栈重复）、Uptime Kuma（当前 blackbox 够用）、Healthchecks（与 Pushgateway+absent 重叠）、任何 0–1 star 的飞书桥接项目。
- **资源评估**：6 个容器约 0.5–1GB 内存、<0.5 核；云端可用 10.5GB / 4 核，满足。

### D2 P0 自动动作边界：只冻结"无歧义"的三类，且复用现有 kill-switch

| 场景 | 动作 | 实现方式 |
|---|---|---|
| 重复下单 / 未授权 live / 同标的双链并存 | **自动冻结该域 live** | 监控写冻结标记文件；50 现有 `50_KILL_SWITCH` 语义消费；13 保持 fail-closed |
| 对账不平 >15min / 实际名义 > 域上限 / 日亏损超限 | **自动冻结该域 live + 撤挂单** | 22 执行器读取冻结标记；撤单走现有 OKX 通道 |
| 其余 P0（如 40 断更、模型失效、监控自身死亡） | **只告警，不自动动仓** | 避免监控系统越权 |

- **观察期**：前 4 周只告警不冻结，验证规则误报率 <5% 后再开启自动冻结。
- **红线**：监控系统不获得"下单/加仓"能力，只能"收紧/冻结"；冻结动作必须幂等、留审计、可人工一键解除。

### D3 节奏与 TTL：以云端真实调度为准

| 链路 | 云端节奏 | 新鲜度 TTL | "没跑"判定 |
|---|---|---|---|
| 40 日更 | 每日 00:02 | 26h | 03:00 未成功 → P1；48h → P0 |
| 40 x0/x1 | 每日 00:10 / 00:25 | 26h | 同上 |
| 42 总线 | 每 15min | 45min | 连续 2 周期无推送 → P1 |
| 43 承接 | 每 30min | 90min | 连续 2 周期无产物 → P1 |
| 50 影子 | 每 15min（7/22/37/52） | 60min | 连续 2 周期无决策 → P1 |
| 50 live + 22 | 每 5min | 15min | 连续 3 轮无运行 → P0 |
| 健康检查 | 每 5min | 15min | 心跳缺失 → P0（元监控） |
| 48 指标 | 每日 06:10 | 26h | 缺更 → P2 |

- 统一用 Pushgateway 的 `push_time_seconds` + `time() - push_time_seconds` 表达"最后一次成功"；**不用进程存活替代业务成功**。

### D4 告警通道：收敛为一个出口，业务通知与告警彻底分离

- **唯一告警出口**：`Alertmanager → feishu-receiver（复用 15/feishu_alert.py 的 app 凭证与卡片）→ 对应群`。
- `6-TRADING/scripts/feishu_notify.py` 保留为**业务通知**（研报/审批/复盘/执行日志），不得再承载告警级别与告警路由。
- 两条路径都加 `channel=alert|business` 标签，便于审计"哪条消息是告警"。
- 分级路由沿用现有群：P0 → Trading-RiskControl；P1 → Trading-Desk；P2 → Trading-Desk；P3 → Trading-Management。

### D5 23 与 50 的名义上限：保留分域差异，但统一校验与监控

- **不统一数值**：50 域（默认 100 / 指数 150–300 USDT）与 23 域（观察到 1600 USDT）是不同风险预算，强行拉平会改变策略行为。
- **统一机制**：上限写入配置（每域一份），下单前由 13/22 校验；监控指标 `notional_over_domain_cap`，越界 = P0 阻断。
- **待确认**：23 的 1600 USDT open 是否为预期。未确认前按 P1 观察 2 周，不直接阻断。

### D6 值班：单人最小 on-call，不建正式轮值表

- P0：飞书群 + `@all` + 10min 未确认重发（最多 3 次）→ 电话；P1：30min 响应；P2：当日；P3：周报。
- 依靠 D2 的自动冻结降低"必须立刻有人"的依赖；人工职责聚焦"确认为什么"和"何时解冻"。

### 7.1 云端最小落地（不改交易代码）

```text
已有 cron/systemd ──push──> Pushgateway ─┐
node_exporter ───────────────────────────┤
blackbox_exporter（HTTP/TCP 探针）───────┼──> Prometheus(9090, 15s) ──rules──> Alertmanager(9093)
business-metrics-exporter（只读 JSON）───┘                                   │
                                                                              └──> feishu-receiver ──> 飞书群
Grafana(3000) ── 只读 Prometheus
```

| 组件 | 是否改交易代码 | 说明 |
|---|---|---|
| node/blackbox/Pushgateway/Prometheus/Alertmanager/Grafana | 否 | 标准镜像 + 配置文件 |
| `business-metrics-exporter` | **否** | 新增只读进程：扫描 40/42/43/50/23/48 产物 + PG/Redis，暴露 `/metrics`（约 300 行） |
| 各 cron/systemd 任务 | **极小** | 成功/失败后 `curl --data-binary @- .../metrics/job/<name>` 推送一次；或在脚本末尾追加一行 |
| `health-check.sh` | **小** | 补 40/42/43/50 产物检查、Redis 走容器内 `redis-cli`、失败时调 feishu-receiver |
| `feishu-receiver` | 否 | 复用 `15/feishu_alert.py`，新增 HTTP 入口解析 Alertmanager webhook |

**首批 12 条告警规则（按优先级）**
1. `MonitorSelfHeartbeatMissing`（15/healthcheck 自身，P0）
2. `NnLiveChainNoRun`（5min 任务 3 轮未跑，P0）
3. `Daily40PipelineFailedOrLate`（03:00 未成功，P1）
4. `ArtifactStale`（40/43/50 产物超 TTL，P1）
5. `BusSourceMissing`（关键 source 连续 2 轮缺失，P1）
6. `BusMetricsMismatch`（metrics 与 bus_state 不一致，P1）
7. `DecisionSilence`（50 有证据但 24h 无决策，P1）
8. `DegradedEventFlood`（42 degraded 单位时间超阈值，P2）
9. `ReconcileBreak`（持仓/成交对账不平 >15min，P0）
10. `NotionalOverDomainCap`（越界，P0）
11. `DailyDrawdownBreach`（日亏损/回撤超限，P0）
12. `ModelPerformanceDecay`（IC/校准/影子一致率连续恶化，P2→P1）

**实施顺序**
- Day 1–2：Compose 起 6 组件；接入 node/blackbox；Grafana 基线面板（主机/端口）。
- Day 3–4：`business-metrics-exporter` + 40/42/43/50/23 产物探针；Pushgateway 接入 cron。
- Day 5：12 条规则 + Alertmanager 路由 + feishu-receiver；做"停 40 流水线 / 停 15 / 造对账不平"三次演练。
- 第 2 周：观察误报，调阈值；开启 D2 自动冻结的前两类。

---

## 8. 参考来源

**计算机工程**
- [The Four Golden Signals of SRE](https://www.sherlocks.ai/blog/four-golden-signals-of-sre)
- [SRE alerting best practices: burn rate & signal-to-noise](https://incident.io/blog/sre-alerting-best-practices)
- [Backend Engineering Essentials: Alerting Philosophy（burn-rate 两级窗口）](https://alivedise.github.io/backend-engineering-essentials/observability/alerting-philosophy)
- [Prometheus: Alerting（metamonitoring / 症状优先）](https://prometheus.io/docs/practices/alerting/)
- [PromLabs: End-to-End Watchdog Alerts](https://training.promlabs.com/training/monitoring-and-debugging-prometheus/metrics-based-meta-monitoring/end-to-end-watchdog-alerts/)
- [Red Hat: Dead man's switch](https://docs.redhat.com/en/documentation/openshift_container_platform/3.11/html/configuring_clusters/prometheus-cluster-monitoring)
- [Monte Carlo 五支柱（数据可观测性）](https://datalakehousehub.com/knowledgebase/monte-carlo/)
- [Data Observability for AI Pipelines: 第六支柱](https://atlan.com/know/ai-agent/data-for-ai/data-observability-for-ai-pipelines/)
- [MLOps 生产监控：PSI/KS/Wasserstein 漂移](https://andrewaltimit.github.io/Documentation/docs/ai-ml/mlops-production.html)
- [Champion-Challenger 与影子部署](https://open-exam-prep.com/study-guides/comptia-secai-plus/operational-risks-ai-assisted-security/model-drift-monitoring-metrics)

**传统金融**
- [MiFID II RTS 6 原文（Art.12 kill functionality / Art.15 pre-trade controls）](https://ec.europa.eu/finance/securities/docs/isd/mifid/rts/160719-rts-6_en.pdf)
- [ESMA Q&A：kill functionality 释义](https://www.esma.europa.eu/sites/default/files/library/esma70-872942901-38_qas_markets_structures_issues.pdf#page=26)
- [FCA: Algorithmic Trading Compliance in Wholesale Markets（交易前控制清单）](https://www.fca.org.uk/publication/multi-firm-reviews/algorithmic-trading-compliance-wholesale-markets.pdf)
- [ESMA: Supervisory Briefing on Algorithmic Trading in the EU](https://www.esma.europa.eu/sites/default/files/2026-02/ESMA74-1505669079-10311_Supervisory_Briefing_on_Algorithmic_Trading_in_the_EU.pdf)
- [SEC Rule 15c3-5（Market Access Rule）](https://www.sec.gov/files/rules/final/2010/34-63241.pdf)
- [SEC 15c3-5 FAQ](https://www.sec.gov/files/faq-15c-5-risk-management-controls-bd.htm)
- [FINRA: Market Access Controls](https://www.finra.org/rules-guidance/guidance/reports/2017-report-exam-findings/market-access-controls)
- [Fed SR 11-7：Model Risk Management（outcomes analysis / ongoing monitoring）](https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107.pdf)
- [Fed SR 26-02（替代 SR 11-7 的新版指引）](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf)
- [Implementation Shortfall / TCA 分解](https://ryanoconnellfinance.com/implementation-shortfall/)
- [TCA 数据延迟与时间戳陷阱](https://www.quodfinancial.com/transaction-cost-analysis-tca-institutional-trading/)
- [T+1 与 reconciliation breaks](https://posttrade360.com/news/infrastructure/cutting-through-the-noise-prioritising-settlement-risk-in-a-t1-world/)
- [实时算法监控：心跳与看门狗](https://blog.traderspost.io/article/real-time-algo-monitoring)
- [实时监控系统指标清单（连接/队列/延迟/错误）](https://breakingalpha.io/insights/real-time-monitoring-systems-trading-algorithms)
- [Bitcoin 2021-05-19：交易所 API 延迟与数据断流实证](https://www.iwh-halle.de/fileadmin/user_upload/publications/iwh_discussion_papers/iwh-discussion-paper_2022_25_Baumgartner_Guettler.pdf)

---

## 附：本稿对应的仓库证据索引

| 结论 | 证据文件 |
|---|---|
| 15 系统停摆 | `15-监控告警系统/logs/monitor.log`（最后 2026-08-07） |
| 覆盖面仅 5 系统 | `15-监控告警系统/config/monitor_config.json` |
| 40 流水线三步+告警逻辑 | `40-周期神经网络系统/scripts/run_daily_pipeline.sh` |
| 40 产物陈旧 | `40-周期神经网络系统/cycle_state.json`（`generated_at`） |
| 42 指标不一致 | `42-神经网络交易协调层/runtime/metrics.json` vs `runtime/bus_state.json` |
| 42 降级日志 | `42-神经网络交易协调层/runtime/degraded_events.jsonl` |
| 43 门禁卡死 | `43-战略承接推演层/runtime/shadow_gate_state.json` |
| 50 测试数据+决策 | `50-NN主矛盾评估器/runtime/decisions.jsonl`、`runtime/trigger_flap.jsonl` |
| 23 健康度 critical | `23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/architecture_health_report.json` |
| 23 执行决策（1600 USDT） | `23-四层闭环自进化交易架构/runtime/execution_decisions.jsonl` |
| 双决策链定义 | `49-交易框架协议/SPEC.md` §0.6 |
| 42 TTL/过滤器 | `42-神经网络交易协调层/SPEC.md` §2.2/§3 |
| 50 live 三前置/幂等 | `50-NN主矛盾评估器/SPEC.md` §3、§3.1 |
| 云端调度节奏 | `43.160.201.117` 的 `crontab -l`（40 02:00 日更、42 `*/15`、50 影子 `7,22,37,52`）与 `systemctl list-timers` |
| 云端健康检查与回滚 | `dreambuddy-healthcheck.service` → `37-一键启动脚本/health-check.sh`；`journalctl -u dreambuddy-healthcheck` |
| 云端无监控栈 | 云端 `ss -ltn`：9090/9093/9100/9115/3000 均未监听；`docker ps` 无 Prometheus/Grafana |
| 云端 NN live 链 | `journalctl -u dreambuddy-nn-live-chain`（每 5min；最近 `executed=0, skipped=20`） |
| 云端未部署 15 | `/home/luke/dreambuddy/15-监控告警系统/logs` 无运行日志 |

> 取证口径提醒：§2.2 中 F3（40 无排程）与 F6（产物陈旧）是**本地**事实；云端有 cron 排程且持续运行，对应风险应改写为"任务失败无通知"，不要据本地产物判断云端状态。
