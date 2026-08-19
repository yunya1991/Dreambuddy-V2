# 💡 认知系统建议（非约束，可自由选择是否遵循）
# 生成时间: 2026-08-18 17:10:15

## 🎯 流程建议
### 1. [t2-trade-execution] t2-trade-execution
   匹配度: 1.00 | kw:execution
   HARD-GATE: 1. **验证前置**：大仓执行前必须有 ≥2 次模拟盘验证实践，且通过验证前置检查（实践次数≥2 + 同方向盈利≥2 + 无单次亏损>5%）。未通过 = 只允
### 2. [t0-market-cognition] t0-market-cognition
   匹配度: 0.00 | 
   HARD-GATE: 1. **双源交叉验证**：任何进入冲突分析的论据必须有 ≥2 个独立信息源交叉验证，单一来源（哪怕权威）不进入主冲突判定。
2. **主冲突唯一性**：主要冲
### 3. [t1-strategy-synthesis] t1-strategy-synthesis
   匹配度: 0.00 | 
   HARD-GATE: 1. **三情景概率闭合**：S1 + S2 + S3 概率之和必须 = 1.0（贝叶斯校准后），允许 ±0.01 容差，不允许"其他"兜底项。
2. **每情

## 📚 相关经验
# 共 5 条
1. [S] [链路bug批量修复 2026-08-15] P0五连修(commit 3847626): ①TP/SL引擎ZeroDivisionError×67根因=降级态entry_price=0时ration
2. [S] [新功能][dreamos] Phase3 Task1 - V15Executor base architecture (TDD) | 原因: - New V15Executor class with
3. [S] [DreamOS每日监控 2026-08-10] cli/scheduler.py 的 backtest_evaluation 与 orchestration_optimize 两个 job 硬编码 
4. [S] [Bug修复] unified budget management — V15 TOTAL_BUDGET=120, Hedge NOTIONAL_PER_LEG=30, fix HedgeExecut
5. [S] [新功能][dreamos] Phase3 Task4 - V15ExecutorNode wrapper (TDD) | 原因: - New V15ExecutorNode extends Base

---
💡 注: 以上建议来自历史沉淀和工程最佳实践，可作为参考但非强制约束。
   如果您有更好的方法，请自由探索——系统会记录并对比不同方案。