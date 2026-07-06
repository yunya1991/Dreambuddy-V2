# 百炼平台能力概览

**版本**: v1.0
**日期**: 2026-05-07
**来源**: 阿里云百炼官方文档

---

## 一、平台概述

### 1.1 什么是百炼
阿里云百炼是一站式大模型开发与应用平台，基于通义千问及主流第三方大模型打造。提供兼容OpenAI的API及全链路模型服务，同时提供可视化应用构建能力。

### 1.2 核心特点
| 特点 | 说明 |
|:---|:---|
| **一站式** | 从模型调用到应用构建全覆盖 |
| **兼容OpenAI** | 轻松迁移现有代码 |
| **可视化** | 无需代码即可构建应用 |
| **安全合规** | 数据不会用于模型训练 |

---

## 二、API能力

### 2.1 OpenAI兼容接口
百炼提供与OpenAI完全兼容的API，只需简单配置即可迁移：

```python
# OpenAI 格式
client = OpenAI(
    api_key="your-api-key",
    base_url="https://api.openai.com/v1"
)

# 百炼格式 (仅需更换 base_url)
client = OpenAI(
    api_key="your-bailian-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
```

### 2.2 多地域支持
| 地域 | Base URL | 适用场景 |
|:---|:---|:---|
| 华北2 (北京) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 中国区 |
| 美东 (弗吉尼亚) | `https://dashscope-us.aliyuncs.com/compatible-mode/v1` | 美洲 |
| 新加坡 | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | 东南亚 |

### 2.3 模型列表

#### 通义千问系列
| 模型 | 说明 | 适用场景 |
|:---|:---|:---|
| qwen-max | 旗舰版，能力最强 | 复杂推理、代码生成 |
| qwen-plus | 均衡版，性价比高 | 通用对话、知识问答 |
| qwen-plus-0329 | Plus升级版 | 更强的指令跟随 |
| qwen-plus-latest | Plus最新 | 持续更新优化 |
| qwen-turbo | 快速版，低延迟 | 实时对话、客服 |
| qwen-flash | 极速版，超低延迟 | 批处理、高并发 |

#### 第三方模型
| 模型 | 提供商 | 说明 |
|:---|:---|:---|
| deepseek-v3 | DeepSeek | 高性价比 |
| deepseek-r1 | DeepSeek | 推理能力 |
| kimi-plus | 月之暗面 | 长上下文 |
| glm-4-plus | 智谱 | 国产优质 |

#### 多模态模型
| 模型 | 能力 | 说明 |
|:---|:---|:---|
| qwen-vl-plus | 图像理解 | 视觉问答、OCR |
| qwen-vl-max | 图像理解(增强) | 复杂视觉任务 |
| qwen-audio-turbo | 语音识别 | 音频转文字 |
| wanx-plus | 图像生成 | 文生图 |

### 2.4 能力矩阵
| 能力 | 支持模型 | 说明 |
|:---|:---|:---|
| 文本生成 | 全部 | 核心能力 |
| 函数调用 | qwen-plus, qwen-max | 工具调用 |
| 流式输出 | 全部 | 实时响应 |
| JSON输出 | 全部 | 结构化返回 |
| 系统提示词 | 全部 | 角色设定 |
| 多轮对话 | 全部 | 上下文记忆 |

---

## 三、知识库RAG

### 3.1 功能特点
- **私有数据连接**: 支持连接本地文件、数据库、API
- **专业领域知识**: 支持垂直领域知识库构建
- **智能问答**: 基于知识库的自然语言问答
- **向量检索**: 基于语义的高精度检索

### 3.2 知识库构建流程
```
[1] 数据采集] → [2] 数据清洗] → [3] 分块处理] → [4] 向量化] → [5] 索引构建] → [6] 检索优化]
```

### 3.3 支持的数据源
| 数据源 | 说明 |
|:---|:---|
| 本地文件 | PDF、Word、Excel、TXT、Markdown |
| 数据库 | MySQL、PostgreSQL、MongoDB |
| API | REST API、GraphQL |
| Web | 网页爬取 |
| 向量库 | FAISS、Milvus、Pinecone |

### 3.4 Embedding模型
| 模型 | 维度 | 说明 |
|:---|:---|:---|
| text-embedding-v3 | 1536 | 推荐默认 |
| text-embedding-v2 | 1536 | 兼容v1 |

---

## 四、工作流编排

### 4.1 功能特点
- **可视化设计**: 拖拽式流程设计器
- **多节点类型**: LLM、Condition、Loop、HTTP、Code
- **条件分支**: 支持复杂条件判断
- **循环处理**: 支持批量数据处理
- **错误处理**: 内置重试和异常处理

