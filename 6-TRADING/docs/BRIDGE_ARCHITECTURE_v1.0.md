# Dream Universal Gateway - 桥接层架构设计 v1.0

> **版本**: v1.0
> **日期**: 2026-05-15
> **目的**: 连接前端(dream-universal-gateway) 和 后端(6-TRADING scripts/)

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Dream Universal Gateway 完整架构                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    dream-universal-gateway (前端)                     │   │
│  │                                                                      │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │   │
│  │  │   Dashboard │  │  Intent Chat │  │    Trading Interface        │ │   │
│  │  └──────┬──────┘  └──────┬───────┘  └─────────────┬──────────────┘ │   │
│  │         │                │                        │                 │   │
│  │  ┌──────▼────────────────▼────────────────────────▼──────────────┐ │   │
│  │  │              bridge-client.ts / trading-hook.ts              │ │   │
│  │  │                     (前端桥接客户端)                          │ │   │
│  │  └──────────────────────────┬────────────────────────────────────┘ │   │
│  └─────────────────────────────┼───────────────────────────────────────┘   │
│                                │ HTTP/REST                                      │
│                                ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    6-TRADING Bridge API (后端)                       │   │
│  │                         Port: 3847                                   │   │
│  │                                                                      │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │   │
│  │  │ /api/market │  │  /api/trade  │  │      /api/skill           │ │   │
│  │  │   行情API    │  │   交易API    │  │      SKILL路由API         │ │   │
│  │  └──────┬──────┘  └──────┬───────┘  └─────────────┬──────────────┘ │   │
│  │         │                │                        │                 │   │
│  │  ┌──────▼────────────────▼────────────────────────▼──────────────┐ │   │
│  │  │                    scripts/                                     │ │   │
│  │  │  okx_cli.py | dream_trade_exec.py | a2_first_principles_v2.6  │ │   │
│  │  └───────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

```
6-TRADING/
├── bridge/                          # 桥接层
│   ├── run_server.py               # 服务启动入口
│   ├── api/                        # API模块
│   │   ├── __init__.py
│   │   ├── dream_api_server.py     # Flask应用核心
│   │   ├── market_data_api.py      # 市场数据API
│   │   ├── trade_exec_api.py       # 交易执行API
│   │   ├── skill_router_api.py     # SKILL路由API
│   │   ├── intent_router_api.py     # 意图路由API
│   │   └── bridge_management_api.py # 桥接管理API
│   ├── scripts/                    # 桥接层专用脚本
│   │   └── (预留扩展)
│   └── utils/                      # 工具函数
│       └── __init__.py
│
└── scripts/                        # 核心交易脚本
    ├── okx_cli.py                  # OKX CLI封装
    ├── okx_unified_toolkit.py      # OKX统一工具包
    ├── a2_first_principles_v2.6_auto.py
    ├── a4_validation_executor.py
    ├── dream_trade_exec.py
    └── ...

3-FRONTEND/dream-universal-gateway/src/lib/
├── bridge-client.ts                # 前端桥接客户端
├── intent-router.ts               # 意图路由器
└── trading-hook.ts                # 交易React Hook
```

---

## 三、API端点

### 3.1 市场数据 (/api/market)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ticker/<inst_id>` | GET | 获取实时行情 |
| `/candles/<inst_id>` | GET | 获取K线数据 |
| `/multi-ticker` | POST | 批量获取行情 |
| `/pairs` | GET | 获取交易对列表 |
| `/funding-rate/<inst_id>` | GET | 获取资金费率 |

### 3.2 交易执行 (/api/trade)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/order` | POST | 下单 |
| `/order/<id>` | GET | 查询订单 |
| `/orders` | GET | 查询所有订单 |
| `/order/<id>` | DELETE | 取消订单 |
| `/positions` | GET | 获取持仓 |
| `/balance` | GET | 获取余额 |
| `/set-leverage` | POST | 设置杠杆 |
| `/close-position` | POST | 平仓 |

### 3.3 SKILL路由 (/api/skill)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/list` | GET | 列出所有SKILL |
| `/execute` | POST | 执行SKILL |
| `/pipeline` | POST | 执行流水线 |
| `/status/<task_id>` | GET | 查询任务状态 |
| `/phase-info/<phase>` | GET | 获取阶段信息 |

### 3.4 意图路由 (/api/intent)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/route` | POST | 路由用户输入 |
| `/batch` | POST | 批量路由 |
| `/examples` | GET | 获取示例 |

### 3.5 桥接管理 (/api/bridge)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/status` | GET | 桥接状态 |
| `/scripts` | GET | 列出脚本 |
| `/skills` | GET | 列出SKILL |
| `/health` | GET | 健康检查 |
| `/ping` | GET | 心跳检测 |

---

## 四、SKILL映射表

