# 7-产物中台

> **版本**: v1.0  
> **更新日期**: 2026-09-30  
> **实现工程**: `dream-product-hub` v0.2.0  
> **技术栈**: Next.js 14 + React 18 + Prisma (SQLite) + Tailwind CSS  
> **开发端口**: 3456

---

## 1. 概述

7-产物中台是 DreamBuddy-V2 的**产物管理与投递中台**总容器，承担三类核心职责：

- **产物管理**：统一索引、组织、检索系统研究沉淀的产物（artifact），构建产物间关系链路与阶段分组
- **进度更新**：通过定时脚本自动检测 Git 状态、运行测试套件、生成监控页面并维护 HTTP 服务自愈
- **投递路由**：以 `ui-map` 独立中台首页为统一出口，将产物数据装配为 view-model，投递至纯渲染壳层

中台采用「总容器 + 实现工程」的双层结构：

- `7-产物中台/` 为总容器与治理文档沉淀区
- `7-产物中台/系统研究索引体系/` 为已归位并可运行的 Next.js 实现工程，承载 `ui-map` 真实实现入口、产物数据源、运营实时数据源、推荐引擎与后台能力
- `ui-map/`、`用户上下文索引系统/`、`策略主线/`、`系统研究链路/`、`系统运营链路/` 为模块预留目录（仅含 `.gitkeep`），真实实现集中在 `系统研究索引体系/app/ui-map/` 与 `系统研究索引体系/lib/`

---

## 2. 目录结构

```
7-产物中台/
├── README.md                         # 本文件
├── docs/                             # 治理文档与标准文档
│   ├── ENGINEERING_INDEX.md          # 工程索引
│   ├── TECHNICAL_DESIGN.md           # 技术设计
│   ├── API_SPEC.md                   # API 规格说明
│   ├── CHANGELOG.md                  # 变更记录
│   ├── FAQ.md                        # 常见问题
│   └── superpowers/                  # 正式 spec / plan / contracts
├── 系统研究索引体系/                   # Next.js 实现工程（可运行）
│   ├── app/
│   │   ├── ui-map/                   # 中台首页装配与渲染（真实入口）
│   │   ├── chain/                    # A 系列三环驾驶舱（summary-only）
│   │   ├── admin/                    # 后台管理页面
│   │   ├── api/                      # HTTP API 路由
│   │   ├── org/                      # 组织树
│   │   ├── meeting/                  # 会议
│   │   └── recommendation-engine/    # 推荐引擎页面
│   ├── lib/                          # 数据源 / adapter / 标准对象
│   ├── prisma/                       # 数据库 schema
│   ├── scripts/                      # 压力测试与维护脚本
│   └── package.json
├── ui-map/                           # 预留目录（占位）
├── 用户上下文索引系统/                 # 预留目录（占位）
├── 策略主线/                          # 预留目录（占位）
├── 系统研究链路/                      # 预留目录（占位）
├── 系统运营链路/                      # 预留目录（占位）
├── progress_auto_update.py           # 进度自动更新脚本
├── progress-monitor.html             # 监控页面（自动生成）
└── .monitor-backups/                  # 监控页历史备份
```

---

## 3. 快速开始

### 3.1 环境要求

- Node.js 20+
- Python 3.11+
- Prisma CLI（项目内已安装）

### 3.2 启动开发服务器

```bash
cd 系统研究索引体系
npm install
npx prisma migrate deploy    # 初始化 SQLite 数据库
npm run dev                  # 启动 http://localhost:3456
```

### 3.3 常用脚本

| 命令 | 说明 |
|------|------|
| `npm run dev` | 开发服务器（端口 3456） |
| `npm run build` | 生产构建 |
| `npm run start` | 生产启动 |
| `npm run test` | 单元测试（`node --test`） |
| `npm run build:static` | 静态导出（Pagefind 全文检索） |

### 3.4 进度自动更新

```bash
python3 progress_auto_update.py
```

建议通过 crontab 定时运行：

```
*/30 * * * * cd /path/to/dreambuddy-v2/7-产物中台 && python3 progress_auto_update.py >> progress-task.log 2>&1
```

---

## 4. 核心功能

| 功能模块 | 实现位置 | 说明 |
|---------|---------|------|
| 产物索引与检索 | `lib/content.server.ts` / `lib/content.repository.ts` | 扫描 `~/.workbuddy/artifacts`，mtime 双级缓存 |
| 产物关系与阶段分组 | `lib/artifact-relations.ts` | `buildArtifactRelations` / `groupRelationsByPhase` |
| ui-map 中台首页 | `app/ui-map/` | 壳层 + view-model + adapter，真实数据/fixture 双入口降级 |
| A 系列三环驾驶舱 | `app/chain/summary-only.ts` | 基于阶段计数推断活跃环，禁止 fs/log/raw |
| 推荐引擎 | `app/api/recommendation-engine/` + `scripts/recommendation-engine/engine.py` | 研报 → 候选策略 → 回测 → 写入 Prisma |
| 后台管理 | `app/admin/` + `app/api/admin/` | 用户/策略/订单/积分/API 配置/渠道/交易参数 |
| 实时事件流 | `lib/realtime-hub.ts` + `app/api/realtime/stream` | 内存 EventEmitter，SSE 推送 |
| Dream Agent 网关 | `lib/dream-agent-gateway.ts` + `app/api/dream-agent/invoke` | 转发至后端并发布实时事件 |
| 进度监控 | `progress_auto_update.py` | Git 检测 + 测试 + 监控页 + HTTP 自愈 |

---

## 5. 配置说明

### 5.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WORKBUDDY_ARTIFACTS_ROOT` | `~/.workbuddy/artifacts` | 产物文件树根路径 |
| `DATABASE_URL` | — | Prisma SQLite 连接串（必填） |
| `DREAM_AGENT_API_BASE` | `http://127.0.0.1:5001` | Dream Agent 后端地址 |
| `RECOMMENDATION_ENGINE_API_URL` | `http://localhost:3456/api/recommendation-engine/internal` | 推荐引擎内部 API |
| `NEXT_PUBLIC_STATIC_EXPORT` | — | 设为 `true` 启用静态导出 |

### 5.2 进度更新脚本配置（progress_auto_update.py）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `62932` | HTTP 服务端口 |
| `MAX_BACKUPS` | `5` | 监控页最大备份份数 |
| 测试超时 | `180s` | 单个测试文件运行超时 |
| HTTP 重启重试 | `8` 次 | 启动后探测重试次数 |

---

## 6. 相关文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 工程索引 | [docs/ENGINEERING_INDEX.md](docs/ENGINEERING_INDEX.md) | 模块定位、目录地图、配置索引 |
| 技术设计 | [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md) | 架构、算法、数据流、扩展性 |
| API 规格 | [docs/API_SPEC.md](docs/API_SPEC.md) | HTTP 接口签名、参数、示例 |
| 变更记录 | [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本历史 |
| FAQ | [docs/FAQ.md](docs/FAQ.md) | 常见问题 |

---

**文档版本**: v1.0  
**最后更新**: 2026-09-30
