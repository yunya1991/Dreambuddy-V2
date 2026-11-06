# M0-04 开关注册表

唯一事实源：[switch_registry.v1.json](switch_registry.v1.json)。回滚演练与校验脚本均读取该文件，不在代码中重复硬编码。

| 开关 | 默认 | 类型 | 生产影响 | 来源 | 回滚 |
|---|---|---|---|---|---|
| `enable_cd_shadow` | False | shadow | none | B-01 | 置 False |
| `enable_dominance_shadow` | False | shadow | none | B-02 | 置 False，argmax 不变 |
| `enable_attention_a_dim` | False | promotion | may_change | B-03 | 置 False，回 identifier A_dim |
| `enable_a_dim_c_to_3` | False | promotion | may_change | B-03 | 置 False，回 legacy C 维度 |
| `enable_primary_contradiction_detector` | False | promotion | may_change | B-04 | 置 False |
| `enable_event_contradiction_shadow` | False | shadow | none | B-04 | 置 False |
| `enable_w6_monitor` | False | shadow | none | B-05 | 置 False |
| `enable_d2_oi_liq` | False | promotion | may_change | B-06 | 置 False，回旧 D2 |
| `enable_self_vote_shadow` | False | shadow | none | B-08 | 置 False |
| `enable_self_vote_cap` | False | promotion | may_change | B-08 | 置 False |

## 规则

- 新增开关必须先登记本表（name/default/kind/production_impact/since/rollback），再写入 `agi_config.py`。
- `kind=shadow` 的开关不得改变 production 输出；`kind=promotion` 的开关必须先有 shadow 证据 + 评审，才可打开。
- 所有开关默认 False；回滚动作优先 `reset_switches()` 或置 False。
- 校验：`python 49-交易框架协议/scripts/validate_switches.py`
- 演练：`python 49-交易框架协议/scripts/rollback_drill.py`