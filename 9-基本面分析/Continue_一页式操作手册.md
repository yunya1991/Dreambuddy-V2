# Continue 一页式操作手册（基本面工程）

工程目录：`/Users/zhangjiangtao/ft_userdata/基本面分析_fundamental`

## 1. 首次使用（一次性）

1. 打开工程目录后，按 `Cmd/Ctrl + L` 打开 Continue 面板。
2. 在 Continue 下拉中确认可见 `engineering-default` 与 `safe-readonly`。
3. 执行 `Developer: Reload Window`。
4. 如检索结果异常，执行 `Continue: Rebuild codebase index`。

## 2. 日常流程（每次开发）

1. 先选上下文：`@Diff` + `@File`，必要时再加 `@Codebase`。
2. 先提问“只分析不改动”，确认影响范围与风险点。
3. 再执行 Edit/Apply，小步改动，避免跨模块大改。
4. 改动后执行验证（lint / typecheck / tests / 接口自检至少一项）。
5. 输出回执：改动点、验证结果、回滚方式。

## 3. 模式切换

- 日常开发：`engineering-default`
- 敏感分析：`safe-readonly` 或本地模型

## 4. 敏感信息红线

- 不向云端模型提交：`.env*`、`user_data/`、数据库文件、日志、地址白名单、账户配置。
- 涉及风控阈值、密钥、账户时，仅贴最小必要片段。

## 5. 快速排障

- 配置改动未生效：`Developer: Reload Window`
- 检索仍命中敏感目录：检查 `.continueignore` 与 `.gitignore`，然后重建索引
