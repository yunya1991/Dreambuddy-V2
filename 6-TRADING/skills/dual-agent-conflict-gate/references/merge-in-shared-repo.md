# 多代理共享仓库中合并 local+remote 的验证协议（2026-09-14 实战）

## 适用场景
仓库有多个代理以不同 author 身份并行提交（如 GitHub User / workbuddy / github-actions[bot] / 用户名），
需要把本地 main 与 origin/main 合并，并证明"合并引入的新失败 = 0"。

## 核心原则
1. **全程用独立 worktree，绝不 stash/reset 主工作区**（见 SKILL.md P1）。
2. **开始前人工过一遍 conflict_gate 决策规则**（脚本可能 fail-crash，见 SKILL.md P2）。
3. **git add 严格圈定本任务文件**，禁 `add -A`/`add .`（既有提交纪律）。

## 步骤
1. 建独立合并工作树：
   ```bash
   git worktree add /tmp/integrate origin/main
   cd /tmp/integrate && git merge <local-main-sha>
   ```
2. **四层验证 battery**：
   - `py_compile` 全量（compileall -q）：在两侧父分支各跑一遍对比"失败集合"，只有两侧都存在的才算祖传，合并树新增的才算新问题。
   - 导入冒烟：逐个 import 核心模块（本地新增 + 远端新增），证明两侧新代码可共存。
   - 领域 golden/eval 脚本（如有）：在合并树跑，对照基线通过率阈值。
   - pytest 全套 + 失败归因（见下）。
3. **失败归因 = 三 worktree 差分法**（决定性证据）：
   对同一批失败测试，在 local 父、remote 父、合并树三个 worktree **各自独立**跑一遍：
   - 三者失败集合完全相同 ⇒ 两侧原有债（test/code 漂移等），非合并引入，写入报告不阻塞。
   - 仅合并树失败 ⇒ 合并引入，必须修复或暂停上报。
4. **环境噪音单独归类**：网络受限机器上外部 API 超时类失败归为"网络"，不计入代码失败（例：腾讯云大陆 OKX/Binance 全封导致的超时）。
5. **报告格式**（用户偏好"直接说结论"）：结论先行（合并新增失败 = N）→ 证据表格 → 冲突/风险 → 编号决策选项。

## 冲突案例时间线（真实）
- 我在主工作区 `git stash -u`（错误动作）→ 回退了并行代理的 6-TRADING 守卫状态文件。
- 并行代理检测到回退 → 从我的 stash 外科式还原 → 提交恢复 commit（38cd8dd4）到 main。
- 后果：我的合并基线（6dc4a2fd）比 main 落后 1 commit；stash pop 会与该恢复 commit 冲突。
- 处置：暂停 → 向用户结构化报告 → 给出选项：
  - A1 直接 PR 已验证合并（干净、不含他域，但比 main 少恢复 commit）
  - A2 先并恢复 commit 再 PR（需手动解冲突且涉他代理域）
  - A3 暂停 PR 等协调
  - B1 选择性 `git checkout stash@{0} -- <file>` 恢复自己域文件（推荐）
  - B2 暂不恢复 / B3 完整 pop（不推荐）

## Checklist
- [ ] worktree 隔离，未动主工作区
- [ ] 门禁规则人工裁决完成（或脚本修好）
- [ ] 四层验证 battery 全跑
- [ ] 失败三 worktree 差分归因
- [ ] 网络类失败单独归类
- [ ] 冲突以编号选项交用户拍板

---

## 案例二：PR 建成后 main 被并行代理全量重写同一 SSoT 文档（2026-09-14）

- 背景：经 Git Data API 推分支建 PR（66/68 文件干净）；建 PR 期间并行代理向 main 推 4 个提交，把 2 个架构文档全量重写（单文件 4513 行变更）→ PR 变 dirty。
- 我方冲突内容不是琐碎改动，而是**用户批准的 SSoT 新增章节**（PROP 审批号可查）→ 属"大冲突（BLOCK 多项）"，禁止自行裁决，必须交用户。
- **关键技术：包含性检查（grep 标记法）** — 把我方新增章节的标题/关键词逐个 `grep -c` main 新版文档：
  - 全部命中 ⇒ 对方重写已覆盖我方内容，可直接取 main 版，冲突自动消解；
  - 全部为 0 ⇒ 两方向独立演进，我方内容在 main 新版中不存在，须显式决策去留。
  这一步把"有冲突"从模糊状态变成**可裁决事实**，给用户的选项才有依据。
- 交给用户的标准三选项（用户偏好"选项只发数字"）：
  1. **缩 PR**（推荐）：剔除冲突文档，PR 只剩干净代码文件立即可并；文档以 main 新版为准，我方新增章节另起提案、对照新结构重新归位（走架构审批）。
  2. **re-apply**：把我方章节手动归位到 main 新版对应位置，PR 保留全量文件（归位判断可能不符用户架构意图，须事先声明）。
  3. **暂停**：先协调并行代理的文档方向再定。
