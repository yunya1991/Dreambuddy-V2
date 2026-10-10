# 2-KNOWLEDGE — 交易系统知识库

> **定位：** 从 Skills 蒸馏的跨领域系统知识，三层分层存储。
> **源：** `~/.hermes/skills/` 中各 SKILL.md
> **消费端：** 飞书知识库文档（https://icnic28nu1x5.feishu.cn/wiki/KOH4wSEcFid298kk7R8cuS7FnTh）
> **同步：** cron 每日审计 → 差异推送飞书

## 目录结构

```
2-KNOWLEDGE/
├── INDEX.md              ← 本文件
├── 0-SCHEMA/             # 知识库Schema与质量标准
│   ├── INDEX.md
│   ├── 使用指南.md
│   ├── 质量标准.md
│   └── 跨域映射.md
├── 1-TRADING/            # 交易领域知识
│   ├── INDEX.md
│   ├── cases/            # 交易案例库（100+案例）
│   ├── 经典模式/          # 经典技术形态与策略
│   ├── V9-马丁基线.md
│   ├── Screen1-七维牛熊评分.md
│   ├── 硬约束总表.md
│   └── ...
├── 2-TECHNICAL/          # 技术运维知识
│   ├── INDEX.md
│   ├── Hermes-架构.md
│   ├── Cron-调度.md
│   ├── 数据管道.md
│   ├── 部署与维护.md
│   └── ...
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
│   ├── 审批工作流.md
│   ├── plans/            # 实施计划
│   └── checklists/       # 检查清单
├── 5-CASE-STUDY/         # 交易案例研究
│   └── 2026-07-15-顶部下跌交易案例-BTC-头肩顶.md
├── 5-METHODOLOGY/        # 方法论（调研/规划/执行）
│   ├── INDEX.md
│   ├── D-调研方法论.md
│   ├── Z-规划方法论.md
│   ├── E-执行方法论.md
│   ├── 三链接力协议.md
│   ├── 回测方法学.md
│   └── 知识库管理框架.md
├── 6-PRODUCT-BUSINESS/   # 产品业务与系统工作流程
│   ├── INDEX.md
│   ├── 产品定位与边界.md
│   ├── 核心目录架构.md
│   ├── 系统工作流程总览.md
│   └── ...
├── 7-EXTERNAL-RESEARCH/  # 外部资料素材库
│   ├── INDEX.md
│   ├── finance/          # 传统金融调研
│   ├── github/           # GitHub开源调研
│   └── technical/        # 技术方案调研
├── 8-AI-COGNITION/       # AI沉淀资料库索引
│   ├── INDEX.md
│   ├── 认知系统架构.md
│   ├── 记忆类型映射.md
│   └── 检索指南.md
├── 9-RAG-INFRA/          # RAG检索基础设施
│   ├── INDEX.md
│   ├── rag_engine/       # 混合检索+重排
│   ├── vector_store/     # 向量存储
│   ├── knowledge_graph/  # 知识图谱
│   └── bridge/           # CBR↔向量桥接
└── wiki/                 # Wiki编译器输出（concepts/entities/sources/syntheses）
    ├── index.md
    ├── concepts/
    ├── entities/
    ├── sources/
    └── syntheses/
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
| 0-SCHEMA | 4 | ✅ 已完成 |
| 1-TRADING | 147（含 115 案例） | ✅ 已完成 |
| 2-TECHNICAL | 10 | ✅ 已完成 |
| 3-THEORY | 4 | ✅ 已完成 |
| 4-OPERATIONS | 14 | ✅ 已完成 |
| 5-CASE-STUDY | 1 | 🟡 起步 |
| 5-METHODOLOGY | 8 | ✅ 已完成 |
| 6-PRODUCT-BUSINESS | 7 | ✅ 已完成 |
| 7-EXTERNAL-RESEARCH | 26 | ✅ 骨架完成，随开发自动积累 |
| 8-AI-COGNITION | 4 | ✅ 已完成 |
| 9-RAG-INFRA | 7 | ✅ v2.0 |
| wiki | 24 | ✅ 编译器自动维护 |
