# Dreambuddy Supplement — systematic-debugging

> **版本**: v0.1 (首次修复 C2：补全 5 标准章节 + 本土触发词专业中文)
> **上游 Skill**: systematic-debugging
> **最后更新**: 2026-08-01
> **状态**: active（5 标准章节 + 本土触发词专业中文已就绪；待后续会话填充细节）

## 1. 本 Skill 在 Dreambuddy 场景的适用范围

适用: 交易系统 Bug / Python 脚本异常 / polling 超时 / 缓存；不适用: 纯外部环境（网络/交易所）故障

## 2. 本土化适配说明

交易系统 debug 必须同时查三个日志源：/tmp/polling_trader_*.log + /tmp/cognitive-daemon.log + OKX 账户资产历史；否则不允许开 fix。

## 3. 常见 Rationalization 反模式

- [ ] 猜 root cause 直接 patch，不做最小复现
- [ ] 4 阶段调试跳过 确认实验，一修就上线
- [ ] 日志不看就说 环境问题 甩锅

## 4. 本土触发条件

注：命中以下任一关键词 / 别名，该 Skill 在 recall 时自动 +2.0 权重（2 倍于普通触发词），优先推荐。
建议至少命中 2 个以上关键词再视为高相关。

- [x] 调试 / debug
- [x] 排错 / bug修复
- [x] 复现问题 / root cause
- [x] 根本原因 / 定位问题
- [x] bugfix / 查日志
- [x] 排查 / 复现失败
- [x] 压力测试 / 压测
- [x] 4 阶段调试 / 防御式调试
- [x] 修复bug / 出现超时
- [x] 故障 / 异常

## 5. 本土成功案例链接

（沉淀后补充；格式：[A/B/C/S 级] applied_id 标题 验证N次 最后日期）

[ ] 待沉淀：（applied_id / 标题 / 质量等级 / 验证次数）
