# 主云端部署 — 当前接口规格

> **版本**：v1.0 | **更新日期**：2026-11-13
> **边界**：仅描述 `.117` 当前部署入口和实测本机接口；分布式 Scheduler/Worker API 未启用。

## 1. 部署与运维接口

| 入口 | 行为 | 当前使用约束 |
|---|---|---|
| `ssh dreambuddy-remote` | 登录主云端 `43.160.201.117` | 评审默认只读 |
| `phase1/update.sh` | G4/评测门禁、拉取代码、前端构建、服务重启、健康检查 | 会修改运行态；审查工作区和异常后再用 |
| `systemctl` / `journalctl` | 查询服务、timer 和日志 | 服务重启不属于只读评审 |
| `docker ps` | 查询 PG/Redis/MinIO 容器 | 当前三容器 healthy |

历史 `phase*/deploy.sh`、`phase*/migrate.sh`、`phase*/install.sh` 不是当前通用接口，不得未经复评直接执行。

## 2. 当前本机端口

| 服务 | 端口 | 当前监听范围 | 已知健康接口 |
|---|---:|---|---|
| 主前端 | 3001 | 127.0.0.1 | `/` 实测 307 |
| 产物中台 | 3456 | 127.0.0.1 | 按应用路由检查 |
| M26 策略管理 | 8093 | 127.0.0.1 | `/health` |
| M27 策略治理 | 8094 | 127.0.0.1 | `/health` |
| M25 策略生成 | 8095 | 127.0.0.1 | `/health` |
| M28 信号触发 | 8096 | 127.0.0.1 | `/health` |
| 易经数据服务 | 8765 | 127.0.0.1 | `/` 实测 200 |
| V15 API | 8771 | 127.0.0.1 | `/health` 实测 200 |
| V15 资金 API | 8770 | 127.0.0.1 | `/status` 实测空响应，当前异常 |
| 基本面服务 | 9094 | 127.0.0.1 | 按应用路由检查 |
| PostgreSQL | 5432 | 127.0.0.1 | Docker health |
| Redis | 6379 | 127.0.0.1 | Docker health |
| MinIO | 9000/9001 | 127.0.0.1 | Docker health |

公网入口以 Nginx 80 为准；上述服务不能因旧文档记载而直接开放公网。另实测有 `127.0.0.1:8790` 监听，本次未核实归属，故不纳入服务契约。

## 3. 健康检查契约

不能只看进程或端口，至少组合以下证据：

```bash
systemctl show <unit> -p ActiveState -p SubState -p NRestarts -p ExecMainStatus -p Result
journalctl -u <unit> -n 50 --no-pager
curl --max-time 10 -i http://127.0.0.1:<port><health-path>
systemctl list-timers --all --no-pager
```

- 常驻服务：active/running + 接口正常 + 无持续重启。
- oneshot：inactive/dead 可以是正常静息态，但最近 `Result` 必须 success、退出码为 0。
- timer：必须有 NEXT；没有 NEXT 的单元不能写成“周期运行中”。

## 4. 环境变量与敏感信息

- 实际 `.env*`、凭据和 token 不进入文档或版本控制。
- 文档只记录变量名、路径和用途，不复制值。
- `phase1/update.sh` 会读取 `/home/luke/.config/dreambuddy/.env.cloud` 并生成前端 `.env.production`，执行前需确认该行为符合本次部署范围。
