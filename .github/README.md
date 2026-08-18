# GitHub 协作指南

> **版本**: v1.0
> **更新日期**: 2026-05-14

---

## 📋 目录

1. [仓库结构](#仓库结构)
2. [分支策略](#分支策略)
3. [协作流程](#协作流程)
4. [代码审查](#代码审查)
5. [发布流程](#发布流程)

---

## 仓库结构

```
dream-multiSkill/
├── .github/
│   ├── workflows/          # GitHub Actions
│   │   ├── ci.yml         # CI流程
│   │   └── pr-review.yml  # PR审查
│   └── ISSUE_TEMPLATE/    # Issue模板
│
├── dream-multiSkill-architecture/  # 架构文档仓库
│   ├── 1-ARCHITECTURE/   # 架构设计
│   ├── 2-GOVERNANCE/     # 治理系统
│   ├── 3-FRONTEND/       # 前端系统
│   ├── 4-MEMORY/         # 记忆系统
│   ├── 5-BUSINESS/       # 业务管理
│   └── 6-TRADING/         # 交易系统
│
├── dream-universal-gateway/  # 用户前端仓库
│   └── src/
│
└── .github/
```

---

## 分支策略

### 主分支

| 分支 | 用途 | 保护 |
|------|------|------|
| `main` | 生产代码 | ✅ 需要PR + 审查 |
| `develop` | 开发分支 | ✅ 需要PR |
| `feature/*` | 功能开发 | 自由提交 |
| `fix/*` | Bug修复 | 自由提交 |
| `docs/*` | 文档更新 | 自由提交 |

### 命名规范

```bash
# 功能分支
feature/trading-a9-exit
feature/governance-pip

# Bug修复
fix/memory-leak
fix/api-timeout

# 文档
docs/architecture-guide
docs/api-reference
```

---

## 协作流程

### 1. Fork & Clone

```bash
# Fork 仓库到个人账户

# Clone 你的 Fork
git clone https://github.com/your-username/dream-multiSkill.git
cd dream-multiSkill

# 添加上游仓库
git remote add upstream https://github.com/org/dream-multiSkill.git
```

### 2. 创建分支

```bash
# 确保在 develop 分支上
git checkout develop

# 创建功能分支
git checkout -b feature/your-feature

# 或修复分支
git checkout -b fix/issue-number
```

### 3. 开发 & 提交

```bash
# 开发...

# 提交 (遵循 Conventional Commits)
git add .
git commit -m "feat(module): add new feature"

# 推送
git push origin feature/your-feature
```

### 4. 创建 PR

1. 在 GitHub 上创建 Pull Request
2. 选择 `develop` 作为目标分支
3. 填写 PR 模板
4. 关联相关 Issue
5. 请求审查

---

## 代码审查

### PR 模板

```markdown
## 描述
<!-- 简要描述更改内容 -->

## 更改类型
- [ ] 新功能
- [ ] Bug修复
- [ ] 文档更新
- [ ] 重构
- [ ] 测试

## 测试
- [ ] 添加了测试
- [ ] 本地测试通过
- [ ] 不需要测试

## 检查清单
- [ ] 代码遵循项目规范
- [ ] 文档已更新
- [ ] 没有引入新警告
```

### 审查标准

| 标准 | 说明 |
|------|------|
| 功能正确 | 代码功能符合需求 |
| 代码质量 | 清晰、可维护、无重复 |
| 测试覆盖 | 关键路径有测试 |
| 文档更新 | 必要时更新文档 |
| 无破坏性变更 | 不影响现有功能 |

---

## 发布流程

### 版本号规范

遵循 [Semantic Versioning](https://semver.org/)：

```
主版本.次版本.修订版本

- 主版本: 不兼容的API变更
- 次版本: 向后兼容的功能新增
- 修订版本: 向后兼容的问题修复
```

### 发布步骤

```bash
# 1. 更新版本号
# package.json, CHANGELOG.md

# 2. 创建发布分支
git checkout develop
git pull upstream develop
git checkout -b release/v1.0.0

# 3. 合并到 main
git checkout main
git merge release/v1.0.0 --no-ff
git tag -a v1.0.0 -m "Release version 1.0.0"

# 4. 推送
git push upstream main
git push upstream --tags

# 5. 创建 GitHub Release
```

---

## 🔗 相关资源

- [代码规范](../1-ARCHITECTURE/README.md)
- [Git工作流](https://git-scm.com/book/zh/v2)
- [Conventional Commits](https://www.conventionalcommits.org/)
