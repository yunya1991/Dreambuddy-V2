# 分布式计算部署 — 技术设计

> **版本**：v0.2 | **更新日期**：2026-10-11

## 1. 架构设计

分布式协同部署方案：**云端常驻实时交易 + 前端入口**，**线下承担训练/优化等重计算**，通过任务队列 + 心跳实现协同与故障降级。

```
┌─────────────────────────────────────────────────────┐
│                    云端（常驻）                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ V15 盯盘  │  │ 前端入口  │  │ 数据层(PG/Redis) │  │
│  │ 事件驱动  │  │ (Next.js)│  │ MinIO            │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
│       ↓               ↓                              │
│  ┌──────────────────────────────┐                    │
│  │ Nginx 反代 + Let's Encrypt   │                    │
│  └──────────────────────────────┘                    │
└─────────────────────────────────────────────────────┘
         ↕ 任务队列 / 心跳 / 降级切换
┌─────────────────────────────────────────────────────┐
│                    线下（重计算）                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ BCRM训练  │  │ BDSM扫描  │  │ 自进化训练/回测  │  │
│  │ 参数优化  │  │ 战略层优化 │  │                  │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## 2. 部署分阶段

### Phase 1 — 云端核心上线

| 脚本 | 职责 |
|------|------|
| 01-cloud-init.sh | Docker + Node22 + Python3.12 + pnpm + PM2 + ufw 防火墙 |
| docker-compose.yml | PG16 + Redis7 + MinIO（仅 127.0.0.1） |
| 02-deploy-data.sh | 数据层 + MinIO bucket 初始化 |
| 03-deploy-frontend.sh | pnpm build + prisma migrate + PM2 |
| 04-deploy-v15.sh | systemd timer：orchestrator 15min + poll_light 5min |
| 05-nginx-ssl.sh | Nginx 反代 + Let's Encrypt |
| 06-deploy-hermes.sh | Hermes 调度器部署 |
| healthcheck.sh | 健康检查 |
| update.sh | 滚动更新 |

### Phase 2 — 协同增强

| 脚本 | 职责 |
|------|------|
| 01-deploy-yijing-data-server.sh | 易经数据服务部署 |
| 02-deploy-product-hub.sh | 产物中台部署 |
| 03-nginx-update.sh | Nginx 路由更新 |
| 04-rebuild-frontend.sh | 前端重建 |
| deploy.sh | 一键入口 |

## 3. 关键设计决策

### 3.1 数据层隔离
所有数据库（PG/Redis/MinIO）仅监听 127.0.0.1，不暴露公网，通过 Nginx 反代前端 API。

### 3.2 V15 用 systemd timer 非 PM2
V15 是周期性任务（盯盘 + 轻仓执行），用 systemd timer 的 oneshot 模式更合适，避免长驻进程资源浪费。

### 3.3 前端用 PM2 长驻
Next.js 前端是长驻 HTTP 服务，用 PM2 管理。

### 3.4 Nginx 路由
- 前端 3001 → /
- V15 API 8771 → /api/v15/
- 资金管理 API 8770 → /api/capital/

## 4. 环境变量

前端 `.env.production` 需配置：DATABASE_URL、NEXTAUTH_SECRET、AUTH_SECRET、ENCRYPTION_KEY、HUB_BASE_URL 等。
云端 V15 配置通过 `config/.env.local`（V15_DATA_SOURCE=hyperliquid, V15_EXECUTION=paper）。

## 5. 降级策略

| 故障 | 降级 |
|------|------|
| 线下节点失联 | 云端推理使用缓存模型，暂停训练 |
| MinIO 故障 | 回退本地文件存储 |
| PG 故障 | Redis 缓存兜底，告警 |
