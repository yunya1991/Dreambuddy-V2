# 46-DSH架构

> **创建**: 2026-11-02 ｜ **定位**: DSH(DeepSeek Harness)架构相关技术文档的统一归集域
> **背景**: 本项目 DSH (0.1.5-rc.2) 经确认为 DeepSeek Harness;DeepSeek 2026-10-31 发布 Super-agent 架构(Router/Worker 双层+事件驱动+存算分离+Watchdog)并开源原型 dsh-superagent-prototype(MIT,Harness bundle)。本域承接相关架构设计、SPEC 与评审产物。
> **口径声明**: 一律使用 v4.1 新 SACG 口径(S=认知规划/A=OKR验收/C=执行驱动/G=压缩沉淀),旧口径已作废;架构总览以 SYSTEM_ARCHITECTURE_OVERVIEW v4.1(SSoT)为准。

## 目录结构

```
46-DSH架构/
├── README.md                              # 本文件(域定位+索引)
└── docs/
    └── tech/                              # 技术文档与 SPEC
        ├── ANALYSIS-SUPERAGENT-ARCH-DATAFLOW.md   # 双维梳理(定稿)
        ├── DESIGN-SUPERAGENT-FUSION.md            # 融合设计 v0.2(待复核)
        ├── REVIEW-SUPERAGENT-FUSION-v0.1.md       # 同行评审报告
        ├── SPEC-EVENT-DRIVEN-L1-GATEWAY.md        # 事件驱动 L1 网关 v0.2(待复核)
        ├── DESIGN-DSH-ARCH-UPGRADE-v0.2.md        # 域主线设计(决议落定)
        ├── ANALYSIS-L0-MCP-ENCAPSULATION.md       # MCP 化评估(归档,以 47 为准)
        └── REPORT-L0-MCP-DSH-IMPACT-v1.1.md      # MCP 影响报告(归档,以 47 为准)
```

## 本域文档

| 文档 | 状态 | 说明 |
| --- | --- | --- |
| [docs/tech/SPEC-EVENT-DRIVEN-L1-GATEWAY.md](docs/tech/SPEC-EVENT-DRIVEN-L1-GATEWAY.md) | 🟡 v0.2 待复核 | 事件驱动 L1 网关;已按评审修订(M3/m2/m3/m4+五系统口径) |
| [docs/tech/ANALYSIS-SUPERAGENT-ARCH-DATAFLOW.md](docs/tech/ANALYSIS-SUPERAGENT-ARCH-DATAFLOW.md) | ✅ 定稿 | Super-agent×DreamOS 架构与数据流双维梳理(评审输入件) |
| [docs/tech/DESIGN-SUPERAGENT-FUSION.md](docs/tech/DESIGN-SUPERAGENT-FUSION.md) | 🟡 v0.2 待复核 | 融合设计(借壳灌芯);已按评审修订(M1/M2+五系统口径+§七护城河) |
| [docs/tech/REVIEW-SUPERAGENT-FUSION-v0.1.md](docs/tech/REVIEW-SUPERAGENT-FUSION-v0.1.md) | 🟡 修改后接受 | 同行评审报告(Major 4 / Minor 4,待修订复核) |
| [docs/tech/ANALYSIS-L0-MCP-ENCAPSULATION.md](docs/tech/ANALYSIS-L0-MCP-ENCAPSULATION.md)（📚 评估归档,实现以 47 为准） | 📚 已归档 | L0 能力 MCP 化评估(定位=对外出口,内部仍 in-process;六域分级) |
| [docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md](docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md) | ✅ v0.2 决议落定,可进 P0 | **域主线设计**:DSH 架构升级(七层目标架构 + 10 条 ADR + P0-P3 路径 + 7 红线) |
| [docs/tech/REPORT-L0-MCP-DSH-IMPACT-v1.1.md](docs/tech/REPORT-L0-MCP-DSH-IMPACT-v1.1.md)（📚 评估归档,实现以 47 为准） | 📚 已归档(v1.1 勘误) | **正式报告**:L0 MCP 封装对 DSH 升级的影响评估与建议(六维矩阵+风险册+分阶段路线) |

## 相关文档(物理位置不动,避免断链;本表为导航)

| 文档 | 位置 | 关系 |
| --- | --- | --- |
| Super-agent 调研与对比分析 | [2026-11-02-DeepSeek-Super-agent架构调研与DreamOS对比分析.md](../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-02-DeepSeek-Super-agent架构调研与DreamOS对比分析.md) | 调研依据(含第八/九章专项分析) |
| SACG-A × Super-agent 连接 SPEC | [SACG_A_SUPERAGENT_CONNECTION_SPEC.md](../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md) | 姊妹 SPEC(契约桥接 P0) |
| 系统架构总览 v4.1 | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) | 口径唯一依据(SSoT) |
| DSH Subagent 详设 | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../../1-ARCHITECTURE/dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) | C 层执行体现状 |
| RESEARCH_DEEPSEEK_HARNESS | [RESEARCH_DEEPSEEK_HARNESS.md](../../1-ARCHITECTURE/前端设计/RESEARCH_DEEPSEEK_HARNESS.md) | Harness 机制调研 |
| SACG↔Harness 映射(旧口径,已归档) | [RESEARCH_SACG_HARNESS_MAPPING.md](../../1-ARCHITECTURE/RESEARCH_SACG_HARNESS_MAPPING.md) | 历史留档,禁止作为实现依据 |
