# Dreambuddy Supplement — requesting-code-review

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: requesting-code-review
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: 提交前预查 / 跨模块重构 / 核心逻辑修改；不适用: 纯文档 / 注释修改

## 2. 本土化适配说明

无人评审时，用自动 lint + test coverage + cognitive_superpowers.verify_process_followed() 三元组合作为替代审查。

## 3. 常见 Rationalization 反模式

- [ ] 大而全 PR 超 800 行提交要求 review
- [ ] lint 没跑 / 测试不过就发起 CR
- [ ] 注释和 commit message 不写，reviewer 必须猜

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] 代码审查 / 发起 review
- [x] 预审查 / 代码评审
- [x] request review / pre-review
- [x] CR 前自检 / 发起 CR
- [x] 代码自查后提交

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
