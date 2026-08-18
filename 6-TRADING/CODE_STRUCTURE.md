# 6-TRADING 代码结构索引 v2.0

> **创建日期**: 2026-05-15
> **更新日期**: 2026-05-27
> **用途**: 工程代码索引、关键路径速查

---

## 一、目录结构

```
6-TRADING/
├── bridge/                    # Bridge API服务（端口3847）
│   ├── api/                   # API端点（9个模块）
│   │   ├── dream_api_server.py       # 主服务器
│   │   ├── trade_exec_api.py         # 交易执行（含余额查询）
│   │   ├── market_data_api.py        # 行情数据
│   │   ├── skill_router_api.py       # SKILL路由
│   │   ├── intent_router_api.py      # 意图识别路由
│   │   ├── bridge_management_api.py  # Bridge管理
│   │   ├── monitoring.py             # 监控
│   │   ├── realtime_api.py           # 实时数据
│   │   └── websocket_manager.py      # WebSocket
│   ├── utils/                  # 工具函数
│   ├── requirements.txt        # Python依赖
│   └── run_server.py           # 启动入口
│
├── scripts/                   # 核心脚本（18个）
│   ├── backtest_strategy.py         # 马丁策略定义（v2.0）
│   ├── backtest_engine.py           # 回测引擎（v2.0，200U资金）
│   ├── backtest_data_fetcher.py     # 数据获取
│   ├── backtest_report.py           # 回测报告生成
│   ├── mailbox_scanner.py           # 6-TRADING邮箱扫描器
│   ├── dream_strategy_pipeline.py   # 策略流水线（88KB）
│   ├── master_strategy_retriever.py # 大师策略检索（42KB）
│   ├── a2_first_principles_v2.6_auto.py  # A2第一性原理
│   ├── a4_validation_executor.py    # A4战术验证
│   ├── a5_guards.py                 # A5门禁
│   ├── dream_trade_exec.py          # 交易执行
│   ├── dream_stop_loss_monitor.py   # 止损监控（v1.1 已修复硬编码凭证）
│   ├── okx_cli.py                   # OKX CLI封装（v1.3.4）
│   ├── okx_unified_toolkit.py       # OKX统一工具包（37KB）
│   ├── stress_test.py               # 压力测试
│   ├── a1_research.py               # A1调研
│   ├── sync_from_44304.sh           # 同步44304
│   └── sync_frontend.sh             # 同步3-FRONTEND
│
├── skills/                    # 项目级SKILL（24个）
│   ├── dream-systematic-trading/   # ★ 三屏交易总入口SKILL
│   ├── dream-screen3-third/         # ★ 第三屏实时执行层（v1.1）
│   ├── dream-doc-sync-gate/         # ★ 文档同步门禁（PR提交前检查）
│   ├── dream-contradiction-theory/  # A0
│   ├── dream-strategy-research/     # A1
│   ├── dream-first-principles/      # A2
│   ├── dream-tactical-validator/    # A4
│   ├── dream-tactical-executor/     # A5
│   ├── dream-intelligence-monitor/  # A6
│   ├── A7-practice-theory/          # A7
│   ├── A8-theory-practice-verification/  # A8
│   ├── dream-exit-skill-v2/         # A9
│   ├── master-seminar/              # A3
│   ├── dream-regime-detector/       # Regime检测
│   ├── dream-signal-scoring-spec/   # 信号评分
│   ├── dream-risk-position-sizing/  # 仓位管理
│   ├── dream-pretrade-gatekeeper/   # 交易前门禁
│   ├── dream-strategy-parser/       # 策略解析
│   ├── dream-strategy-designer/     # 策略设计
│   ├── dream-data-analysis/         # 数据分析
│   ├── dream-knowledge/             # 知识库
│   ├── dream-oneirology/            # 做梦部
│   ├── dream-bailian-integration/   # 百炼集成
│   └── learning-episode-writer/     # Episode记录
│
├── data/                      # 数据目录
│   ├── backtest/              # 回测数据（BTC-USDT-SWAP 1D CSV）
│   ├── episodes/              # 交易Episode记录（11个JSON）
│   └── reports/               # 分析报告（4个MD）
│
├── reports/                   # 回测报告
│   ├── backtest_result_v2.json      # 200U回测结果
│   └── backtest_v2_10k.json         # 10kU回测结果
│
├── sessions/                  # 交易会话归档（每次研究一个文件夹）
│   ├── README.md              # 命名规范：{YYYYMMDD}-{SYMBOL}-{TRIGGER}/
│   └── _template/             # 会话目录模板
│       ├── meta.json          # 会话状态机（created→monitoring→closed）
│       ├── team-a/            # Team A 研究产物（screen1/ screen2/）
│       ├── team-b/            # Team B 执行日志（a4/a5/a6/a7/a9）
│       ├── gate-c/            # Gate C 门禁结果
│       └── review/            # A8 复盘
│
├── docs/                      # 架构与规范文档（12个）
│   ├── ARCHITECTURE_DESIGN_v2.0.md       # 架构设计（120KB）
│   ├── ARCHITECTURE_DIAGRAM_v2.0.svg     # 架构图
│   ├── CLAUDE_CODE_COLLAB_PLAN.md        # ★ Claude Code 协作方案（v1.0）
│   ├── ARTIFACT_STORAGE_GUIDE.md         # ★ 产物存储规范（v1.0，Sessions方案）
│   ├── TRADING_WORKFLOW_SPEC_v1.md       # 工作流规范（v1.1）
│   ├── BRIDGE_ARCHITECTURE_v1.0.md       # Bridge架构
│   ├── A0_A9_SKILL_COVERAGE_v1.0.md     # SKILL覆盖
│   ├── ARCHITECTURE_REVIEW_v1.0.md       # 架构评审
│   ├── GAP_ANALYSIS_v1.0.md             # GAP分析
│   ├── dream-systematic-trading-SKILL-design.md
│   └── dream-systematic-trading-SKILL-research-report.md
│
├── automation/                # 自动化脚本
│   └── a2_automation_prompt_v2.6.1.md
│
├── config/                    # 配置文件
│   └── strategy_library.yaml  # 策略库（v2.2）
│
├── .workbuddy/memory/         # 工作记忆
│   ├── MEMORY.md              # 核心长期记忆
│   ├── 2026-05-15.md          # 日志
│   └── 2026-05-16.md          # 日志
│
├── DOC_INDEX.md               # ★ 文档总入口
├── FAQ.md                     # 常见问题（20条）
├── CODE_STRUCTURE.md          # 本文档
├── TRADING_SYSTEM.md          # 交易系统完整设计（v2.2）
├── A_SERIES_DETAIL.md         # A0-A9详解
├── README.md                  # 系统概述
└── API_CONFIG_GUIDE.md        # API配置指南
```

