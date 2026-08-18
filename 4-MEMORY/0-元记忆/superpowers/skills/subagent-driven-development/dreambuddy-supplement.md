# Dreambuddy Supplement — subagent-driven-development

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: subagent-driven-development
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: ≥ 2 小时 / 跨模块 / 可独立拆分的开发；不适用: <30 分钟单文件改动

## 2. 本土化适配说明

我们环境 SDD 派发到 general_purpose_task / Skill 机制，不派发到真正独立进程；两阶段 review 由当前主 agent 串联完成。

## 3. 常见 Rationalization 反模式

- [ ] 子任务无自包含性，依赖前一个的实现细节
- [ ] 派发出的 task 描述含糊，reviewer 靠猜
- [ ] 一阶段 review 一次就过，不做 second-look

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] SDD / 子代理开发
- [x] 派发 subagent / 派发任务
- [x] 两阶段审查 / review-reviewer
- [x] implementer / 子智能体
- [x] 并发执行 / 子代理 审查
- [x] 两阶段 review / task-brief
- [x] 独立子任务

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
