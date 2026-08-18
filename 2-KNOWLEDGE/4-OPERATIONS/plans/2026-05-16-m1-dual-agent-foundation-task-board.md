# M1 Dual-Agent Foundation Task Board

## Milestone
- `M1 dual-agent-collaboration-foundation`
- Active branch: `milestone/dual-agent-foundation`

## Execution Policy
- Default mode: `PHASE_BROADCAST`
- Owner directories default to parallel progress inside declared scope
- Direct takeover is allowed only for small, local, deterministic fixes and only with explicit user authorization

## Direct Takeover Allowlist
- wrong export / wrong symbol fix
- pseudo test / invalid assertion fix
- relative import path fix
- `NodeNext` / `ESM` `.js` extension fix
- local explicit typing fix
- build dependency / type dependency fix
- small-scope lint or build fix

## Strong Sync Required When
- touching shared boundaries
- touching frozen contracts
- changing ownership scope
- changing branch or milestone closeout strategy
- preparing milestone or `main` merge
- scope escalates from local fix to architecture adjustment

## SOLO First Batch
| ID | Task | Status |
|----|------|--------|
| A1 | 固化 checklist、模板、contracts 目录 | ✅ Done |
| A2 | 冻结 `health-summary.v1.json` | ✅ Done |
| A3 | 冻结 `trace-summary.v1.json` | ✅ Done |
| A4 | 冻结 `route-decision-summary.v1.json` | ✅ Done |
| A5 | 冻结 `workflow-summary.v1.json` | ✅ Done |
| A6 | 建立里程碑分支并准备收口 | ✅ Done |

## Claude Code First Batch
| ID | Task | Status |
|----|------|--------|
| C1 | 按冻结 contracts 设计页面数据 adapter 结构 | ⏳ Pending |
| C2 | 用 mock 数据先起 `ops-ui` 页面壳 | ⏳ Pending |
| C3 | 准备 trace / health / workflow 三类卡片的数据消费边界 | ⏳ Pending |
| C4 | 不改共享 contracts，只围绕页面层推进 | ⏳ Pending |

## Shared Freeze Items（进入强同步前禁止修改）
- `health-summary.v1.json`
- `trace-summary.v1.json`
- `route-decision-summary.v1.json`
- `workflow-summary.v1.json`
- 顶层 `README`
- 顶层 spec 索引

## Do Not Touch Without Re-Assignment
- `7-ARTIFACT-HUB-V2/src/**`（SOLO 主责，`7-ARTIFACT-HUB-V2/src/ops-ui/**` 页面层目录除外）
- `7-ARTIFACT-HUB-V2/src/ops-ui/**`（Claude Code 主责，用于 C1/C2/C3 页面层任务）
- `dreambuddy/meta/**`（SOLO 主责）
- `dreambuddy/config/**`（SOLO 主责）
- `docs/superpowers/contracts/**`（SOLO 主责）

## Conflict Gate
每次任务前运行：
```bash
python3 AGENT协作工具/SKILLS/dual-agent-conflict-gate/conflict_gate.py \
  --agent <claude|solo> \
  --task "<任务名>" \
  --files "<文件列表>" \
  --contracts "<契约名列表>"
```

记录要求：
- 将 `decision` / `reason_codes` 写入任务卡或 PR 结构化评论
- 若命中共享边界，转入强同步收口模式，而不是继续默认并行
- 若为白名单接管，需在评论中显式写明 `Direct Takeover`

## Exit Criteria
- [ ] SOLO 与 Claude Code 首批任务均已完成
- [ ] 共享冻结项无冲突
- [x] `milestone/dual-agent-foundation` 已建立并可收口
- [x] 下一里程碑进入 `ops-ui` 骨架阶段，Claude Code 可在 `7-ARTIFACT-HUB-V2/src/ops-ui/**` 内推进页面层任务
