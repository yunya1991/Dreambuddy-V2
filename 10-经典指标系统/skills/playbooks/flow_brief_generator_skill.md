# 资金流简报生成器 SKILL（契约化）

更新时间：2026-03-17  
状态：Active

## 目标

将 `flow_regime_*.json` 生成可阅读的资金流简报，并以 request/receipt 契约纳入治理链路。

## 运行命令

```bash
cd /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1/flow
python3 scripts/flow_brief_generator.py
```

可选：

```bash
python3 scripts/flow_brief_generator.py --with-news
python3 scripts/flow_brief_generator.py -o outputs/flow_brief_manual.md
```

## 契约与 Schema

- request schema：`ops/nanoclaw/core_task1/schema/flow_brief_request.schema.json`
- receipt schema：`ops/nanoclaw/core_task1/schema/flow_brief_receipt.schema.json`
- request pointer：`skills/contracts/flow_brief_request.schema.pointer.json`
- receipt pointer：`skills/contracts/flow_brief_receipt.schema.pointer.json`

## 校验命令

```bash
python3 scripts/validate_flow_brief_contract.py --mode request --input /path/to/request.json
python3 scripts/validate_flow_brief_contract.py --mode receipt --input /path/to/receipt.json --check-path
```

## 边界

- 只读建议层，不触发交易执行
- 不绕过审批/审计链路
