# 主云端部署 — 当前技术设计

> **版本**：v1.0 | **更新日期**：2026-11-13
> **适用范围**：`43.160.201.117` 单机部署；原分布式协同设计暂停。

## 1. 当前结构

```text
GitHub origin/main（交付代码源，不代表云端已部署）
                         │ 人工核对后更新
                         ▼
云端 43.160.201.117 /home/luke/dreambuddy
├─ systemd：前端、业务 API、轮询/训练/监控服务与 timers
├─ Docker：PostgreSQL、Redis、MinIO
└─ Nginx：公网 80 → 本机前端/业务接口

本地 macOS：开发、评审、按需任务
（不是当前云端的热备或分布式 Worker）
```

当前没有任务队列调度中心、跨端心跳、自动降级接管、多节点 Worker、联邦训练或模型自动回传。Redis 的存在不等于 Redis Streams 分布式调度已启用。

## 2. 主机与目录

| 项 | 当前值 |
|---|---|
| SSH | `dreambuddy-remote`（`43.160.201.117`） |
| OS | Ubuntu 24.04.5 LTS |
| 资源 | 4 vCPU；15GiB RAM；178G 根文件系统 |
| 云端仓库 | `/home/luke/dreambuddy` |
| 仓库属主 | `luke`；涉及仓库写操作时需保持正确身份与权限 |
| Python 环境 | 历史单元使用 `/home/luke/venv-trading`，具体以各 unit 的 ExecStart 为准 |

## 3. 进程与网络边界

- 常驻业务由 `systemd` 管理；周期性任务使用 service + timer。
- 前端当前为 `dreambuddy-frontend.service`，不是 PM2。
- `dreambuddy-pg`、`dreambuddy-redis`、`dreambuddy-minio` 为 Docker 容器。
- 2026-11-13 实测业务端口均绑定 `127.0.0.1`：3001、3456、8093-8096、8765、8770、8771、9094、9000/9001、5432、6379。
- 公网监听仅见 22（SSH）与 80（Nginx）。旧文档中“8765 对公网开放”的描述已不适用于当前状态。
- Nginx 是本机服务的唯一 HTTP 公网入口；具体路由以云端当前配置为准。

## 4. 代码与运行态不是同一状态

1. GitHub 推送只完成代码交付，不自动证明云端已更新。
2. 本次云端 HEAD `d7f94378e2b40d1b8b0924f19bdb7df5194c4cbd` 落后于当时 `origin/main` 的 `5bfdbb5a1aabacbd3387f663b9555ca5a747c5c2`。
3. 云端工作区存在未提交修改，既包括运行态文件，也包括源码文件；不能直接 reset、clean 或盲目 stash。
4. 服务加载的代码、unit 配置和依赖必须分别核对；`active` 只表示进程状态，不代表业务接口健康。
5. 更新前按 [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) 检查，更新后必须验证接口和关键日志。

## 5. 当前更新入口

`phase1/update.sh` 包含 G4/评测门禁、git 更新、前端构建、systemd 重启和健康检查。它不是只读脚本：

- 工作区有修改时会交互询问，并可能 stash/pop。
- 会拉取代码、生成前端生产环境文件、安装依赖、构建并重启服务。
- 当前云端已有源码修改和异常服务，未逐项审查前不得直接执行。
- 本次文档治理未执行该脚本，也未改变云端运行态。

## 6. 当前健康判断原则

必须同时满足：

1. unit 为 active/running，或 oneshot 最近一次退出码为 0；
2. 对应端口与 HTTP 接口按契约返回；
3. 日志无持续崩溃/重启；
4. 数据更新时间与业务语义正常；
5. timer 有有效下次触发时间，且对应 service 最近执行成功。

当前反例：`yijing-polling-trader` 持续重启、`dreambuddy-healthcheck` failed、`v15-capital-api /status` 空响应，均不能仅凭旧清单或端口状态判为健康。
