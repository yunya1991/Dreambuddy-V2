# 执行引擎中心 — 变更记录

## v1.0（2026-10-11）

### 新增
- 补建 docs/ 五件套文档（ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG）
- 核心引擎：engine / config / protocol / contract / router / kill_switch / failopen / auditor
- 适配器：OKX 实盘 / Paper 模拟盘 / Lark 通知
- 执行算法：DirectMarket / SmartPassive / SmartTWAP
- 滑点估计器
- V15 + 易经子系统集成
- Task 1-12 TDD 测试套件
- 影子对比与滑点对比脚本

### 架构
- 分层架构：core → adapters → algorithms → estimators → integrations
- FAIL-OPEN 降级优先
- 全链路审计不可绕过
