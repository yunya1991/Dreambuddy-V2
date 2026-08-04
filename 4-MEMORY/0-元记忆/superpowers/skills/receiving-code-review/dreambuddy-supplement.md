# Dreambuddy Supplement — receiving-code-review

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: receiving-code-review
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: 收到 review comments 后；不适用: 尚未发起 CR

## 2. 本土化适配说明

审查意见 > 8 条或 > 2 个文件涉及核心逻辑时，必须先补单测覆盖，再开始修复意见。

## 3. 常见 Rationalization 反模式

- [ ] 每条 comment 最小改法 patch，不理会结构性意见
- [ ] 不理解的评论直接 done，不改代码
- [ ] review 后新增未覆盖的代码路径不补测试

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] 处理审查意见 / review反馈
- [x] review 修复 / review 回应
- [x] 处理评论 / code review 后续
- [x] 修复审查问题 / 审查反馈处理

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
