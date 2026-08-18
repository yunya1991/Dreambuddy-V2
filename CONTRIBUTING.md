# Contributing to Dream-MultiSkill

感谢您对 Dream-MultiSkill 项目的兴趣！🎉

本文档将帮助您了解如何为项目做出贡献。

---

## 📋 目录

1. [行为准则](#行为准则)
2. [如何贡献](#如何贡献)
3. [开发流程](#开发流程)
4. [提交规范](#提交规范)
5. [代码审查](#代码审查)

---

## 行为准则

作为贡献者，请您：
- 使用包容和尊重的语言
- 尊重不同的观点和经验
- 专注于对社区最有利的事情
- 与社区其他成员善意合作

---

## 如何贡献

### 🐛 报告Bug

请通过 GitHub Issues 报告Bug，包括：
- 清晰的标题和描述
- 复现步骤
- 预期行为 vs 实际行为
- 环境信息 (OS, Node版本等)

### 💡 提出新功能

欢迎提出新功能建议！请：
- 搜索现有 Issues 避免重复
- 清晰描述功能需求
- 解释为什么这对项目有价值

### 🔧 修复Bug / 实现功能

1. **认领 Issue**: 在评论中说明您要修复/实现
2. **创建分支**: `git checkout -b feature/xxx` 或 `fix/xxx`
3. **编写代码**: 遵循项目的代码规范
4. **添加测试**: 确保新代码有测试覆盖
5. **提交 PR**: 描述更改内容和原因

---

## 开发流程

### 1. 环境设置

```bash
# 克隆仓库
git clone https://github.com/your-org/dream-multiSkill.git
cd dream-multiSkill

# 安装依赖
pnpm install

# 复制环境配置
cp .env.example .env
# 编辑 .env 填写必要的环境变量
```

### 2. 创建分支

```bash
# 功能分支
git checkout -b feature/my-new-feature

# Bug修复分支
git checkout -b fix/issue-description

# 文档分支
git checkout -b docs/improve-documentation
```

### 3. 开发

```bash
# 启动开发服务器
pnpm dev

# 运行测试
pnpm test

# 代码检查
pnpm lint
```

### 4. 提交

```bash
# 暂存更改
git add .

# 提交 (遵循Conventional Commits)
git commit -m "feat: add new feature"
git commit -m "fix: resolve issue #123"
git commit -m "docs: update README"
```

---

## 提交规范

我们使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

### 类型 (type)

| 类型 | 描述 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug修复 |
| `docs` | 文档更新 |
| `style` | 代码格式（不影响功能） |
| `refactor` | 重构（不是新功能或修复） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统或依赖变更 |
| `ci` | CI配置 |
| `chore` | 其他更改 |

### 范围 (scope)

| 范围 | 描述 |
|------|------|
| `trading` | 交易系统 (A0-A9) |
| `governance` | 治理系统 |
| `frontend` | 前端系统 |
| `memory` | 记忆系统 |
| `business` | 业务管理 |
| `core` | 核心架构 |

### 示例

```
feat(trading): add A9 exit skill with 21-event risk library

fix(governance): resolve pretrade gatekeeper false positive

docs(frontend): update API configuration guide

refactor(memory): optimize episode storage format
```

---

## 代码审查

### PR 要求

- ✅ 遵循代码规范
- ✅ 添加/更新测试
- ✅ 更新相关文档
- ✅ 通过所有 CI 检查
- ✅ 描述清楚更改内容

### 审查流程

1. **自动检查**: CI 运行测试和代码检查
2. **人工审查**: 维护者审核代码
3. **反馈**: 如有需要，提出修改建议
4. **合并**: 审查通过后合并到主分支

---

## 🆘 寻求帮助

- 📖 查看 [Wiki](https://github.com/your-org/dream-multiSkill/wiki)
- 💬 加入 [Discussions](https://github.com/your-org/dream-multiSkill/discussions)
- 🐛 提交 [Issue](https://github.com/your-org/dream-multiSkill/issues)

---

再次感谢您的贡献！🙏
