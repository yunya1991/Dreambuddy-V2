# DreamOS 渐进式对话模式（先呈现后追问）

> PROP-20260829D Phase 3 — prompt/skill 层，零代码改动
> 生效日期：2026-08-29 ｜ 状态：已实施（灰度期）

## 一句话

**首答轻量呈现，追问再深化**——把完整编排的决策权交还用户，
用 `phase` 参数控制 DreamOS 一次跑多深。

## 三档对话协议

| 用户行为 | 调用方式 | DreamOS 行为 |
|---|---|---|
| 首次提问（默认） | `dreamos_run_analysis(user_input, ...)` | 完整编排（等同现状） |
| 首次提问（轻量模式） | `dreamos_run_analysis(..., phase=1)` | 仅必要节点，返回 `deferred_nodes` + `next_step_hint` |
| 用户追问「展开/深入/详细」 | `dreamos_run_analysis(..., phase=2)` | 完整执行（深化） |
| 简单查询（价格/仓位） | 普通调用 + `DREAMOS_PHASED_ORCHESTRATION=on` | T0 零编排直答（`mode=T0_direct_answer`） |

## Hermes 呈现规范（必须遵守）

1. **先呈现**：把 `action/confidence/rationale` 直接给用户，不堆砌中间节点细节。
2. **后追问**：若响应含非空 `next_step_hint`，在结论末尾附一句深化引导
   （例：「如需展开资金费率/持仓量/情报监控分析，可继续追问」）。
3. **不越权**：`deferred_nodes` 是「可选深化项」，不是「缺失项」——
   不得向用户暗示首答不完整或有遗漏。
4. **T0 直答**：`mode=T0_direct_answer` 时直接报 `market_snapshot`，
   不触发任何分析话术。

## 门禁与灰度

- `phase` 参数显式传入才生效；缺省 = 完整编排（零回归）。
- T0 短路与 LLM 兜底跳过由 `DREAMOS_PHASED_ORCHESTRATION=on` 门禁，
  默认关闭。灰度期观察 `~/.dreamos/phased_shadow.jsonl` 分级分布。
- 影子日志字段：`ts/tier/rule_hit/intent_type/msg_len`。

## 验收锚点（AC 对照）

- AC1 轻量首答：`phase=1` → 节点 ≤5、估算 tokens 显著下降 ✅（1000 vs 5300）
- AC2 分级一致率：黄金集 23/23 = 100% ✅
- AC3 零回归：`phase` 缺省编排与基线快照逐字段一致 ✅
- AC4 节省可观测：`estimated_total_tokens` + 影子日志 ✅
- AC5 T0 直答：1.6ms、0 tokens ✅

## 关联

- 提案：`3-EVOLUTION/proposals/PROP-20260829D-DREAMOS-复杂度分级渐进式编排.md`
- 黄金集：`dreamos-tests/golden_set_complexity.json`
- 基线快照：`dreamos-tests/baseline_complexity_snapshot.json`
- 复跑：`python3 dreamos-tests/test_complexity_grading.py golden|baseline`
