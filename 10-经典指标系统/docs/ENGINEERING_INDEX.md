# 经典指标系统 - 工程索引

## 1. 概述

经典指标系统（Classic Indicator System）是 DreamBuddy-v2 的核心交易决策引擎，基于传统技术指标（RSI、MACD、布林带等）构建的多策略信号生成与执行系统。

### 1.1 核心定位

| 属性 | 说明 |
|------|------|
| 系统名称 | 经典指标系统 |
| 目录位置 | `10-经典指标系统/` |
| 主入口 | `ml_trade_service.py` |
| 核心模块 | `talib/`、`models/` |
| 依赖系统 | 通用风控模块（13）、三屏趋势系统（12） |

### 1.2 功能概览

- 多策略信号生成（16层信号体系）
- 机器学习模型集成
- 基本面分析整合
- 退出系统管理
- 自动化交易执行
- 前端监控面板

## 2. 目录结构

```
10-经典指标系统/
├── agent_client/            # Tauri 桌面客户端
│   ├── src/
│   ├── src-tauri/
│   └── package.json
├── frontend/                # React 前端监控面板
│   ├── src/
│   │   ├── components/
│   │   ├── lib/
│   │   └── pages/
│   └── package.json
├── models/                  # ML 模型文件
│   ├── committee_meta.json
│   ├── committee_meta.xgb
│   └── exit_atr_multiplier_*.json
├── ops/                     # 运维部署
│   ├── cron.d/
│   ├── launchd/
│   ├── nanoclaw/
│   └── systemd/
├── skills/                  # 技能定义
│   ├── catalog/
│   ├── contracts/
│   ├── playbooks/
│   └── routing/
├── talib/                   # 技术指标封装
│   ├── __init__.py
│   └── abstract.py
├── tools/                   # 工具脚本
│   ├── paramopt_bayes_daily.sh
│   ├── live_btcalts_smoke.py
│   └── ...
├── user_data/               # 用户数据与配置
│   ├── ai_integration/
│   ├── backtest_configs/
│   ├── data/
│   ├── models/
│   └── config_*.json
├── docs/                    # 文档
│   ├── ENGINEERING_INDEX.md # 工程索引（本文档）
│   ├── TECHNICAL_DESIGN.md  # 技术设计文档 v2.0
│   ├── API_SPEC.md          # 接口规格 v1.1
│   ├── CHANGELOG.md         # 变更日志 v1.1
│   ├── 系统运营技术文档.md    # 运营手册
│   ├── 基本面分析文档.md      # 基本面分析参考
│   ├── 策略开发规范.md        # 策略开发规范
│   ├── 集成指南.md           # 系统集成指南
│   ├── 一页式操作手册.md      # 快速操作指南
│   └── archive/             # 历史归档
│       ├── 技术文档_历史.md          # 旧版技术文档（已被 TECHNICAL_DESIGN.md v2.0 替代）
│       ├── 交易AI_Agent_技术文档_历史.md
│       ├── NanoClaw技能协调方案_历史.md
│       └── 新闻分析技能技术文档_历史.md
├── ml_trade_service.py      # 主服务入口
├── classic_exit_system.py   # 退出系统
├── carry_service.py         # 套利服务
└── requirements.txt
```

## 3. 关键文件说明

### 3.1 核心服务

| 文件 | 功能说明 |
|------|----------|
| `ml_trade_service.py` | 主交易服务，信号生成与执行 |
| `classic_exit_system.py` | 经典退出系统，管理持仓退出逻辑 |
| `carry_service.py` | 套利策略服务 |

### 3.2 技术指标

| 文件 | 功能说明 |
|------|----------|
| `talib/__init__.py` | TA-Lib 封装入口 |
| `talib/abstract.py` | 抽象指标定义 |

### 3.3 运维部署

| 文件 | 功能说明 |
|------|----------|
| `ops/launchd/` | macOS launchd 配置 |
| `ops/systemd/` | Linux systemd 配置 |
| `ops/cron.d/` | Cron 定时任务 |
| `ops/nanoclaw/` | 技能调度框架 |

### 3.4 工具脚本

| 文件 | 功能说明 |
|------|----------|
| `tools/paramopt_bayes_daily.sh` | 贝叶斯参数优化 |
| `tools/live_btcalts_smoke.py` | 实时回测烟雾测试 |
| `tools/verify_env_policy.py` | 环境策略验证 |

