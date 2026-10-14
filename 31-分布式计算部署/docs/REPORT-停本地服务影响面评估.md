# REPORT — 暂停本地前后端服务对远端的影响面评估

> **定位**：分布式计算改造前置风险报告（供用户决策「是否暂停本地前后端服务」）
> **日期**：2026-10-14 | **证据级**：SSH 实测 + 本地实测 + 代码核对
> **关联**：[SERVICE_INVENTORY.md](./SERVICE_INVENTORY.md) · [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) · [SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md)

---

## 0. 结论（先读这段）

**暂停本地前后端服务，不会影响远端系统自身的运行。**

- 远端是一个**自足权威节点**：19 个 systemd 常驻服务 + 11 个 timer 全部 `active running`，自带 Nginx（仅回环转发到本机端口）、PostgreSQL / Redis / MinIO（均 127.0.0.1）。
- 远端 **无任何反向依赖本地**：所有 systemd unit、Nginx、cron 均未引用本地主机，也不 SSH 回连本地（`grep` 实测 0 命中）。
- 唯一现存「本地→远端」链路是**单向上行同步**（`com.dreambuddy.dbsync` / `08-local-mirror.sh`，把本地独有认知行与 gene_data 新增上行到远端）。本地停服后本地不再产生新写入，该通道自然无需工作，**远端无损失**。
- 停本地还**降低**双写分叉风险（本地不再与远端并发写权威库）。

**结论：可以暂停本地前后端服务；本地独有缺口 `etl-worker` 已于 2026-10-14 补齐云端（见 §5，phase10），另需注意 3 个不宜误伤项。**

---

## 1. 代码一致性核对（"三端一致"验证）

| 端 | 分支 / 版本 | 状态 |
|---|---|---|
| 本地 | `main` @ `3e0d7928ce` | ahead/behind origin/main = **0 / 0**，工作区仅 1 个运行时文件 modified（`12-三屏趋势系统/signal_pool/pool.json`） |
| 远端 | `main` @ `3e0d7928` | `/home/luke/dreambuddy` |
| GitHub | `origin/main` | 与本地一致（0/0） |

→ **三端代码一致已核实**，停服不会引入代码差异。

---

## 2. 远端服务清单（SSH 实测 2026-10-14 19:23）

### 2.1 常驻服务（systemd，active running，19 个）

| 服务 | 端口/职责 |
|---|---|
| `v15-api.service` | 8771 V15 策略 API |
| `v15-capital-api.service` | 8770 资金管理 API |
| `yijing-data-server.service` | 8765 易经数据服务 |
| `yijing-polling-trader.service` | BCRM2 + Strategy + BDSM 轮询交易 |
| `dreambuddy-frontend.service` | 3001 Next.js 15（主前端） |
| `product-hub.service` | 3456 Next.js 14（产物中台） |
| `datacenter-scheduler.service` | 18 采集调度（含 18→19 回填） |
| `cognitive-daemon.service` | 认知库守护 |
| `dreamos-scheduler.service` | DreamOS 编排（每小时多币扫描） |
| `dreamos-dynamic-evaluator.service` | 动态评估（6h） |
| `fundamental.service` | 9094（`ml_trade_service_v2.py`） |
| `m25-strategy-generation.service` | 8095 |
| `m26-strategy-lib.service` | 8093 |
| `m27-governance.service` | 8094 |
| `m28-signal-trigger.service` | 8096 |
| `signal-scanner.service` | 12-三屏信号池（300s） |
| `trailing-stop-runner.service` | 16-调控 trailing stop（OKX real，300s） |
| `hermes-gateway.service` | 飞书消息网关 |
| `hermes-dashboard.service` | Web UI :9119 |

### 2.2 Timer（实测 enabled，11 个）

