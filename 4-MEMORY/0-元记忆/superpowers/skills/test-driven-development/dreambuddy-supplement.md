# Dreambuddy Supplement — test-driven-development

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: test-driven-development
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: Python/TS 确定性代码 / 交易策略 / 回测；不适用: 纯视觉 UI / 仅配置改动

## 2. 本土化适配说明

sz<20 USDT 时允许跳过实盘测试，但必须在 applied.metadata 中打标签 `# sz_too_so_small_skip_live_test` 并记录理由。

## 3. 常见 Rationalization 反模式

- [ ] 先写代码后补测试也叫 TDD（严格禁止）
- [ ] 先写 mock 绿测再写代码（没有红阶段的不算）
- [ ] 测试只覆盖 happy path 无边界值

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] TDD / 测试驱动
- [x] 先写测试 / 写单测
- [x] 补单测 / 红-绿-重构
- [x] red green refactor / 失败测试
- [x] 测试用例 / pytest
- [x] 写 UT / 单元测试
- [x] 测试先行 / 红绿提交
- [x] 写失败测试 / 回归测试
- [x] 写脚本 / 写 Python
- [x] Python 脚本 / 开发代码
- [x] 写代码 / 代码开发
- [x] 实现功能 / 功能开发

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
