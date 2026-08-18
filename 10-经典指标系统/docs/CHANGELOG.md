# 变更日志 — 经典指标系统

> **定位**：记录每次变更的原因、内容、验证方式
> **格式**：[版本] - 日期 → 变更类型（新增/修改/修复/删除）
> **当前接口版本**：v1.2（与 `docs/API_SPEC.md`、`docs/ENGINEERING_INDEX.md` 对齐）

---

## [v1.2] - 2026-08-01

### 修复

- **修复**: ClassicExitAdapter 在 DreamOS 离场模块择优调用中的 4 个 bug
  - Bug1: `leverage` 硬编码 1.0 → `pnl_eff = unrealized_pnl_pct × 1.0` 过小，P0 硬退出阈值无法触发
    - 修复: `auto_trader.py` 新增 `_position_exit_state` 存储 per-symbol 持仓运行时状态，从交易所持仓取真实 leverage
  - Bug2: `candles_1h` 永远为空 → ClassicExitSystem 无法获取 K 线数据
    - 修复: `_fetch_market_data` 在 hyperliquid 和 aster 路径均返回 `candles_1h`（统一 dict 格式 t/o/h/l/c/v）
  - Bug3: `trailing_armed` / `trailing_stop_price` 状态丢失 → 跟踪止损跨巡检不累积
    - 修复: `auto_trader.py` 维护 per-symbol trailing 状态，`UnifiedExitDecision` 新增 `new_trailing_armed` / `new_trailing_stop` 字段
  - Bug4: `mfe_pnl_pct` / `max_dd_pct` 硬编码 0 → L1/L2 价值-风险评估拿到错误数据
    - 修复: 按 `peak_price` / `trough_price` 实时累计计算
  - **影响范围**: `1-ARCHITECTURE/dreamos/cli/auto_trader.py`、`1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_adapter.py`
  - **验证方式**: `python3 -m py_compile` 通过；50 笔 BTC 回测确认 classic 触发率从 2% 恢复正常
  - **回滚策略**: 恢复 `auto_trader.py` 中 `_try_selector_exit` 的 leverage=1.0 / mfe=0 / max_dd=0 硬编码

- **修复**: 离场模块回测器（`exit_module_backtester.py`）5 个 bug 导致回测数据失真
  - Bug1: Yijing 1h 缓存门禁用墙钟 `time.time()`，回测时所有 bar 在几秒内跑完 → 缓存命中 → yijing 0% 触发率
  - Bug2: `leverage=1.0` 硬编码 → classic 的 `pnl_eff` 过小 → P0/P1/P2 阈值无法触发
  - Bug3: `trailing_armed` / `trailing_stop_price` 不传 → 跟踪止损跨 bar 状态丢失
  - Bug4: `mfe_pnl_pct` / `max_dd_pct` 用瞬时 PnL 而非累计峰值/谷值
  - Bug5: `exit_reasons` 用 `action.lower()` 分类 → `time_limit` 也被记为 `"close"`，无法区分模块触发 vs 超时
  - **修复**: 每 bar 清 coin 级缓存；`DEFAULT_BACKTEST_LEVERAGE=5.0`；跨 bar 维护 trailing；按 peak/trough 累计 mfe/max_dd；用 reason 前缀分类 exit_reasons
  - **影响范围**: `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_backtester.py`、`exit_module_adapter.py`（SimpleExitAdapter 补齐 trailing 参数）
  - **验证方式**: 62 笔 BTC 回测：simple 93.5% 触发率（40 SL + 18 TP）、yijing 17.7%（6 SL + 5 TP）、classic 1.6%；三者 PnL 不再一致
  - **回滚策略**: 恢复 `exit_module_backtester.py` 的 `leverage=1.0`、删除 yijing 缓存清理、恢复 `exit_reasons` 用 `action.lower()`

---

## [v1.1] - 2026-07-25

### 修改
- **变更内容**: 修复 `docs/ENGINEERING_INDEX.md` 索引断链 — 将失效的 `docs/TECHNICAL_DESIGN.md` 引用修正为实际存在的技术文档（`技术文档2.0.md` 为当前权威、`技术文档.md` 为历史维护版）；同步移除目录结构中不存在的 `README.md` 引用。
  - 同步补全 `docs/API_SPEC.md` 与 `docs/CHANGELOG.md`（本文档），按 `PROJECT_DOC_STANDARD.md` 规范对齐 14-V15 标杆格式。
  - ENGINEERING_INDEX 文档版本升至 v1.1。
