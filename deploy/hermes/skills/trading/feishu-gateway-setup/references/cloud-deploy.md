# 腾讯云 Lighthouse 部署方案

## 架构

```
Ubuntu 22.04 LTS (2C4G)
  ├── Hermes Gateway   → systemd service (开机自启, crash 10s 自动重启)
  ├── group_poller.py  → systemd service (15s 自动重启)
  ├── hermes dashboard → systemd service (:9119, 仅本地监听)
  ├── 7 cron jobs      → Linux crontab
  └── feishu_notify    → Python venv
```

## 部署步骤

```bash
# 1. 克隆（含 deploy/ 脚本）
git clone https://github.com/yunya1991/Dreambuddy-V2.git /home/luke/tmp

# 2. 上传 .env（含 FEISHU_APP_ID/SECRET）
scp .env luke@<云IP>:/home/luke/.hermes/.env

# 3. 一键部署
cd /home/luke/tmp/deploy && sudo bash deploy.sh
```

## 路径迁移

```
Windows                           → Linux
C:\tmp\                           → /home/luke/tmp/
C:\Users\luke.zhang\.hermes\      → /home/luke/.hermes/
cron workdir: C:\tmp              → /home/luke/tmp
```

## Systemd 服务

- `hermes-gateway.service` — Gateway 永活
- `group-poller.service` — 群聊轮询永活（依赖 gateway）
- `hermes-dashboard.service` — Web UI（可选）

## Windows 特有的坑（云上自动消失）

- MSYS bash 路径映射失败 → 原生 bash
- terminal 工具 cd 报错 → 正常工作
- tasklist/netstat 编码乱码 → ps/ss 干净输出
- hermes.exe 路径折腾 → hermes 在 PATH 里
- send_message 工具缺失 → CLI 模式下完整可用
- channel_directory 重启丢失 → 不丢（不重启 OS，且有 deploy 脚本预写入）

## 审批机器人、任务机器人、OKR 机器人

这三个是飞书平台内置的，API 调用后自动推送通知，**不需要手动集成**。
