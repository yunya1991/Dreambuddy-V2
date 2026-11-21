---
name: nature-shared
description: nature-skills 共享内容目录，提供通用样式模板和工具函数
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: MIT
status: active
category: tooling
domain: 1-ARCHITECTURE
triggers: []
depends_on: []
provides:
  - shared-templates
  - shared-styles
cognitive_links: []
---

## Autonomy Boundary

可自主执行：
- 工具调用与数据转换
- 文档格式转换（Markdown/JSON/CSV）
- 通用查询与搜索操作
- 代码生成与重构建议

需用户确认：
- 执行破坏性操作（删除/覆盖重要文件）
- 修改系统核心配置

禁止：
- 未经授权执行不可逆操作
- 访问未授权的外部资源


# nature-shared — nature-skills 共享内容

> 源自 Yuan1z0825/nature-skills（MIT 协议）。共享支持包，被 nature-figure 等技能引用，不作为独立任务调用。

## 用途

- 提供 Nature 风格的通用样式模板
- 提供图表渲染的公共工具函数
- 提供字体、颜色、布局的统一配置

## 被依赖的 SKILL

- nature-figure
