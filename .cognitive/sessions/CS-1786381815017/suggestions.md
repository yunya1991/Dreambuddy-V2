# 💡 认知系统建议（非约束，可自由选择是否遵循）
# 生成时间: 2026-08-11 01:10:15

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
1. [S] [DreamOS每日监控 2026-08-10] cli/scheduler.py 的 backtest_evaluation 与 orchestration_optimize 两个 job 硬编码 
2. [S] [认知系统每日监控 2026-08-10 bug修复经验] 记忆库数据卫生三件套(全部当场验证通过)：①相同内容的timeout解决路径会跨会话重复入库(本次清15条重复/占总量24%)——去重应保留
3. [S] [解决路径] 问题: 任务涉及 7 个文件 | 方案: 修改了 9 次文件 | 结果: timeout (9步, 23.8min)
4. [S] [解决路径] 问题: 任务涉及 2 个文件 | 方案: 修改了 2 次文件 | 结果: timeout (2步, 29.8min)
5. [S] [DreamOS每日监控 2026-08-10] 节点 C_MARTIN_V15 系统性产出 confidence<0.3，触发 Reflector REDO，被 graph_executor RED

---
💡 注: 以上建议来自历史沉淀和工程最佳实践，可作为参考但非强制约束。
   如果您有更好的方法，请自由探索——系统会记录并对比不同方案。