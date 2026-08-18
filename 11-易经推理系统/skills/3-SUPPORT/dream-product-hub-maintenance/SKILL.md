---
name: dream-product-hub-maintenance
version: "1.0.0"
description: "产物中心前端(localhost:3456)维护指南。覆盖内容扫描、文件格式、分类映射、常见踩坑及修复。触发词：产物中心、Product Hub、feed修复、内容不显示、excerpt、article显示"
tags: [frontend, maintenance, product-hub, nextjs]
agent_created: true
created_at: "2026-05-06"
---

# 产物中心 (Product Hub) 维护指南

## 概述

产物中心是 Dream-MultiSkill 的前端展示系统，运行在 `http://localhost:3456`。
技术栈：Next.js 14 + RSC + gray-matter + Tailwind CSS。
代码位置：`{workspace}/.workbuddy/skills/dream-exit-skill-v2/web/`
产物数据目录：`~/.workbuddy/artifacts/`

## 核心架构

```
~/.workbuddy/artifacts/          # 后端产物数据目录
  ├── exit/index.json           # 分类索引
  ├── exit/L0_rules.md          # 分类下的产物文件
  ├── advanced_orders/index.json
  ├── a_series/index.json
  └── ...

web/
  ├── lib/content.server.ts     # 核心内容扫描引擎（SSR）
  ├── lib/types.ts              # TypeScript 类型定义
  ├── components/FeedCard.tsx   # Feed 卡片组件
  ├── app/feed/FeedClient.tsx   # Feed 客户端（过滤/搜索/分页）
  └── app/feed/[...slug]/page.tsx  # 详情页路由
```

### 数据流

```
index.json → content.server.ts (扫描) → ArtifactIndex[] → FeedClient (过滤) → FeedCard (渲染)
                                                              ↓
                                                    getArtifactBySlug → 详情页
```

## 一、添加新产物

### 步骤

1. 在 `~/.workbuddy/artifacts/{category}/` 下创建分类目录（如已存在则跳过）
2. 编写 `.md` 文件（推荐）或 `.json` 文件（JSON产物自动回退转Markdown）
3. 更新 `index.json` 注册产物条目

### index.json 格式

```json
[
  {
    "id": "{category}/{artifact_id}",
    "title": "产物标题",
    "department": "knowledge|trading|dream|support",
    "type": "strategy|exit_rule|template|knowledge|...",
    "date": "2026-05-06",
    "status": "completed|active|in_progress",
    "chain_phase": "A0|A1|...|A9|",
    "url": "/feed/{category}/{artifact_id}",
    "tags": "tag1 tag2 tag3",
    "filename": "{artifact_id}.md"  // 可选，默认 {artifact_id}.md
  }
]
```

### .md 文件格式

```markdown
---
title: 产物标题
type: strategy
status: completed
tags: [tag1, tag2, tag3]
date: 2026-05-06
department: knowledge
---

正文内容（Markdown格式）
```

### .json 文件格式（自动回退）

任何 JSON 文件放在 `artifacts/{category}/` 下，在 `index.json` 中注册即可。
`content.server.ts` 的 `jsonToMarkdown()` 会自动将其转为 Markdown 表格展示。

## 二、分类映射

### 目录 → 部门映射 (`CATEGORY_TO_DEPARTMENT`)

| 目录 | 部门 | 说明 |
|------|------|------|
| masters, tools, macro, risk, exit, practice, web_strategy, advanced_orders | knowledge | 知识部 |
| a_series, trading | trading | 交易部 |
| oneirology | dream | 做梦部 |
| audit | support | 支持部 |

### 知识库子分类（FeedClient.tsx `KNOWLEDGE_CATS`）

| key | 标签 | emoji | 匹配 tags |
|-----|------|-------|-----------|
| masters | 蒸馏大师库 | 🏛️ | master, masters, master_* |
| tools | OKX工具库 | 🛠️ | okx_tools, okx_strategy, tools, commands |
| macro | 宏观资产库 | 📊 | macro, macro_assets, correlation, cross_asset |
| risk | 风险库 | ⚠️ | risk, thresholds |
| exit | 离场规则库 | 🚪 | exit, rules |
| practice | 实践教训库 | ⚔️ | practice, lessons |
| web_strategy | 联网策略库 | 🌐 | web_strategy |
| advanced_orders | 高级委托库 | ⚡ | advanced_order, trailing, oco |
| audit | 审计报告库 | 📋 | audit, report |
| exit_rules | 离场规则库 | 🚪 | exit_rules, L0, L1, L2 |
| risk_concept | 风险概念库 | ⚠️ | risk_concept, risk |
| template | 模板库 | 📝 | template, log_template |

