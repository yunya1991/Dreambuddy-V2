# SKILL: agent-collab-screen1
# 触发: Trading-Research 群里用户 @hermes 做本周Screen1研判
# 角色: 总调度，协调 Dream 扮演多个研究角色

## Hermes 在研究室的总调度角色

当用户说"做本周Screen1研判"或"运行Screen1"时：

### 协调流程

**Step 1: 委托 Dream 采集五维度数据**
@ Dream（`ou_f6118fb8df62f58e861afebd7dedb66e`）：
```
请作为【数据采集员】，并行采集以下五个维度的最新数据：
B-减半周期: 当前阶段/天数/S2F/基线得分
C-矿工经济: Hash Ribbon/Puell/MPI/均成本
D-链上估值: MVRV Z/NUPL/RHODL/STH-MVRV  
E-宏观金融: Fed利率/M2/DXY/10Y/ETF流向
F-跨市场: 美林时钟象限/黄金vs股票/BTC角色

搜索当前价格和各指标数据，返回结构化 JSON。
```

**Step 2: 收到数据后 → 委托 Dream 做 A1 矛盾分析**
@ Dream：
```
请作为【矛盾分析师】，基于以下数据做 A1 矛盾论分析：
[插入 Step 1 数据]
识别多空主要矛盾，检查锚定偏见/可得性启发/代表性启发，输出方向和置信度。
```

**Step 3: 收到 A1 后 → 委托 Dream 做 A2**
@ Dream：
```
请作为【第一性原理分析师】，基于上述数据做 A2 分析：
推导供给/需求基本面，找出最小阻力路径和趋势转换窗口。
```

**Step 4: 收到 A2 后 → 委托 Dream 做 A3**
@ Dream：
```
请作为【沙盘推演师】，做 A3 三情景推演：
S1（主方向延续）/S2（区间震荡）/S3（反转）各自概率和触发条件。
```

**Step 5: 收到 A3 后 → 委托 Dream 做红队挑战**
@ Dream：
```
请作为【红队审核员】，挑战以上分析：
找出3个最强的反向理由，识别最脆弱假设，评估 red_team_flag 是否应设为 true。
```

**Step 6: 汇总交付**
整合所有分析，生成完整 Screen1 报告卡片推送到本群，
同时调用 feishu_notify.py screen1 写入研究室存档。

## 关键规则
- 每步等待 Dream 回复后再发下一步，不要一次性发完
- 每条消息必须用 post 富文本 @ Dream
- 用户随时可以插话纠偏，收到用户反馈后调整下一步指令
- 中间步骤的输出都公开在群里，让用户全程可见
