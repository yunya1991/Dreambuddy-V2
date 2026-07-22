"""
Dream OS 交易系统评估器包

两级优化闭环：
- Level 1 (L4 粗筛)：L4StatsAdapter 从 L4 案例库读取历史统计
- Level 2 (回测精调)：BacktestFineTuner 用回测引擎跑不同子系统组合
- 整合层：DynamicOrchestrator 生成动态场景→子系统映射
"""
