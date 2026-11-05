# 48-涌现架构

> **定位**: 智能涌现（emergence）的研究、度量与实验域——研究系统何时/如何表现出组件不具备、不可从单组件预测的整体能力，并**以可证伪的度量**追踪涌现是否真实发生。
> 不是哲学讨论域：一切涌现主张必须落到可度量指标与可复现实验。

## 为什么独立成域

涌现横跨三个既有域但不属于任何一个：

| 域 | 涌现用到的资产 | 为什么涌现不放它里面 |
|---|---|---|
| 35-广义认知（C1-C4） | GWT Workspace Bus、记忆蒸馏、hermes 反思 | 35 管认知系统内部定义，涌现还要动交易架构 |
| 23-四层闭环 / 46-DSH | DomainCouplingHead、MoE、做梦器、CBR 案例库 | 23/46 管交易策略与进化闭环，涌现是跨系统现象 |
| 47-MCP管理系统 | 壳间广播通道（L0-I） | 47 是纯文档统筹层，放不下实验与度量实现 |

## 边界声明（硬约束）

- **不重复定义**：C1-C4 认知四层以 35 为准；L0/L1 契约以 46/47 为准；本域只引用不复制
- **不改写既有门禁**：ablation gate / PSI 阈值等不放宽（VM-1793798309647 硬约束）
- **度量先行**：任何"涌现出现"的主张必须先在 `metrics/` 有可复现数据，否则视为假设
- **FAIL-OPEN**：涌现实验不得影响生产交易链路，全部 shadow 模式先行

## 核心判据速查（详见 SPEC §1）

涌现判定五判据：E1 组合泛化 / E2 自生成目标 / E3 非线性耦合 / E4 自指纠错 / E5 规模相变。
当前系统状态：E4 部分具备，E1-E3 有种子未验证，E5 无度量。

## 文档清单

| 文档 | 职责 | 状态 |
|---|---|---|
| [docs/tech/SPEC-EMERGENCE-EVOLUTION-v0.1.md](./docs/tech/SPEC-EMERGENCE-EVOLUTION-v0.1.md) | 涌现评估 + 判据 + 缺口 + Phase E0-E6 实施路径 | 🟡 v0.5：六维实证评审封口（第三轮，修改后接受）；E0a/E0b/E4a 已落盘（2026-11-05） |
| [docs/tech/REVIEW-CHECKLIST-v0.1.md](./docs/tech/REVIEW-CHECKLIST-v0.1.md) | SPEC 评审六维检查清单（引用存在性/数据健康度/版本一致性/存量盘点/门禁强制等级/可观测性） | ✅ v0.1：SPEC 升版评审必跑 |
| docs/tech/research/ | [LLM 涌现调研](./docs/tech/research/RESEARCH-LLM-EMERGENCE-v0.1.md) + [生物学原理调研](./docs/tech/research/RESEARCH-BIO-EMERGENCE-v0.1.md) | ✅ v0.1 完成（60+ 来源） |
| experiments/ | 可复现实验记录（反事实验证、广播联动观测） | 🟡 E0b 回放器落盘：`replay/replay_decisions.py`（shadow/FAIL-OPEN；支持跨天日志回退），`registry/run_human_baseline.py` 产出 OOS 基线（33 笔实盘）；🟡 E3 落盘（2026-11-05）：`e3_coupling/retrain_head_shadow.py`（120 步 shadow 重训，regime 32/32/32 分层，final_loss 0.013，生产 static JSON/ckpt 零触碰）+ `e3_coupling/coupling_counterfactual.py`（对角 ridge 严格抽项 + 置换检验 + 方向检查 + insufficient_data 联动 E6 需求单）；真实评估：生产 coupling falsified（p=0.003 方向负，β 原型第二次证伪），重训后 inconclusive（方向扳正 +5.38%，p=0.055 差一步显著）；14 测试全绿 |
| metrics/ | emergence_metrics.jsonl 历史快照 | 🟡 E4a 骨架落盘：`metrics/emergence_metrics.py`（含 M7 需求闭环 + M1 广播联动 + M3 反事实耦合字段），云端每日 06:10 timer（`dreambuddy-emergence-metrics.timer`）持续快照 |
| registry/ | E0a 配置基线 + E6 需求闭环设施 | 🟢 E6 基础设施落盘（2026-11-05）：`capability_gaps.py` 需求单存储 + `gap_router.py` 路由器 + `gap_backfill_verify.py` 回填验证；15 测试全绿，L1 验收（3 缺口全链路）通过；真实冒烟首单 GAP-20261105-64d7320e 闭环。回填验证数据源口径实证修正：all_trades.jsonl（止 10-13）→ bcrm_trades.db（与 E0b 同源） |
| bus/ | E1 广播总线接线 + shadow 订阅者 + M1 度量 | 🟢 E1 基础设施落盘（2026-11-05）：`emergence_bus.py`（3σ 点火 + 接线复用 4-MEMORY `workspace_bus.py` + shadow envelope 落盘 `events/emergence_shadow/`，开关 `EMERGENCE_BUS=1`/flag 默认关）+ `shadow_subscribers.py`（rea/eval/data 兴趣规则 + watchlist 动作下限）+ `m1_linkage.py`（M1=actions/consumed）+ `anomaly_probe.py`（coupling 矩阵 3σ 探测）；11 测试全绿；真实演示 PSI z=4.2 突刺 → eval 动作，M1=0.5。剩余：7 天 shadow 跑数 + ≥1 次非预设联动候选（人工复核） |

## 维护

- 新增/修订 SPEC、实验、度量口径时更新本 README
- 由 `0-系统文档管理/4-工具与自动化/doc_coverage.py` + `link_checker` 校验断链
