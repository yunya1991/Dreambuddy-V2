# Dreambuddy Supplement — finishing-a-development-branch

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: finishing-a-development-branch
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: 开发完成 / PR 提交 / merge 后清理；不适用: 分支未达到完成态

## 2. 本土化适配说明

所有分支清理前必须先跑：`pytest 4-MEMORY/9-工具与接口/tests/ -q` 无 FAILED；否则禁止 discard 或 merge。

## 3. 常见 Rationalization 反模式

- [ ] 未跑回归测试就合并
- [ ] 分支删了但 commit message 没写 traceability（指向 session_id / doc）
- [ ] 遗留 TODO/FIXME 不记录，下一次再回来根本看不懂

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] 收尾分支 / 合并分支
- [x] PR 提交 / merge
- [x] 工作区清理 / 分支清理
- [x] 开发完成 收尾 / discard 分支
- [x] 提交完成 / 开发收尾
- [x] commit 完成 / 合并主干
- [x] cleanup

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
