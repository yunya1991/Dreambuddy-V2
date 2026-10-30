# SPEC — 双端研发协作治理（模块租约 + 角色分离 + 文档双向同步）

> 日期：2026-10-30（v2.1：新增 R8「终审权归云端」）
> 阶段：设计（待跨端评审）
> 上游：[SPEC-three-tier-collab-management.md](SPEC-three-tier-collab-management.md)
> 目标读者：项目 owner（单人维护，本地 + 云端各一个 AI 会话）

---

## 零、调研结论（是否合理）

**方向合理，但有 3 处必须收紧、1 项明确不做、1 项残余风险必须承认。**

| 设想 | 判定 | 依据 | 收紧点 |
|---|---|---|---|
| 开发/调研双端参与，GitHub 为中枢 | ✅ | GitOps 单一真源；GitHub 是双方唯一共享、可审计的状态载体 | 明确 main 是唯一真源，两端均为工作副本 |
| 避免两端同时开发同一模块 | ✅ | ownership + 互斥锁；无锁双改同一批文件，rebase 救不回 | 锁必须落 GitHub；本地文件锁对另一端不可见 |
| 一端开发、一端测试 | ✅ | SoD 职责分离 | 必须绑定"非持有方 + 独立会话 + 证据"，否则自证 |
| 文档双侧参与、上传 GitHub、云端即时拉取评审 | ✅ | 文档与代码同源，评审记录随 git 留存 | 文档纳入租约；拉取只做 fetch + 路径级 checkout |
| 反向同步回本地 44 目录 | ✅ | 保证"评审后开发"链条不断 | 同步判定用 commit sha，不引入本地 ACK 状态文件 |
| 设计-评审-开发-测试-部署闭环 | ⚠️ 缺测试门 | 现有 `collab-developer-agent` 自 build/test 并自出 TEST_REPORT | 新增 **G3.5 独立测试/评审门** |
| 分布式锁服务 / 消息队列 | ❌ 不做 | 4C8G + 单人，成本远大于收益 | GitHub Actions + 仓库内租约文件 |

**残余风险（必须承认）**：两端共用同一 GitHub 账号，**"端"无法被技术性强制验证**，只能靠租约声明 + 独立会话留痕 + 分支保护。门禁防"误撞"，不防"蓄意伪造"。真实隔离需双 bot 账号或 GPG 签名身份（P1，见 §3.6）。

---

## 一、现有资产盘点与差距

| 能力 | 已有资产 | 差距 |
|---|---|---|
| 协作规则 | `AGENT协作工具/SKILLS/agent-collab-supervisor/rules.json`（RULE_001~010，含 RULE_007 非所有者评审、RULE_010 共享文件声明） | 规则只在 SKILL 内，**无 CI 强制执行** |
| 协作流水线 | `.github/workflows/collab-developer-agent.yml` / `collab-validator-agent.yml` / `agent-collaboration-claim-guard.yml` | 只有评论字段（`Claim Target`、`冲突门禁结果: SAFE`），**无真实锁**；developer agent 自测自判 |
| 代码门禁 | `ci.yml`、`drift-guard.yml`、`agent-*-guard.yml` | 无"改动是否被租约覆盖"的校验 |
| 文档流转 | `44-.../{docs,review}` 目录 | 单向流程，无反向同步，无文档租约 |
| 三端职责 | `dream-three-tier-collab` SKILL | 未覆盖双端并行；门禁链无测试门 |
| 分支保护 | **main 当前未启用分支保护**（`gh api .../protection` 返回 404） | PR 门禁可被直接绕过；须 owner 开启（P0 前置） |

**结论：不新建体系，全部扩展现有资产。**

---

## 二、设计原则（四条）

1. **单一真源**：`origin/main` 是代码与文档唯一真源；两端目录均为工作副本；**禁止绕 PR 直推 main**（自动化 bot 除外，见 §6.2 白名单）。
2. **租约互斥**：模块级锁，状态存 `44-三端协作架构系统/github/leases/<module-slug>.json`（按模块分文件，随 main 审计，带 TTL）。
3. **角色分离（SoD）**：持有 `dev` 租约方不得对自己的模块出具最终测试/评审结论；新增 G3.5 门。
4. **失败可恢复、冲突硬阻断**：同步失败降级为"待同步"；**互斥冲突一律硬阻断**（宁可不开发，不可双开发）。
5. **终审在云端**：技术文档的最终批准（`review/approved/`）只能由云端评审方出具——云端最贴近生产环境，终审必须建立在生产侧事实（D1-D8 实况）之上；本地最多出具评审意见与建议结论。

