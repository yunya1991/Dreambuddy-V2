# 经典指标系统

> DreamBuddy-V2 核心交易决策引擎，基于 16 层信号体系的多策略信号生成与执行系统。

> **版本**: v1.0 | **更新日期**: 2026-08-02

---

## 概述

经典指标系统（Classic Indicator System）是 DreamBuddy-V2 的核心交易决策引擎，基于传统技术指标（RSI、MACD、布林带等）构建多策略信号生成与执行系统。它在 DreamBuddy-V2 三层架构中归属于能力层 C_domain（经典量化），向上为应用层提供交易信号，向下与通用风控模块（13）、三屏趋势系统（12）联动。

核心能力包括：16 层信号体系、机器学习模型集成、基本面分析整合、ClassicExitSystem 四层优先级退出、自动化交易执行、前端监控面板。

---

## 目录结构

```
10-经典指标系统/
├── docs/                    # 技术文档
│   ├── ENGINEERING_INDEX.md # 工程索引 v1.1
│   ├── TECHNICAL_DESIGN.md  # 技术设计 v2.0
│   ├── API_SPEC.md          # 接口规格 v1.1
│   ├── CHANGELOG.md         # 变更日志 v1.1
│   └── archive/             # 历史归档
├── talib/                   # 技术指标封装
├── models/                  # ML 模型文件
├── frontend/                # React 前端监控面板
├── agent_client/            # Tauri 桌面客户端
├── skills/                  # 技能定义（catalog/contracts/playbooks/routing）
├── ops/                     # 运维部署（launchd/systemd/cron/nanoclaw）
├── tools/                   # 工具脚本
├── user_data/               # 用户数据与配置
├── ml_trade_service.py      # 主服务入口（端口 8092）
├── classic_exit_system.py   # 退出系统
├── carry_service.py         # 套利服务
└── requirements.txt
```

---

## 快速开始

### 1. 环境要求

- Python 3.9+
- Node.js 18+（前端面板）
- 依赖：`pip install -r requirements.txt`

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env 填入 API 密钥、数据库连接、风控参数等
```

### 3. 运行主服务

```bash
python ml_trade_service.py
# 默认监听 http://localhost:8092
```

### 4. 启动退出系统（可选）

```bash
python classic_exit_system.py
```

---

## 核心功能

| 功能 | 说明 | 入口 |
|------|------|------|
| 16 层信号生成 | 多指标多周期信号融合 | `ml_trade_service.py` → `_decision_entry_impl()` |
| ClassicExitSystem | 四层优先级退出（ATR/趋势/指标/止损） | `classic_exit_system.py` → `ClassicExitSystem` |
| 套利服务 | 跨期/跨品种套利 | `carry_service.py` |
| ML 模型集成 | 委员会投票 + XGBoost | `models/committee_meta.xgb` |
| 前端监控面板 | 信号/持仓/PnL 实时监控 | `frontend/` |

---

## 配置说明

| 配置项 | 位置 | 说明 |
|--------|------|------|
| API 密钥 | `.env` | 交易所/数据源凭证 |
| 交易参数 | `user_data/config.json` | 交易对、杠杆、仓位 |
| ML 配置 | `user_data/ml_config.json` | 模型路径、阈值 |
| LLM 趋势 | `user_data/llm_trend.json` | LLM 趋势判断缓存 |

> 完整配置参数索引见 [docs/ENGINEERING_INDEX.md](./docs/ENGINEERING_INDEX.md) §5。

---

## 测试

```bash
python -m pytest tests/ -v
# 或运行根目录测试脚本
python test_talib_fallback.py
python test_signals_dedup.py
```

---

## FAQ

**Q: 主服务端口是多少？**
A: 默认 8092，详见 [docs/API_SPEC.md](./docs/API_SPEC.md)。

**Q: 退出系统如何与 16 号调控系统协作？**
A: ClassicExitSystem 提供四层优先级退出，16 号调控系统通过技术/策略离场适配器调用，详见 [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md)。

---

## 相关文档

- [工程索引](./docs/ENGINEERING_INDEX.md) — 文件级索引 v1.1
- [技术设计](./docs/TECHNICAL_DESIGN.md) — 架构设计 v2.0
- [接口规格](./docs/API_SPEC.md) — API 文档 v1.1
- [变更日志](./docs/CHANGELOG.md) — 版本历史 v1.1
- [一页式操作手册](./docs/一页式操作手册.md) — 快速操作指南
- [项目文档索引](../0-系统文档管理/INDEX.md) — 全项目导航

---

**维护者**: DreamBuddy v2
