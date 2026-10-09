# 31-分布式计算部署 — 变更日志

## v0.1 — 2026-10-09

### 新增
- 创建模块目录结构
- 编写 `SPEC-分布式计算协同部署方案.md` v0.1：
  - 整体架构设计（云端实时交易+前端入口 / 线下训练优化）
  - 6 大子交易系统模块分工（V15、BCRM2、BDSM、战略层、自进化、事件驱动）
  - Redis Streams 任务队列 + 心跳机制
  - 故障降级接管策略（线下ML挂→云端简化模型继续交易）
  - 成本估算（¥215/月，预算 ¥300-500 内）
  - 4 阶段实施路线

## v0.3 — 2026-10-09

### 更新
- 确认 D-11~D-13 三项决策：服务器地域（香港/新加坡）、Phase 1 优先级（V15+前端）、Conda 环境策略（2个环境）
- 新增 §12.3 第3轮确认决策表
- 新增 §12.4 Conda 环境策略详解：base（现有）+ dreambuddy-torch（新建）
- 更新 §8 成本：服务器标注香港/新加坡节点
- 更新 §9 Phase 1：明确 V15+前端优先，后续逐步迁移其余子系统
- Worker 环境路由：task_type → 对应 Conda 环境执行

## v0.2 — 2026-10-09

### 更新
- SPEC 升级 v0.2：确认 4 项关键决策（D-7~D-10）
- 新增 §4.4 模型热加载灰度策略（默认关闭，初期直接切换，成熟后手动开启灰度）
- 重写 §5 通信机制：API 中转 + MinIO 直传混合架构
  - 控制面走 FastAPI HTTPS（任务拉取/结果上报/心跳）
  - 数据面走 MinIO presigned URL（模型权重/大文件直传）
  - 新增 API 中转对分布式架构适用性评估（7 维度，结论：适合）
  - 新增 5 个 API 端点设计
- 更新 §8 成本：腾讯云轻量 4C8G ¥150/月（合计 ¥185/月）
- 更新 §10 技术栈：线下用 Conda/Anaconda 环境
- 重写 §12：10 项已确认决策 + 4 项待探讨问题

## v0.5 — 2026-10-09

### 新增
- **Phase 1 部署方案补全**（6 项）：
  - `phase1/06-deploy-hermes.sh` — 飞书网关 (Hermes) 部署脚本（venv + hermes-cli + lark-cli + config.yaml + systemd）
  - `phase1/healthcheck.sh` — 统一健康检查脚本（10 维度：前端/V15 API/timers/Docker/Hermes/Nginx/HTTPS/磁盘/内存，支持 --json 模式）
  - `phase1/logrotate-dreambuddy.conf` — 日志轮转配置（V15/Hermes/PM2/Nginx 日志 daily+14天保留+compress）
  - `phase1/update.sh` — 代码更新脚本（git pull → 前端 pnpm install+build+pm2 restart → V15 API restart → Hermes restart）

### 更新
- `03-deploy-frontend.sh` — 新增 PM2 startup 持久化（`pm2 startup systemd` + `pm2 save`，服务器重启后前端自动恢复）
- `04-deploy-v15.sh` — 新增 V15 API 长驻 systemd 服务：
  - `v15-api.service`（端口 8771，决策信号 API，`run.py api --port 8771`）
  - `v15-capital-api.service`（端口 8770，资金管理 API，`run.py capital_engine api --port 8770`）
- `deploy.sh` — 步骤从 5 步扩展为 7 步（+飞书网关 +日志轮转&健康检查），更新最终验证命令
- `deploy-checklist.md` — 新增 Step 7（Hermes）/ Step 8（logrotate+healthcheck）/ Step 9（最终验收）+ 日常运维章节
- `.env.cloud.example` — 新增 `LARK_APP_ID`/`LARK_APP_SECRET` 飞书凭据变量

## v0.4 — 2026-10-09

### 新增
- **Phase 1 部署脚本全套完成**（9 文件）：
  - `phase1/docker-compose.yml` — PostgreSQL 16 + Redis 7 + MinIO（Docker Compose）
  - `phase1/01-cloud-init.sh` — 云端环境初始化（Docker + Node 22 + Python 3.12 + pnpm + PM2 + ufw）
  - `phase1/02-deploy-data.sh` — 数据层部署 + MinIO bucket 初始化
  - `phase1/03-deploy-frontend.sh` — Next.js 15 前端部署（pnpm build + Prisma migrate + PM2）
  - `phase1/04-deploy-v15.sh` — V15 马丁策略部署（systemd timer: orchestrator 15min + poll_light 5min）
  - `phase1/05-nginx-ssl.sh` — Nginx HTTPS 反代 + Let's Encrypt SSL
  - `phase1/deploy.sh` — 一键部署入口
  - `phase1/.env.cloud.example` — 云端环境变量模板
  - `phase1/deploy-checklist.md` — 部署检查清单 + 常见问题

### 更新
- **前端环境变量补全**：审查 `3.1-FRONTEND/.env.local` 后发现遗漏大量变量
  - `.env.cloud.example` 新增：`ENCRYPTION_KEY`（AES-256-GCM 凭证加密）、`DEEPSEEK_API_KEY`/`DEEPSEEK_MODEL`（LLM 桥接）、`TAVILY_API_KEY`（搜索）、`AUTH_URL`/`AUTH_TRUST_HOST`、5 个外部服务 URL（Bridge/Hub/WorkBuddy/TrendSystem）
  - `03-deploy-frontend.sh` 步骤从 5 步扩展为 6 步：`.env.production` 生成完整变量集 + Prisma seed 初始化
  - 前端依赖的外部服务（Bridge 3847 / Hub 8787 / WorkBuddy 8080 / TrendSystem 8765 / TradingRanking 3456）Phase 1 默认指向 127.0.0.1，后续迁移后更新
  - `deploy-checklist.md` 补全新增必填项和可选服务 URL

### 待办
- [ ] 确认服务器地域（Q-1）→ 已确认 D-11: 香港
- [ ] 补充 TECHNICAL_DESIGN.md（降级算法实现细节）
- [ ] 补充 API_SPEC.md（Scheduler/Worker 接口契约）
- [x] 实施 Phase 1 脚本编写（云端核心上线）
- [x] Phase 1 部署方案补全（PM2持久化+V15 API+Hermes+healthcheck+logrotate+update）
- [ ] Phase 1 实际部署（购买服务器后执行）
- [ ] 实施 Phase 2（任务队列 + 线下 Worker）