`v15-poll-light`(5min) · `v15-orchestrator`(15min) · `datacenter-backfill`(每小时:15) · `dreambuddy-snapshot`(**10min**) · `dal-integrity`(6h) · `dal-backup`(04:00) · `dal-rotate`(05:00) · `ranking-trigger` · `yijing-monitor` · `dreambuddy-continual-training`(**30min**) · `memory-cleanup`(02:05)

### 2.3 Nginx 路由（全部指向本机回环）

`/`→3001 · `/api/v15/`→8771 · `/api/capital/`→8770 · `/api/trend/`→8765 · `/api/fundamental/`→9094 · `/api/m25/`→8095 · `/api/m26/`→8093 · `/api/m27/`→8094 · `/api/m28/`→8096

→ **无一条路由指向本地 Mac**。

### 2.4 数据层与健康

- Docker：`dreambuddy-pg`(5432) · `redis`(6379) · `minio`(9000/9001)，均 127.0.0.1。
- 健康抽查：`3001=307`（Next 重定向，正常）· `8771` 存活 · `8765=200` · `3456=307`，服务在线。

### 2.5 反向依赖检查（关键）

```
远端 systemd unit / nginx / cron 中检索 "Mac|zhangjiangtao|192.168|ssh .*@" → 0 命中
```

→ **远端不依赖本地任何端点**。这与协同设计一致：线下（本地）故障时云端用自身完整链继续交易。

---

## 3. 本地服务全貌（LaunchAgents 实测 ~35 个）

按处置分类（沿用 SERVICE_INVENTORY 分组）：

| 组 | 代表项 | 与远端关系 |
|---|---|---|
| **A 云端已覆盖（冗余可停）** | `v15_light_poll` / `v15_orchestrator` / `yijing_data_server` / `yijing.polling-trader` / `yijing_trading` / `yijing_live_300s` / `yijing_monitor` / `datacenter` / `dc-scheduler` / `dreamos` / `ranking-trigger` | 云端均有等价常驻/ timer |
| **B 本地独有 / 待补** | `trailing-stop-runner`(**已补云端**) / `signal_scanner`(**已补云端**) / `memory_cleanup`(**已补云端**) / `hermes`(**云端已启用**) / `etl-worker`(**已补云端**) / `screen_*`·`ab_*`·`agent-b-*`(latent) / `com.l3.commandcenter.*`(独立项目×5) | 见 §5 |
| **C 训练/自进化（本次保留本地）** | `continual-training` / `evolution_scheduler` / 按需 `train_neural_sde`·`shadow_rl_trainer`·`distributed_backtest`·`walk_forward` | 改造目标，**不属"前后端服务"** |
| **D 治理/同步** | `dbsync`(10min) / `cognitive-ttl`(04:00) / `cognitive_mcp_server` | 本地→远端上行同步 |

**本地监听端口**：前端 3001(Vite preview)·3002(next dev)·3456(product-hub 本地)；后端 8000-8003·8093·8094·8095·8096·8097·8125·8765·8770·8771·9094·3847/3848。

---

## 4. 停服影响面矩阵

| 链路 | 方向 | 停本地后 | 对远端影响 |
|---|---|---|---|
| 远端服务自身运行 | — | 不受影响 | **无**（远端自足） |
| 认知库聚合（dbsync） | 本地→远端上行 | 停（无新本地数据） | 无（远端仍自写） |
| 认知库下行合并 | 远端→本地 | 停 | 无 |
| gene_data 双向 merge | 双向 | 停 | 无（远端权威基因库继续自演化） |
| 本地前端 3001/3002 | — | 停 | 无（远端 3001 独立服务） |
| 本地后端 8770/8771/8765/8093-8096/9094 | — | 停 | 无（远端同端口同名服务在线） |
| 双写分叉风险 | — | **消除** | 风险下降 |

---

## 5. 前置条件与红线（停服前需处理）