---

## 三、模块租约协议

### 3.1 模块定义

| 变更路径 | 模块 ID |
|---|---|
| `44-.../github/leases/**` | `lease`（**特例：申请租约的 PR 自身免租约**，lease-guard 显式豁免） |
| `44-.../docs/**` | `docs:<相对 docs 路径>`（如 `docs:tech/SPEC-xxx.md`） |
| `44-.../review/**` | `review:<相对 review 路径>` |
| `.github/**` | `root:ci` |
| 其余一级子系统（`18-数据获取中心/...` 等） | 取第一级目录名 |
| 根级文件（`CLAUDE.md`/`README.md`/registry 等） | `root:repo` |
| 分支 `hotfix/<id>` | `hotfix:<id>`（**免租约**，24h 内补审 + 留 hotfix 记录） |

> 粒度：一级子系统为默认粒度；docs/review 细分到文件；`root:*` 更细以免一次改 `.github` 锁死全仓。

### 3.2 租约文件与字段

一个模块一个文件：`github/leases/<module-slug>.json`（`docs:tech/SPEC-xxx.md` → `docs__tech__SPEC-xxx.md.json`）。

```json
{
  "schema_version": "1.0",
  "module": "18-数据获取中心",
  "leases": [
    {"end": "local", "role": "dev", "task_id": "T-20261030-001", "session": "trae-local-a1",
     "base_sha": "abc1234", "started_at": "2026-10-30T10:00:00+08:00", "ttl_hours": 24,
     "status": "active", "released_at": null}
  ]
}
```

`role` ∈ `dev | test | review`；`status` ∈ `active | released | expired`。

### 3.3 互斥规则（硬约束）

| # | 规则 | 冲突动作 |
|---|---|---|
| R1 | 同一模块最多 1 个 `active` `dev` 租约 | 拒绝（exit 2） |
| R2 | `test`：须存在**同 task_id 的 dev 租约**（active 或已 released，可继承） | 拒绝 |
| R3 | `review`（文档）：**不要求** dev 前置 | — |
| R4 | `test`/`review` 的 `end` 必须 ≠ dev 租约的 `end`；同端时 `session` 必须不同且留痕 | 拒绝 |
| R5 | 不同模块可并行，不限端 | 允许 |
| R6 | TTL 默认 24h、上限 72h；超期读取时判 `expired`（不依赖定时任务） | 需重新申请 |
| R7 | `root:ci` / `root:repo` 同时只允许 1 个 active 租约（任意角色） | 拒绝 |
| R8 | **终审权归云端**：`review:approved/**` 模块的租约 `end` 必须为 `cloud`；本地端申请或把文档推进到 `approved/` 的 PR 一律阻断 | 拒绝（exit 2） |

> R8 依据：终审要对照生产实况（D1 代码一致性、D4 数据链路、D5 模型质量、D6 风控行为），只有云端能直接观测；本地终审会脱离生产环境。R8 与"单端评审不强制另一端"并不冲突——本地仍可写 `review/feedback/` 出具评审意见，只是不能签发最终批准。

### 3.4 操作入口

| 动作 | 命令 |
|---|---|
| 申请/续期 | `python3 44-.../shared/tools/lease.py claim --module M --end local\|cloud --role dev\|test\|review --task T [--session S] [--ttl 24]` |
| 释放 | `python3 44-.../shared/tools/lease.py release --module M --task T` |
| 查看 | `python3 44-.../shared/tools/lease.py status [--module M]` |
| PR 校验（CI） | `python3 44-.../shared/tools/lease.py check-pr --branch <ref> --body <body> --files <file-list>` |

### 3.5 PR 约定

- 分支：`feat/<task-id>@<end>`（`feat/T-001@local`）或 `hotfix/<id>`。
- PR 描述必填：

```
[协作 PR]
Task ID: T-20261030-001
端: local
角色: dev
模块: 18-数据获取中心
```

- `lease-guard`：PR 每一改动文件 → 模块 → 必须有覆盖 `端+角色+Task ID` 的 active 租约；`lease` / `hotfix:` 模块豁免。

### 3.6 身份可信度（残余风险处置）

| 层 | 机制 | 状态 |
|---|---|---|
| L1（默认） | 分支名 + PR 声明 + 独立 `session` 留痕 + 租约审计 | 落地 |
| L2（可选） | `github/identities.json` 登记两端 author email，CI 校验 author 与声明端一致 | 文件存在则生效，缺失仅告警 |
| L3（P1） | 双 bot 账号或 GPG/SSH 签名提交，CI 校验签名指纹 | 待用户决定 |

