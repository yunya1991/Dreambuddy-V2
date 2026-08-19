# 💡 认知系统建议（非约束，可自由选择是否遵循）
# 🔄 刷新第 17 次  | 2026-08-14 01:11:09  |  触发: 动作数触发 (45 >= 5)
# 生成时间: 2026-08-14 01:11:09

## 🎯 流程建议
### 1. [t4-intelligence-radar] intelligence-radar
   匹配度: 2.00 | kw:system ; kw:trading
   HARD-GATE: P0 告警必须立即触发 T2 离场检查，零延迟。
持仓期间 T4 不得停止运行。
三屏方向不一致时必须发出 Level 1.5 告警。
### 2. [t5-meta-reflection] meta-reflection
   匹配度: 1.00 | kw:trading
   HARD-GATE: 复盘必须基于实际 episode 数据，不允许凭记忆复盘。
认知偏差识别必须给出具体证据（哪笔交易/哪个决策点）。
迭代 lesson 必须可执行，不允许"以后
### 3. [t0-market-cognition] t0-market-cognition
   匹配度: 0.00 | 
   HARD-GATE: 1. **双源交叉验证**：任何进入冲突分析的论据必须有 ≥2 个独立信息源交叉验证，单一来源（哪怕权威）不进入主冲突判定。
2. **主冲突唯一性**：主要冲

## 📚 相关经验
# 共 5 条
1. [A] [架构事实] 审批超时守卫 trading 类提醒机制（扩展 governance 约定，2026-08-10 首次执行验证）：approval_agent.py check 对 trading 审批
2. [S] [DreamOS每日监控 2026-08-10] cli/scheduler.py 的 backtest_evaluation 与 orchestration_optimize 两个 job 硬编码 
3. [S] [DreamOS每日监控 2026-08-10] 节点 C_MARTIN_V15 系统性产出 confidence<0.3，触发 Reflector REDO，被 graph_executor RED
4. [S] [修复] 问题: approval_agent.py 活跃副本(/home/ubuntu/Dreambuddy-V2-main/6-TRADING/scripts/)是 pre-v3 版本，check
5. [B] 双实例清理+守护进程重启操作经验（2026-08-10 治理周报a/b项执行，全部验证通过）：1) polling_trader 实际有4个重复实例（周报只报了2个，另有2个bash包装变体），全部源

---
💡 注: 以上建议来自历史沉淀和工程最佳实践，可作为参考但非强制约束。
   如果您有更好的方法，请自由探索——系统会记录并对比不同方案。