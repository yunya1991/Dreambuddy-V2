# 文档索引

> **更新日期**：2026-10-01（补建 README，对齐 DOC_STANDARD L3 五文档标准）
> **模块定位**：监控告警系统 — 为 Dreambuddy 全链路提供监控、告警与仓位同步能力

## 标准五件套（SSoT，对齐 DOC_STANDARD L3）

| 文档 | 说明 |
|------|------|
| [README.md](./README.md) | 文档索引（本文件） |
| [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 模块工程索引 |
| [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 模块技术设计 |
| [API_SPEC.md](./API_SPEC.md) | 模块接口规格 |
| [CHANGELOG.md](./CHANGELOG.md) | 模块变更记录 |

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
