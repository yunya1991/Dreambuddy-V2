# 变更日志 — 16-调控系统

> **定位**：记录每次变更的原因、内容、影响范围、验证方式与回滚策略
> **格式**：[版本] - 日期 → 变更类型（新增/修改/修复/删除）
> **版本：** v2.0 | **更新：** 2026-07-25

---

## [v2.0] - 2026-07-25

### 新增 — 工程索引重建 + 接口规格与变更日志补全

- **变更内容**: 重建 `docs/ENGINEERING_INDEX.md` 至 v2.0，对齐 `core/` 实际代码结构（19 个核心 Python 文件）；新建 `docs/API_SPEC.md` v2.0 与本 CHANGELOG
- **影响范围**:
  - `docs/ENGINEERING_INDEX.md`（v2.0 重建，覆盖持仓/数据/SKILL 引擎/分析适配/决策融合/执行反馈/进化闭环/回测/产物投递全链路）
  - `docs/API_SPEC.md`（首版，含 5 章节规范：接口概览 / 认证方式 / 接口详情 / 错误码 / 版本管理）
  - `docs/CHANGELOG.md`（首版，含 Phase 阶段演进 + SKILL 版本矩阵 + 已知技术债）
- **验证方式**:
  - 文档章节与 `core/__init__.py` 实际导出（`fetch_all_positions` / `get_position_summary` / `SkillEngine` / `SkillResult` / `register_skill`）逐一对照
  - 函数签名、参数默认值、返回值字段与源码逐一对照（含 `unified_position_query.py` / `skill_engine.py` / `a9_exit_decision.py` / `exit_executor.py` / `feedback_and_permission.py` / `backtest_framework.py` / `auto_exit_system.py` 等）
  - SKILL 版本矩阵与各适配器 `@register_skill` 装饰器声明对照
- **回滚策略**: 删除两个新增文档；恢复 `docs/ENGINEERING_INDEX.md` 至 v1.0 版本（git 回滚即可）

---

### 新增 — SKILL 版本矩阵归档

- **变更内容**: 显式归档 5 个已注册 SKILL 的版本信息（来源：各适配器 `@register_skill` 装饰器声明）
- **影响范围**: `docs/API_SPEC.md` §5.2、`docs/ENGINEERING_INDEX.md` §5

| SKILL 名称 | 版本 | 注册模块 |
|-----------|------|----------|
| `dream-strategy-research` | 1.7.0 | `core/a1_research_adapter.py` |
| `dream-first-principles` | 2.6.1 | `core/a2_first_principles_adapter.py` |
| `dream-strategy-designer` | 2.7.0 | `core/a3_strategy_adapter.py` |
| `dream-exit-skill-v2` | 2.2.0 | `core/a9_exit_decision.py` |
| `technical-exit-adapter` | 1.0.0 | `core/technical_exit_adapter.py` |

- **验证方式**: `grep -rn "@register_skill" core/` 比对装饰器参数
- **回滚策略**: 无独立回滚需求（信息归档，不修改代码）

---

### 修改 — 文档定位修正

- **变更内容**: 系统定位从「统一持仓离场评估系统」修正为「统一 AI 调控系统」（反映 Phase 3+ 实际覆盖的执行反馈 + 进化闭环 + 回测 + 产物投递全链路）
- **影响范围**: `docs/API_SPEC.md` 头部、`docs/ENGINEERING_INDEX.md` §1
- **验证方式**: 与 `core/` 19 个文件的实际职责对照
- **回滚策略**: 文档头部字符串回退

---

### 已知技术债（如实记录）

#### TD-1: TECHNICAL_DESIGN.md 范围错位

