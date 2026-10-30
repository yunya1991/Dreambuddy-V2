# docs-sync 端到端验证记录（2026-10-30）

> 目的：验证「本地 push 文档 → GitHub Actions SSH 触发 → 云端 ff-only 拉取」的秒级链路。
> 手段：本文件自身即为一次**纯文档变更**，push 后应被云端 docs-sync 拉取。

## 已验证环节

| 环节 | 证据 | 结果 |
|---|---|---|
| 云端脚本可执行 | `/home/luke/dreambuddy/37-一键启动脚本/docs-sync.sh` 权限 775，手工执行输出 `OK: 已同步（d8d6aee679…），无需拉取`，rc=0 | ✅ |
| 云端仓库可达最新 | `git rev-parse HEAD` = `f143abcafe8b4cd520899cdec7b5d89a58716bd5` | ✅ |
| Actions → SSH → 脚本 | `gh workflow run docs-sync.yml` → run `41012445582` success（11s） | ✅ |
| 失败可见性 | 拉取失败时脚本 `exit 2`，Actions step 变红；fetch 失败 FAIL-OPEN `exit 0` | ✅ 设计确认 |
| 未跟踪评审草稿不阻断 | 修复后仅「已跟踪改动」触发 `dirty_worktree` | ✅（f143abcafe 提交） |
| **真实拉取（手工触发脚本）** | `SYNCED: f143abcafe… -> d9179a2002…`，目标文件已落盘 | ✅ |
| **真实拉取（Actions 触发）** | 见下一次 push 的 run 结论（commit `……`） | 待回填 |

## 根因归档（本日两处云端故障）

1. `37-一键启动脚本/` 目录为 `root:root 755`，luke 无法 unlink 该目录文件 → `git pull` 报 `unable to unlink old ... Permission denied`，工作区半更新。
   处置：`chown luke:luke 37-一键启动脚本`，并以 luke 手工 ff-only 收敛。
2. 旧脚本的脏检查把云端侧**未跟踪**评审草稿判为 dirty → `exit 2`，Actions 变红。
   处置：dirty 判定仅取已跟踪改动（`grep -v '^??'`）。

## 结论

文档双向同步链路（P0 timer + P1 Actions 秒级）已可用；代码变更仍按设计**不**经 docs-sync，走 `update.sh` + G4。
