# 系统文件归档索引

本文件记录项目根目录下散落的文档和目录的归档情况。

## 归档记录

### artifacts/
- 原始位置: `artifacts/`
- 归档位置: `11-易经推理系统/artifacts/supplement-memory/`
- 内容: 补充内存数据

### data/
- 原始位置: `data/`
- 归档位置: `11-易经推理系统/data/bcrm2/`
- 内容: 易经推理系统数据文件

### docs/
- 原始位置: `docs/`
- 归档位置:
  - `docs/superpowers/checklists/` → `2-KNOWLEDGE/4-OPERATIONS/checklists/`
  - `docs/superpowers/plans/` → `2-KNOWLEDGE/4-OPERATIONS/plans/`
  - `docs/superpowers/contracts/` → `7-产物中台/docs/superpowers/contracts/`
  - `docs/superpowers/specs/` → `7-产物中台/docs/superpowers/specs/`
  - `docs/superpowers/templates/` → `7-产物中台/docs/superpowers/templates/`
  - `docs/superpowers/trading-monitor/` → `15-监控告警系统/`

### dreambuddy/
- 原始位置: `dreambuddy/`
- 归档位置:
  - `dreambuddy/artifacts/intent-specs/` → `16-调控系统/core/intent-specs/`
  - `dreambuddy/artifacts/trading/` → `6-TRADING/artifacts/trading/`
  - `dreambuddy/artifacts/tasks/` → `6-TRADING/sessions/tasks/`
  - `dreambuddy/artifacts/research/` → `6-TRADING/knowledge/research/`
  - `dreambuddy/artifacts/governance/` → `16-调控系统/core/governance/`
  - `dreambuddy/artifacts/results/` → `16-调控系统/core/results/`
  - `dreambuddy/s1_market_intel_*.md` → `6-TRADING/knowledge/market_intel/`
  - `dreambuddy/s2_first_principles_*.md` → `6-TRADING/knowledge/first_principles/`
  - `dreambuddy/s3_scenario_design_*.md` → `6-TRADING/knowledge/scenario_design/`
  - `dreambuddy/s4_validation_report_*.md` → `6-TRADING/knowledge/validation/`
  - `dreambuddy/config/` → `16-调控系统/core/config/`
  - `dreambuddy/meta/` → `16-调控系统/core/meta/`

### features/
- 原始位置: `features/`
- 归档位置:
  - `features/settings/` → `3-FRONTEND/dream-universal-gateway/src/app/dashboard/settings/`
  - `features/three-screens/` → `3-FRONTEND/dream-universal-gateway/src/app/dashboard/three-screens/`
- 内容: React 前端组件（ApiKeyManager、TradingParamsPanel、三屏分析面板）

### ops/
- 原始位置: `ops/`
- 归档位置: `deploy/ops/`
- 内容: 系统运维脚本（launchd管理、master daemon、日志、状态文件）

### scripts/
- 原始位置: `scripts/`
- 归档位置: `16-调控系统/scripts/`
- 内容: 调控系统脚本（notebook_hook、review_filter、step_controller、sync_artifact等）

### models/
- 原始位置: `models/`
- 状态: 空目录，已删除

### scheduler_data/
- 原始位置: `scheduler_data/`
- 状态: 空目录，已删除

### _tmp_debug_path.py
- 原始位置: `_tmp_debug_path.py`
- 状态: 已删除
- 内容: 临时调试 TradingAgent 路径的脚本，已过时

### feed
- 原始位置: `feed`
- 状态: 已删除
- 内容: 用途不明的二进制文件

### generate_fundamental_sample_data.py
- 原始位置: `generate_fundamental_sample_data.py`
- 归档位置: `9-基本面分析/scripts/`
- 内容: 生成基本面分析后端所需的样例数据文件（news brief、flow regime、narrative registry 等）

### install_all_launchd.py
- 原始位置: `install_all_launchd.py`
- 归档位置: `deploy/ops/`
- 内容: DreamBuddy 全系统 Launchd 统一安装脚本（管理 8 个 launchd 服务）

### test_fundamental_endpoints.py
- 原始位置: `test_fundamental_endpoints.py`
- 归档位置: `9-基本面分析/tests/`
- 内容: 用 python urllib 测试基本面分析后端各端点的脚本

## 归档原则

1. **按功能归属**: 文件按其功能模块归属到对应的系统目录
2. **保持目录结构**: 迁移时尽量保持原有的子目录结构
3. **统一管理**: 同类文件集中管理，便于维护和查找
4. **清理空目录**: 空目录直接删除，避免冗余

## 归档日期

- 创建时间: 2026-07-21