---
name: dream-cost-control
description: "Dream-MultiSkill 成本控制部 (CFO) - 交易成本分析、算力预算控制、收益归因、ROI评估。超预算时告警。触发：成本、预算、ROI、收益、手续费、滑点、API费用"
metadata:
  version: "1.0.0"
  author: Dream-MultiSkill
  category: finance
  last_updated: "2026-04-18"
---

# Dream Cost Control - 成本控制部 (CFO)

> **⚠️ 顾问集成 (v2.0)**: 超预算告警时可调用 `advisor_direct_call.advisors_review(scene="COST_REVIEW")` 获取 advisor-co（成本控制顾问）+ advisor-rm（风险管理顾问）的联合评审。

> **部门定位**: 首席财务官 (Chief Financial Officer)
> 
> **汇报对象**: 总经理 (Smart Skill Manager)
> 
> **协作部门**: 绩效考核部、风险管理部、执行部门

---

## 核心职责

1. **交易成本分析** - 手续费、滑点、延迟损耗
2. **算力预算控制** - 每日/每周 API 调用预算
3. **收益归因** - PnL 分解到各技能贡献
4. **ROI 评估** - 评估各技能的资源投入产出比
5. **告警通知** - 超预算时立即通知

---

## 遇到以下情况请查阅

| 情况 | 查阅章节 | 行动 |
|:---|:---|:---|
| 需要分析交易成本 | §2 成本分析体系 | 执行成本分析 |
| 需要设置预算 | §3 预算控制 | 配置预算规则 |
| 需要评估技能ROI | §4 ROI评估 | 执行评估流程 |
| 超预算告警 | §5 告警机制 | 触发降级/通知 |
| 收益归因分析 | §6 收益归因 | 分解各技能贡献 |

---

## §1 成本分类体系

### 1.1 成本类型

| 类型 | 说明 | 典型场景 |
|:---|:---|:---|
| **显性成本** | 可直接量化的成本 | 手续费、API调用费 |
| **隐性成本** | 间接/难以直接量化的成本 | 滑点、延迟损耗 |
| **机会成本** | 放弃的最佳替代收益 | 应该买但没买 |
| **风险成本** | 潜在损失 | 回撤、极端行情 |

### 1.2 成本监控指标

```python
cost_metrics = {
    "交易成本": {
        "手续费率": "手续费 / 交易额",
        "滑点率": "实际成交价 vs 预期价差 / 交易额",
        "延迟损耗": "延迟时间 × 市场波动率",
    },
    "算力成本": {
        "API调用量": "每日/每周 API 调用次数",
        "Token消耗": "LLM Token 消耗量",
        "计算资源": "CPU/GPU 使用时长",
    },
    "总成本": {
        "日成本": "交易成本 + 算力成本 + 风险成本",
        "周成本": "本周累计成本",
        "月成本": "本月累计成本",
    }
}
```

---

## §2 交易成本分析体系

### 2.1 成本分析流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    💰 交易成本分析流程                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  触发时机:                                                           │
│  ├── 每日收盘后自动执行 (22:00 UTC+8)                                 │
│  ├── 交易执行后即时分析                                              │
│  └── 人工触发                                                        │
│                                                                      │
│  分析内容:                                                           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 1. 手续费统计                                                │   │
│  │    → 按币种统计: BTC/ETH/SOL/...                           │   │
│  │    → 按方向统计: 做多/做空                                   │   │
│  │    → 按仓位统计: 开仓/平仓                                  │   │
│  │                                                              │   │
│  │ 2. 滑点分析                                                  │   │
│  │    → 预期价 vs 实际成交价                                   │   │
│  │    → 极端滑点识别 (触发阈值检查)                             │   │
│  │    → 滑点原因归类                                           │   │
│  │                                                              │   │
│  │ 3. 延迟损耗                                                  │   │
│  │    → 决策延迟: 信号产生 → 决策完成                           │   │
│  │    → 执行延迟: 决策完成 → 订单成交                           │   │
│  │    → 总延迟损耗 = 延迟时间 × 市场波动率                       │   │
│  │                                                              │   │
│  │ 4. 综合成本                                                  │   │
│  │    → 公式: 总成本 = 手续费 + 滑点 + 延迟损耗                 │   │
│  │    → 成本率 = 总成本 / 交易额                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  输出:                                                               │
│  → 每日成本报告 (dream_data/cost/{date}_cost_report.md)             │
│  → 异常交易标记                                                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 成本报告模板

