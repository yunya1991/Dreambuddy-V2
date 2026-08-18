# 6-TRADING 文档索引

> **版本**: v2.1
> **日期**: 2026-05-27
> **定位**: 项目文档总入口，四大文档体系导航

---

## 文档体系总览

| 体系 | 核心文档 | 说明 |
|:-----|:---------|:-----|
| **交易系统SKILL** | `skills/dream-systematic-trading/SKILL.md` | 三屏交易+马丁策略完整定义 |
| **工作流程与规范** | `docs/TRADING_WORKFLOW_SPEC_v1.md` | 策略流程规范+自动化体系 |
| **工程索引与FAQ** | 本文档 + `FAQ.md` + `CODE_STRUCTURE.md` | 工程路径索引+常见问题 |
| **交易系统记忆与优化** | `.workbuddy/memory/MEMORY.md` | 长期记忆+策略优化记录 |

---

## 一、交易系统SKILL

### 1.1 核心交易SKILL (24个)

| SKILL | A系 | 路径 | 职责 |
|:------|:----|:-----|:-----|
| dream-systematic-trading | - | `skills/dream-systematic-trading/` | **三屏交易总入口SKILL** |
| dream-screen3-third | - | `skills/dream-screen3-third/` | **第三屏实时执行层（A7→A4→GateC→A5→A6→A9）** |
| dream-doc-sync-gate | - | `skills/dream-doc-sync-gate/` | **文档同步门禁（PR提交/合并前检查文档一致性）** |
| dream-contradiction-theory | A0 | `skills/dream-contradiction-theory/` | 矛盾分析（矛盾论+孙子兵法+战争论） |
| dream-strategy-research | A1 | `skills/dream-strategy-research/` | 深度调研（Tavily+OKX+链上） |
| dream-first-principles | A2 | `skills/dream-first-principles/` | 第一性原理（阻力最小+趋势延续） |
| master-seminar | A3 | `skills/master-seminar/` | 大师研讨（10位大师分阵营辩论） |
| dream-tactical-validator | A4 | `skills/dream-tactical-validator/` | 战术验证（三层索引+委托落地） |
| dream-tactical-executor | A5 | `skills/dream-tactical-executor/` | 决策执行（综合判断+OKX下单） |
| dream-intelligence-monitor | A6 | `skills/dream-intelligence-monitor/` | 情报监控（实时雷达+异常检测） |
| A7-practice-theory | A7 | `skills/A7-practice-theory/` | 实践论门禁（理论vs实践一致性） |
| A8-theory-practice-verification | A8 | `skills/A8-theory-practice-verification/` | 知行合一验证（自我批评+系统进化） |
| dream-exit-skill-v2 | A9 | `skills/dream-exit-skill-v2/` | 离场决策（四层离场+21事件库） |

### 1.2 辅助SKILL

| SKILL | 路径 | 职责 |
|:------|:-----|:-----|
| dream-regime-detector | `skills/dream-regime-detector/` | 市场状态检测（7种Regime） |
| dream-signal-scoring-spec | `skills/dream-signal-scoring-spec/` | 信号评分标准化 |
| dream-risk-position-sizing | `skills/dream-risk-position-sizing/` | 仓位管理与风险预算 |
| dream-pretrade-gatekeeper | `skills/dream-pretrade-gatekeeper/` | 交易前门禁 |
| dream-strategy-parser | `skills/dream-strategy-parser/` | 策略解析（strategy_library.yaml） |
| dream-strategy-designer | `skills/dream-strategy-designer/` | 策略设计 |
| dream-data-analysis | `skills/dream-data-analysis/` | 数据分析与趋势图 |
| dream-knowledge | `skills/dream-knowledge/` | 知识库管理 |
| dream-oneirology | `skills/dream-oneirology/` | 做梦部（潜意识分析） |
| dream-bailian-integration | `skills/dream-bailian-integration/` | 百炼API集成 |
| learning-episode-writer | `skills/learning-episode-writer/` | 学习Episode记录 |

### 1.3 用户级SKILL（`~/.workbuddy/skills/`）

| SKILL | 职责 |
|:------|:-----|
| dream-constitution | 系统宪法（最高指导） |
| dream-multiSkill | 交易指挥官（OKX Agent Trade Kit） |
| boss-secretary | 秘书部（6-TRADING邮箱管理） |
| dream-tactical-validator | A4验证（用户级） |
| dream-tactical-executor | A5执行（用户级） |
| 其他A系列SKILL | 用户级独立部署 |

---

## 二、工作流程与规范

