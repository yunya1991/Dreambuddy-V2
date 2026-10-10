# 执行引擎中心 — 工程索引

> **版本**：v1.0 | **更新日期**：2026-10-11
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
└── tests/                       # TDD 测试（Task 1-12）
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

## 4. 测试覆盖

Task 1-12 TDD 测试套件覆盖：脚手架配置、客户端能力、协议适配器、滑点估计、订单路由、执行算法、熔断开关、FAIL-OPEN、审计器、引擎、脚本规范、V15 生产替换。

## 5. 关联子系统

- 14-V15经典马丁策略 — 策略信号来源
- 11-易经推理系统 — 推理信号来源
- 13-通用风控模块 — 风控前置检查