## 三、常见踩坑与修复

### BUG-001: tags 字符串被忽略

**症状**: 产物出现在列表但无法被分类过滤
**原因**: `content.server.ts` 只处理 `Array.isArray(tags)`，字符串 tags 返回空
**修复**: 增加 `typeof === 'string'` 分支

```typescript
tags: Array.isArray(frontmatter.tags) ? frontmatter.tags.join(' ') :
      Array.isArray(item.tags) ? item.tags.join(' ') :
      (typeof frontmatter.tags === 'string' ? frontmatter.tags :
       typeof item.tags === 'string' ? item.tags : ''),
```

### BUG-002: 双重目录路径导致文件找不到

**症状**: 标题显示但 excerpt 为空/undefined
**原因**: `id="exit/L0_rules"` → `filename="exit/L0_rules.md"` → `filePath="artifacts/exit/exit/L0_rules.md"`（不存在）
**修复**: strip category prefix

```typescript
const rawId = item.artifact_id || item.id || 'unknown';
const artifactId = rawId.includes('/') ? rawId.split('/').pop()! : rawId;
```

### BUG-003: JSON 产物详情页 404

**症状**: Feed 列表能看到标题但点进去 404
**原因**: `getArtifactBySlug` 只查找 `.md` 文件，`.json` 产物无对应 `.md`
**修复**: `getArtifactBySlug` 增加 `.json` 回退，调用 `jsonToMarkdown()` 转换

### BUG-004: excerpt 不显示

**症状**: 卡片只有标题没有内容预览
**原因**: 1) 文件路径错误（见BUG-002）2) FeedCard 缺少 excerpt 渲染
**修复**:
1. 确保 `content.server.ts` 正确提取 excerpt（前200字符，去markdown标记）
2. `FeedCard.tsx` 增加渲染：

```tsx
{artifact.excerpt && (
  <p className="mt-2 text-sm text-gray-600 line-clamp-2 leading-relaxed">
    {artifact.excerpt}
  </p>
)}
```

### BUG-005: 缺少 by_a_phase 字段

**症状**: 构建时 TypeScript 类型错误
**原因**: `emptyArtifactsData()` 缺少 `by_a_phase: {}`
**修复**: 确保返回的 statistics 包含所有 5 个维度

### BUG-006: npm run start 报 "Missing script"

**症状**: 从项目根目录运行 npm start 失败
**原因**: package.json 在 `web/` 子目录，必须 cd 到 web/ 才能运行
**修复**:

```bash
cd {workspace}/.workbuddy/skills/dream-exit-skill-v2/web && npm run start
```

或用绝对路径的 next binary：

```bash
{workspace}/.workbuddy/skills/dream-exit-skill-v2/web/node_modules/.bin/next start -p 3456
```

## 四、操作命令

### 构建和启动

```bash
# 构建
cd {workspace}/.workbuddy/skills/dream-exit-skill-v2/web
npm run build

# 启动（端口3456已硬编码在 package.json）
npm run start

# 验证
curl -s -o /dev/null -w "%{http_code}" http://localhost:3456/feed
curl -s http://localhost:3456/feed | grep "产物标题"
```

### 验证产物注册

```bash
# 检查 index.json 中的条目
cat ~/.workbuddy/artifacts/{category}/index.json | python3 -m json.tool

# 检查 .md/.json 文件是否存在
ls ~/.workbuddy/artifacts/{category}/{artifact_id}.md
ls ~/.workbuddy/artifacts/{category}/{artifact_id}.json

# 检查详情页
curl -s -o /dev/null -w "%{http_code}" http://localhost:3456/feed/{category}/{artifact_id}
```

### 重启服务

```bash
pkill -f "next start" 2>/dev/null
sleep 1
cd {workspace}/.workbuddy/skills/dream-exit-skill-v2/web && npm run build && npm run start
```

## 五、缓存机制

`content.server.ts` 有 5 秒 TTL 缓存，基于 `ARTIFACTS_ROOT` 的目录 mtime。
修改产物文件后最多等 5 秒即可在前端看到更新，无需重启服务。
如果修改了 `index.json` 结构或代码，则需要 `npm run build` + 重启。

## 六、关键类型定义 (types.ts)

```typescript
interface ArtifactIndex {
  id: string;           // "{category}/{artifact_id}"
  title: string;
  department: string;   // knowledge|trading|dream|support
  type: string;
  date: string;
  status: string;
  chain_phase: string;  // A0-A9
  url: string;          // "/feed/{category}/{artifact_id}"
  tags: string;         // space-joined tags
  excerpt?: string;     // 内容预览（前200字符）
}
```
