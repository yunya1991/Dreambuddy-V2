# 产物中台 (Artifact Hub) 完整设计

> **版本**: v2.0
> **更新日期**: 2026-05-14

---

## 🏛️ 系统定位

产物中台是Dream-MultiSkill系统的核心交付物管理平台，负责：
- 统一管理所有AI执行产物（A系列报告、交易决策、策略文档）
- 产物投递验证与归档
- 邮件路由（P0→A1-A5通道 / P1/P2→调研部 / P3→归档）
- 跨部门协作的交付物流转

---

## 📐 架构设计

### 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        用户请求入口                            │
│  (WorkBuddy / Dream Universal Gateway / Telegram / Webhook)   │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────┐
│                      产物路由层 (Router)                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐         │
│  │ P0紧急  │  │ P1重要  │  │ P2一般  │  │ P3低    │         │
│  │ A1-A5   │  │ 调研部  │  │ 调研部  │  │ 归档    │         │
│  │ 专属通道 │  │ 邮箱    │  │ 邮箱    │  │ 处理    │         │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘         │
└───────┼────────────┼───────────┼───────────┼────────────────┘
        │            │           │           │
        ▼            ▼           ▼           ▼
┌──────────────────────────────────────────────────────────────┐
│                     产物处理层 (Processor)                     │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │ artifact-      │  │ boss-secretary │  │ auto-repair    │  │
│  │ alignment-     │  │ 秘书系统       │  │ 系统修复       │  │
│  │ manager        │  │                │  │                │  │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘  │
└──────────┼───────────────────┼───────────────────┼───────────┘
           │                   │                   │
           ▼                   ▼                   ▼
┌──────────────────────────────────────────────────────────────┐
│                      产物存储层 (Storage)                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ ~/.workbuddy/artifacts/                                 │ │
│  │ ├── masters/          # 大师知识库                       │ │
│  │ ├── tools/           # 交易工具库                       │ │
│  │ ├── macro/           # 宏观分析                          │ │
│  │ ├── risk/            # 风险管理                          │ │
│  │ ├── exit/            # 离场策略库                        │ │
│  │ ├── practice/        # 实践经验库                        │ │
│  │ ├── a_series/        # A系列产物 (A0-A9)                │ │
│  │ ├── oneirology/      # 做梦洞察                          │ │
│  │ ├── trading/         # 交易执行结果                      │ │
│  │ └── dashboard/       # 前端Dashboard任务                 │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔧 核心模块

### 1. 产物投递管理 (artifact-alignment-manager)

**核心功能**:
- 产物索引同步 (`sync_artifact.py`)
- 投递验证与归档
- 分类映射管理
- 产物统计报告

**关键文件**:
- `~/.workbuddy/skills/artifact-alignment-manager/`
- `sync_artifact.py` - 同步脚本

### 2. 秘书路由系统 (boss-secretary)

**邮件路由规则**:
| 优先级 | 类型 | 路由目标 | 处理时限 |
|--------|------|----------|----------|
| P0 | 紧急/关键 | A1-A5专属通道 | 即时 |
| P1 | 重要 | 调研部邮箱 | 48h |
| P2 | 一般 | 调研部邮箱 | 7天 |
| P3 | 低 | 归档 | 批量 |

**产物投递双通道**:
1. 秘书邮箱 → `~/.workbuddy/skills/boss-secretary/reports/`
2. 前端Dashboard → `artifacts/trading/` + `index.json`

### 3. 自动修复系统 (auto-repair)

**核心功能**:
- 账户隔离监控（实盘 vs 模拟盘）
- 三邮箱状态检查
- 72h健康检查
- 提案落地追踪

---

## 📊 数据结构

### 产物索引格式 (index.json)

```json
{
  "version": "2.0",
  "last_updated": "2026-05-14T12:00:00Z",
  "artifacts": [
    {
      "artifact_id": "a4_validation_20260514_1200",
      "title": "A4战术验证报告",
      "type": "validation_report",
      "status": "completed",
      "chain_phase": "A4",
      "department": "trading",
      "tags": ["btc", "validation", "trend"],
      "date": "2026-05-14T12:00:00Z",
      "filename": "a4_validation_20260514_1200.md"
    }
  ]
}
```

### 分类→部门映射