| 文档 | 路径 | 版本 | 说明 |
|:-----|:-----|:-----|:-----|
| **Claude Code 协作方案** | `docs/CLAUDE_CODE_COLLAB_PLAN.md` | v1.0 | ★ Team A/B 分工+CronCreate+Session归档+代码化路线 |
| **工作流规范** | `docs/TRADING_WORKFLOW_SPEC_v1.md` | v1.1 | 三屏策略流程+Sessions产物体系+自动化任务（待审核） |
| **产物存储规范** | `docs/ARTIFACT_STORAGE_GUIDE.md` | v1.0 | ★ Sessions目录方案+产物分类+ACTIVE_SESSION索引 |
| **交易系统设计** | `TRADING_SYSTEM.md` | v2.2 | A0-A9完整设计+三屏执行+马丁策略 |
| **A系详解** | `A_SERIES_DETAIL.md` | v1.0 | A0-A9各模块职责说明 |
| **架构设计** | `docs/ARCHITECTURE_DESIGN_v2.0.md` | v2.0 | DreamBuddy系统架构（120KB） |
| **架构图** | `docs/ARCHITECTURE_DIAGRAM_v2.0.svg` | v2.0 | 可视化架构图 |
| **Bridge架构** | `docs/BRIDGE_ARCHITECTURE_v1.0.md` | v1.0 | API层设计 |
| **SKILL覆盖** | `docs/A0_A9_SKILL_COVERAGE_v1.0.md` | v1.0 | A0-A9 SKILL覆盖分析 |
| **SKILL设计** | `docs/dream-systematic-trading-SKILL-design.md` | v1.0 | 系统交易SKILL设计文档 |

---

## 三、工程索引

### 3.1 目录结构

```
6-TRADING/
├── bridge/                    # Bridge API服务（端口3847）
│   ├── api/                   # API端点（9个模块）
│   ├── utils/                 # 工具函数
│   └── run_server.py          # 启动入口
├── scripts/                   # 核心脚本（18个）
│   ├── backtest_*.py          # 回测引擎（v2.0）
│   ├── mailbox_scanner.py     # 邮箱扫描器
│   ├── dream_strategy_pipeline.py  # 策略流水线
│   ├── okx_cli.py / okx_unified_toolkit.py  # OKX工具
│   └── a*_*.py               # A系列脚本
├── skills/                    # 项目级SKILL（24个）
├── sessions/                  # ★ 交易会话归档
│   ├── README.md              # 命名规范：{YYYYMMDD}-{SYMBOL}-{TRIGGER}/
│   └── _template/             # 会话目录模板（meta.json + team-a/b/ + gate-c/ + review/）
├── data/                      # 数据目录
│   ├── backtest/              # 回测数据（BTC-USDT-SWAP 1D）
│   ├── episodes/              # 交易Episode记录（11个）
│   └── reports/               # 分析报告
├── reports/                   # 回测报告
│   ├── backtest_result_v2.json    # 200U回测结果
│   └── backtest_v2_10k.json       # 10kU回测结果
├── docs/                      # 架构与规范文档（12个）
├── automation/                # 自动化脚本
├── config/                    # 配置文件
│   └── strategy_library.yaml  # 策略库（v2.2）
└── .workbuddy/memory/         # 工作记忆
```

### 3.2 核心脚本索引

| 脚本 | 功能 | 版本 | 对应A系 |
|:-----|:-----|:-----|:---------|
| `scripts/backtest_strategy.py` | 马丁策略定义（v2.0修正） | v2.0 | 全流程 |
| `scripts/backtest_engine.py` | 回测引擎（200U资金） | v2.0 | 全流程 |
| `scripts/backtest_data_fetcher.py` | 数据获取 | v1.0 | 数据层 |
| `scripts/mailbox_scanner.py` | 6-TRADING邮箱扫描器 | v1.0 | 自动化 |
| `scripts/dream_strategy_pipeline.py` | 策略流水线（88KB） | v2.6 | A3 |
| `scripts/a2_first_principles_v2.6_auto.py` | 第一性原理自动化 | v2.6 | A2 |
| `scripts/a4_validation_executor.py` | 战术验证执行 | v1.0 | A4 |
| `scripts/okx_cli.py` | OKX CLI封装 | v1.3.4 | 执行层 |
| `scripts/okx_unified_toolkit.py` | OKX统一工具包 | v1.0 | 执行层 |
| `scripts/dream_stop_loss_monitor.py` | 止损监控（凭证已安全化） | v1.1 | A9 |

