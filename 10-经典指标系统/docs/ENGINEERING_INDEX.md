# 经典指标系统 - 工程索引

> **版本**: v1.4 | **更新**: 2026-10-11

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
├── 币安Skill/               # 币安官方技能包（spot/web3）
│   └── binance-skills-hub-main/
├── classic_pipeline/        # 模块化经典流水线（C0-C8 架构）
│   ├── api/                 # 适配层（universe/three_screen/quant/s1_s2_mapper）
│   ├── backtest/            # 回测引擎（engine/blueprint）
│   ├── c1_universe/         # 标的池（universe/blueprint）
│   ├── core/                # 核心运行时（runtime/locks/logging/http/config/utils）
│   ├── data/                # 数据层（adapter/provider）
│   ├── indicators/          # 指标层（momentum/trend/volatility）
│   ├── plan/                # 计划层（generator/blueprint）
│   ├── risk/                # 风控层（gatekeeper/blueprint）
│   ├── signals/             # 信号层（quant_signal/three_screen/blueprint）
│   ├── strategy_factory/    # 策略工厂（gate/pipeline/registry/execution/changeset/blueprint/approval/audit）
│   ├── app.py
│   └── __init__.py
├── frontend/                # React 前端监控面板
│   ├── src/
│   │   ├── components/      # 含 evolution/ 子目录（BcrmParams/Dotplot/RegimeProb 等）
│   │   ├── lib/
│   │   └── pages/
│   └── package.json
├── models/                  # ML 模型文件
│   ├── committee_meta.json
│   ├── committee_meta.xgb
│   └── exit_atr_multiplier_*.json
├── ops/                     # 运维部署
│   ├── cron.d/
│   ├── devtools/            # 开发工具（e2e_approval_brief）
│   ├── launchd/             # install/uninstall 脚本集（8092/prod/pilot/explore/dashboard/fundamental_sync）
│   ├── nanoclaw/            # 技能调度框架（bootstrap/setup/check_boundary 等）
│   ├── systemd/
│   ├── twitter_outbox_sender.py
│   ├── paramopt_bayes_daily.sh
│   ├── fundamental_research_sync.sh
│   └── binance_ingest_hourly.sh
├── skills/                  # 技能定义
│   ├── catalog/
│   ├── contracts/
│   ├── playbooks/
│   ├── routing/
│   └── SKILLS_技术文档规范.md
├── talib/                   # 技术指标封装
│   ├── __init__.py
│   └── abstract.py
├── tests/                   # 流水线单元测试（与根级 test_*.py 区分）
│   ├── test_three_screen.py
│   ├── test_risk_plan.py
│   ├── test_indicators.py
│   ├── test_quant_signal.py
│   ├── test_data_provider.py
│   └── test_backtest.py
├── tools/                   # 工具脚本
│   ├── paramopt_bayes_daily.sh
│   ├── live_btcalts_smoke.py
│   ├── verify_env_policy.py
│   ├── tv_strategy_pipeline.py
│   ├── tri_layer_replay_validate.py
│   ├── tri_layer_replay_after_pipeline.py
│   ├── run_strategy_paramopt_n300_compare.py
│   ├── reconcile_github_strategy_assets.py
│   ├── paramopt_strategy_compare.py
│   ├── paramopt_bayes_validation_cron.py
│   ├── paramopt_bayes_validation.py
│   ├── paramopt_batch_dashboard.py
│   ├── online_replay_stats_viz.py
│   ├── macro_tri_layer_backtest_export_check.py
│   ├── macro_release_acceptance.py
│   ├── fundamental_signal_bridge_check.py
│   ├── fundamental_research_sync.py
│   ├── feature_coverage_chain_check.py
│   ├── exit_regime_defaults_backtest.py
│   ├── ports_check.sh
│   └── llama_cpp_server_openai_compat.sh
├── user_data/               # 用户数据与配置
│   ├── ai_integration/
│   ├── backtest_configs/
│   ├── data/                # 含 hyperliquid/ 与 aggregated/ 行情数据
│   ├── models/
│   ├── pairlists/
│   ├── scripts/             # download_history/multiple_timeframe_compare/extract_params/classify_volatility
│   ├── strategies/          # 策略集（含 classic_10_strategies/、github/ 子目录）
│   ├── backtest_offline_10_strategies.py
│   ├── config_*.json        # 多套配置（含 vol_low/vol_high/short_hyperopt/mock_backtest/freqtrade/backtest_btc）
│   └── llm_trend_5m.json
├── docs/                    # 文档
│   ├── ENGINEERING_INDEX.md # 工程索引（本文档）
│   ├── TECHNICAL_DESIGN.md  # 技术设计文档 v2.0
│   ├── API_SPEC.md          # 接口规格 v1.1
│   ├── CHANGELOG.md         # 变更日志 v1.1
│   ├── 拆分方案-C0-C8模块化架构-v1.0.md  # 流水线拆分方案
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
├── classic_system_server.py # 经典系统 FastAPI 服务端
├── fastapi_compat_shim.py   # FastAPI 兼容垫片
├── classic_exit_system.py   # 退出系统
├── carry_service.py         # 套利服务
├── usercustomize.py         # 用户自定义入口
├── debug_cache.py           # 缓存调试工具
├── multi_system_exit_test.py# 多系统退出测试
├── backtest_strategies.py   # 策略回测入口
├── backtest_all_strategies.py # 全策略回测入口
├── selfcheck_signals_recent_dedup.py # 信号去重自检
├── generate_history.py      # 历史数据生成
├── lite_code_index.py       # 轻量代码索引
├── arena_param_grid_eval.py # Arena 参数网格评估
├── system_backup.sh         # 系统备份脚本
├── system_restore.sh        # 系统恢复脚本
├── test_*.py                # 根级测试套件（见 §7）
└── requirements.txt
```

## 3. 关键文件说明

### 3.1 核心服务

| 文件 | 功能说明 |
|------|----------|
| `ml_trade_service.py` | 主交易服务，信号生成与执行 |
| `classic_system_server.py` | 经典系统 FastAPI 服务端 |
| `fastapi_compat_shim.py` | FastAPI 兼容垫片 |
| `classic_exit_system.py` | 经典退出系统，管理持仓退出逻辑 |
| `carry_service.py` | 套利策略服务 |
| `usercustomize.py` | 用户自定义入口 |
| `debug_cache.py` | 缓存调试工具 |
| `backtest_strategies.py` | 策略回测入口 |
| `backtest_all_strategies.py` | 全策略回测入口 |
| `multi_system_exit_test.py` | 多系统退出测试 |
| `selfcheck_signals_recent_dedup.py` | 信号去重自检 |
| `generate_history.py` | 历史数据生成 |
| `lite_code_index.py` | 轻量代码索引 |
| `arena_param_grid_eval.py` | Arena 参数网格评估 |
| `system_backup.sh` | 系统备份脚本 |
| `system_restore.sh` | 系统恢复脚本 |

### 3.2 技术指标

| 文件 | 功能说明 |
|------|----------|
| `talib/__init__.py` | TA-Lib 封装入口 |
| `talib/abstract.py` | 抽象指标定义 |
| `classic_pipeline/indicators/momentum.py` | 动量指标（RSI/MACD 等） |
| `classic_pipeline/indicators/trend.py` | 趋势指标（均线/ADX 等） |
| `classic_pipeline/indicators/volatility.py` | 波动率指标（布林带/ATR） |

### 3.3 模块化经典流水线（classic_pipeline）

C0-C8 九节点 TDD 迁移产出的模块化流水线，对应 `docs/拆分方案-C0-C8模块化架构-v1.0.md`。

| 模块 | 关键文件 | 功能说明 |
|------|----------|----------|
| 核心 | `core/runtime.py` `core/config.py` `core/http.py` `core/locks.py` `core/logging.py` `core/utils.py` | 运行时/配置/HTTP/锁/日志/工具 |
| 数据层 | `data/adapter.py` `data/provider.py` | 数据适配与供给 |
| 标的池 | `c1_universe/universe.py` `c1_universe/blueprint.py` | 标的池构造 |
| 信号层 | `signals/quant_signal.py` `signals/three_screen.py` `signals/blueprint.py` | 量化信号/三屏信号 |
| 指标层 | `indicators/momentum.py` `indicators/trend.py` `indicators/volatility.py` | 动量/趋势/波动率指标 |
| 计划层 | `plan/generator.py` `plan/blueprint.py` | 交易计划生成 |
| 风控层 | `risk/gatekeeper.py` `risk/blueprint.py` | 风控守门人 |
| 策略工厂 | `strategy_factory/gate.py` `pipeline.py` `registry.py` `execution.py` `changeset.py` `blueprint.py` `approval.py` `audit.py` | 策略注册/执行/变更/审批/审计 |
| 回测 | `backtest/engine.py` `backtest/blueprint.py` | 回测引擎 |
| 适配层 | `api/universe_adapter.py` `api/three_screen_adapter.py` `api/quant_adapter.py` `api/s1_s2_mapper.py` | 外部子系统适配 |
| 入口 | `app.py` `__init__.py` | 流水线应用入口 |

### 3.4 运维部署

| 文件 | 功能说明 |
|------|----------|
| `ops/launchd/` | macOS launchd 配置（含 install/uninstall 脚本集） |
| `ops/systemd/` | Linux systemd 配置 |
| `ops/cron.d/` | Cron 定时任务 |
| `ops/nanoclaw/` | 技能调度框架（bootstrap/setup/check_boundary） |
| `ops/devtools/e2e_approval_brief.py` | 端到端审批简报 |
| `ops/twitter_outbox_sender.py` | Twitter 发件箱发送器 |
| `ops/paramopt_bayes_daily.sh` | 贝叶斯参数优化定时任务 |
| `ops/fundamental_research_sync.sh` | 基本面研究同步 |
| `ops/binance_ingest_hourly.sh` | 币安数据小时级摄入 |

### 3.5 工具脚本

| 文件 | 功能说明 |
|------|----------|
| `tools/paramopt_bayes_daily.sh` | 贝叶斯参数优化 |
| `tools/live_btcalts_smoke.py` | 实时回测烟雾测试 |
| `tools/verify_env_policy.py` | 环境策略验证 |
| `tools/tv_strategy_pipeline.py` | TradingView 策略流水线 |
| `tools/tri_layer_replay_validate.py` | 三层重放验证 |
| `tools/tri_layer_replay_after_pipeline.py` | 流水线后三层重放 |
| `tools/run_strategy_paramopt_n300_compare.py` | N300 参数优化对比 |
| `tools/reconcile_github_strategy_assets.py` | GitHub 策略资产对账 |
| `tools/paramopt_strategy_compare.py` | 参数优化策略对比 |
| `tools/paramopt_bayes_validation.py` | 贝叶斯参数优化验证 |
| `tools/paramopt_bayes_validation_cron.py` | 贝叶斯验证定时任务 |
| `tools/paramopt_batch_dashboard.py` | 参数优化批量看板 |
| `tools/online_replay_stats_viz.py` | 在线重放统计可视化 |
| `tools/macro_tri_layer_backtest_export_check.py` | 宏观三层回测导出检查 |
| `tools/macro_release_acceptance.py` | 宏观发布验收 |
| `tools/fundamental_signal_bridge_check.py` | 基本面信号桥接检查 |
| `tools/fundamental_research_sync.py` | 基本面研究同步 |
| `tools/feature_coverage_chain_check.py` | 特征覆盖链检查 |
| `tools/exit_regime_defaults_backtest.py` | 退出机制默认值回测 |
| `tools/ports_check.sh` | 端口占用检查 |
| `tools/llama_cpp_server_openai_compat.sh` | llama.cpp OpenAI 兼容服务 |

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
| `user_data/config_freqtrade.json` | Freqtrade 配置 |
| `user_data/config_backtest_btc.json` | BTC 回测配置 |
| `user_data/config_vol_low.json` | 低波动配置 |
| `user_data/config_vol_high.json` | 高波动配置 |
| `user_data/config_short_hyperopt.json` | 做空超参配置 |
| `user_data/config_mock_backtest.json` | Mock 回测配置 |
| `user_data/llm_trend_5m.json` | LLM 5 分钟趋势配置 |
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

### 7.1 根级测试文件（test_*.py）

| 文件 | 测试内容 |
|------|----------|
| `test_dual_side_support.py` | 多空双方向支持测试 |
| `test_exit_system_backtest.py` | 退出系统回测测试 |
| `test_gtw_sandbox_smoke.py` | 风控沙箱烟雾测试 |
| `test_signals_dedup.py` | 信号去重测试 |
| `test_talib_fallback.py` | TA-Lib降级测试 |
| `tests_three_chain_eval.py` | 三链评估测试 |
| `test_agent_e2e_acceptance.py` | Agent端到端验收测试 |
| `test_classic_system_server.py` | 经典系统服务端测试 |
| `test_breakout_short_support.py` | 突破做空支持测试 |
| `test_carry_funding_ledger.py` | 套利资金费率账本测试 |
| `test_bt_metrics_exec_risk.py` | 回测指标执行风险测试 |
| `test_arena_feature_diversity.py` | Arena 特征多样性测试 |
| `test_automation_control_plane_orchestrator_skill.py` | 自动化控制面编排技能测试 |
| `test_agent_doc_constraints.py` | Agent 文档约束测试 |
| `test_fundamental_news_brief_cache.py` | 基本面新闻简报缓存测试 |
| `test_fundamental_route_retirement.py` | 基本面路由退役测试 |
| `test_governance_changeset_restart_audit.py` | 治理变更集重启审计测试 |
| `test_live_spot_order_smoke.py` | 实盘现货订单烟雾测试 |
| `test_live_preflight_aster_positions.py` | Aster 持仓预检测试 |
| `test_macro_tri_layer_veto.py` | 宏观三层否决测试 |
| `test_ops_restart.py` | 运维重启测试 |
| `test_post_close_cooldown.py` | 收盘后冷却测试 |
| `test_serving_pipeline_second_approval.py` | 服务流水线二次审批测试 |
| `test_strategy_optimization_rules.py` | 策略优化规则测试 |
| `test_sys_monitor_restart_after_apply.py` | 系统监控应用后重启测试 |
| `test_sys_monitor_feedback_consecutive.py` | 系统监控连续反馈测试 |
| `test_twitter_rr.py` | Twitter 风险回报测试 |
| `test_user_data_dir_resolution.py` | 用户数据目录解析测试 |
| `test_web3_market_digest_automation.py` | Web3 市场摘要自动化测试 |
| `multi_system_exit_test.py` | 多系统退出测试 |

### 7.2 流水线单元测试（tests/）

| 文件 | 测试内容 |
|------|----------|
| `tests/test_three_screen.py` | 三屏信号单元测试 |
| `tests/test_risk_plan.py` | 风控计划单元测试 |
| `tests/test_indicators.py` | 指标计算单元测试 |
| `tests/test_quant_signal.py` | 量化信号单元测试 |
| `tests/test_data_provider.py` | 数据供给器单元测试 |
| `tests/test_backtest.py` | 回测引擎单元测试 |

### 7.3 测试命令

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
| 流水线拆分方案 | `docs/拆分方案-C0-C8模块化架构-v1.0.md` |
| 主服务入口 | `ml_trade_service.py` |
| 经典系统服务端 | `classic_system_server.py` |
| 模块化流水线 | `classic_pipeline/` |
| 退出系统 | `classic_exit_system.py` |
| TA-Lib封装 | `talib/` |
| ML模型 | `models/` |
| 前端监控 | `frontend/` |
| 部署脚本 | `ops/` |
| 工具脚本 | `tools/` |
| 根级测试 | `test_*.py`（见 §7.1） |
| 流水线单元测试 | `tests/`（见 §7.2） |

## 9. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 配置文件过多 | 高 | `user_data/config_*.json` 超过20个配置文件 |
| 前端与后端耦合 | 中 | 前端API调用与后端接口定义不一致 |
| ML模型版本管理缺失 | 高 | 模型文件无版本控制 |
| 缺少统一日志框架 | 中 | 日志分散在多个脚本中 |
| 技能定义与代码同步 | 中 | `skills/` 目录与实际代码存在偏差 |
| 流水线与单体服务并存 | 中 | `classic_pipeline/` 与 `ml_trade_service.py` 并行，迁移未完成 |

---

**文档版本**: v1.4
**最后更新**: 2026-10-11

## 更新记录

- 2026-10-11 v1.3→v1.4 全量补全索引漂移：移除 v1.3 漂移告警占位符；扫描实际目录补录 11 个顶层 Python 文件（classic_system_server/fastapi_compat_shim/usercustomize/debug_cache/backtest_strategies/backtest_all_strategies/multi_system_exit_test/selfcheck_signals_recent_dedup/generate_history/lite_code_index/arena_param_grid_eval）、2 个 shell 脚本（system_backup/system_restore）、完整 `classic_pipeline/` 模块化流水线（11 子模块共 40+ 文件）、`tests/` 单元测试目录（6 文件）、22 个新根级 test_*.py、18 个新 tools/ 脚本、5 个新 ops/ 文件、7 个新配置文件、`docs/拆分方案-C0-C8模块化架构-v1.0.md`、`币安Skill/` 目录。
- 2026-07-31 归档历史技术文档：`技术文档.md`（12414行）已迁移至 `docs/archive/技术文档_历史.md`，权威技术设计以 `docs/TECHNICAL_DESIGN.md` v2.0 为准（DD-006 已关闭）。根目录 8 个散落 .md 文件归入 `docs/` 和 `docs/archive/`（DD-007 已关闭）。
- 2026-07-25 修复索引断链：将失效的 `docs/TECHNICAL_DESIGN.md` 引用修正为实际存在的技术文档（`技术文档2.0.md` 为当前权威、`技术文档.md` 为历史维护版）；同步移除目录结构中不存在的 `README.md` 引用。