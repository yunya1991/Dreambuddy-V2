# DeepSeek 单模型基线对比（8 题 × 六维，分列）

- DeepSeek 调用次数: 8 / 上限 40
- 时延口径: 系统侧时延为 P1 单次实测（n=1），非推断统计；DeepSeek 侧同为 n=1
- D2 口径: 关键词命中率（must_have_facts[].match）× 5，非 LLM 评审
- D6 口径: 系统侧 token 用量未在产品链 SSE 中暴露，记 null

| 题 | D1 能力覆盖<br>sys/base | D2 正确性<br>sys/base | D3 调度<br>sys/base | D4 证据<br>sys/base | D5 时延分<br>sys/base | D6 token<br>sys/base |
|---|---|---|---|---|---|---|
| S1 | 2/0 | 5/2.5 | 3/0 | 5/0 | 5/5 | n/a/5 |
| S2 | 2/0 | 1.67/5 | 3/0 | 5/0 | 4/5 | n/a/5 |
| S3 | 2/0 | 0/5 | 3/0 | 5/0 | 4/5 | n/a/5 |
| S4 | 2/0 | 5/5 | 5/0 | 5/0 | 4/5 | n/a/5 |
| S5 | 3/0 | 5/2.5 | 3/0 | 5/0 | 3/5 | n/a/5 |
| S7 | 2/0 | 1.67/5 | 3/0 | 5/0 | 4/5 | n/a/5 |
| S10 | 2/0 | 0/2.5 | 3/0 | 0/0 | n/a/5 | n/a/5 |
| S13 | 3/0 | 0/2.5 | 3/0 | 5/0 | 5/5 | n/a/5 |

## 原始时延/token

| 题 | sys 时延(ms) | base 时延(ms) | base tokens | 系统工具命中 |
|---|---|---|---|---|
| S1 | 4449.345 | 892.233 | 94 | l0.data.mcp:data_fetch, l1.intent.mcp:classify_intent |
| S2 | 6653.427 | 1938.669 | 231 | l0.data.mcp:data_store_read, l0.store-admin.mcp:store_admin_status |
| S3 | 5360.828 | 1994.896 | 290 | l0.semantic-39.mcp:query_entity, l0.semantic-39.mcp:semantic_lookup |
| S4 | 7775.696 | 2854.175 | 374 | l0.cognition.mcp:recall, l0.rea.mcp:submit_rea_analyze |
| S5 | 23293.889 | 2420.664 | 306 | l0.rea.mcp:submit_rea_trace, l1.strategy.mcp:list_strategies, l2.debate.mcp:start_debate |
| S7 | 6141.061 | 3849.312 | 586 | l0.trade-exec.mcp:pre_trade_check, l1.trading.mcp:get_signal_state |
| S10 | None | 1595.693 | 184 | l2.emergence.mcp:list_experiments, l2.train.mcp:get_training_status |
| S13 | 1416.174 | 1935.701 | 285 | l0.data.mcp:data_fetch, l0.store-admin.mcp:store_admin_status, l1.ops.mcp:get_health |
