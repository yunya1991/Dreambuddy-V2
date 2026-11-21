---
name: dreamos-dev
description: "DREAM 架构落地的元 SKILL（唯一入口）：以 run 绑定 + G0-G5 机器可判定门禁驱动工程开发流程，只做路由与门禁，不内联实现。当需要按 SACG 口径开工、给开发挂 run_id/model_id/phase、跑 G0 绑定检查或 G3 越界检查、判断阶段是否可推进时调用。"
version: 0.1.0
created: 2026-11-12
updated: 2026-11-12
license: Internal
status: active
category: orchestration
triggers: [开工, run绑定, G0, G3, 门禁, 阶段推进, 架构落地, dreamos-dev]
depends_on: [dream-rea-architecture-query, dream-arch-research-orchestrator, dream-tdd-dev-workflow, dream-acceptance-verify, dream-completion-evolution-workflow]
provides: [run-binding-gate, dev-phase-machine, gate-rules, dev-node-mapping]
cognitive_links: []
---

## 定位

薄提示 + 厚契约：**判定在 `contracts/` 与 `scripts/`，不在本文件**。本 SKILL 只做三件事——建 run、判 G0/G3、按 `routing.yaml` 分派 owner SKILL。架构分层唯一为 SACG（v4.2），本 SKILL 不新增层。

上游依据：`1-ARCHITECTURE/specs/DREAM_ARCH_LANDING_SPEC.md`（§4 缺口、§5 形态、§6 门禁、§7 状态机）。

## 开工三步

1. **建 run**（`run_id` 直接取 `trace_id`，不新造 ID；人工改动 `model_id=human`）

```bash
mkdir -p .runs/<run_id>
# 写 .runs/<run_id>/run.json：{run_id, model_id, phase:"D0-intake", created_at, task{intent,owner_skill,scope[]}}
```

2. **过 G0**（不过即拒开工，0 例外）

```bash
python3 .trae/skills/dreamos-dev/scripts/g0_check.py --run .runs/<run_id>/run.json
```

3. **分派**：按 `routing.yaml` 找 owner SKILL，进对应阶段；实现/验收分离（写代码者不得自评）。

## 阶段与门禁

| phase | DEV 节点 | gate | 产物 | 不过怎么办 |
|---|---|---|---|---|
| D0-intake | DEV-intake | G0 | run.json | 硬拒开工 |
| D1-context | DEV-context | G1 | context.json | 退回 D1（pending:SPEC-A，FAIL-OPEN） |
| D2-plan | DEV-plan | G2 | plan.md | 退回 D2；计划须含验收标准/falsifier/回滚/影响面/复用盘点 |
| E1-execute | DEV-exec | G3 | changes.json | 越界即停 → 回 D2 |
| A1-verify | DEV-verify | G4 | acceptance.md | 不得宣称完成；五维证据须带 command + exit_code |
| M1-settle | DEV-settle | G5 | settle.json | 不得关闭 run |

G3 越界检查：

```bash
python3 .trae/skills/dreamos-dev/scripts/g3_check.py --run .runs/<run_id>/run.json
```

当前可机器判定：G0/G1/G2/G3/G5 全部脚本化（`scripts/g?_check.py`），G4 可用命令为 tsc/build/lint/test；`check:contracts`/`check:boundary` 属 SPEC-C 待建，保持 `pending:SPEC-C` + FAIL-OPEN。

## 契约

| 文件 | 作用 |
|---|---|
| `contracts/run.schema.json` | run 绑定契约（run_id/model_id/phase/task/scope/evidence） |
| `contracts/phases.yaml` | 六阶段状态机（phase 枚举唯一来源） |
| `contracts/gates.yaml` | G0-G5 规则 + 可用证据命令 + pending 标记 |
| `contracts/dev_nodes.yaml` | DEV-* 节点映射 + 开发信号阈值（部分 uncalibrated） |
| `routing.yaml` | 任务类型 → owner SKILL |
| `scripts/g0_check.py` / `scripts/g3_check.py` | 可执行门禁（输出 JSON 证据 + 退出码） |

## 不做

- 不新增架构层、不复活 `1-ARCHITECTURE/dreamos/`、不用旧 SACG 口径。
- 不在本文件内联实现步骤（缺项补 `routing.yaml`）。
- 不新建事件总线/状态库/计划格式/ID 体系/鉴权中间件（分别由 SPEC C-3/B-7/B-5/C-C7/C-C6 承担）。
- 不让 C-Drive 直接改代码；不在提示词里实现门禁判定。
