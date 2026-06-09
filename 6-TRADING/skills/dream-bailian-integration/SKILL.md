---
name: "dream-bailian-integration"
description: >
  Dream-MultiSkill 百炼集成中心 - 统一管理百炼API调用、知识库构建、
  工作流编排、Function Calling、产物传递(AAM)。触发词：百炼、知识库构建、
  RAG配置、API调用、百炼工作流、模型蒸馏、Function Calling配置。
version: "v1.0"
created: "2026-05-07"
updated: "2026-05-07"
status: "active"
---

# Dream-MultiSkill 百炼集成中心 v1.0

## 定位

**百炼集成中心**是Dream-MultiSkill与阿里云百炼平台的统一接口层，负责：
1. 标准化API调用
2. 知识库RAG构建
3. 工作流编排
4. Function Calling配置
5. 产物传递(AAM)
6. 合规审查

## 核心能力

| 能力 | 说明 | 状态 |
|:---|:---|:---:|
| API调用 | OpenAI兼容接口，qwen-plus/qwen3.6-35b-a3b | ✅ |
| 知识库RAG | 连接私有数据和专业知识 | ✅ |
| 工作流编排 | 可视化流程设计 | ✅ |
| Function Calling | 工具调用能力 | ✅ |
| MCP扩展 | 灵活个性化扩展 | ✅ |
| 多模态 | 文本/视觉/语音/视频 | ✅ |

## 百炼API配置

### API Key
```
sk-c233489e73e94b9591e4776d89ec8cb8
```

### Base URL
```python
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

### 推荐模型
| 模型 | 用途 | 成本 |
|:---|:---|:---|
| qwen-plus | 通用对话 | 中 |
| qwen3.6-35b-a3b | 高性能蒸馏 | 低 |
| qwen-max | 复杂推理 | 高 |

### 调用示例
```python
import urllib.request
import json

def call_bailian(messages, model="qwen3.6-35b-a3b"):
    api_key = "sk-c233489e73e94b9591e4776d89ec8cb8"
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    data = {
        "model": model,
        "messages": messages
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
        return result['choices'][0]['message']['content']
```

## 文档结构

```
dream-bailian-integration/
├── SKILL.md                          # 本文件 - 主入口
├── docs/
│   ├── bailian_platform_overview.md   # 百炼平台能力概览
│   ├── api_reference.md               # API调用参考
│   ├── function_calling_guide.md      # Function Calling指南
│   └── rag_knowledge_base.md           # 知识库RAG构建指南
├── governance/
│   ├── constitution.md                # 宪法 - 最高指导原则
│   ├── workflow.md                    # 工作流程与规范
│   ├── faq.md                         # 常见问题
│   └── engineering_index.md            # 工程索引
├── technical/
│   ├── architecture.md               # 技术架构设计
│   ├── api_design.md                  # API设计规范
│   └── integration_patterns.md         # 集成模式
└── skill_templates/
    ├── aam_skill.md                   # AAM SKILL模板
    └── compliance_skill.md            # 合规SKILL模板
```

## 产物传递(AAM)规范

### 双通道投递
- **秘书邮箱**: `~/.workbuddy/skills/boss-secretary/reports/`
- **前端产物中心**: `~/.workbuddy/artifacts/`

### frontmatter规范
```yaml
---
title: "产物标题"
department: trading|governance|hr|knowledge|support|cfo
chain_phase: A1|A2|A3|A4|A5|A6|A7|A8|A9
date: "YYYY-MM-DDTHH:MM:SS+08:00"
type: report|analysis|decision|skill|artifact
status: draft|review|completed|archived
tags: "tag1 tag2 tag3"
by_a_phase: A1|A2|A3|A4|A5|A6|A7|A8|A9
---
```

## 合规审查

所有百炼集成变更必须通过 ai-trading-compliance SKILL 审查：
- P0/P1变更 → 必须人工确认
- P2/P3变更 → 自动执行

## 版本历史

| 版本 | 日期 | 变更 |
|:---|:---|:---|
| v1.0 | 2026-05-07 | 初始版本，包含基础API配置和文档结构 |