- **影响范围**: `docs/ENGINEERING_INDEX.md`、`docs/API_SPEC.md`、`docs/CHANGELOG.md`
- **验证方式**:
  - `Read docs/ENGINEERING_INDEX.md` 确认 §8 快速导航指向 `技术文档2.0.md`，§2 目录结构不再出现 `README.md`。
  - 全文检索 `TECHNICAL_DESIGN.md` 引用应仅出现在历史变更记录上下文中。
  - `docs/API_SPEC.md` 中所有路由与 `grep -n "@app.route" *.py` 结果一致；Python API 签名与 `classic_exit_system.py` 实际定义一致。
- **回滚策略**: 恢复 `docs/ENGINEERING_INDEX.md` 中的旧引用路径，删除新增的 `docs/API_SPEC.md` 与 `docs/CHANGELOG.md`。

### 新增
- **变更内容**: Dream OS v2.6 功能升级与系统修复（仓库级提交 `feat: Dream OS v2.6 功能升级与系统修复`，触及本子系统）。
  - ml_trade_service.py 文件大小约 7.9 MB（约 18.6 万行），主服务入口与执行/路由体系进一步完善。
- **影响范围**: `ml_trade_service.py` 及配套 launchd/systemd 部署配置
- **验证方式**: `bash ops/launchd/install_8092.sh` 后 `curl http://127.0.0.1:8092/exit/features/latest?pairs=BTC-PERP` 返回 `{"ok": true, ...}`。
- **回滚策略**: 通过 `git revert` 回滚对应提交；launchd 配置使用 `ops/launchd/uninstall_8092.sh` 卸载。

---

## [v1.0] - 2026-07-14

### 新增
- **变更内容**: 集成「三屏趋势系统 Phase 3 — 模型调优、版本化、回测框架」（仓库级提交，触及本子系统）。
  - 经典指标系统作为三屏趋势信号的下游消费方，与 12-三屏趋势系统通过桥接调用对接趋势过滤信号。
  - `tools/` 下新增 `tri_layer_replay_after_pipeline.py`、`tri_layer_replay_validate.py`、`macro_tri_layer_backtest_export_check.py` 等回测/校验脚本。
- **影响范围**: `tools/`、`ml_trade_service.py`（三屏桥接调用）、`tests_three_chain_eval.py`
- **验证方式**: `python -m pytest tests_three_chain_eval.py -v` 通过；`python tools/tri_layer_replay_validate.py` 返回 0 退出码。
- **回滚策略**: `git revert` 对应提交；移除 `tools/tri_layer_*.py` 与 `tools/macro_tri_layer_*.py`。

### 修改
- **变更内容**: 美林时钟模块重构 — 库存周期 × BTC.D 资金流转（仓库级提交，触及本子系统）。
  - 影响宏观资金流快照 `_macro_flow_at()` 等被 `/exit/features/latest?include_macro=true` 依赖的内部函数。
- **影响范围**: `ml_trade_service.py`（宏观资金流相关函数）
- **验证方式**: `curl "http://127.0.0.1:8092/exit/features/latest?pairs=BTC-PERP&include_macro=true"` 响应包含 `macro_flow_snap` 字段且 `macro_flow_dir ∈ {-1, 0, 1}`。
- **回滚策略**: `git revert` 对应提交，恢复旧美林时钟实现。

---

## [v0.9] - 2026-07-08

### 新增
- **变更内容**: 易经推理系统监控增强 + 三屏马丁策略优化 + DreamOS 节点扩展（仓库级提交，触及本子系统）。
  - 经典指标系统与 11-易经推理系统的监控/反馈链路增强；ml_trade_service 的 agent_driver 子命令入口稳定化。
  - `ml_trade_service.py` 新增 `--agent-driver-once` 入口（stdin JSON → `_agent_chat_driver_process`），供外部 agent 调用。
- **影响范围**: `ml_trade_service.py`（`__main__` 区段、agent driver）
- **验证方式**: `echo '{"cmd":{}, "llm":{}}' | python ml_trade_service.py --agent-driver-once` 以退出码 0 退出。
- **回滚策略**: `git revert` 对应提交；移除 `--agent-driver-once` 分支。

---

## [v0.8] - 2026-07-06

### 新增
- **变更内容**: 经典指标系统深度集成 + V3 前端重构（仓库级提交 `feat: 三屏马丁策略 + 经典指标系统深度集成 + V3前端重构`）。
  - `frontend/` React 监控面板 V3 重构，新增 `ExitSystemPage.tsx`、`CarryTradePage.tsx`、`FundamentalTradingConsolePage.tsx` 等页面组件，对接 `/exit/*`、`/carry/*`、`/funding/*` 路由。
  - `frontend/src/lib/classic-system-bridge.ts`、`classic-system-pipeline.ts`、`classic-system-examples.ts` 作为前端与经典指标系统的桥接层。
  - `classic_exit_system.py` 作为单一真相源（Single Source of Truth）定型，四大优先级离场架构（P0 → P2 → P3 → P1）落地。
