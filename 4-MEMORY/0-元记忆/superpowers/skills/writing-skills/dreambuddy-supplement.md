# Dreambuddy Supplement — writing-skills

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: writing-skills
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: 本土方法论标准化 / 经验沉淀为标准；不适用: 临时一次性方案

## 2. 本土化适配说明

本土自创 Skill 命名：前缀 `local-`（如 `local-trading-debug`），避免与 upstream 新增 Skill 冲突。

## 3. 常见 Rationalization 反模式

- [ ] 自创 Skill 不加 local- 前缀，上游同步后名字冲突
- [ ] SKILL.md 没有 HARD-GATE 和 Checklist，全是流程描述
- [ ] Frontmatter 分隔符乱改，导致 SkillLoader FAIL FAST 无法加载

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] 新技能 / 创建 skill
- [x] 写 SKILL.md / 技能文档
- [x] 创建 Prompt / 技能规范
- [x] SKILL.md 格式 / prompt 工程
- [x] 创建新的 Skill / 自定义技能
- [x] 写技能 / 写代码
- [x] 写脚本 / 写 Python
- [x] 代码开发 / 开发代码
- [x] 程序实现 / 编程
- [x] 脚本实现 / 功能实现
- [x] 写程序 / Python 开发
- [x] OKX 脚本 / 下单脚本
- [x] 量化脚本 / 策略脚本

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