```markdown
## 💰 交易成本报告

**日期**: {date}
**分析时间**: {timestamp}

### 一、成本概况

| 指标 | 数值 | 环比 | 状态 |
|:---|:---:|:---:|:---:|
| 总交易额 | {volume} USDT | {delta}% | {status} |
| 总手续费 | {fee} USDT | {delta}% | {status} |
| 总滑点 | {slippage} USDT | {delta}% | {status} |
| 延迟损耗 | {delay_cost} USDT | {delta}% | {status} |
| **总成本** | **{total_cost} USDT** | {delta}% | {status} |
| **成本率** | **{cost_rate}%** | {delta}% | {status} |

### 二、分币种成本

| 币种 | 交易额 | 手续费 | 滑点 | 成本率 |
|:---|:---:|:---:|:---:|:---:|
| BTC | {vol} | {fee} | {slip} | {rate}% |
| ETH | {vol} | {fee} | {slip} | {rate}% |
| SOL | {vol} | {fee} | {slip} | {rate}% |

### 三、异常交易

| 订单ID | 时间 | 币种 | 类型 | 滑点 | 原因 |
|:---|:---|:---|:---|:---:|:---|
| {id} | {time} | {inst} | {type} | {slip}% | {reason} |

### 四、成本趋势

[7日/30日成本走势图]

### 五、改进建议
1. {suggestion_1}
2. {suggestion_2}
```

---

## §3 算力预算控制

### 3.1 预算体系

```python
budget_config = {
    # 日预算
    "daily": {
        "api_calls": {
            "tavily": {"limit": 50, "unit": "次"},
            "odaily": {"limit": 30, "unit": "次"},
            "neodata": {"limit": 100, "unit": "次"},
        },
        "llm_tokens": {
            "limit": 50000,
            "unit": "tokens",
        }
    },
    
    # 周预算
    "weekly": {
        "api_calls": {
            "limit": 500,
            "unit": "次",
        },
        "llm_tokens": {
            "limit": 300000,
            "unit": "tokens",
        }
    },
    
    # 紧急预算 (P0 事件)
    "emergency": {
        "api_calls": {"multiplier": 2.0},
        "llm_tokens": {"multiplier": 2.0},
    }
}
```

### 3.2 预算告警规则

```python
def check_budget_alert(usage: float, limit: float, period: str) -> Dict:
    """检查预算告警"""
    usage_rate = usage / limit
    
    if usage_rate >= 0.95:
        return {
            "level": "P0",
            "message": f"{period}预算即将用尽 ({usage_rate:.1%})",
            "action": "立即降级所有非必要API调用"
        }
    elif usage_rate >= 0.85:
        return {
            "level": "P1", 
            "message": f"{period}预算使用超85% ({usage_rate:.1%})",
            "action": "减少非关键API调用"
        }
    elif usage_rate >= 0.70:
        return {
            "level": "P2",
            "message": f"{period}预算使用超70% ({usage_rate:.1%})",
            "action": "监控使用速度"
        }
    else:
        return {
            "level": "OK",
            "message": f"{period}预算充足 ({usage_rate:.1%})",
            "action": "正常执行"
        }
```

---

## §4 ROI 评估体系

### 4.1 技能 ROI 计算

