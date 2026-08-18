# 审计追踪规范

> **版本**: v1.0
> **更新日期**: 2026-05-14

---

## 📋 目录

1. [审计目标](#审计目标)
2. [审计范围](#审计范围)
3. [审计流程](#审计流程)
4. [审计记录](#审计记录)
5. [报告模板](#报告模板)

---

## 审计目标

### 核心目标

1. **可追溯性**: 每笔交易可追溯到决策依据
2. **可解释性**: 决策过程清晰可解释
3. **合规性**: 符合监管要求
4. **改进性**: 基于审计结果持续改进

---

## 审计范围

### 交易审计

| 审计项 | 描述 | 频率 |
|--------|------|------|
| 交易记录 | 所有交易明细 | 每笔 |
| 决策链路 | A0-A9决策过程 | 每笔 |
| 评分变化 | 多维评分历史 | 实时 |
| 持仓变动 | 账户持仓变化 | 实时 |

### 系统审计

| 审计项 | 描述 | 频率 |
|--------|------|------|
| 登录日志 | 用户认证记录 | 每次 |
| 配置变更 | 系统参数修改 | 每次 |
| 异常事件 | 错误/告警记录 | 实时 |
| 性能指标 | 响应时间/成功率 | 每小时 |

---

## 审计流程

### 日审计

```
1. 汇总24h交易记录
        ↓
2. 检查异常交易
        ↓
3. 验证评分一致性
        ↓
4. 生成日审计报告
```

### 周审计

```
1. 汇总7天交易统计
        ↓
2. 分析策略表现
        ↓
3. 检查合规指标
        ↓
4. 生成周审计报告
```

### 月审计

```
1. 汇总30天数据
        ↓
2. 性能归因分析
        ↓
3. 风险评估更新
        ↓
4. 生成月审计报告
        ↓
5. 提交治理委员会
```

---

## 审计记录

### 交易记录结构

```typescript
interface TradeAuditRecord {
  id: string;                    // 唯一ID
  timestamp: string;            // 时间戳
  symbol: string;               // 交易对
  side: 'BUY' | 'SELL';         // 方向
  amount: number;                // 数量
  price: number;                // 价格
  fee: number;                   // 手续费
  decisionChain: {              // 决策链路
    a0?: string;               // 矛盾分析
    a1?: string;               // 调研报告
    a2?: string;               // 第一性分析
    a3?: string;               // 推演报告
    a4?: string;               // 验证报告
    a5?: string;               // 执行结果
  };
  riskIndicators: {             // 风险指标
    leverage: number;
    positionRatio: number;
    drawdown: number;
  };
  compliance: {                 // 合规检查
    pretrade: boolean;
    posttrade: boolean;
    score: number;
  };
}
```

### 审计日志格式

```json
{
  "audit_id": "AUD-20260514-001",
  "type": "TRADE_EXECUTION",
  "timestamp": "2026-05-14T12:00:00Z",
  "actor": "dream-tactical-executor",
  "action": "BUY",
  "target": "BTC-USDT-SWAP",
  "result": "SUCCESS",
  "metadata": {
    "order_id": "OKX123456",
    "amount": "0.1",
    "price": "80000"
  },
  "compliance": {
    "passed": true,
    "score": 85
  }
}
```

---

## 报告模板

### 日审计报告

```markdown
# 日审计报告 - 2026-05-14

## 基本信息
- 报告ID: AUD-Daily-20260514
- 审计周期: 2026-05-13 00:00 - 2026-05-14 00:00
- 审计员: dream-posttrade-mrm-audit

## 交易统计
| 指标 | 数值 |
|------|------|
| 总交易笔数 | 25 |
| 总交易金额 | $125,000 |
| 盈利交易 | 18 |
| 亏损交易 | 7 |
| 胜率 | 72% |

## 合规检查
| 检查项 | 结果 |
|--------|------|
| 交易频率 | ✅ 通过 |
| 仓位限制 | ✅ 通过 |
| 杠杆限制 | ✅ 通过 |
| 止损触发 | ✅ 通过 |

## 异常事件
- 无

## 建议
- 建议优化网格间距参数
```

---

## 🚀 快速链接

- [治理章程](./GOVERNANCE_CHARTER.md)
- [合规规则](./COMPLIANCE_RULES.md)
- [盘后审计SKILL](../SKILL/dream-posttrade-mrm-audit/)
