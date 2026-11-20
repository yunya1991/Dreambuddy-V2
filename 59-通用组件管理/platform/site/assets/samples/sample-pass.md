---
name: sample-skill
slug: sample-skill
displayName: 示例技能（合规样本）
version: 1.0.0
description: 当用户需要验证体检链路是否正常时使用本技能，它覆盖 frontmatter、使用说明、可执行示例与限制声明。
summary: 合规示例样本，用于演示体检报告全部通过时的形态。
license: MIT
---

# 示例技能（合规样本）

> 示例样本：仅用于演示体检报告，不具备真实业务能力，也不会上架分发。

## 使用

把本文件放在 Skill 包根目录，保持 `SKILL.md` 与 `scripts/` 的相对结构不变。
宿主读取 frontmatter 后即可按 description 的触发条件决定是否启用本技能。

## 示例

```bash
python3 scripts/demo.py --dry-run
```

预期输出一行 `ok`，不写入任何文件，也不访问网络。

## 限制

- 只做结构演示，不处理真实数据。
- 不包含任何凭据、绝对路径或外部服务调用。
- 需要 Python 3.9 及以上版本。

## FAQ

Q：为什么这个样本什么都不做？
A：体检关注的是结构与声明是否完整，样本保持最小可运行即可。
