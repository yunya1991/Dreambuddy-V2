# 产物中台全链路压力测试报告 v1.0

**生成时间**: 6/20/2026, 12:31:28 AM
**总测试数**: 29
**总耗时**: 178.1 秒

## 一、整体统计

| 指标 | 值 |
|------|-----|
| 总测试数 | **29** |
| 成功率 | **62.1%** (18/29) |
| 失败数 | 0 |
| 意图识别准确率 | **62.1%** |
| 包含 graph_reflection | **9** (31.0%) |
| 包含 step_metadata | **9** (31.0%) |
| 平均响应时间 | 1311 ms |
| 中位数响应时间 | 532 ms |
| 最快响应 | 471 ms |
| 最慢响应 | 5127 ms |
| 总产物文件数 | 78 |

## 二、Graph-Reflection 模块效果

| 指标 | 值 |
|------|-----|
| graph-reflection 激活次数 | 9 |
| 平均置信度 avg_confidence | **0.885** |
| 平均总节点数 total_nodes | **5.0** |
| 平均高价值节点数 | **2.6** |
| 平均可压缩节点数 | 0.0 |

### 置信度分布（Graph-Reflection 激活时）

| 置信度范围 | 次数 |
|------------|------|
| <0.5 | 0 |
| 0.5-0.6 | 0 |
| 0.6-0.7 | 0 |
| 0.7-0.8 | 3 |
| 0.8-0.9 | 0 |
| >=0.9 | 6 |

## 三、按意图分类分析

| 意图 | 测试数 | 成功 | 意图匹配 | 链长度 | 产物数 | Graph-Reflection | 平均置信度 | 平均响应 |
|------|--------|------|----------|--------|--------|------------------|------------|----------|
| deep_analysis | 4 | 100% | 100% | 4.0 | 4.0 | 0/4 | 0.00 | 549ms |
| scenario_sim | 4 | 100% | 100% | 4.0 | 4.0 | 0/4 | 0.00 | 514ms |
| strategy_verify | 4 | 100% | 100% | 3.0 | 3.0 | 0/4 | 0.00 | 998ms |
| execute_trade | 4 | 0% | 0% | 4.0 | 4.0 | 0/4 | 0.00 | 517ms |
| triple_chain | 4 | 0% | 0% | 3.0 | 3.0 | 0/4 | 0.00 | 1607ms |
| market_query | 3 | 100% | 100% | 3.7 | 1.0 | 3/3 | 0.94 | 2864ms |
| simple_qa | 3 | 100% | 100% | 3.7 | 0.0 | 3/3 | 0.77 | 554ms |
| system_config | 3 | 0% | 0% | 3.7 | 1.0 | 3/3 | 0.94 | 3681ms |

## 四、按思考深度分类

| 思考深度 | 测试数 | 成功 | 平均响应 | 平均置信度 |
|----------|--------|------|----------|----------|
| quick | 8 | 63% | 1427ms | 0.33 |
| standard | 8 | 63% | 1340ms | 0.33 |
| deep | 13 | 62% | 1223ms | 0.21 |

## 五、按资产分类

| 资产 | 测试数 | 成功率 |
|------|--------|------|
| BTC | 8 | 63% |
| ETH | 8 | 63% |
| SOL | 8 | 63% |
| DOGE | 5 | 60% |

## 六、产物类型分布

| 产物类型 | 次数 |
|----------|------|
| dynamic_chain_s1_research | 12 |
| dynamic_chain_s2_analysis | 20 |
| dynamic_chain_s3_design | 20 |
| dynamic_chain_s4_validate | 20 |
| intelligence_brief | 6 |

## 七、链路完整性分析

### Execution Loop（深度分析类请求）
- 测试数: 20
- 成功率: 60.0%
- Graph-Reflection 激活率: 0.0%
- 平均链长度: 3.6
- 平均置信度: 0.000

### Intelligence Loop（情报查询类请求）
- 测试数: 3
- 成功率: 100.0%
- 平均链长度: 3.7

### General Loop（快速回答类请求）
- 测试数: 6
- 成功率: 50.0%
- Graph-Reflection 激活率: 100.0%

## 九、问题模式识别

### 意图识别错误
- 基于当前 BTC 行情，先深度分析再制定交易计划 → expected=execute_trade, got=deep_analysis
- 基于当前 ETH 行情，先深度分析再制定交易计划 → expected=execute_trade, got=deep_analysis
- 基于当前 SOL 行情，先深度分析再制定交易计划 → expected=execute_trade, got=deep_analysis
- 基于当前 DOGE 行情，先深度分析再制定交易计划 → expected=execute_trade, got=deep_analysis
- 对 BTC 进行完整策略制定：调研→分析→设计→验证→执行 → expected=triple_chain, got=strategy_verify
- 对 ETH 进行完整策略制定：调研→分析→设计→验证→执行 → expected=triple_chain, got=strategy_verify
- 对 SOL 进行完整策略制定：调研→分析→设计→验证→执行 → expected=triple_chain, got=strategy_verify
- 对 DOGE 进行完整策略制定：调研→分析→设计→验证→执行 → expected=triple_chain, got=strategy_verify
- 系统状态查询 → expected=system_config, got=market_query
- 系统状态查询 → expected=system_config, got=market_query
- 系统状态查询 → expected=system_config, got=market_query

### Execution Loop 缺少 Graph-Reflection
- deep_analysis / BTC / quick
- deep_analysis / ETH / standard
- deep_analysis / SOL / deep
- deep_analysis / DOGE / deep
- scenario_sim / BTC / quick
- scenario_sim / ETH / standard
- scenario_sim / SOL / deep
- scenario_sim / DOGE / deep
- strategy_verify / BTC / quick
- strategy_verify / ETH / standard

## 十、性能瓶颈与优化建议

### 慢速请求 (>2000ms)
- system_config / ETH / standard: 5127ms
- triple_chain / DOGE / deep: 4739ms
- market_query / BTC / quick: 3275ms
- system_config / SOL / deep: 3021ms
- market_query / SOL / deep: 2950ms
- system_config / BTC / quick: 2895ms
- strategy_verify / BTC / quick: 2446ms
- market_query / ETH / standard: 2366ms

### 建议
- ⚠️ 意图识别准确率 <90%，建议扩展硬编码关键词规则
- ⚠️ 部分 execution loop 请求缺少 graph_reflection，建议检查 graph-reflection-bridge 初始化
- ✅ 系统整体稳定，产物生成机制正常工作

## 十一、结论与系统评估

- **系统稳定性**: 62.1% 成功率 (18/29)
- **意图识别准确率**: 62.1%
- **Graph-Reflection 集成率**: 31.0% (execution loop 中 0.0%)
- **自省 Gate 效果**: 平均置信度 0.885
- **压缩效率**: 平均保留 2.6 个高价值节点
- **产物生成**: 共产出 78 个产物文件

---
*测试环境: local dev server · 29 次请求 · 共 178 秒*
