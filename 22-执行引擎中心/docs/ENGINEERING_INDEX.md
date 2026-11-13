# 执行引擎中心 — 工程索引

> **版本**：v1.2 | **更新日期**：2026-11-14
> **模块定位**：Dreambuddy 交易执行引擎（TEE）— 订单路由、执行算法、滑点估计、熔断与审计

## 1. 模块概览

TEE（Trading Execution Engine）是 Dreambuddy 的交易执行核心，负责将策略信号转化为实际订单执行，支持多种执行算法（直连市价、智能被动、智能 TWAP），内置滑点估计、熔断开关、FAIL-OPEN 降级与全链路审计。

## 2. 目录结构

```
22-执行引擎中心/
├── docs/
│   ├── ENGINEERING_INDEX.md     # 本文件
│   ├── README.md                # 文档索引
│   ├── TECHNICAL_DESIGN.md      # 技术设计
│   ├── API_SPEC.md              # 接口规格
│   └── CHANGELOG.md             # 变更记录
├── tee_core/
│   ├── core/                    # 核心引擎
│   │   ├── engine.py            # 执行引擎主类
│   │   ├── config.py            # 配置管理
│   │   ├── protocol.py          # 订单协议
│   │   ├── contract.py          # 契约定义
│   │   ├── router.py            # 订单路由
│   │   ├── kill_switch.py       # 熔断开关
│   │   ├── failopen.py          # FAIL-OPEN 降级
│   │   ├── auditor.py           # 审计器
│   │   └── exceptions.py        # 异常定义
│   ├── adapters/                # 交易所适配器
│   │   ├── okx_adapter.py       # OKX 实盘适配
│   │   ├── paper_adapter.py     # 模拟盘适配
│   │   └── lark_bridge.py       # 飞书通知桥接
│   ├── algorithms/              # 执行算法
│   │   ├── base.py              # 算法基类
│   │   ├── direct_market.py     # 直连市价
│   │   ├── smart_passive.py     # 智能被动
│   │   └── smart_twap.py        # 智能 TWAP
│   ├── estimators/              # 估计器
│   │   └── slippage.py          # 滑点估计
│   └── integrations/            # 子系统集成
│       ├── v15_integration.py   # V15 马丁集成
│       └── yijing_integration.py # 易经系统集成
├── scripts/                     # 工具脚本
│   ├── docs_consistency.py      # 文档一致性检查
│   ├── shadow_compare.py        # 影子对比
│   └── slip_compare_report.py   # 滑点对比报告
├── trade_execution_gateway.py   # 统一执行入口（13 风控 → 22 下单，fail-closed）
├── x1_paper_executor.py         # X1 纸面成交记录器（意图 → 13→16→22 → 18 价格源撮合）
├── x1_paper_config.json         # 纸面成交配置（venue=paper，持仓周期/滑点/手续费）
├── x1_live_executor.py          # NN 链 live 执行器（消费 50 runtime/live/outbox.jsonl → 复核 → 13 风控定容 → 持仓守卫 → 触发 11 live_order_bridge）
├── risk_bridge.py               # 13 事前风控桥（PreTradeGate 判定 + risk_capital 真实权益 + PACA 定容，fail-closed）
├── runtime/
│   └── x1_live_processed.json   # live 决策幂等去重（processed）+ 冷静期起点（last_entry）
├── audit/
│   ├── x1_paper_fills.jsonl     # 纸面成交账本
│   └── x1_live_fills.jsonl      # live 成交账本（venue/order_placed/order_id/fill_px 扁平字段）
└── tests/                       # TDD 测试（Task 1-12 + live 执行器）
```

## 3. 核心能力

| 能力 | 实现 | 说明 |
|------|------|------|
| 订单路由 | core/router.py | 多交易所/多账户路由 |
| 执行算法 | algorithms/ | 直连市价/智能被动/智能TWAP |
| 滑点估计 | estimators/slippage.py | 实时滑点建模 |
| 熔断开关 | core/kill_switch.py | 异常自动熔断 |
| FAIL-OPEN | core/failopen.py | 降级容错 |
| 审计 | core/auditor.py | 全链路审计日志 |
| V15 集成 | integrations/v15_integration.py | V15 马丁策略执行 |
| 易经集成 | integrations/yijing_integration.py | 易经推理系统对接 |
| live 执行（NN 灰度） | x1_live_executor.py | 50 live 决策 → 执行权/额度/kill-switch/幂等复核 → 11 live_order_bridge 下单，审计落 `audit/x1_live_fills.jsonl` |
| 事前风控 + 定容 | risk_bridge.py | 13 `PreTradeGate` 判定 + `risk_capital` 真实权益 + PACA `position_pct` 定容，名义金额 10~100 USDT、杠杆 3；任一环节异常 fail-closed |
| 持仓守卫 | x1_live_executor.py | 真实下单前查 11 持仓，同标的已有仓位则跳过；查询失败 fail-closed |
| 开仓冷静期 | x1_live_executor.py | 同标的距上次真实成功开仓不足 8h（`22_LIVE_COOLDOWN_HOURS` 可覆盖）不再建仓 |
| 云端调度 | `dreambuddy-nn-live-chain.timer` | 每 5 分钟执行 50 `run_live.py` → 22 `x1_live_executor.py --limit 3` |

## 4. 测试覆盖

Task 1-12 TDD 测试套件覆盖：脚手架配置、客户端能力、协议适配器、滑点估计、订单路由、执行算法、熔断开关、FAIL-OPEN、审计器、引擎、脚本规范、V15 生产替换。

## 5. 关联子系统

- 14-V15经典马丁策略 — 策略信号来源
- 11-易经推理系统 — 推理信号来源
- 13-通用风控模块 — 风控前置检查
