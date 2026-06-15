# 3-SUPPORT：运营支持体系
> **原始SKILL**: boss-secretary, dream-operation-director, dream-cost-control,
> dream-performance-review, ai-trading-compliance, auto-repair,
> dream-hr-recruitment, resource-efficiency-analyst, dream-product-hub-maintenance

---

## 老板秘书（boss-secretary）
**定位**: 系统中枢—协调、归档、通知

### 会议室管理
```
meetings/
├── meeting_0001.yaml  # 首次会议记录
├── meeting_0002.yaml  # 战略会议
├── meeting_0003.yaml  # 回顾会议
└── meeting_0004.yaml  # 复盘会议
```

### 待处理任务
```
pending_tasks/inbox/
└── advisor_review_*.json  # 顾问评审待处理
```

### 知识库
- `keyword_mapping.yaml` — 关键词路由
- `advisor_routing.yaml` — 顾问分配规则
- `company_structure.yaml` — 公司架构(6部门+4顾问)
- `lessons.yaml` — 经验教训库(P0-P3分级)
- `risk_thresholds.yaml` — 5大风险场景+评分阈值

### 6大部门
| 部门 | 负责人 | 核心Skill |
|:---|:---|:---|
| 市场情报部 | ADVISOR-MR | Tavily/Odaily/NeoData |
| 研究部 | ADVISOR-QT | 信号评分/技术分析 |
| 风控部 | ADVISOR-RM | 仓位/门禁/成本 |
| 执行部 | ADVISOR-EE | OKX交易CLI |
| 运营总监 | dream-operation-director | 流程协调 |
| 合规部 | dream-output-quality-gate | 输出质检 |

### 4位顾问
| 顾问 | 评级 | 权重 |
|:---|:---:|:---:|
| ADVISOR-QT (量化) | A | 30-40% |
| ADVISOR-RM (风控) | C (待优化) | 35-45% |
| ADVISOR-MR (宏观) | B | 25-35% |
| ADVISOR-TR (趋势) | B | 20-30% |

---

## 运营总监（dream-operation-director）
流程协调、任务分配、跨部门沟通

## 成本控制（dream-cost-control）
Token预算管理、API调用优化

## 绩效审查（dream-performance-review）
KPI跟踪、效率分析、改进建议

## 合规审计（ai-trading-compliance）
变更合规检查、交易合规审计、change_bundle机制

## 自动修复（auto-repair）
已知问题自动修复脚本、监控告警自动处理

## 资源效能（resource-efficiency-analyst）
计算资源利用率分析、优化建议
