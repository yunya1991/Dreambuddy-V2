# 💡 认知系统建议（非约束，可自由选择是否遵循）
# 生成时间: 2026-08-16 22:26:08

## 🎯 流程建议
### 1. [t4-intelligence-radar] intelligence-radar
   匹配度: 1.00 | kw:trading
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
1. [A] [事故+修复] 2026-08-14: 审批超时守卫发现 approval_agent.py 被回退为 pre-v3（8/10 归档恢复事件连带回退，文件头 "v2: lark-cli"，无 reso
2. [A] [架构事实] 审批超时守卫 trading 类提醒机制（扩展 governance 约定，2026-08-10 首次执行验证）：approval_agent.py check 对 trading 审批
3. [B] [新功能][dreamos] Phase2 Task1 - YijingSignalGenerator base (TDD) | 原因: - New YijingSignalGenerator cla
4. [B] [新功能][dreamos] Phase2 Task4 - YijingSignalGeneratorNode wrapper (TDD) | 原因: - New YijingSignalGenera
5. [S] [链路bug批量修复 2026-08-15] P0五连修(commit 3847626): ①TP/SL引擎ZeroDivisionError×67根因=降级态entry_price=0时ration

---
💡 注: 以上建议来自历史沉淀和工程最佳实践，可作为参考但非强制约束。
   如果您有更好的方法，请自由探索——系统会记录并对比不同方案。

---
## 🔄 演进于 2026-08-16 22:28:00  task_type → memory-system

# 💡 认知系统建议（非约束，可自由选择是否遵循）
# 生成时间: 2026-08-16 22:28:00

## 🎯 流程建议
### 1. [t4-intelligence-radar] intelligence-radar
   匹配度: 1.00 | kw:trading
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
### 4. [brainstorming] brainstorming
   匹配度: 0.00 | 
   HARD-GATE: Do NOT invoke any implementation skill, write any code, scaffold any project, or
### 5. [dispatching-parallel-agents] dispatching-parallel-agents
   匹配度: 0.00 | 

## 📚 相关经验
# 共 5 条
1. [S] [链路bug批量修复 2026-08-15] P0五连修(commit 3847626): ①TP/SL引擎ZeroDivisionError×67根因=降级态entry_price=0时ration
2. [A] [事故+修复] 2026-08-14: 审批超时守卫发现 approval_agent.py 被回退为 pre-v3（8/10 归档恢复事件连带回退，文件头 "v2: lark-cli"，无 reso
3. [S] [修复] 问题: approval_agent.py 活跃副本(/home/ubuntu/Dreambuddy-V2-main/6-TRADING/scripts/)是 pre-v3 版本，check
4. [S] [架构事实] 审批超时守卫 governance 提醒机制分工：approval_agent.py check 对 governance 审批只打印 [GOVERNANCE] 行（lines 281-
5. [S] [治理决策] 用户批准(2026-08-09)Hermes×认知系统边界四规则：①内容单一所有权(用户偏好/环境事实/操作流程→Hermes权威；任务经验/验证方案/领域方法论→认知系统权威)，同一事

---
💡 注: 以上建议来自历史沉淀和工程最佳实践，可作为参考但非强制约束。
   如果您有更好的方法，请自由探索——系统会记录并对比不同方案。