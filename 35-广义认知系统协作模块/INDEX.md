# 35-广义认知系统协作模块 — 文档索引

> **版本**: v1.1 | **更新日期**: 2026-10-12
> **定位**: 跨系统协作设计 SSoT（纯文档统筹层，不含代码实现）
> **上级索引**: [0-系统文档管理/INDEX.md](../0-系统文档管理/INDEX.md) v2.8

---

## 文档清单

| 文档 | 版本 | 职责 | 状态 |
|---|---|---|---|
| [SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md) | v0.2 | 大认知系统进化蓝图：四层架构(L1→L4) + 五系统接线 + PoE/因果/预测编码升级路线 | ✅ 开发完成 (P0-P3 24/24, 2026-10-12 验收通过) |
| [SPEC-Unified-PoE-Framework.md](./SPEC-Unified-PoE-Framework.md) | v2.0 | 统一 PoE 框架：双模式(重型/轻量) + 有界信任传递 + 6 失效条件 | 用户确认 |
| [COLLABORATION-CONTRACT.md](./COLLABORATION-CONTRACT.md) | v1.6 | 跨系统协作接口契约：record_hook/verify_hook/Evidence Ledger/PoE 信任链路 + MCP 写治理 | ✅ 治理已落地 |
| [QUICKSTART-AI-HOST-INTEGRATION.md](./QUICKSTART-AI-HOST-INTEGRATION.md) | v1.0 | 换 AI 宿主 3 分钟接入：安装器/print-config/自检/踩坑固化 | ✅ 新建 |
| [SPEC-ResidualMemory-Admission.md](./SPEC-ResidualMemory-Admission.md) | v1.4 | 残差记忆准入与遗忘治理：不可再推导准入 + 四禁入/四残差/三测试 + 记忆三形态（M1 指针索引 150 容量门）+ 减记忆增能力（缺口适配层 + M1-T 路由表）+ 记忆树与 **D0-D4 级联编排器 + telemetry** + 分级 TTL 两阶段 + 指纹去重 + 近义合并双门 + 树梢痕迹池 + 分级 grace + `verify(supersedes)` + 记忆漂移检测 + degraded 契约 | 🟡 P0-P4 已实施；P3 云端 timer 挂载完成（7 天验收中）；P4 漂移批量 apply 586→0（2026-11-16） |
| [SPEC-ResidualMemory-Admission-REVIEW.md](./SPEC-ResidualMemory-Admission-REVIEW.md) | v2.0 | 一二审记录：一审 3 个 P0（F-0 根因误判/双路径未清/无基线即清空）+ 二审 2 个新 P0（R1 升级路径不可达 / R2 级联删除缺失）+ A1-A5（痕迹归位/指标采集点/degraded），均已修入 SPEC v0.7 | ✅ 全部关闭 |
| [README.md](./README.md) | v1.0 | 模块定位 + 核心原则 + 文档清单 + 子系统关系 | 新建 |

---

## 协作关系图

```
┌──────────────────────────────────────────────────┐
│  35-广义认知系统协作模块（本模块 — 协作设计 SSoT）  │
│  SPEC + 契约定义，不含代码                          │
└─────────┬────────────────────────┬────────────────┘
          │ 定义协作契约           │
          ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐
│ 4-MEMORY        │    │ 33-REA逆向解析工程    │
│ 认知系统实现层   │    │ 重型 PoE + 逆向分析  │
│ cognitive_loop  │    │ DESIGN-PHILOSOPHY-   │
│ _entry.py       │    │ PoE.md              │
│ evidence_ledger │    │ SPEC-工程实践复现器.md │
└────────┬────────┘    └──────────┬──────────┘
         │ record_hook/verify_hook │ Evidence-First
         ▼                         ▼
┌─────────────────┐    ┌─────────────────────┐
│ 2-KNOWLEDGE     │    │ 0-系统文档管理       │
│ RAG + memory_   │    │ 规范/地图/治理       │
│ bridge          │    │ doc_coverage.py     │
└─────────────────┘    └─────────────────────┘
```

---

## 引用本模块的外部文档

| 引用方 | 引用形式 | 说明 |
|---|---|---|
| `4-MEMORY/9-工具与接口/*.py` (17 处) | 纯文本注释 `SPEC: SPEC-CognitiveSystem-Evolution.md §X.X` | 非路径引用，注释指向 SPEC 名 + 章节号 |
| `33-REA逆向解析工程/` 下 PoE 设计文档 | markdown 链接 | 由 SPEC-Unified-PoE-Framework.md 反向引用 |

---

## 维护规则

1. 新增协作 SPEC / 契约修订 → 更新本 INDEX
2. 代码实现层变更 → 检查 [COLLABORATION-CONTRACT.md](./COLLABORATION-CONTRACT.md) 是否需要同步
3. 断链检查由 `0-系统文档管理/4-工具与自动化/link_checker` 自动校验