### 4.2 节点类型
| 节点 | 说明 |
|:---|:---|
| **LLM节点** | 调用大模型处理 |
| **知识检索节点** | RAG检索增强 |
| **条件节点** | 条件分支判断 |
| **循环节点** | 批量循环处理 |
| **HTTP节点** | 外部API调用 |
| **代码节点** | Python代码执行 |
| **分支节点** | 多分支并行处理 |
| **聚合节点** | 多分支结果聚合 |

### 4.3 工作流模板
```yaml
workflow:
  name: "智能问答工作流"
  nodes:
    - id: "start"
      type: "start"

    - id: "retrieve"
      type: "knowledge_retrieval"
      config:
        top_k: 5
        similarity_threshold: 0.7

    - id: "generate"
      type: "llm"
      config:
        model: "qwen-plus"
        prompt_template: "基于以下知识回答：\n{{context}}\n\n问题：{{question}}"

    - id: "quality_check"
      type: "condition"
      condition: "confidence > 0.7"

    - id: "end"
      type: "end"
```

---

## 五、Function Calling

### 5.1 功能特点
- **声明式定义**: JSON Schema定义函数
- **自动参数提取**: 模型自动提取参数
- **多函数并行**: 支持多函数同时调用
- **安全校验**: 内置参数类型校验

### 5.2 函数定义示例
```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，如北京、上海"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "default": "celsius"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

# 调用
response = client.chat.completions.create(
    model="qwen-plus",
    messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
    tools=tools
)

# 获取函数调用
tool_calls = response.choices[0].message.tool_calls
for call in tool_calls:
    if call.function.name == "get_weather":
        args = json.loads(call.function.arguments)
        result = get_weather(args["city"], args.get("unit", "celsius"))
```

---

## 六、插件与MCP

### 6.1 插件能力
- **官方插件**: 天气查询、股票数据、地图服务等
- **自定义插件**: 支持HTTP调用自定义API
- **插件市场**: 丰富的社区插件

### 6.2 MCP支持
Model Context Protocol (MCP) 支持：
- **文件系统**: 读写本地文件
- **数据库**: SQL查询
- **Git**: 代码版本控制
- **自定义**: 灵活扩展

---

## 七、应用构建

### 7.1 应用类型
| 类型 | 说明 |
|:---|:---|
| **Agent应用** | 智能体，自动规划执行 |
| **工作流应用** | 流程编排，自动化 |
| **对话应用** | 聊天机器人 |
| **知识库应用** | 智能问答 |

### 7.2 部署方式
| 方式 | 说明 |
|:---|:---|
| **网页应用** | 生成可嵌入的Web组件 |
| **钉钉机器人** | 企业内部机器人 |
| **公众号** | 微信公众号接入 |
| **API** | 提供REST API |

---

## 八、计费说明

### 8.1 计费模式
| 模式 | 说明 |
|:---|:---|
| **按量付费** | 按调用量计费，最灵活 |
| **包年包月** | 预付费，更优惠 |
| **资源包** | 预购Token额度 |

### 8.2 免费额度
- 新用户有专属免费额度
- 部分模型有免费调用量
- 免费额度用完后自动切换按量

### 8.3 成本控制建议
1. **优先使用免费额度模型**
2. **合理设置max_tokens**避免过度输出
3. **使用缓存**减少重复调用
4. **批量处理**提高效率

---

## 九、快速开始

### 9.1 环境准备
```bash
pip install openai
```

### 9.2 第一个调用
```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-c233489e73e94b9591e4776d89ec8cb8",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-plus",
    messages=[{"role": "user", "content": "你好"}]
)

print(response.choices[0].message.content)
```

### 9.3 官方资源
| 资源 | 链接 |
|:---|:---|
| 控制台 | https://bailian.console.aliyun.com |
| 帮助文档 | https://help.aliyun.com/zh/model-studio |
| API文档 | https://help.aliyun.com/zh/model-studio/use-turned-on-apis |
| 社区 | https://help.aliyun.com/zh/model-studio/developer-experience |

---

## 十、Dream-MultiSkill集成

### 10.1 集成架构
```
Dream-MultiSkill
    │
    ├─ A1 深度调研 → 百炼RAG → 知识库检索
    ├─ A2 第一性原理 → 百炼LLM → 推理分析
    ├─ A3 矛盾推演 → 百炼LLM → 情景模拟
    ├─ A4 战术验证 → 百炼Function Calling → 工具调用
    ├─ A5 战术执行 → 百炼API → 信号生成
    └─ A9 离场决策 → 百炼LLM → 决策支持
```

### 10.2 集成优势
| 优势 | 说明 |
|:---|:---|
| **能力增强** | 大模型推理能力 |
| **知识沉淀** | RAG知识库 |
| **成本优化** | 免费额度优先 |
| **灵活扩展** | Function Calling |

---

*本文档基于阿里云百炼官方文档整理，用于Dream-MultiSkill系统集成参考。*