1. ~~**`etl-worker`（7-产物中台，本地独有）** — 云端未部署~~ → ✅ **已于 2026-10-14 补齐云端**（`phase10/10-deploy-etl-worker.sh`：`events/{dreamos,dsh,frontend,hub}` 数据源 + venv `psycopg2-binary 2.9.13` + 幂等建 observability 三表 + `etl-worker.service`（`--daemon --interval 60`）+ product-hub drop-in 对齐 `WORKBUDDY_EVENTS_ROOT`）。
   验收证据：部署脚本内**冒烟前置**通过（DSN 去 Prisma 专有 `?schema=` 后 psycopg2 连通）；全链路实测用临时 `EVENTS_ROOT` fixtures 跑单次 ETL → `dreamos_sessions/spans/dsh_subagent_calls` 各落 1 行（session 由 start/end upsert 合并为 1 行 `completed`，`total_nodes=3`）；验收后 DDL 数据与 `/tmp` fixtures 均已清理，三表计数归 0。当前 `etl-worker.service` active，`product-hub` 存活（3001/3456 返回 307）。**注**：云端 `events/` 数据源尚无真实生产者落盘（远端 `event_writer` 默认根 = `/home/luke/dreambuddy/events`），daemon 现为「空转待数据」状态。
2. **不宜误伤项**（不属"dreambuddy 前后端服务"）：
   - `com.l3.commandcenter.*`（5 个）—— L3 Command Center，**独立项目**；
   - `com.ft_userdata.web_server` / `ft_userdata` 相关 —— 独立目录；
   - 组 C 训练链 —— 本次"本地转训练"目标，**应保留**。
3. **停服顺序建议**：停服前先手动跑一次 `08-local-mirror.sh`，把本地独有认知行一次性上行收口，再停服（避免本地独有行滞留）。
4. `dbsync` 停服后若继续定时跑会空跑（无副作用）；可一并暂停。

---

## 6. 建议动作（分层，非一次性全停）

| 批次 | 内容 | 风险 |
|---|---|---|
| 第一批（安全） | 组 A 全部 + 本地前端预览 `3001`/`3002` | 云端已覆盖，低 |
| 第二批（确认后） | `ml_trade_service` 各端口(8092/8093/8094) + `fundamental_research_sync`(9094) | 与远端 m25/m26/m27/m28/fundamental 对齐冗余 |
| 第三批（独立决策） | `L3 commandcenter`（`etl-worker` 已于 2026-10-14 补齐云端，可随第一批停本地） | 见 §5 |
| **保留** | 组 C 训练链 + 组 D 同步/认知 | 改造目标，不应停 |

---

## 附录：核对命令（可复现）

```bash
# 远端服务/端口/反向依赖
ssh dreambuddy-remote 'systemctl list-units --type=service --state=running --no-pager | grep -iE "dreambuddy|v15|yijing|cognitive|dreamos|m2[0-9]|fundamental|product|hermes|trailing|signal"; \
  systemctl list-timers --all --no-pager; sudo grep -rE "proxy_pass" /etc/nginx/sites-available/dreambuddy; ss -tlnp'
# 本地服务/端口
for f in ~/Library/LaunchAgents/*.plist; do python3 -c "import plistlib,sys;print(plistlib.load(open(sys.argv[1],'rb')).get('Label'))" "$f"; done
lsof -nP -iTCP -sTCP:LISTEN
# 代码一致性
git rev-parse --abbrev-ref HEAD; git log --oneline -1; git rev-list --left-right --count origin/main...HEAD
ssh dreambuddy-remote 'cd /home/luke/dreambuddy && git rev-parse --abbrev-ref HEAD && git log --oneline -1'
```

---

## 7. 待用户决策

1. 是否按 §6 分层暂停本地前后端服务（并保留训练链）？
2. ✅ ~~`etl-worker`（本地独有）如何处置：补云端 / 废弃 / 保留？~~ → 已裁定**补云端并落地**（2026-10-14 phase10，见 §5）。
3. 停服前是否先执行一次 `dbsync` 上行收口？
