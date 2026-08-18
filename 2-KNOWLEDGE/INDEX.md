# 2-KNOWLEDGE — 交易系统知识库

> **定位：** 从 Skills 蒸馏的跨领域系统知识，三层分层存储。
> **源：** `~/.hermes/skills/` 中各 SKILL.md
> **消费端：** 飞书知识库文档（https://icnic28nu1x5.feishu.cn/wiki/KOH4wSEcFid298kk7R8cuS7FnTh）
> **同步：** cron 每日审计 → 差异推送飞书

## 目录结构

```
2-KNOWLEDGE/
├── INDEX.md              ← 本文件
├── 1-TRADING/            # 交易领域知识
│   ├── INDEX.md
│   ├── V9-马丁基线.md
│   ├── Screen1-七维牛熊评分.md
│   ├── Screen2-日线入场信号.md
│   ├── Screen3-监控与离场.md
│   ├── A系列调度链.md
│   ├── 三屏系统架构.md
│   ├── 风控体系.md
│   └── 交易参数速查.md
├── 2-TECHNICAL/          # 技术运维知识
│   ├── INDEX.md
│   ├── Hermes-架构.md
│   ├── Cron-调度.md
│   ├── 飞书集成指南.md
│   └── 部署与维护.md
├── 3-THEORY/             # 哲学/理论
│   ├── INDEX.md
│   ├── 第一性原理.md
│   ├── 矛盾分析法.md
│   └── 大师谱系.md
├── 4-OPERATIONS/         # 运营治理
│   ├── INDEX.md
│   ├── 三段式门禁.md
│   ├── 索引体系.md
│   ├── OKR管理.md
│   └── 审批工作流.md
└── 5-CHAIN-DEVELOPMENT/  # 三链开发方法论
    ├── INDEX.md
    ├── D-调研方法论.md
    ├── Z-规划方法论.md
    ├── E-执行方法论.md
    └── 三链接力协议.md
```

## 建设原则

1. **Source of Truth = Skills** — 每个技能 SKILL.md 是单域权威来源，KB 做跨域蒸馏
2. **原子化存储** — 每文件解决一个独立问题/概念，可独立引用
3. **两向同步** — 本地 MD ↔ 飞书 Doc，不双写不丢失
4. **仅保留精华** — 不复制原始数据（如行情/回测），只保留模式/规则/参数/架构
5. **版本标记** — 每文件末尾注明 `最后更新：YYYY-MM-DD | 来源：<skill_name>`

## 进度

| 域 | 文件数 | 状态 |
|:---|:---:|:---:|
| 1-TRADING | 9 | ✅ 已完成 |
| 2-TECHNICAL | 5 | ✅ 已完成 |
| 3-THEORY | 4 | ✅ 已完成 |
| 4-OPERATIONS | 6 | ✅ 已完成 |
| 5-CHAIN-DEVELOPMENT | 5 | ✅ 已完成 |
