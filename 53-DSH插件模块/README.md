# 53-DSH插件模块

> **创建**: 2026-11-12 ｜ **定位**: DSH (DeepSeek Harness) Cordis 插件生态的接入域 —— 消费社区插件、封装 L0 能力为 DSH 插件、规划插件治理层
> **背景**: 系统底层基于 DSH v0.1.5-rc.2，其 Cordis「一切皆插件」架构提供了天然的插件扩展能力。当前 DSH 社区已积累 25,000+ 插件 (dsh.so)，且 Creator mode 可对话写插件。本域承接"接入生态 + 反向赋能 + 治理规划"三维工作。
> **上下游**: 上游 —— L0 六域能力 (认知/检索/REA/评测/金融语义/数据)、47-MCP管理系统、46-DSH架构 v0.2 升级路径；下游 —— DSH Worker 工具面、42 协调层插件总线扩展

## 目录结构

```
53-DSH插件模块/
├── README.md                                    # 本文件 (域定位+索引)
├── SPEC-53-DSH插件生态接入总规范.md               # 核心 SPEC (§九 含落地进展)
├── plugin_whitelist.yaml                        # 插件白名单唯一事实源 (deny-by-default)
└── check_whitelist.py                           # 白名单校验器 (按 profile 校验)
```

## 本域文档

| 文档 | 状态 | 说明 |
| --- | --- | --- |
| [SPEC-53-DSH插件生态接入总规范.md](SPEC-53-DSH插件生态接入总规范.md) | 🟢 v0.2（§九 已落地） | **核心 SPEC**: 三维接入 (消费/封装/治理) + 技术规范 + 分阶段路线 + 7 条 ADR |
| [plugin_whitelist.yaml](plugin_whitelist.yaml) | 🟢 v1 | 插件白名单：11 个自有 approved + 5 个社区 candidate + 交易热路径 forbidden 通配 |
| [check_whitelist.py](check_whitelist.py) | 🟢 v1 | 校验器：未登记/越 profile/forbidden/未 sandbox 实测 → 退出码 1 |


## 相关文档 (导航)

| 文档 | 位置 | 关系 |
| --- | --- | --- |
| DSH 架构升级方案 v0.2 | [46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md](../46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md) | 上层架构约束 |
| MCP 管理系统 SPEC | [47-MCP管理系统/README.md](../47-MCP管理系统/README.md) | L0 能力封装的当前形态 |
| 42 协调层 (插件总线) | [49-交易框架协议/SPEC.md §42](../49-交易框架协议/SPEC.md) | 内部插件治理参考 |
| Cordis 官方教程 | https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/ | 插件开发规范依据 |
| DSH 插件目录 (社区) | https://www.dsh.so/ | 社区插件来源 |
| DSH GitHub (官方) | https://github.com/deepseek-ai/deepseek-harness | 底层源码 |
| Cordis 论文 | https://arxiv.org/abs/2608.25512 | 架构原理论证 |
