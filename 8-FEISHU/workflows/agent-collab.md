# Agent 协作工作流

## 方向A：风控审批闭环（Trading-RiskControl）

```
你 → "@Dream 运行Gate-C"
  Step1: Dream @Hermes 请求 Gate-C 评估（post富文本）
  Step2: Hermes @Dream 返回 JSON 评估结果
  Step3: Dream 推送交互审批卡片（[批准] [拒绝]）
  Step4: 你点按钮 → Dream @Hermes "已批准/拒绝"
  Step5: Hermes 执行入场 → 推送执行日志到 Trading-Desk
  Step6: 30分钟超时 → approval_agent.py AI 自动决策
```

Bot open_id：
- Dream: `ou_f6118fb8df62f58e861afebd7dedb66e`
- Hermes: `ou_bcf92b6057e502054ca32bcd8ebf6570`

## 方向B：Screen1 多角色研究（Trading-Research-Team）

```
你 → "@Hermes 做本周Screen1研判"
  Hermes @Dream(数据采集员) → B/C/D/E/F五维度
  Dream @Hermes → 数据返回
  Hermes @Dream(矛盾分析师) → A1结论
  Hermes @Dream(第一性原理师) → A2结论
  Hermes @Dream(沙盘推演师) → A3三情景
  Hermes @Dream(红队审核员) → 红队挑战
  Hermes → 汇总推送完整报告到研究室
```

## @ 消息格式（必须用 post 富文本）

```json
{
  "zh_cn": {
    "title": "消息标题",
    "content": [[
      {"tag": "at", "user_id": "ou_xxx"},
      {"tag": "text", "text": " 消息内容"}
    ]]
  }
}
```