- **执行用户选择前必须重新核对 main HEAD** — 并行代理可能再次推送，选项所基于的快照会过期。
- 教训：向活跃共享仓库建 PR 前，先查 main 最近提交时间/author；若有并行代理活跃推送，PR 创建后立刻复查 `mergeable_state`，不要默认"建成即干净"。

---

## 上传前盘点：本地未进 origin 的工作分三层（2026-09-15 实战）

用户问"还有没有其他没提交的代码/文档"时，答案几乎从不是单层。把"尚未进 origin/main 的本地工作"拆三层分别盘点，避免漏报，也避免把运行时噪音当真工作上传：

| 层 | 是什么 | 怎么查 | 处置 |
|----|--------|--------|------|
| ① 已提交未推送 | 本地 main 领先 origin/main 的 commit | `git log --oneline origin/main..main` | 区分**真提交** vs **guard/cron 噪音提交**（`grep -viE 'guard\|提醒推送\|approval reminder\|escalation\|sync'`）；真提交可能已被某 squash PR 收录（见下陷阱） |
| ② 未提交工作区 | working tree 相对 HEAD 的改动 | `git status --porcelain` + `git diff --shortstat` | 再分**真代码/文档** vs **运行时噪音**（见清单），只上传真文件 |
| ③ 运行时噪音 | 自动生成的状态/缓存/DB | 见下方 Dreambuddy-V2 噪音清单 | **绝不提交**；靠 `.gitignore` 收口（已 tracked 的须 `git rm --cached`） |

### 关键陷阱：squash PR 的祖先检查会假阴性
`git merge-base --is-ancestor <local-commit> origin/<PR-head>` 对**被 squash 进 PR 的提交返回 false**（SHA 变了），极易误判"这些提交没进 PR"。
- **正解：比内容不比血缘** — `git diff --shortstat origin/<PR-head> main -- <file>`，输出为空 ⇒ PR 已含 main 的该文件版本（squash 快照内容 ≈ main HEAD）；非空 ⇒ main 比 PR 新。
- 抽查 1~2 个核心文件即可定性 PR 与 main HEAD 的内容关系，再判断第②层工作区改动是"PR 之后的新开发"还是"已在 PR 内"。
- 注意 `git rev-list --count origin/main..origin/<PR-head>` 对 squash PR 会返回 1（单快照），不代表只并了 1 个提交的工作量。

### Dreambuddy-V2 运行时噪音清单（git status 常客，全部排除）
```
.cognitive/sessions/*                         （.current / action_chain.jsonl / session.json / suggestions*）
1-ARCHITECTURE/dreamos/cli/.4h_dedup.json, .trade_time.json
1-ARCHITECTURE/dreamos/cli/scheduler_data/*   （coin_pool / orchestrator_v2_state / pool_dynamic_scores / position_snapshot / scheduler_history / scheduler_jobs …）
1-ARCHITECTURE/dreamos/core/memory/execution_feedback.json
1-ARCHITECTURE/dreamos/data/cognitive_lessons.json
11-易经/**/account_baseline.json
14-V15/**/backtest_cache/*, v15_state.json
3-FRONTEND/**/user-preference-memory/anonymous.json
4-MEMORY/0-元记忆/template_mappings.json
4-MEMORY/2-交易记忆单元/bayesian_memories.json
4-MEMORY/data/cognitive_memory.db
**/solution_paths/*.json
18-数据获取中心/data_center.db
```
（2026-09-15 实测：60 个 tracked 改动里仅 ~31 是真代码/文档，~29 是上述噪音；34 个 untracked 里仅 1 个是真新文档，其余 33 是 solution_paths/*.json + data_center.db。即"未提交工作"里往往一半以上是噪音，先过滤再谈上传。）

### 别切主 worktree 的分支（guard cron 占用 main）
Dreambuddy-V2 主工作区由 guard cron 每整点提交到 main。`git switch -c feature` 会让 cron 的下次提交落到错误分支、扰乱自动化。
- 上传第②层工作区改动时**不动主工作区**：用 Git Data API/plumbing 直接在远端重建提交（见 `git-push-via-github-api`），或 `git worktree add` 一棵独立树操作。
- 零风险保全（不需 token、不动仓库）：先把真文件导成 patch 备份 — `git diff -- <真文件…> > /tmp/upload.patch` + 手动复制 untracked 真文档，再谈推送。

### 盘点报告格式（用户偏好"直接说结论"+"选项只发数字"）
结论先行（"是/否，还有 N 个真文件未上传"）→ 三层表格 → 抽查实证（哪个文件比 PR 多几行）→ 上传方案 → 编号决策（新 PR vs 并入现有 PR；是否需要 token）。不要逐文件罗列噪音。