- **影响范围**: `classic_exit_system.py`、`frontend/`、`frontend/src/lib/classic-system-*.ts`
- **验证方式**: `cd frontend && npm run build` 成功；`python classic_exit_system.py test` 自检全绿；`curl http://127.0.0.1:8095/health` 返回 `{"ok": true, "service": "classic_exit_system", ...}`。
- **回滚策略**: `git revert` 对应提交；前端回退到 V2 版本组件。

### 修改
- **变更内容**: 集成易经推理系统作为核心推理引擎（同日后续提交），经典指标系统的信号生成与易经推理系统的决策链路打通。
- **影响范围**: `ml_trade_service.py`、`skills/`
- **验证方式**: 检查 `skills/playbooks/` 下技能定义与代码实际调用一致。
- **回滚策略**: `git revert` 对应提交，恢复独立决策链路。

---

## [v0.7] - 2026-07-01

### 新增
- **变更内容**: DreamBuddy OS SACG 四层架构 + 模块接口层 + 压力测试框架（仓库级提交 `feat(dreambuddy-os): SACG四层架构 + 模块接口层 + 压力测试框架`）。
  - 经典指标系统作为 SACG（Strategy / Action / Control / Governance）中的 Strategy 层关键模块，对外接口契约由模块接口层规范化。
  - 引入 `test_agent_e2e_acceptance.py`、`test_strategy_optimization_rules.py` 等端到端验收与策略优化规则测试。
- **影响范围**: `ml_trade_service.py`、`test_agent_e2e_acceptance.py`、`test_strategy_optimization_rules.py`
- **验证方式**: `python -m pytest test_agent_e2e_acceptance.py test_strategy_optimization_rules.py -v` 通过。
- **回滚策略**: `git revert` 对应提交；保留旧版非 SACG 架构。

---

## [v0.6] - 2026-06-25

### 新增
- **变更内容**: 更新运行时数据 + 新增测试脚本与系统维护工具（仓库级提交）。
  - 新增 `system_backup.sh`、`system_restore.sh`、`selfcheck_signals_recent_dedup.py`、`debug_cache.py` 等运维与自检脚本。
  - `user_data/data/aggregated/` 与 `user_data/data/hyperliquid/futures/` 下沉淀历史 K 线数据，供离线回测使用。
- **影响范围**: `system_backup.sh`、`system_restore.sh`、`selfcheck_signals_recent_dedup.py`、`user_data/data/`
- **验证方式**: `bash system_backup.sh` 完成无报错；`python selfcheck_signals_recent_dedup.py` 退出码 0。
- **回滚策略**: 删除新增脚本；`git checkout -- user_data/data/` 恢复旧数据快照。

---

## [v0.5] - 2026-06-22

### 修复
- **变更内容**: 补全缺失的 `_evaluation_acceptance_status` 函数（PR #42，`fix: 补全缺失的 _evaluation_acceptance_status 函数`）。
  - 修复 ml_trade_service 在调用评估验收状态时因函数缺失导致的 `NameError`。
- **影响范围**: `ml_trade_service.py`
- **验证方式**: 触发评估验收流程（`/exit/features/latest` 或相关内部调用）不再抛出 `NameError: name '_evaluation_acceptance_status' is not defined`；`python -m pytest test_serving_pipeline_second_approval.py -v` 通过。
- **回滚策略**: `git revert` 对应 PR 提交，重新引入缺失函数的调用方需同步回退。

---

## [v0.4] - 2026-06-21

### 新增
- **变更内容**: Phase 2-4 基本面分析系统 + 图压缩模块 + 信号路由（PR #40，`feat: Phase 2-4 基本面分析系统 + 图压缩模块 + 信号路由`）。
  - 在 ml_trade_service 中引入 `/fundamental/*` 路由族（flows / narrative / trading / overview），统一基本面信号入口。
  - 引入信号路由器与图压缩模块，对接外部技能与 LLM 路由规则。
- **影响范围**: `ml_trade_service.py`、`skills/routing/`、`skills/contracts/`
- **验证方式**: `curl http://127.0.0.1:8092/fundamental/overview/latest` 当时返回 `{"ok": true, ...}`（后续 v1.1 退役为 410）；`python tools/fundamental_signal_bridge_check.py` 通过。
- **回滚策略**: `git revert` PR #40，移除 `/fundamental/*` 路由族与信号路由配置。

---

## 历史版本（v0.3 及更早）

> v0.3 及更早版本发生在 DreamBuddy-v2 仓库初始化与 ml_trade_service 早期搭建阶段，未单独标注本子系统的版本号。如需追溯，请通过 `git log --follow -- 10-经典指标系统/ml_trade_service.py` 查看文件级历史。

---

_维护规则：每次代码变更后必须在此文件追加变更记录，按时间倒序排列；同时同步更新 `docs/API_SPEC.md` 与 `docs/ENGINEERING_INDEX.md`。_