```typescript
const CATEGORY_TO_DEPARTMENT: Record<string, string> = {
  'masters': 'knowledge',
  'tools': 'knowledge',
  'macro': 'knowledge',
  'risk': 'knowledge',
  'exit': 'knowledge',
  'practice': 'knowledge',
  'web_strategy': 'knowledge',
  'advanced_orders': 'knowledge',
  'audit': 'support',
  'oneirology': 'dream',
  'trading': 'trading',
  'a_series': 'trading',
  'tasks': 'dashboard',
  'results': 'dashboard',
};
```

---

## 🚀 API接口

### content.server.ts (产物服务端)

**导出函数**:
```typescript
// 获取产物索引（用于列表/搜索）
export function getArtifactsIndex(): ArtifactIndex[]

// 获取完整产物数据（含统计）
export function getArtifactsData(): ArtifactsData

// 获取单个产物内容
export function getArtifactBySlug(slug: string): ArtifactContent | null

// 获取所有slug（用于静态生成）
export function getAllSlugs(): string[]

// 手动刷新缓存
export function invalidateCache(): void
```

### 缓存机制

- 5秒短过期兜底
- 精确检测子目录变更（所有index.json的mtime）
- 手动失效接口供API路由调用

---

## 📁 目录结构

```
~/.workbuddy/artifacts/
├── masters/                    # 大师知识库
│   ├── index.json
│   ├── master_*.md
│   └── *.md
├── tools/                     # 交易工具库
│   ├── index.json
│   └── *.md
├── macro/                     # 宏观分析
│   ├── index.json
│   └── *.md
├── risk/                      # 风险管理
│   ├── index.json
│   └── *.md
├── exit/                      # 离场策略库
│   ├── index.json
│   └── *.md
├── practice/                  # 实践经验库
│   ├── index.json
│   └── *.md
├── a_series/                  # A系列产物
│   ├── index.json
│   ├── a0_*.md
│   ├── a1_*.md
│   └── ... (A2-A9)
├── oneirology/                # 做梦洞察
│   ├── index.json
│   └── *.md
├── trading/                  # 交易执行结果
│   └── *.md
├── tasks/                    # Dashboard任务（无index.json）
│   └── task_*.json
└── results/                  # 执行结果（无index.json）
    └── result_*.json
```

---

## 🔄 工作流程

### 产物创建流程

```
1. SKILL执行 → 生成产物
        ↓
2. 产物写入 artifacts/{category}/
        ↓
3. sync_artifact.py 同步 → 更新 index.json
        ↓
4. content.server.ts 扫描 → 生成前端索引
        ↓
5. 前端Dashboard 展示 → 用户查看
```

### 产物投递流程

```
1. 任务完成 → 调用 artifact-alignment-manager
        ↓
2. 产物验证 → 检查格式/完整性
        ↓
3. 分类归档 → 根据 type/department 路由
        ↓
4. 索引更新 → sync_artifact.py
        ↓
5. 前端同步 → content.server.ts 缓存刷新
```

---

## ⚙️ 配置管理

### 环境变量

```bash
ARTIFACTS_ROOT=~/.workbuddy/artifacts
CACHE_TTL=5000  # 缓存TTL (ms)
```

### SKILL配置

```yaml
# artifact-alignment-manager/config/
├── category_mapping.yaml    # 分类映射配置
├── sync_rules.yaml          # 同步规则
└── validation.yaml          # 验证规则
```

---

## 🧪 测试与验证

### 单元测试

```bash
# 测试产物同步
python scripts/test_sync.py

# 测试索引生成
python scripts/test_index.py

# 测试API接口
curl http://localhost:3000/api/artifacts
```

### 集成测试

```bash
# 端到端测试
pytest tests/integration/test_artifact_hub.py
```

---

## 📝 维护指南

### 日常维护

1. **索引同步**: 每次产物创建后自动同步
2. **缓存清理**: 每周清理过期缓存
3. **存储清理**: 定期归档旧产物（>90天）

### 故障排查

| 问题 | 解决方案 |
|------|----------|
| 产物不显示 | 检查index.json是否更新，运行sync_artifact.py |
| 缓存不刷新 | 调用invalidateCache()或重启服务 |
| 分类错误 | 检查CATEGORY_TO_DEPARTMENT映射 |
