# 事件驱动策略系统 — 变更日志

> **版本**：v1.0 | **更新日期**：2026-10-04

## [1.0.0] - 2026-10-04

### 新增
- 🎉 **独立子交易系统迁移**：从 `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/` 迁出至 `29-事件驱动策略系统/`，成为独立子交易系统（与 BCRM2.0、BDSM 平级）
- 📁 建立标准目录结构：`event_driven/` 核心包 + `tests/` + `docs/` 五文档标准
- 📝 补建五文档：README / ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG
- 🔗 `event_driven/__init__.py` 统一导出所有公开 API

### 变更
- 生产消费者 `kline_event_handler.py` / `backtest_macro_event.py` import 路径更新为 `event_driven.*`
- 23 号原位置保留 4 个 re-export shim 兼容层（向后兼容）
- 23 号 `conftest.py` 添加 29 号目录到 sys.path

### 测试
- 114 测试全部通过（迁移后验证）
- 23 号全量回归零失败

### 迁移文件清单
| 原位置 | 新位置 |
|--------|--------|
| 23/.../engines/event_driven_strategy.py | 29/event_driven/event_driven_strategy.py |
| 23/.../engines/conviction_scorer.py | 29/event_driven/conviction_scorer.py |
| 23/.../engines/event_dominance_controller.py | 29/event_driven/event_dominance_controller.py |
| 23/.../engines/event_case_library.py | 29/event_driven/event_case_library.py |
| 23/tests/test_event_*.py (3个) | 29/tests/ |
| 23/dreambuddy_evolution/tests/test_event_signal_contract.py | 29/tests/ |
| 23/dreambuddy_evolution/tests/test_phase3_event_driven_upgrade.py | 29/tests/ |

### 关联 SPEC
- SPEC-事件驱动策略独立化-共享事件层与弹性约束.md v1.2（定位：独立子交易系统）
