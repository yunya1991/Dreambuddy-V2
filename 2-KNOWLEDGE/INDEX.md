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
├── 5-CHAIN-DEVELOPMENT/  # 三链开发方法论
│   ├── INDEX.md
│   ├── D-调研方法论.md
│   ├── Z-规划方法论.md
│   ├── E-执行方法论.md
│   └── 三链接力协议.md
├── 6-PRODUCT-BUSINESS/   # 产品业务与系统工作流程
│   ├── INDEX.md
│   ├── 产品定位与边界.md
│   ├── 核心目录架构.md
│   ├── 系统工作流程总览.md
│   ├── 模块间关系图.md
│   ├── 交易执行链路.md
│   └── 风控体系工作流.md
├── 7-EXTERNAL-RESEARCH/  # 外部资料素材库
│   ├── INDEX.md
│   ├── finance/          # 传统金融调研
│   │   ├── quant-methods/    # 量化方法
│   │   ├── risk-models/      # 风控模型
│   │   ├── market-structure/ # 市场结构
│   │   └── trading-psychology/ # 交易心理
│   ├── github/           # GitHub开源调研
│   │   ├── ml-frameworks/    # 机器学习框架
│   │   ├── trading-systems/  # 交易系统
│   │   ├── data-engineering/ # 数据工程
│   │   └── infra-tools/      # 基础设施工具
│   └── technical/         # 技术方案调研
│       ├── architecture/     # 架构模式
│       ├── algorithms/       # 算法实现
│       └── testing/          # 测试方法
└── 8-AI-COGNITION/       # AI沉淀资料库索引
    ├── INDEX.md
    ├── 认知系统架构.md
    ├── 记忆类型映射.md
    └── 检索指南.md
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
| 1-TRADING | 19 | ✅ 已完成 |
| 2-TECHNICAL | 5 | ✅ 已完成 |
| 3-THEORY | 4 | ✅ 已完成 |
| 4-OPERATIONS | 6 | ✅ 已完成 |
| 5-CHAIN-DEVELOPMENT | 5 | ✅ 已完成 |
| 6-PRODUCT-BUSINESS | 7 | ✅ 已完成 |
| 7-EXTERNAL-RESEARCH | 4+11目录 | ✅ 骨架完成，随开发自动积累 |
| 8-AI-COGNITION | 4 | ✅ 已完成 |
