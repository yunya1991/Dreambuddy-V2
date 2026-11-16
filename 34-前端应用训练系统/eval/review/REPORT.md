# E1 测试集复核报告（Agent）

- 样本数：500
- 通过：470（94.0%）
- 待人工复核：30（6.0%）

## 按分段

| 分段 | 总数 | 通过 | 通过率 |
|---|---|---|---|
| clarify | 40 | 40 | 100.0% |
| compound | 80 | 63 | 78.8% |
| data | 80 | 79 | 98.8% |
| out_of_scope | 120 | 118 | 98.3% |
| regression | 40 | 40 | 100.0% |
| semantic | 80 | 80 | 100.0% |
| trap | 60 | 50 | 83.3% |

## 待复核原因分布

| 原因 | 数量 |
|---|---|
| compound_not_detected | 17 |
| near_dup_unit | 5 |
| no_regex_match | 5 |
| intent_conflict | 3 |

## 待复核样例（最多 20 条）

- `E1-0068` BTC和黄金比哪个涨得多 → intent_conflict:regex=data_query
- `E1-0222` 明天会下雨吗 → near_dup_unit:stat_query
- `E1-0225` 附近有什么好吃的 → near_dup_unit:stat_query
- `E1-0283` 巨鲸动向和资金费率 → compound_not_detected
- `E1-0289` BTC和ETH相关性对比以及CPI → compound_not_detected
- `E1-0302` 先说下以太坊新闻，然后讲BTC现价 → compound_not_detected
- `E1-0303` 巨鲸在干什么，顺手看下资金费率 → compound_not_detected
- `E1-0305` CPI出了多少，非农呢 → compound_not_detected
- `E1-0307` ETH支撑位在哪，阻力位呢 → compound_not_detected
- `E1-0313` BTC年化波动率多少，巨鲸在干嘛 → compound_not_detected
- `E1-0314` 下次议息会议什么时候，CPI又是哪天 → compound_not_detected
- `E1-0322` 以太坊行情加新闻，一次说完 → compound_not_detected
- `E1-0324` BTC能做多吗，CPI影响大吗 → compound_not_detected
- `E1-0332` BTC波动率和VIX一起看 → compound_not_detected
- `E1-0334` SOL现价与SOL新闻 → compound_not_detected
- `E1-0345` BTC历史分位和年化波动率 → compound_not_detected
- `E1-0346` CPI同比、环比、月频序列都要 → compound_not_detected
- `E1-0354` 下次CPI时间和下次议息时间 → compound_not_detected
- `E1-0357` 巨鲸在买什么，BTC价格多少 → compound_not_detected
- `E1-0358` BTC技术面、资金面、情绪面一起评 → compound_not_detected

> 说明：复核结论由确定性规则产出；`golden` 仍需 10% 抽检人工确认。
