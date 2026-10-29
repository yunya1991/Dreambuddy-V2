# 意图注册表（INTENT REGISTRY）

> 自动生成：sync_intent_registry.py（2026-10-24 13:05 UTC）
> 权威源：3.1-FRONTEND/src/lib/intent/intent-descriptions.ts（唯一权威源，本文件为只读投影）
> 同步通道：spec v0.5 §5⑤（38 侧 intent_registry 表 + 41 侧本文档）

共 15 种意图。

| 意图 ID | 名称 | 分层 | 规则 | 关键词 |
|---|---|---|---|---|
| market_query | 市场行情查询 | L0 | hc_market_query | 价格、行情、多少、涨跌、涨了、跌了 |
| deep_analysis | 深度分析 | L0 | hc_deep_analysis | 分析、研究、看看、怎么样、能买吗、能涨吗 |
| triple_chain | 全链分析+规划+执行 | L0 | hc_triple_chain | 全链、完整、全面、一条龙、分析规划执行、全套 |
| scenario_sim | 情景推演/假设分析 | L0 | hc_scenario_sim | 如果、假如、假设、万一、要是、情景 |
| strategy_verify | 策略验证/回测 | L0 | hc_strategy_verify | 回测、验证、策略、测试、历史表现、胜率 |
| execute_trade | 交易执行/下单 | L0 | hc_execute_trade | 买入、卖出、开仓、平仓、做多、做空 |
| risk_alert_response | 风险告警响应 | L0 | hc_risk_alert_response | 告警、提醒、止损、止盈、爆仓、风险 |
| simple_qa | 简单问答/非交易话题 | L0 | hc_simple_qa | 你好、谢谢、再见、是什么、为什么、怎么 |
| command | 系统命令 | L0 | hc_command | 清空、重置、刷新、导出、重启、清理 |
| system_config | 系统配置/设置 | L0 | hc_system_config | 设置、配置、修改、调整、参数、阈值 |
| credits_query | 查询余额/积分 | L0 | hc_credits_query | 余额、积分、额度、使用量、还剩、花费 |
| artifact_query | 查询历史记录/产物 | L0 | hc_artifact_query | 历史、记录、上次、之前、报告、产物 |
| need_clarification | 需要澄清 | L0 | hc_need_clarification | - |
| developer | 开发者请求 | L0 | hc_developer | 写、函数、脚本、代码、调试 |
| clarification_result | 澄清结果 | L0 | hc_clarification_result | - |

## 示例

- **market_query**（市场行情查询）：BTC现在多少钱；ETH今天涨了多少；SOL的成交量
- **deep_analysis**（深度分析）：分析一下BTC的走势；ETH怎么样能买吗；BTC为什么跌了
- **triple_chain**（全链分析+规划+执行）：对BTC做一次完整的分析规划执行；全面分析ETH并给出交易计划；一条龙分析SOL并执行
- **scenario_sim**（情景推演/假设分析）：如果BTC跌破5万会怎样；假如美联储降息对ETH的影响；万一SOL暴涨怎么操作
- **strategy_verify**（策略验证/回测）：回测一下BTC的均线策略；验证这个策略的胜率；测试ETH的突破策略
- **execute_trade**（交易执行/下单）：买入1个BTC；平掉ETH的多单；做空SOL
- **risk_alert_response**（风险告警响应）：BTC止损告警了怎么办；ETH快爆仓了要不要平；收到风险提醒怎么处理
- **simple_qa**（简单问答/非交易话题）：你好；谢谢你；什么是区块链
- **command**（系统命令）：清空会话；导出分析结果；刷新数据
- **system_config**（系统配置/设置）：设置止损阈值；修改风控参数；配置API key
- **credits_query**（查询余额/积分）：我还有多少积分；余额查询；这个月用了多少额度
- **artifact_query**（查询历史记录/产物）：看看上次的分析；历史交易记录；之前的BTC报告
- **need_clarification**（需要澄清）：帮我看看；分析一下；这个怎么样
- **developer**（开发者请求）：帮我写个函数计算移动平均线