---

## 二、关键路径速查

### 数据路径

| 路径 | 说明 |
|:-----|:-----|
| `data/backtest/BTC_USDT_SWAP_1D_20250101_20260516.csv` | BTC日线回测数据（136MB） |
| `data/episodes/*.json` | 交易Episode记录 |
| `reports/backtest_result_v2.json` | 200U回测结果 |
| `reports/backtest_v2_10k.json` | 10kU回测结果 |

### 配置路径

| 路径 | 说明 |
|:-----|:-----|
| `config/strategy_library.yaml` | 策略库（v2.2） |
| `~/.workbuddy/6-trading-env.sh` | 环境变量（TAVILY/OKX） |
| `dream_gateway.db` | 前端SQLite数据库 |

### 产物存储路径

| 路径 | 说明 |
|:-----|:-----|
| `sessions/ACTIVE_SESSION.json` | ★ 当前活跃会话指针 |
| `sessions/{YYYYMMDD}-{SYMBOL}-{TRIGGER}/` | 每次交易会话目录 |
| `sessions/{id}/team-a/screen1/` | 第一屏研究产物 |
| `sessions/{id}/team-a/screen2/` | 第二屏预设产物 |
| `sessions/{id}/team-b/` | 执行日志/仓位状态 |
| `~/.workbuddy/workbuddy.db` | 自动化存储（SQLite） |

### 外部项目路径

| 路径 | 说明 |
|:-----|:-----|
| `../3-FRONTEND/dream-universal-gateway/` | Next.js前端（端口3000） |
| `~/.workbuddy/skills/` | 用户级SKILL |
| `~/.workbuddy/skills/boss-secretary/` | 秘书部（邮箱管理） |
| `~/.workbuddy/skills/dream-constitution/` | 系统宪法 |

---

## 三、版本信息

| 组件 | 版本 | 说明 |
|:-----|:-----|:-----|
| 策略引擎 | v2.0 | 固定20%止损+三级ATR止盈+取消WAIT |
| 回测引擎 | v2.0 | 200U初始资金，与10kU线性缩放 |
| Bridge API | v1.3.4 | OKX CLI封装 |
| 策略库 | v2.2 | strategy_library.yaml |
| 前端 | Next.js | 端口3000 |
| 邮箱扫描器 | v1.0 | 每小时扫描 |
| 工作流规范 | v1.1 | TRADING_WORKFLOW_SPEC（Sessions方案替代旧邮箱） |
| 产物存储规范 | v1.0 | ARTIFACT_STORAGE_GUIDE（Sessions分类+索引） |
| dream-doc-sync-gate SKILL | v1.0 | 文档同步门禁（PR前检查） |
| dream_stop_loss_monitor | v1.1 | 凭证改用 env vars/~/.okx/config.toml |
| dream-screen3-third SKILL | v1.1 | 第三屏执行层完整定义 |
| Claude Code 协作方案 | v1.0 | docs/CLAUDE_CODE_COLLAB_PLAN.md |

---

*最后更新: 2026-05-27*