**明确不承诺**：L1/L2 下"端"可被蓄意伪造；系统目标是防止无意并发与自证，而非对抗恶意。

---

## 四、角色分离（SoD）与 G3.5

```
设计 → 开发 → PR CI → 独立测试/评审 → 部署窗口 → 部署验证 → 健康检查 → 模型评估
 G1     G2    G3      G3.5（新增）      G4          G5          G6          G7
```

| 门 | 检查 | 失败处理 |
|---|---|---|
| G3.5 | ① 存在 `test`/`review` 租约且非开发方；② 证据含命令、退出码、关键日志行；③ 结论中 `reviewer` 与 `author` 不同 | PR 不得 merge（与 G3 同等） |

**硬约束**：禁止开发方自审自测；禁止同一会话换角色名；必须给可复现证据；模型 promote 规则不受影响。

---

## 五、技术文档双向同步

### 5.1 路径与状态机

| 阶段 | 目录 | 写入方 |
|---|---|---|
| 草稿/调研 | `docs/tech/`、`docs/design/` | 起草方（持 `docs:<path>` 租约） |
| 待评审 | `review/pending/` | 起草方 |
| 评审意见 | `review/feedback/YYYY-MM-DD-<slug>-review.md` | **评审方**（任一端，持 `review` 租约） |
| 通过归档（终审） | `review/approved/` | **仅云端**（R8 硬约束；本地不得写入） |

### 5.2 同步方向

```
本地起草 → PR → main → 云端 docs-sync 拉取(44) → 云端评审+终审(approved) → PR → main → 本地 ff-only 拉取 → 本地开发
云端起草 → PR → main → 本地 ff-only 拉取 → 本地评审(feedback 意见) → PR → main → 云端 docs-sync 拉取 → 云端终审(approved) → 云端开发
```

> 两条路径的**终审都发生在云端**（R8）：本地评审只产出 `review/feedback/` 意见 + 建议结论，`review/approved/` 的签发必须由云端在对照生产实况（D1/D4/D5/D6）后完成；云端终审提交合入 main 后，本地再 ff-only 拉取拿到批准结论。

- **同步判定不设本地状态文件**：`git rev-parse HEAD` == `git rev-parse origin/main` 即"已同步"，否则"待同步"。证据统一为 commit sha（与 D1 同源）。
- **云端拉取契约**：`git fetch` 后先比对"待同步提交的全部变更文件集"——仅当所有变更都落在文档路径（`44-.../docs|review`、`docs`、`developers`）时才执行 `git pull --ff-only`；出现任何代码/配置变更即跳过并交由 `update.sh` + G4。**不做路径级 checkout**（会让工作区相对 HEAD 长期漂移，D1 一致性失真），改为"整提交原子拉取 + 全量路径校验"。
- 云端由两条通道触发：`docs-sync.timer`（15 分钟兜底）+ GitHub Actions SSH（秒级，受 forced command 约束），脚本内置 `flock` 互斥。
- **禁止**两端同时写同一文档；`review/feedback/` 只由评审方写；**`review/approved/` 只由云端写**（R8）。

### 5.3 工具

`44-.../shared/tools/docs_sync.sh`

| 子命令 | 行为 |
|---|---|
| `pull [--end local\|cloud]` | 检查目标路径干净 → `git fetch` → `git merge --ff-only origin/main`（cloud 端仅 44 路径 checkout） |
| `push "<msg>"` | 仅提交 44 目录改动（不夹带运行时文件）→ push 当前分支 |
| `status` | 输出 ahead/behind、是否已同步（HEAD vs origin/main） |

---

## 六、闭环状态机与自动化边界

### 6.1 状态

```
[draft] --评审通过--> [reviewed] --dev租约--> [in_dev] --G3.5--> [tested] --G4/G5/G6--> [deployed]
   └--驳回--> [rejected]        └--撤销--> [draft]
```

单一载体原则：**leases = 谁在做；文档 frontmatter `status:` = 生命周期；目录位置 = 由 CI 与 frontmatter 派生校验**。不新建状态数据库，状态可由 git 历史 + leases + PR 评论重建。

### 6.2 自动化直推白名单（免租约、免 PR）

仅限 `AGENT协作工具/ledger/**` 与 44 目录下的租约文件，由 `agent-collaboration-claim-guard.yml` / `collab-ledger-sync.yml` 的 bot 提交。其余自动化一律不得直推 main。

### 6.3 分支保护前置（P0，需 owner 执行）

`main` 当前**无分支保护**。落地前必须开启：必需检查含 `ci`、`lease-guard`、`guard`，`strict=true`，禁止 force push。命令见 §七 交付物备注。

