# 🤖 部署配置 (deploy/)
> **用途**: 系统部署配置，含 Hermes skills/cron/memories、运维脚本、systemd 服务
> **最后更新**: 2026-10-11

## 目录结构

| 目录/文件 | 用途 |
|:---|:---|
| `hermes/skills/` | 预部署技能集（14 个 trading SKILL） |
| `hermes/cron/jobs.json` | 预部署 cron 配置 |
| `hermes/memories/` | 预部署记忆（USER.md、MEMORY.md） |
| `hermes/config.yaml` | Hermes 网关配置 |
| `hermes/SOUL.md` | Hermes Agent 灵魂定义 |
| `hermes/group_poller.py` | 群消息轮询器 |
| `hermes/sitecustomize.py` | Python 站点定制 |
| `hermes/start_gateway.sh` / `start_dashboard.sh` | 网关 / 仪表盘启动脚本 |
| `hermes/channel_directory.json` | 频道目录 |
| `ops/` | 运维：launchd plist、master_daemon.py、install_all_launchd.{sh,py} |
| `ops/state/` | 守护进程状态文件（pid/json） |
| `systemd/` | systemd 服务定义（cognitive-daemon.service） |
| `01-install-deps.sh` ~ `04-hermes-config.sh` | 分步部署脚本 |
| `deploy.sh` | 一键部署入口 |
| `git-sync.sh` / `git-setup-tracking.sh` | Git 同步 / 追踪配置 |
| `hermes-gateway.service` / `hermes-dashboard.service` / `group-poller.service` | systemd 服务单元 |
