# 文档索引

> **更新日期**：2026-11-17（v2.0：新增云端全链路监控目标架构与调研文档）
> **模块定位**：监控告警系统 — 为 Dreambuddy 全链路提供监控、告警与仓位同步能力

> **口径提醒**：云端监控以 [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) 第 10 章为准；第 1–9 章为本地 v1.0 适配器现状（仅覆盖 5 个老系统）。

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 说明 |
|------|------|
| [README.md](./README.md) | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 模块工程索引 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 模块技术设计（v2.0：第 10 章为云端权威口径） |
| [API_SPEC.md](./API_SPEC.md) | 模块接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | 模块变更记录 |

## 调研与决策

| 文档 | 说明 |
|------|------|
| [RESEARCH-全链路监控体系调研-v0.2.md](./RESEARCH-全链路监控体系调研-v0.2.md) | 40/23 链路节点表、SRE/金融监控框架、GitHub 选型、云端实测与 D1–D6 决策 |

## 核心能力

| 模块 | 文件 | 职责 |
|------|------|------|
| 监控核心 | `monitor_core.py` | 系统状态监控与指标采集 |
| 飞书告警 | `feishu_alert.py` | 飞书 Webhook 告警推送 |
| 仓位同步 | `position_sync.py` | 跨系统持仓数据同步 |
| 调度器 | `scheduler.py` | 定时任务调度 |
| 启动脚本 | `start_monitor.sh` | 监控服务启动入口 |

## 子目录

- `adapters/` — 外部系统适配器
- `config/` — 配置管理
- `trading-monitor/` — 前端交易监控页面（index.html）
