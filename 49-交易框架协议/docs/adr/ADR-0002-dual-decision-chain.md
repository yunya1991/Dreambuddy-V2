# ADR-0002: Dual Decision Chain and 50-NN Contradiction Evaluator

- 状态：proposed（待评审）
- 日期：2026-11-07
- 决策人：49 交易框架协议 owner
- 关联：SPEC-49 v0.14；FinalDecisionSignal v1；SignalSchema v1；MacroElasticConstraint v1；48/42/43/50

## Context

23 四层闭环自进化交易架构已稳定运行，并已形成完整的内部链路（SubSystemBridge → `_discover_paths` → 矛盾识别 → 路径选择）。若把 42 协调层的子系统信号直接并入 23，会改变其已验证链路，并让对照实验失去独立基线。

同时，42 已完成 P1-01～P1-07：8 源总线、TTL/去重、路径环境变量、11 子池状态文件、canonical source、参数分发、可观测性、`run_bus` 入口。上游 40→43 已能产出弹性约束（资产偏置/多空数量/仓位/杠杆方向），但尚未字段化落齐。

## Decision

1. **采用双决策链**：
   - **NN 闭环链**：39（L0 MCP）/ 9（纳入 48）+ 全链路交易数据 → **48（40 的唯一对接口）** → 40 → 43 弹性约束 → 42 8 源总线 → **50-NN主矛盾评估器** → 执行层 13/16/22 + 11 执行器 → 结果回 48。
   - **23 自进化链**：保持独立、自行进化，作为对照实验。
2. **50 独立实现**：不 import 23 的运行时模块/状态；23 只提供**可参考/可复制的主矛盾架构设计**，不构成持续基因流或运行时依赖。
3. **基因注入方向为 NN → 23**：经原 42→23 shadow 端口，选择性注入 NN 验证过的优质基因（维度口径、置信度校准、证据融合能力）；必须 shadow、可回滚、不破坏 23 主链。
4. **48 升级为 40 的唯一对接口**：39 经 L0 MCP、9 纳入 48 统一口径；全链路交易数据统一进 48；训练建议制，遵守 40 P5/P6 门禁（DEC-29）。
5. **弹性约束四项**：资产偏置（数量）、相关资产多空数量偏置、仓位约束、杠杆约束；只作用于最终仓位/开仓许可，不进入矛盾评分。
6. **契约**：50 输出复用 FinalDecisionSignal v1；新增 `source=50-nn`（additive）；需更新 `contract_manifest.v1.json` 并在 ADR 记录，不改 v1 必填字段。
7. **执行权**：`execution_rights` 分区；50 初期 paper-only；23 保持 live 现状；同一标的同时刻单出口；live 灰度需评审。

## Consequences

- 23 生产链路零改动，对照实验有效；NN 链可独立迭代、独立回滚。
- 运维与治理成本增加：双链并行、双套监控、双套训练数据；需 gene registry 与 A/B 评审。
- 50 需要独立实现 23 的主矛盾架构（可复制后适配），存在代码漂移风险；通过 gene registry + 一致性测试 + 定期评审控制。
- 与 DEC-02“23 唯一最终决策出口”冲突：本 ADR 定义**过渡期**双链架构，最终由 ≥4-8 周对照数据裁决收敛方向（DEC-43）。

## Contract Impact

- Breaking：无。
- Additive：`FinalDecisionSignal v1` 的 `source` 枚举新增 `50-nn`；`contract_manifest.v1.json` 更新。
- 不改：SignalSchema v1 / FinalDecisionSignal v1 / MacroElasticConstraint v1 / UpperLayerContext v1 的必填字段与语义。

## Alternatives

1. 直接改造 23 承接 42 信号：侵入已验证链路，对照实验失效，回滚成本高。
2. 50 直接 import 23 模块：运行时耦合，23 重构会传导，且共享全局状态/W6 存储，违背隔离目标。
3. 不建 50，仅保留 23：无法形成独立 NN 闭环，也无法对照验证。

## Rollback

- 50 全部开关默认关闭（`ENABLE_50_* = 0`）；置 0 即回 23 单链。
- 删除/停用 50 不影响 23、40、42、48。
- 执行侧回滚优先 `execution_rights=disabled` + 13 风控拦截。
- 验证：50 shadow 报告 + 49 rollback drill（扩展 50 开关后）。