# 44 三端协作架构系统

本架构用于云端、开发者、GitHub 三方协作，支持技术文档上传与本地云端评审。

## 目录结构

```
44-三端协作架构系统/
├── cloud/          # 云端：部署与运行环境
│   ├── deploy/      # 部署脚本与发布产物
│   ├── config/      # 云端环境配置
│   └── scripts/     # 云端运维脚本
├── developers/      # 开发者：协作工作区
│   ├── workspace/   # 开发者工作区
│   └── guidelines/   # 开发规范与流程说明
├── github/          # GitHub：仓库协作
│   ├── repo/        # 仓库内容（克隆/同步目标）
│   ├── workflows/   # CI/CD 工作流定义（生效文件在仓库根 .github/workflows/）
│   ├── leases/      # 模块租约（每模块一个 JSON，随 main 审计）
│   └── templates/   # Issue/PR/Postmortem 模板
├── docs/            # 技术文档区（草稿/调研）
│   ├── tech/        # 技术文档（上传区）
│   ├── api/        # API 文档
│   └── design/      # 设计文档
├── review/          # 评审区
│   ├── pending/     # 待评审文档
│   ├── approved/    # 已通过评审
│   └── feedback/    # 评审意见与反馈
└── shared/          # 共享资源
    ├── assets/      # 共享素材
    └── tools/       # 共享工具（lease.py / docs_sync.sh / test_lease.py）
```

## 协作流程（双向 + 模块租约）

> 真源：`origin/main`。本地与云端均为工作副本。上游 SPEC：
> [SPEC-dual-end-collab-governance.md](docs/tech/SPEC-dual-end-collab-governance.md)

1. **领租约**：`python3 shared/tools/lease.py claim --module <模块> --end local|cloud --role dev|test|review --task <ID>`。同一模块同时只允许一个 `dev` 租约；`test`/`review` 必须由非开发方（另一端或独立会话）持有。
2. **文档上传**：技术文档写入 `docs/tech/` 或 `docs/design/`，PR 合入 `main`。
3. **跨端同步**：另一端执行 `bash shared/tools/docs_sync.sh pull`（云端加 `--end cloud`，仅同步 44 目录）。同步判定 = `HEAD` sha == `origin/main` sha。
4. **评审与终审**：待评审文档移入 `review/pending/`；**评审方**（非起草方，任一端）写 `review/feedback/YYYY-MM-DD-<slug>-review.md`；**终审只能由云端签发**——通过后由云端移入 `review/approved/`（R8 硬约束），本地不得写入 `approved/`。
5. **开发**：持 `dev` 租约方在 `developers/workspace/` 工作，遵循 `developers/guidelines/`；分支命名 `feat/<task-id>@<end>`。
6. **测试/验收（G3.5）**：由非开发方出具证据（命令 + 退出码 + 日志），开发方不得自证。
7. **GitHub 同步**：`.github/workflows/` 放置 CI；`lease-guard.yml` 校验模块租约与角色分离。
8. **云端部署**：部署相关内容放在 `cloud/`；部署仍走 G4 波动率窗口，不因文档同步绕过。