```python
def calculate_skill_roi(skill_id: str, period: str = "7d") -> Dict:
    """计算技能 ROI"""
    
    # 获取成本数据
    cost_data = get_skill_cost(skill_id, period)
    
    # 获取收益数据
    benefit_data = get_skill_benefit(skill_id, period)
    
    # 计算各项指标
    direct_cost = cost_data["api_cost"] + cost_data["llm_cost"]
    indirect_cost = cost_data["delay_cost"] + cost_data["risk_cost"]
    total_cost = direct_cost + indirect_cost
    
    direct_benefit = benefit_data["trades_generated"] * benefit_data["avg_profit_per_trade"]
    indirect_benefit = benefit_data["risk_avoided"] + benefit_data["efficiency_gain"]
    total_benefit = direct_benefit + indirect_benefit
    
    # ROI 计算
    roi = (total_benefit - total_cost) / total_cost * 100 if total_cost > 0 else 0
    
    # 效率指标
    cost_per_task = total_cost / cost_data["tasks_executed"] if cost_data["tasks_executed"] > 0 else 0
    benefit_per_task = total_benefit / cost_data["tasks_executed"] if cost_data["tasks_executed"] > 0 else 0
    
    return {
        "skill_id": skill_id,
        "period": period,
        "cost": {
            "direct": round(direct_cost, 2),
            "indirect": round(indirect_cost, 2),
            "total": round(total_cost, 2)
        },
        "benefit": {
            "direct": round(direct_benefit, 2),
            "indirect": round(indirect_benefit, 2),
            "total": round(total_benefit, 2)
        },
        "roi": round(roi, 1),  # 百分比
        "metrics": {
            "cost_per_task": round(cost_per_task, 4),
            "benefit_per_task": round(benefit_per_task, 4),
            "tasks_executed": cost_data["tasks_executed"],
            "success_rate": benefit_data["success_rate"]
        },
        "grade": "A" if roi > 50 else "B" if roi > 20 else "C" if roi > 0 else "D"
    }
```

### 4.2 ROI 评估报告

```markdown
## 📈 技能 ROI 评估报告

**周期**: {period}
**生成时间**: {timestamp}

### 一、总体 ROI 分布

| ROI 范围 | 技能数 | 占比 | 说明 |
|:---|:---:|:---:|:---|
| > 100% | {n} | {r}% | 明星技能 |
| 50-100% | {n} | {r}% | 优质技能 |
| 20-50% | {n} | {r}% | 良好技能 |
| 0-20% | {n} | {r}% | 待优化 |
| < 0% | {n} | {r}% | 亏损技能 |

### 二、技能 ROI 排行榜

| 排名 | 技能 | ROI | 成本 | 收益 | 评级 |
|:---:|:---|:---:|:---:|:---:|:---:|
| 1 | {skill} | {roi}% | {cost} | {benefit} | ⭐ |
| 2 | {skill} | {roi}% | {cost} | {benefit} | A |
| ... | ... | ... | ... | ... | ... |

### 三、成本效率分析

[散点图: X轴成本, Y轴收益, 点大小=任务数]

### 四、改进建议

#### 高成本低收益技能 (需优化或替换)
| 技能 | ROI | 问题 | 建议 |
|:---|:---:|:---|:---|
| {skill} | {roi}% | {issue} | {suggestion} |

#### 高成本高收益技能 (需优化效率)
| 技能 | 成本 | 收益 | 建议 |
|:---|:---:|:---:|:---|
| {skill} | {cost} | {benefit} | {suggestion} |

### 五、决策建议
1. {suggestion_1}
2. {suggestion_2}
3. {suggestion_3}
```

---

## §5 告警机制

### 5.1 告警分级

| 级别 | 触发条件 | 行动 | 通知对象 |
|:---:|:---|:---|:---|
| **P0** | 预算用尽 / 单日亏损 > 5% | 立即停止交易 | 总经理、风控 |
| **P1** | 预算使用 > 90% / 成本率 > 2% | 降级非必要调用 | 总经理、COO |
| **P2** | 预算使用 > 70% / 单笔滑点 > 1% | 减少调用频率 | COO、本部门 |
| **P3** | 成本率环比 > 20% | 监控，暂不行动 | 本部门 |

### 5.2 告警通知模板

```markdown
## 🚨 成本告警

**级别**: {P0/P1/P2/P3}
**时间**: {timestamp}
**来源**: 成本控制部

### 告警详情
- **触发条件**: {condition}
- **当前值**: {current_value}
- **阈值**: {threshold}
- **超出比例**: {exceed_ratio}%

### 影响分析
{impact_analysis}

### 建议行动
{recommended_action}

### 自动执行
- [ ] 已降级非必要API调用
- [ ] 已通知相关方
- [ ] 待人工确认是否停止交易
```

---

## §6 收益归因

### 6.1 PnL 分解模型

