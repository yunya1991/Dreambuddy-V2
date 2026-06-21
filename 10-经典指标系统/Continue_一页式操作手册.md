# Continue 一页式操作手册（经典指标工程）

工程目录：`/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统`

## 1. 首次使用（一次性）

1. 打开工程目录，按 `Cmd/Ctrl + L` 打开 Continue 面板。
2. 确认可见 `engineering-default` 与 `safe-readonly` 两个 agent。
3. 执行 `Developer: Reload Window`。
4. 如 `@Codebase` 异常，执行 `Continue: Rebuild codebase index`。

## 2. 日常流程（每次开发）

1. 先选上下文：`@Diff` + `@File`，再按需使用 `@Codebase`。
2. 先审计后改动：先让模型给风险点与最小改动计划。
3. 小步改动：优先单链路修改，避免跨模块连锁影响。
4. 改动后验证：语法检查 + 目标测试；涉及前端时加 lint。
5. 回执记录：改动点、验证结果、风险与回滚口径。

## 3. 模式切换

- 日常开发：`engineering-default`
- 执行门禁/风控相关审计：`safe-readonly` 或本地模型

## 4. 敏感信息红线

- 不向云端模型提交：`.env*`、`user_data/datasets/`、`user_data/agent_outbox/`、账户配置、白名单。
- 涉及执行与风控参数时，先只读分析，再落地改动。

## 5. 快速排障

- 配置未刷新：`Developer: Reload Window`
- 检索命中敏感文件：校验 `.continueignore` 与 `.gitignore`，然后重建索引