---

## 七、落地清单

| # | 交付物 | 路径 | 验收 |
|---|---|---|---|
| 1 | 租约工具 | `44-.../shared/tools/lease.py` | `claim/status/check-pr` 可运行；R1-R8 有单测；冲突 exit 2；**R8：本地申请 `review:approved/**` 必须 exit 2** |
| 2 | 文档同步工具 | `44-.../shared/tools/docs_sync.sh` | `bash -n` 通过；`status` 正确识别同步态 |
| 3 | CI 门禁 | `.github/workflows/lease-guard.yml` | PR 事件触发；无租约 PR 阻断；`lease`/`hotfix` 豁免 |
| 4 | 协作 SKILL | **扩展** `dream-three-tier-collab` v1.3（不新建 SKILL） | registry `validate_registry.py` exit 0 |
| 5 | 目录流程 | `44-.../README.md` 更新为双向 + 租约 | 与 SKILL 一致 |
| 6 | 分支保护 | `gh api -X PUT repos/.../branches/main/protection`（owner 手动执行） | 必需检查生效 |

---

## 八、风险与红线

| 风险 | 处置 |
|---|---|
| 租约文件冲突热点 | 按模块分文件，冲突面收敛到单模块 |
| 双端空转互等 | `lease.py status` 显式展示 + TTL 自动过期 |
| 云端拉取覆盖未提交改动 | 只 fetch + 44 路径 checkout；工作区不干净即中止 |
| root 模块过粗 | 拆 `root:ci` / `root:repo` |
| 端身份可伪造 | §3.6 分层处置，明确不防恶意 |

**红线**

1. **禁止**两端同时对同一模块持 `dev` 租约。
2. **禁止**开发方自审自测作为合并依据（G3.5 硬阻断）。
3. **禁止**绕过 PR 直推 main（白名单自动化除外）。
4. **禁止**把租约/ACK 之外的运行时状态（日志、DB、cache、`.sync/`）提交入库。
5. **必须**文档评审意见由非起草方出具并落盘 `review/feedback/`。
6. **必须**"已同步/已评审/已完成"结论附 commit sha 或 PR 编号。
7. **必须**技术文档终审（`review/approved/`）由云端签发（R8）；**禁止**本地端签发最终批准或把文档直接推进到 `approved/`。

---

## 九、与三端协同体系的边界

- 本 SPEC 只治理**研发协作过程**（谁写、谁测、文档怎么流动）。
- 云端八维评审 D1-D8、G1-G4/G5-G7 实现细节、模型双轨仍归 `dream-three-tier-collab`。
- 新增 G3.5 插入既有编号，不重排 G4-G7。

---

## 十、评审闭环（独立评审 → 修订）

| 编号 | 评审意见 | 处置 | 落点 |
|---|---|---|---|
| M1 | 端身份不可验证，G3.5 可自证 | 承认残余风险，分层处置（L1 声明审计 / L2 email 白名单 / L3 签名身份），并明确不防恶意 | §3.6 |
| M2 | 租约路径未被映射，申请租约需先持租约（死锁） | 新增 `lease` 特例，lease-guard 豁免 | §3.1 |
| M3 | 未接入分支保护，且已有 bot 直推 main | 分支保护列为 P0 前置；明确自动化直推白名单 | §6.2 / §6.3 |
| M4 | 云端全仓 pull 绕过 G4，且只校验 44 目录 | 改为 fetch + 44 路径 checkout（独立 worktree） | §5.2 |
| M5 | ACK 文件不入库，另一端与 CI 不可见，构成第二真源 | 删除 ACK 文件，同步判定 = HEAD vs origin/main | §5.2 |
| M6 | test/review 强制 dev 前置导致文档评审无租约 | test 可继承已释放 dev；review 不要求 dev | §3.3 R2/R3 |
| S1 | `root` 过粗 | 拆 `root:ci` / `root:repo` | §3.1 |
| S2 | 不新建 SKILL，避免同 category+role 漂移 | 扩展 `dream-three-tier-collab` v1.3 | §七 #4 |
| S3 | 状态载体过多 | 单一载体原则 | §6.1 |
| S4 | hotfix 缺租约豁免 | `hotfix:<id>` 免租约 + 24h 补审 | §3.1 |
| M7 | （owner 补充）技术文档终审须落在云端，因云端最贴合生产环境 | 新增 R8：`review:approved/**` 仅 cloud 可持租约；两条同步路径的终审均在云端；本地只出 feedback 意见 | §二.5 / §3.3 R8 / §5.1 / §5.2 / §八.7 |
