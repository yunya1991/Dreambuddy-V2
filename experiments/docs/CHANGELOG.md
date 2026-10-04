# Experiments 变更记录

> **最后更新**：2026-09-30

---

## v1.0 (2026-09-30)

- 初始文档创建（从代码提取真实信息）
- 补齐 README.md、ENGINEERING_INDEX.md、TECHNICAL_DESIGN.md、API_SPEC.md、CHANGELOG.md

---

## 历史变更（从代码与 INDEX.md 提取）

### v2.1 (2026-07-17)

| 变更 | Agent | 文件 | 说明 |
|------|-------|------|------|
| 连败保护 48h 超时 | A | `core/agent_a_memory.py` | 超时自动重置 loss_streak，避免无限保护 |
| 连败保护倒计时 | A | `agents/agent_a_runner.py` + `monitor.html` | 页面显示剩余时间，决策日志含 countdown 字段 |
| 保留原始置信度 | A | `agents/agent_a_runner.py` | 风控拦截不再覆盖 confidence，添加 risk_gate_blocked 标记 |
| 执行异常保护 | A | `agents/agent_a_runner.py` | try/except 包裹交易执行，API 失败不崩溃 |
| 实际余额资金分配 | B | `core/chain_router.py` + `agents/agent_b_runner.py` | 移除 min(equity, 60) 截断，直接使用账户实际权益 |

### 实验启动 (2026-06-23)

- `experiment.id`: `ab-trading-v2`
- `experiment.start_date`: `2026-06-23`
- `experiment.target_cycles`: `84`
- `experiment.cron_interval_hours`: `1`
- `experiment.venue`: `hyperliquid`
- `experiment.market_type`: `perp`
- A 主账户合约 vs B 子账户合约，同市场、不同决策框架
