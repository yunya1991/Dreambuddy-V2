# 44 三端协作架构系统

本架构用于云端、开发者、GitHub 三方协作，支持技术文档上传与本地云端评审。

## 目录结构

```
44-collab-architecture/
├── cloud/          # 云端：部署与运行环境
│   ├── deploy/      # 部署脚本与发布产物
│   ├── config/      # 云端环境配置
│   └── scripts/     # 云端运维脚本
├── developers/      # 开发者：协作工作区
│   ├── workspace/   # 开发者工作区
│   └── guidelines/   # 开发规范与流程说明
├── github/          # GitHub：仓库协作
│   ├── repo/        # 仓库内容（克隆/同步目标）
│   ├── workflows/   # CI/CD 工作流定义
│   └── templates/   # Issue/PR 模板
├── docs/            # 技术文档区
│   ├── tech/        # 技术文档（上传区）
│   ├── api/        # API 文档
│   └── design/      # 设计文档
├── review/          # 评审区
│   ├── pending/     # 待评审文档
│   ├── approved/    # 已通过评审
│   └── feedback/    # 评审意见与反馈
└── shared/          # 共享资源
    ├── assets/      # 共享素材
    └── tools/       # 共享工具
```

## 协作流程

1. **文档上传**：技术文档上传至 `docs/tech/`。
2. **评审**：待评审文档移入 `review/pending/`，评审意见记录在 `review/feedback/`，通过后移入 `review/approved/`。
3. **开发协作**：开发者在 `developers/workspace/` 中工作，遵循 `developers/guidelines/` 中的规范。
4. **GitHub 同步**：仓库内容同步至 `github/repo/`，CI/CD 工作流放在 `github/workflows/`。
5. **云端部署**：部署相关内容统一放在 `cloud/` 下。