### 3.3 Bridge API端点

| 端点 | 文件 | 功能 |
|:-----|:-----|:-----|
| `GET /health` | `api/dream_api_server.py` | 健康检查 |
| `POST /api/config/okx` | `api/trade_exec_api.py` | OKX API配置 |
| `GET /api/trade/balance` | `api/trade_exec_api.py` | 获取账户余额 |
| `GET /api/market/*` | `api/market_data_api.py` | 行情数据 |
| `POST /api/trade/*` | `api/trade_exec_api.py` | 交易执行 |
| `GET /api/skill/*` | `api/skill_router_api.py` | SKILL路由 |
| `WS /ws/*` | `api/websocket_manager.py` | WebSocket连接 |

### 3.4 自动化任务（5个）

| 任务 | ID | 频率 | 说明 |
|:-----|:---|:-----|:-----|
| 第一屏-周线分析 | TBD（待 CronCreate 注册） | 每周日 20:00 | 周线方向+策略选择（先于周一开盘） |
| 第二屏-日线预设 | TBD（待 CronCreate 注册） | 每工作日 07:30 | 日线预设+三大预设价位表 |
| Team B 状态检查 | TBD（待 CronCreate 注册） | 每工作日 09:00 | 持仓监控/入场执行 |
| Process D 复盘 | TBD（待 CronCreate 注册） | 每周一 06:00 | A8 复盘+改进提案 |
| 交易工作流监控 | `automation-1778908570394` | 每4h | 监控自动化运行状态 |

### 3.5 产物存储体系（Sessions 方案）

> 旧邮箱方案 `~/.workbuddy/boss-secretary/` 已废弃。产物统一存入 `sessions/`，详见 **`docs/ARTIFACT_STORAGE_GUIDE.md`**。

```
sessions/
├── ACTIVE_SESSION.json        # ★ 当前活跃会话指针
├── SESSION_INDEX.json         # 历史会话索引
├── _template/                 # 会话目录模板
│   ├── meta.json
│   ├── team-a/                # 研究产物（Screen1/Screen2）
│   ├── team-b/                # 执行产物（A4/A5/A6/A9）
│   ├── gate-c/                # 门禁产物
│   └── review/                # 复盘产物（A8）
└── {YYYYMMDD}-{SYMBOL}-{TRIGGER}/   # 每次交易会话
```

---

## 四、交易系统记忆与优化

| 文档 | 路径 | 说明 |
|:-----|:-----|:-----|
| **核心记忆** | `.workbuddy/memory/MEMORY.md` | 长期记忆（v2.7） |
| **今日日志** | `.workbuddy/memory/2026-05-16.md` | 当日工作记录 |
| **回测报告(200U)** | `reports/backtest_result_v2.json` | v2.0策略回测 |
| **回测报告(10kU)** | `reports/backtest_v2_10k.json` | 大资金验证 |

### 策略优化记录

| 版本 | 日期 | 关键修正 |
|:-----|:-----|:---------|
| v1.0 | 05-14 | 初始三屏体系 |
| v2.0 | 05-16 | WAIT=弱多头LONG(20%); 止损固定20%; 止盈分三级(2x/3x/5x ATR); 取消开仓评分门槛 |
| v2.1 | 05-16 | 加仓阶梯预设基于20日波动率; 最多3次加仓 |
| v2.2 | 05-16 | A9 L1分层执行; 第三屏独立运行; 置信度驱动 |

---

## 五、配置与部署

| 文档 | 路径 | 说明 |
|:-----|:-----|:-----|
| API配置指南 | `API_CONFIG_GUIDE.md` | API Key配置（Tavily/OKX/通知） |
| 策略库 | `config/strategy_library.yaml` | 策略配置（v2.2） |
| 前端项目 | `../3-FRONTEND/dream-universal-gateway/` | Next.js前端（端口3000） |
| 产物中台 | `localhost:3456/dashboard` | 交易面板 |

### 快速启动

```bash
# Bridge API (端口3847)
python bridge/run_server.py

# 前端 (端口3000)
cd ../3-FRONTEND/dream-universal-gateway && pnpm dev

# 同步前端
./scripts/sync_frontend.sh
```

### 环境变量

```bash
# 数据源
TAVILY_API_KEY          # A1调研（Tavily搜索）
OKX_API_KEY             # OKX实盘
OKX_SECRET_KEY
OKX_PASSPHRASE
```

---

## 六、FAQ

详见 [FAQ.md](FAQ.md)

---

*最后更新: 2026-05-27*