| 阶段 | KEY | SKILL名称 | 功能 |
|------|-----|----------|------|
| A0 | A0 | dream-contradiction-theory | 矛盾识别 |
| A1 | A1 | dream-strategy-research | 深度调研 |
| A2 | A2 | dream-first-principles | 第一性原理 |
| A3 | A3 | dream-tactical-validator | 战术验证 |
| A4 | A4 | dream-tactical-validator | 战术验证 |
| A5 | A5 | dream-tactical-executor | 综合执行 |
| A6 | A6 | dream-intelligence-monitor | 情报监控 |
| A7 | A7 | A7-practice-theory | 实践理论 |
| A8 | A8 | A8-theory-practice-verification | 知行合一 |
| A9 | A9 | dream-exit-skill-v2 | 离场决策 |

---

## 五、意图路由

### 5.1 支持的意图类型

| 意图类型 | 关键词 | 路由到 | 说明 |
|---------|-------|--------|------|
| market_analysis | 分析、行情、走势 | A1/A2/regime | 市场分析 |
| trade_execution | 买入、卖出、做多、做空 | A5/A9 | 交易执行 |
| risk_control | 止损、止盈、风控 | A9/risk | 风险控制 |
| intelligence | 监控、提醒、警报 | A6/intelligence | 情报监控 |
| strategy_design | 策略、方案、计划 | A3/A4/strategy-parser | 策略设计 |
| signal_query | 信号、指标、MACD | signal/regime | 信号查询 |
| contradiction | 矛盾、冲突、多空 | A0/A1 | 矛盾分析 |
| review | 复盘、总结、回顾 | A7/A8/episodes | 复盘回顾 |
| exit | 离场、退出、结束 | A9/exit | 离场决策 |

### 5.2 意图路由流程

```
用户输入
    │
    ▼
┌─────────────┐
│ 本地快速识别 │  ← 检测关键词、币种、方向
└──────┬──────┘
       │
       ▼ (高置信度 > 0.5)
┌─────────────┐
│   直接执行   │  ← 立即返回结果
└─────────────┘

       │ (低置信度)
       ▼
┌─────────────┐
│  桥接层路由  │  ← 调用 /api/intent/route
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ SKILL执行/  │  ← A1/A2/A3... 执行相应SKILL
│  交易执行   │
└─────────────┘
```

---

## 六、启动与配置

### 6.1 启动桥接服务

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING

# 安装依赖
pip3 install flask flask-cors psutil

# 启动服务
python3 bridge/run_server.py
```

### 6.2 环境变量

| 变量 | 默认值 | 说明 |
|------|-------|------|
| BRIDGE_HOST | 127.0.0.1 | 服务地址 |
| BRIDGE_PORT | 3847 | 服务端口 |
| BRIDGE_DEBUG | false | 调试模式 |

### 6.3 前端配置

```typescript
// .env.local
NEXT_PUBLIC_BRIDGE_URL=http://127.0.0.1:3847
```

---

## 七、数据流

### 7.1 用户意图处理流程

```
用户: "买入1手BTC"
    │
    ▼
bridge-client.routeIntent()
    │
    ▼
本地识别: intent=trade_execution, symbol=BTC-USDT-SWAP, direction=long
    │
    ▼
桥接层: POST /api/intent/route
    │
    ▼
返回: { intent: "trade_execution", skills: ["A5", "A9"], direction: "long" }
    │
    ▼
前端展示确认对话框
    │
    ▼
用户确认 → bridge-client.Trade.placeOrder()
    │
    ▼
POST /api/trade/order → 返回订单结果
```

### 7.2 SKILL执行流程

```
触发: 用户请求市场分析
    │
    ▼
routeIntent() → intent="market_analysis", skills=["A1", "A2", "regime"]
    │
    ▼
执行主SKILL: SkillAPI.executeSkill("A2")
    │
    ▼
POST /api/skill/execute { skill: "A2", params: { symbol } }
    │
    ▼
桥接层 → scripts/a2_first_principles_v2.6_auto.py
    │
    ▼
返回分析结果 → 前端展示
```

---

## 八、测试

### 8.1 健康检查

```bash
curl http://127.0.0.1:3847/api/health
```

### 8.2 测试意图路由

```bash
curl -X POST http://127.0.0.1:3847/api/intent/route \
  -H "Content-Type: application/json" \
  -d '{"text": "买入1手BTC"}'
```

### 8.3 测试下单

```bash
curl -X POST http://127.0.0.1:3847/api/trade/order \
  -H "Content-Type: application/json" \
  -d '{
    "inst_id": "BTC-USDT-SWAP",
    "side": "buy",
    "pos_side": "long",
    "sz": "1",
    "px": "95000"
  }'
```

---

## 九、后续计划

- [ ] 添加WebSocket实时推送
- [ ] 实现OKX真实API对接
- [ ] 添加SKILL执行状态实时反馈
- [ ] 完善前端交易界面组件
- [ ] 添加交易历史和报表功能
