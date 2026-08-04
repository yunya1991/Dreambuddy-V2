# Dreambuddy Supplement — using-git-worktrees

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: using-git-worktrees
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: 多分支并行调试 / 长期任务隔离；不适用: 单分支小改动

## 2. 本土化适配说明

我们交易环境 executionId 隔离机制已覆盖此需求。原版 git worktree 不推荐使用，避免多进程共享账户冲突。

## 3. 常见 Rationalization 反模式

- [ ] worktree 与主工作区共用 venv，pip 污染互相覆盖
- [ ] git worktree add 后不 clean，切换分支后未提交的变更丢失
- [ ] 本土已用 executionId 隔离，强行再加 worktree 导致双层隔离 bug

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] git worktree / 工作区隔离
- [x] worktree / 多工作区
- [x] 分支切换隔离 / 并行分支
- [x] 本地多分支开发

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
