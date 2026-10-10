# 分布式计算部署 — 接口规格

> **版本**：v0.2 | **更新日期**：2026-10-11

## 1. 部署脚本接口

### 1.1 Phase 1 脚本

| 脚本 | 参数 | 说明 |
|------|------|------|
| `01-cloud-init.sh` | 无 | 初始化云端环境（Docker/Node/Python/PM2/ufw） |
| `02-deploy-data.sh` | 无 | 启动 PG/Redis/MinIO，初始化 bucket |
| `03-deploy-frontend.sh` | 无 | 构建并启动前端（PM2） |
| `04-deploy-v15.sh` | 无 | 配置并启动 V15 systemd timer |
| `05-nginx-ssl.sh` | DOMAIN | 配置 Nginx 反代 + SSL |
| `06-deploy-hermes.sh` | 无 | 部署 Hermes 调度器 |
| `deploy.sh` | 无 | Phase 1 一键部署入口 |

### 1.2 Phase 2 脚本

| 脚本 | 说明 |
|------|------|
| `01-deploy-yijing-data-server.sh` | 部署易经数据服务 |
| `02-deploy-product-hub.sh` | 部署产物中台 |
| `03-nginx-update.sh` | 更新 Nginx 路由 |
| `04-rebuild-frontend.sh` | 重建前端 |
| `deploy.sh` | Phase 2 一键部署入口 |

## 2. 服务端口

| 服务 | 端口 | 暴露方式 |
|------|------|---------|
| 前端 Next.js | 3001 | Nginx 反代 / |
| V15 API | 8771 | Nginx 反代 /api/v15/ |
| 资金管理 API | 8770 | Nginx 反代 /api/capital/ |
| PostgreSQL | 5432 | 仅 127.0.0.1 |
| Redis | 6379 | 仅 127.0.0.1 |
| MinIO | 9000/9001 | 仅 127.0.0.1 |

## 3. 健康检查接口

`healthcheck.sh` 检查：
- Docker 容器状态（pg/redis/minio）
- PM2 进程状态（前端）
- systemd timer 状态（V15）
- Nginx 端口监听
- 前端 HTTP 200

## 4. 环境变量规范

`.env.cloud.example` 定义云端环境变量模板，实际 `.env.production` 不入版本控制。

## 5. 日志管理

`logrotate-dreambuddy.conf` 配置日志轮转，覆盖 V15、前端、Hermes 等服务日志。