## 4. 依赖关系

### 4.1 外部依赖

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| pandas | >=1.5.0 | 数据处理 |
| numpy | >=1.21.0 | 数值计算 |
| talib | >=0.4.0 | 技术指标 |
| xgboost | >=1.7.0 | ML模型 |
| scikit-learn | >=1.2.0 | ML工具 |
| requests | >=2.28.0 | HTTP请求 |
| ccxt | >=4.0.0 | 交易所API |

### 4.2 内部依赖

| 系统 | 依赖方式 | 用途 |
|------|----------|------|
| 12-三屏趋势系统 | 桥接调用 | 获取趋势过滤信号 |
| 13-通用风控模块 | 接口调用 | 风控评估 |

## 5. 配置管理

### 5.1 配置文件

| 文件 | 用途 |
|------|------|
| `user_data/config.json` | 主配置文件 |
| `user_data/config_local.json` | 本地开发配置 |
| `user_data/config_test.json` | 测试配置 |
| `user_data/ml_config.json` | ML模型配置 |
| `.env.example` | 环境变量模板 |
| `.env.template` | 环境变量模板 |

### 5.2 环境变量

| 变量 | 说明 |
|------|------|
| EXCHANGE_API_KEY | 交易所API Key |
| EXCHANGE_SECRET | 交易所API Secret |
| LLM_API_KEY | 大模型API Key |
| PORT | 服务端口（默认8092） |

## 6. 部署与运行

### 6.1 启动方式

```bash
# 开发模式
python ml_trade_service.py --config user_data/config_local.json

# 生产模式
python ml_trade_service.py --config user_data/config.json

# 通过launchd部署
bash ops/launchd/install_8092.sh
```

### 6.2 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| ml_trade_service | 8092 | 主交易服务 |
| frontend | 5173 | 前端监控面板 |

## 7. 测试体系

### 7.1 测试文件

| 文件 | 测试内容 |
|------|----------|
| `test_dual_side_support.py` | 多空双方向支持测试 |
| `test_exit_system_backtest.py` | 退出系统回测测试 |
| `test_gtw_sandbox_smoke.py` | 风控沙箱烟雾测试 |
| `test_signals_dedup.py` | 信号去重测试 |
| `test_talib_fallback.py` | TA-Lib降级测试 |
| `tests_three_chain_eval.py` | 三链评估测试 |
| `test_agent_e2e_acceptance.py` | Agent端到端验收测试 |

### 7.2 测试命令

```bash
# 运行所有测试
python -m pytest test_*.py -v

# 运行特定测试
python -m pytest test_exit_system_backtest.py -v
```

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 技术设计文档 | `docs/TECHNICAL_DESIGN.md` |
| 主服务入口 | `ml_trade_service.py` |
| 退出系统 | `classic_exit_system.py` |
| TA-Lib封装 | `talib/` |
| ML模型 | `models/` |
| 前端监控 | `frontend/` |
| 部署脚本 | `ops/` |

## 9. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 配置文件过多 | 高 | `user_data/config_*.json` 超过20个配置文件 |
| 前端与后端耦合 | 中 | 前端API调用与后端接口定义不一致 |
| ML模型版本管理缺失 | 高 | 模型文件无版本控制 |
| 缺少统一日志框架 | 中 | 日志分散在多个脚本中 |
| 技能定义与代码同步 | 中 | `skills/` 目录与实际代码存在偏差 |

---

**文档版本**: v1.2
**最后更新**: 2026-07-31

## 更新记录

- 2026-07-31 归档历史技术文档：`技术文档.md`（12414行）已迁移至 `docs/archive/技术文档_历史.md`，权威技术设计以 `docs/TECHNICAL_DESIGN.md` v2.0 为准（DD-006 已关闭）。根目录 8 个散落 .md 文件归入 `docs/` 和 `docs/archive/`（DD-007 已关闭）。
- 2026-07-25 修复索引断链：将失效的 `docs/TECHNICAL_DESIGN.md` 引用修正为实际存在的技术文档（`技术文档2.0.md` 为当前权威、`技术文档.md` 为历史维护版）；同步移除目录结构中不存在的 `README.md` 引用。