# PROPOSAL — D3 在线 A/B 实验设计协议 v1.0

> **状态**: 🟡 待评审（GAP-3 出口，供 DreamOS / 35-广义认知 / 48 域评审）
> **日期**: 2026-11-12
> **归属**: 48-涌现架构（判据与实验协议）；实现归 DreamOS / 35-广义认知
> **来源**: 缺口清单 v1.1 GAP-3 + D2-D3-CHAIN-SSOT §D3（D3-A/D3-B 均为代理标签+离线反事实，未接在线 A/B）
> **前置**: D3-A（TOP1=0.908 vs 规则基线 0.886）与 D3-B（召回步数 8.10→1.0）已 formal candidate

---

## §0 设计目标

把 D3 从『task_type 代理标签 + 离线反事实』升级为『在线真实接受率/纠正率』验证，回答：意图预测与知识组合在真实使用中是否缩短到达正确动作的路径。

## §1 实验设计（2×2 因子）

| 臂 | 意图预测 | 知识组合 | 说明 |
|---|---|---|---|
| A（基线） | off | off | 现状：无预测无组合 |
| B | on | off | 仅预测：展示下一意图建议 |
| C | off | on | 仅组合：展示知识组合（memory/SKILL/doc） |
| D | on | on | 预测+组合联动 |

- **随机化单元**: 会话（session_id），按日交替分配（避免同会话内臂切换污染）
- **主终点（primary endpoint）**: time-to-correct-action（从会话开始到用户确认正确动作的时长）
- **次终点**: 接受率（建议被采纳比例）/ 纠正率（用户纠正建议后系统学习比例）/ 澄清轮次

## §2 数据采集（最小埋点集）

```
intent_predicted   — 预测事件（含 top1/top3 与置信度）
combo_presented     — 组合展示事件（含组合成员 id）
user_action         — 用户动作（accept / reject / modify / ignore）
time_to_action      — 预测/展示 → 动作的时长
session_meta        — 会话元数据（arm / task_type 代理标签）
```

落盘：`48-涌现架构/events/d3_online_ab/*.jsonl`（append-only，event_id 幂等，FAIL-OPEN）

## §3 判定标准（预注册）

1. **主检验**: D 臂 vs A 臂 time-to-correct-action，双侧 t 检验 p<0.05，且效应量 Cohen's d ≥ 0.3
2. **因子分解**: B/C 臂单独 vs A 臂，识别预测与组合的独立贡献（对应 E1 组合泛化判据）
3. **样本量**: 每臂 ≥ 50 会话（按 D3-A 的 273 test sessions 规模，预计 2-4 周积累）
4. **四态判定**: candidate（主检验通过）/ falsified（方向相反显著）/ inconclusive / insufficient_data

## §4 隐私与安全约束

- 会话内容不落盘，仅落盘事件元数据与动作标签（hash≠匿名化，访问控制沿用 35 域）
- 全部 shadow 展示（建议仅展示，不自动执行），FAIL-OPEN
- 用户可随时关闭（opt-out），关闭会话不入统计

## §5 实施依赖

| 依赖 | 归属 | 状态 |
|---|---|---|
| 意图预测服务化（D3-A 模型在线推理） | DreamOS | 待实现 |
| 知识组合展示接口（D3-B 组合在线推送） | 35-广义认知 | 待实现 |
| 埋点与分流 | DreamOS + 48 | 本协议定义，待实现 |

## §6 评审请求

1. DreamOS：裁决预测服务化与分流实现排期
2. 35-广义认知：裁决组合展示接口与隐私约束
3. 48 域：确认判定标准预注册后，纳入 verdict 仪表盘第 11 个实验