```python
def attribute_pnl(period: str = "1d") -> Dict:
    """PnL 归因分解"""
    
    # 获取总PnL
    total_pnl = get_total_pnl(period)
    
    # 各技能贡献分解
    contributions = {}
    
    # 1. 数据采集贡献 (市场情报部)
    data_contribution = calculate_data_contribution()
    contributions["market_intelligence"] = data_contribution
    
    # 2. 信号评分贡献 (研究部)
    signal_contribution = calculate_signal_contribution()
    contributions["research"] = signal_contribution
    
    # 3. 仓位管理贡献 (风险管理部)
    risk_contribution = calculate_risk_contribution()
    contributions["risk_management"] = risk_contribution
    
    # 4. 执行贡献 (执行部)
    execution_contribution = calculate_execution_contribution()
    contributions["execution"] = execution_contribution
    
    # 5. 成本扣除
    total_cost = get_total_cost(period)
    contributions["cost"] = -abs(total_cost)
    
    # 验证分解完整性
    sum_contributions = sum(contributions.values())
    unexplained = total_pnl - sum_contributions
    
    return {
        "period": period,
        "total_pnl": total_pnl,
        "contributions": contributions,
        "sum_of_parts": sum_contributions,
        "unexplained": unexplained,
        "reconciliation": "OK" if abs(unexplained) < 0.01 else "WARNING"
    }
```

### 6.2 归因报告

```markdown
## 📊 PnL 归因报告

**周期**: {period}
**总PnL**: {total_pnl} USDT

### 一、各部门贡献

| 部门 | 贡献 | 占比 | 说明 |
|:---|:---:|:---:|:---|
| 市场情报部 | {contrib} | {ratio}% | {desc} |
| 研究部 | {contrib} | {ratio}% | {desc} |
| 风险管理部 | {contrib} | {ratio}% | {desc} |
| 执行部 | {contrib} | {ratio}% | {desc} |
| **成本** | **{cost}** | {ratio}% | 手续费+滑点+算力 |
| **未解释** | {unexplained} | {ratio}% | 模型误差 |

### 二、贡献趋势

[堆叠面积图: 7日/30日各部门贡献趋势]

### 三、重点分析
{analysis}
```

---

## 决策树

```
【开始】
│
├─ 需要分析交易成本？
│   └─ 是 → §2 交易成本分析
│
├─ 预算快用尽了？
│   └─ 是 → §3 预算控制 + §5 告警机制
│
├─ 需要评估技能ROI？
│   └─ 是 → §4 ROI评估
│
├─ 收到成本告警？
│   └─ 是 → §5 告警机制 → 执行降级/通知
│
├─ 需要收益归因？
│   └─ 是 → §6 收益归因
│
└─ 其他问题
    └─ 找总经理决策
```

---

## 关键指标 (KPI)

| 指标 | 目标值 | 当前值 | 状态 |
|:---|:---:|:---:|:---:|
| 日均成本率 | ≤ 0.5% | ? | 📊 |
| 预算执行偏差 | ≤ 10% | ? | 📊 |
| 技能平均ROI | ≥ 30% | ? | 📊 |
| 成本告警准确率 | ≥ 90% | ? | 📊 |

---

## 附录：部门索引

| 部门 | 遇到问题时找谁 |
|:---|:---|
| 成本问题 | 本部门 |
| 绩效评估 | 绩效考核部 |
| 风控超标 | 风险管理部 |
| 执行异常 | 执行部门 |
| 战略决策 | 总经理 |

---

*最后更新: 2026-04-18*
*负责人: Dream Cost Control*


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | CFO |
| **目标邮箱** | 秘书汇总邮箱 (secretary) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/` |
| **投递方式** | 直接复制/写入Markdown文件到指定目录 |
| **投递命令** | 直接写入文件到 `~/.workbuddy/skills/boss-secretary/reports/<文件名>.md` |

### 投递工作流

```
1. 本部门完成工作（自动化任务/手动触发）
2. 整理工作总结（Markdown格式）
3. 确定优先级: P0(紧急)/P1(重要)/P2(观察)/P3(正常)
4. 执行投递命令
5. 确认邮件ID返回 → 投递完成
```

### 代码入口

- **投递方式**: 直接写入Markdown文件到指定邮箱目录
- **查看邮箱**: `ls ~/.workbuddy/skills/boss-secretary/reports/`
