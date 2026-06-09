# FAQ - 常见问题解答

> **版本**: v1.0  
> **创建日期**: 2026-05-14

---

## 📂 分类索引

### 1. 架构相关
### 2. SKILL使用
### 3. 交易系统
### 4. 前端部署
### 5. 踩坑记录

---

## ❓ 架构相关

### Q1: Dream-MultiSkill的核心架构是什么？
**A**: 采用A0-A9九步流水线：
- A0: 矛盾分析
- A1: 深度调研
- A2: 第一性原理
- A3: 沙盘推演
- A4: 战术验证
- A5: 决策执行
- A6: 情报监控
- A7: 实践论门禁
- A8: 理论实践验证
- A9: 离场决策

### Q2: 六大核心系统是什么？
**A**: 
1. 产物中台 (Artifact Hub)
2. 用户前端 (Dream Universal Gateway)
3. 底层记忆系统 (Memory System)
4. 业务管理系统 (Business Management)
5. 中台治理系统 (Governance)
6. 交易研究系统 (Trading Research - A0-A9)

---

## ❓ SKILL使用

### Q3: 如何快速调度特定SKILL？
**A**: 使用触发词自动调度：
- 交易决策 → A0-A9系列
- 治理合规 → dream-governance-manager
- 记忆学习 → memory-*
- 外部研究 → tavily/deep-research

### Q4: SKILL存储位置？
**A**: 
- 用户级: `~/.workbuddy/skills/`
- 项目级: `/workbuddy/.../.workbuddy/skills/`

---

## ❓ 交易系统

### Q5: 三叉戟决策模型是什么？
**A**: 
| 信号 | 条件 | 行动 |
|------|------|------|
| BUY | 评分≥35 + Edge>0 + 阻力突破 | 做多 |
| SHORT | 评分≤15 + Edge<-20 + 阻力确认 | 做空 |
| SKIP | 其他 | 空仓等待 |

### Q6: 评分体系如何构成？
**A**: 8维80分：
- 技术指标(20%)
- 宏观信号(20%)
- 链上数据(15%)
- 情绪指标(15%)
- 策略匹配(15%)
- 地缘风险(10%)
- 记忆反馈(5%)

---

## ❓ 前端部署

### Q7: Dream Universal Gateway技术栈？
**A**: 
- 框架: Next.js 14
- 语言: TypeScript
- 样式: TailwindCSS
- 数据库: Prisma
- 状态: Zustand
- 认证: NextAuth.js

### Q8: 如何部署Gateway？
**A**: 支持腾讯云和本地部署，需评估：
- 用户规模扩展性
- 前端技术栈兼容性
- API调用频率限制

---

## ❓ 踩坑记录

### Q9: OKX API常见错误？
**A**: 
- CLI用`okx`非`okx-trade`
- funding-rate用`okx market funding-rate`(非swap)
- `--posSide long`多头也必需
- SHORT TP/SL参数反直觉

### Q10: Demo环境已知问题？
**A**: 
- 持仓同步BUG
- 验证委托"幽灵触发"
- 需要`x-simulated-trading: 1`头

---

## 📞 联系方式

如有更多问题，请查阅各模块详细文档或联系系统管理员。
