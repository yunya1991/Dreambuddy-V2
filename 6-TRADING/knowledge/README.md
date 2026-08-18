# 6-TRADING Strategy Knowledge Base

> **SKILL**: dream-knowledge v1.1 (dream-multiskill-v2/skills/0-CORE/dream-knowledge)
> **集成规范**: [skills/0-core-integration/knowledge/INTEGRATION.md](../skills/0-core-integration/knowledge/INTEGRATION.md)

---

## 目录结构

```
knowledge/
├── README.md               # 本文件
├── regime_patterns/        # 市场状态模式库（BTC 特有模式）
├── strategy_scores/        # 已执行策略评分记录（每次 A9 离场后更新）
└── master_profiles/        # 大师策略提炼（引用 dream-multiskill-v2 master_profiles）
```

---

## 写入规则

- **写入者**: Process D (A8 后触发 dream-knowledge)
- **读取者**: Screen 1 Phase-0 P0.7 步骤
- **格式**: JSON（strategy_scores）/ JSON（regime_patterns）
- **更新频率**: 每周一 Process D 执行后

---

## 评级标准

| 评级 | 分数范围 | 含义 |
|-----|---------|------|
| S | >=80 | 高置信策略，历史胜率强，可加大仓位系数 |
| A | 60-79 | 稳健策略，常规执行 |
| B | 40-59 | 待验证，保守仓位 |
| C | <40 | 暂停使用，等待复盘改进 |

---

*初始化于: 2026-05-26*