- **问题描述**: `docs/TECHNICAL_DESIGN.md` v1.0（2026-07-12）标题为「统一持仓离场评估系统 技术设计文档」，仅覆盖离场评估子模块（持仓聚合 + A1/A2/A3 + A9 四态），未覆盖系统实际具备的执行反馈 / 进化闭环 / 回测 / 产物投递全链路（共 19 个核心 Python 文件）
- **影响范围**: `docs/TECHNICAL_DESIGN.md`
- **当前处置**: 在 `docs/ENGINEERING_INDEX.md` §9 中明确标注范围错位；`docs/API_SPEC.md` v2.0 已对齐实际代码，可作为代码侧权威索引
- **后续建议**: 将 `TECHNICAL_DESIGN.md` 升级为覆盖完整调控系统的设计文档，或拆分为多个子模块设计文档（不在本次变更范围）
- **验证方式**: 对比 `TECHNICAL_DESIGN.md` 章节与 `ENGINEERING_INDEX.md` §3 文件清单

#### TD-2: auto_exit_system.py 调用不存在的函数

- **问题描述**: `scripts/auto_exit_system.py:183` 调用 `a9_exit_decision.evaluate_position_for_exit(pos, a3_result.data)`，但 `core/a9_exit_decision.py` 中该函数**并不存在**。实际存在的公开函数为 `a9_exit_decision_handler(inputs, engine)`（通过 `@register_skill` 注册为 `dream-exit-skill-v2` v2.2.0）
- **影响范围**: `scripts/auto_exit_system.py` — 运行至步骤 7「A9 宏观离场 + 融合决策」时会抛 `AttributeError: module 'a9_exit_decision' has no attribute 'evaluate_position_for_exit'`
- **当前处置**: 在 `docs/API_SPEC.md` §3.3 与 §3.11.1 标注此已知 Bug；文档如实描述 `a9_exit_decision_handler` 的实际签名与四层决策链
- **后续建议**: 修复 `auto_exit_system.py` 调用方式（应改为构造 `inputs` 字典后通过 `SkillEngine.execute("dream-exit-skill-v2", inputs)` 或直接调用 `a9_exit_decision_handler`），或为 `a9_exit_decision.py` 补充 `evaluate_position_for_exit` 包装函数
- **验证方式**: `python scripts/auto_exit_system.py` 实跑复现；`grep -n "evaluate_position_for_exit" core/a9_exit_decision.py` 应为空

#### TD-3: auto_exit_system.py SKILL 名称与注册名不一致

- **问题描述**: `scripts/auto_exit_system.py` 步骤 3-5 调用 `engine.execute("dream-research-skill-v2", ...)` / `("dream-first-principles-v2", ...)` / `("dream-strategy-designer-v2", ...)`，而实际注册的 SKILL 名称是 `dream-strategy-research` / `dream-first-principles` / `dream-strategy-designer`（无 `-v2` 后缀，且 A1 名称顺序不同）
- **影响范围**: `scripts/auto_exit_system.py` — 步骤 3-5 会因 `not_registered` 降级回退，无法获得真实宏观分析结果
- **当前处置**: `docs/API_SPEC.md` §3.4 与 §5.2 如实记录注册名
- **后续建议**: 修正 `auto_exit_system.py` 中的 SKILL 名称引用，或统一注册名规范
- **验证方式**: `grep -n "register_skill" core/a1_research_adapter.py core/a2_first_principles_adapter.py core/a3_strategy_adapter.py` 比对

---

## 阶段演进历史

> 以下阶段记录依据 `docs/ENGINEERING_INDEX.md` v2.0 §7 阶段规划整理。每阶段含核心模块、关键能力、验证状态。

### [Phase 0 MVP] - 2026-07 初

- **新增**: 技术通路验证版 `unified_position_query.py`（初版）
  - 聚合 6 个交易系统持仓（Agent A/B/C / V15 马丁 / 易经推理 / 三屏趋势）
  - 单系统失败降级容错
  - 进程内 60s 缓存
  - **影响范围**: `core/unified_position_query.py`
  - **验证方式**: 手动调用 `fetch_all_positions()` 检查 6 系统数据完整性
  - **回滚策略**: git 回退至 Phase 0 之前提交
  - **状态**: ✅ 完成

---

### [Phase 1 查询层] - 2026-07 初

- **新增**: 6 系统全覆盖的统一持仓查询层
  - Hyperliquid REST 查询（Agent A/B）
  - memory.json 解析（Agent C，共用 Agent B 账户）
  - OKX state.json + API 双通道（V15 马丁）
  - open_positions/*.json 解析（易经推理）
  - ml_trade_service API 查询（三屏趋势，过渡期架构）
  - 统一数据模型（`_make_position` / `_make_system_result`）
  - 单源 8s 超时控制
  - **影响范围**: `core/unified_position_query.py`
  - **验证方式**: `python core/unified_position_query.py --summary` 输出 6 系统摘要
  - **回滚策略**: git 回退
  - **状态**: ✅ 完成

---

### [Phase 2 分析层升级] - 2026-07 中

- **新增**: SKILL 执行引擎 `core/skill_engine.py`
  - `SkillEngine` 类：注册表 / `execute()` / `load_skill_md()` / `parse_phases()`
  - `@register_skill` 装饰器
  - `SkillResult` / `SkillPhase` 数据类
  - 降级回退机制（未注册 / handler 异常时返回 `fallback_used=True`）
  - **影响范围**: `core/skill_engine.py`、`core/__init__.py`（导出 `SkillEngine` / `SkillResult` / `register_skill`）

- **新增**: A1/A2/A3 宏观分析 SKILL 适配器
  - `a1_research_adapter.py`（`dream-strategy-research` v1.7.0，含 `_build_market_state` / `_build_triangle_compliance` / `_build_signal_sufficiency` 等 14 个内部函数）
  - `a2_first_principles_adapter.py`（`dream-first-principles` v2.6.1，第一性原理分析 + 市场状态分类 + 综合判断）
  - `a3_strategy_adapter.py`（`dream-strategy-designer` v2.7.0，方向偏置 / 仓位修正 / 杠杆上限 / 目标币种）
  - **影响范围**: `core/a1_research_adapter.py`、`core/a2_first_principles_adapter.py`、`core/a3_strategy_adapter.py`

- **新增**: 市场数据层
  - `market_data_fetcher.py`：Hyperliquid REST → CoinGecko → 本地缓存三源降级，60s 缓存
  - `realtime_market_stream.py`：Hyperliquid WebSocket 全市场 ticker，自动重连，线程安全单例，WS 不可用回退 REST 轮询
  - **影响范围**: `core/market_data_fetcher.py`、`core/realtime_market_stream.py`

- **新增**: LLM 桥接层 `core/llm_bridge.py`
  - OpenAI / DeepSeek / Anthropic / 本地多 Provider
  - 失败降级到规则引擎
  - Token 预算控制
  - 60s 缓存
  - JSON 模式
  - **影响范围**: `core/llm_bridge.py`

- **新增**: A9 离场决策 `core/a9_exit_decision.py`（`dream-exit-skill-v2` v2.2.0）
  - 四层决策链：战略一致性 → 置信度加权 → 市场状态修正 → 最终合成 + 紧急度
  - 四态输出：CLOSE / REDUCE / HOLD / RAISE_TP
  - **影响范围**: `core/a9_exit_decision.py`

- **新增**: 历史档案中心 `core/archive_center.py` 与做梦产物集成 `core/dream_insights_integration.py`
  - 历史 Episode 检索 / 战略库查询 / 记忆库查询
  - 基于价格 / 波动率 / RSI 的相似度匹配
  - dream_journal / brainstorm / insight 产物解析与 A1 交叉验证
  - **影响范围**: `core/archive_center.py`、`core/dream_insights_integration.py`

- **新增**: `scripts/phase2_exit_evaluator.py` Phase 2 离场评估脚本
  - **影响范围**: `scripts/phase2_exit_evaluator.py`
  - **状态**: ⏳ 进行中（部分模块仍在迭代）

---

### [Phase 3 决策+执行层] - 2026-07 中下

- **新增**: 技术离场适配器 `core/technical_exit_adapter.py`（`technical-exit-adapter` v1.0.0）
  - 接入 ClassicExitSystem SSOT
  - P0 一票否决 / 技术+宏观强化 / 矛盾降级
  - `fuse_macro_technical()` 融合函数
  - `_calc_simple_technical_signals()` 降级方案（P0-P2 核心逻辑）
  - **影响范围**: `core/technical_exit_adapter.py`

- **新增**: 策略离场设计原则适配层 `core/strategy_exit_adapter.py`
  - 6 种离场哲学枚举（趋势 / 均值 / 马丁 / 基本面 / 情绪 / 震荡）
  - `ExitDesignPhilosophy` / `MacroExitInfluenceLevel` 枚举
  - `StrategyExitDesign` 数据类
  - `evaluate_exit_rationality()` / `get_strategy_exit_design()` / `get_all_strategy_designs()`
  - 核心思想：宏观离场是"增强"而非"替代"
  - **影响范围**: `core/strategy_exit_adapter.py`

- **新增**: 离场执行器 `core/exit_executor.py`
  - `ExitExecutor` 类：评估 → 权限检查 → 执行 → 记录 → 反馈
  - `ExecutionMode`（dry_run / simulated / real）/ `ExecutionStatus`（pending / executing / success / failed / skipped / rejected）枚举
  - `ExitExecution` 数据类
  - `create_executor_from_env()` 工厂
  - 默认 dry_run，显式开启实盘
  - 最大执行数量限制防批量砸盘
  - L4 TradeEvent 跨系统统一记录
  - **影响范围**: `core/exit_executor.py`

- **新增**: 权限反馈系统 `core/feedback_and_permission.py`
  - 5 级权限体系（NOTIFY / ADVISE / AUTO_REDUCE / AUTO_CLOSE / FULL_AUTO）
  - 各系统默认权限配置（`DEFAULT_SYSTEM_PERMISSIONS`）
  - `can_auto_execute()` / `record_feedback()` / `get_feedback_stats()` / `set_system_permission()` / `get_system_permission()`
  - 审计日志落盘 `artifacts/feedback/`
  - **影响范围**: `core/feedback_and_permission.py`

- **新增**: 回测验证框架 `core/backtest_framework.py`
  - 模拟价格走势（几何布朗运动 + 波动率聚集）
  - 逐 bar 回测
  - 多策略对比矩阵（baseline / macro_enhanced / hold）
  - 绩效指标（胜率 / 盈亏比 / 最大回撤 / 夏普比）
  - `run_backtest()` / `generate_simulated_bars()` / `BacktestResult`
  - **影响范围**: `core/backtest_framework.py`

- **新增**: AAM 产物投递 `core/aam_deliverer.py`
  - 标准化 frontmatter
  - 双通道投递（秘书邮箱 + 前端产物中心）
  - `index.json` 更新与投递验证
  - **影响范围**: `core/aam_deliverer.py`

- **新增**: `scripts/phase3_exit_evaluator.py` Phase 3 完整评估脚本
  - 支持 `USE_LLM` / `DELIVER` / `BACKTEST` / `USE_REALTIME` 环境变量
  - **影响范围**: `scripts/phase3_exit_evaluator.py`
  - **状态**: ⏳ 进行中

---

### [Phase 3+ 进化闭环] - 2026-07 下

- **新增**: 基础进化闭环 `core/evolution_loop.py`
  - 7 步闭环：记录决策 → 追踪结果 → 分析准确性 → 参数调优 → 反馈决策 → 回测验证 → 采纳/回滚
  - `EvolutionLoop` 类 + `get_evolution_loop()` 单例
  - `DecisionRecord` / `StrategyEvolutionParams` / `EvolutionAdjustment` 数据类
  - **影响范围**: `core/evolution_loop.py`

- **新增**: 增强版进化闭环 `core/enhanced_evolution.py`
  - Layer 1: A8 理论实践验证（内部自我批评）
  - Layer 2: 做梦部潜意识分析（外部视角反思）
  - Layer 3: 数据驱动调优（历史准确性参数自适应）
  - 验证三层：回测验证 + Walk-Forward 滚动前向 + 7 天观察期再采纳
  - 集成 DreamOS `gap_score`、三屏置信度校准（ECE/Platt Scaling）、过拟合检测（参数敏感性/置换检验）
  - `EnhancedEvolutionLoop` 类 + `get_enhanced_evolution()` 单例
  - `EvolutionLayer` / `EvolutionStatus` / `EvolutionProposal` / `CalibrationResult` / `GapAnalysisResult` 数据类
  - **影响范围**: `core/enhanced_evolution.py`

- **新增**: 自动化调度主脚本 `scripts/auto_exit_system.py`
  - 10 步完整流程：初始化 → 查询持仓 → 市场数据 → A1 → A2 → A3 → 技术离场 → A9 融合 → 执行 → 进化闭环 → 报告投递
  - 7 个环境变量配置（`EXIT_MODE` / `USE_LLM` / `DELIVER` / `MAX_EXECUTIONS` / `MIN_POSITION_USDT` / `EVOLUTION` / `BACKFILL`）
  - 日志输出（控制台 + 文件）
  - 产物落盘（JSON + Markdown 双格式）
  - **影响范围**: `scripts/auto_exit_system.py`
  - **状态**: ⏳ 进行中（存在 TD-2 / TD-3 已知 Bug）

- **新增**: E2E 测试与压力测试脚本
  - `scripts/test_e2e_exit_system.py`（产物 `artifacts/tests/e2e_exit_test.json`）
  - `scripts/stress_test_7scenarios.py`（7 场景压力测试，步进式笔记本框架 + 三链门禁）
  - **影响范围**: `scripts/test_e2e_exit_system.py`、`scripts/stress_test_7scenarios.py`

---

## 历史产物时间线

> 依据 `artifacts/` 目录实际文件整理，反映系统迭代节点

| 时间 | 产物 | 说明 |
|------|------|------|
| 2026-07-04 ~ 2026-07-05 | `core/intent-specs/spec_task_*.json/md`（60+ 文件） | 任务意图规格归档 |
| 2026-07-12 | `artifacts/exit-evaluations/exit_evaluation_20260712_*.json/md` | Phase 2 早期评估产物 |
| 2026-07-12 | `artifacts/exit-evaluations/phase2_exit_evaluation_20260712T153025Z.*` | Phase 2 评估产物（ISO 时间戳命名） |
| 2026-07-13 | `artifacts/exit-evaluations/phase2_exit_evaluation_20260713T*.json/md` | Phase 2 评估产物 |
| 2026-07-14 | `artifacts/backtests/backtest_data_20260714_*.json` / `backtest_report_*.md` | 回测数据与报告 |
| 2026-07-14 | `artifacts/exit-evaluations/phase3_exit_evaluation_20260714_*.json/md`（10+ 文件） | Phase 3 评估产物 |
| 2026-07-14 | `artifacts/execution_logs/exit_execution_20260714_003449.json` | 首批执行日志 |
| 2026-07-21 | `artifacts/execution_logs/exit_execution_20260721_034942.json` | 最新执行日志 |

---

## 文档版本对齐状态

| 文档 | 当前版本 | 对齐状态 | 备注 |
|------|----------|----------|------|
| `docs/ENGINEERING_INDEX.md` | v2.0 (2026-07-25) | ✅ 已对齐 `core/` 实际代码（19 个核心 Python 文件） | 代码侧权威索引 |
| `docs/API_SPEC.md` | v2.0 (2026-07-25) | ✅ 已对齐实际函数签名与返回值 | 首版，覆盖全链路 |
| `docs/CHANGELOG.md` | v2.0 (2026-07-25) | ✅ 已对齐阶段规划与已知技术债 | 首版 |
| `docs/TECHNICAL_DESIGN.md` | v1.0 (2026-07-12) | ⚠️ 范围错位（TD-1） | 仅覆盖离场评估子模块，未覆盖执行反馈/进化闭环/回测/产物投递 |

---

_维护规则：每次代码变更后必须在此文件追加变更记录；新版本记录插入到 `[v2.0]` 段之上_
