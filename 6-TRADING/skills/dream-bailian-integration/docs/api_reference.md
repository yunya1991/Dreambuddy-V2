# 百炼API调用参考

**版本**: v1.0
**日期**: 2026-05-07

---

## 一、快速开始

### 1.1 安装依赖
```bash
pip install openai httpx
```

### 1.2 基础调用
```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-c233489e73e94b9591e4776d89ec8cb8",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "system", "content": "你是一个专业的交易助手"},
        {"role": "user", "content": "请分析BTC当前趋势"}
    ]
)

print(response.choices[0].message.content)
```

---

## 二、聊天补全 API

### 2.1 请求格式
```http
POST /chat/completions
Authorization: Bearer {API_KEY}
Content-Type: application/json

{
    "model": "qwen-plus",
    "messages": [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户消息"}
    ],
    "stream": false,
    "max_tokens": 1000,
    "temperature": 0.7,
    "top_p": 0.9,
    "presence_penalty": 0,
    "frequency_penalty": 0
}
```

### 2.2 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|:---|:---|:---:|:---:|:---|
| `model` | string | ✅ | - | 模型名称 |
| `messages` | array | ✅ | - | 消息列表 |
| `stream` | boolean | - | false | 是否流式输出 |
| `max_tokens` | integer | - | - | 最大生成token数 |
| `temperature` | float | - | 0.7 | 随机性 (0-2) |
| `top_p` | float | - | 0.9 | 核采样 |
| `presence_penalty` | float | - | 0 | 重复惩罚 |
| `frequency_penalty` | float | - | 0 | 频率惩罚 |
| `stop` | string/array | - | - | 停止词 |
| `tools` | array | - | - | 工具定义 |
| `tool_choice` | string | - | auto | 工具选择 |

### 2.3 响应格式
```json
{
    "id": "chatcmpl-xxx",
    "object": "chat.completion",
    "created": 1715149200,
    "model": "qwen-plus",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "回答内容"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150
    }
}
```

### 2.4 Python SDK 调用
```python
# 标准调用
response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "user", "content": "你好"}
    ]
)

# 带系统提示
response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "system", "content": "你是一个专业的量化交易分析师"},
        {"role": "user", "content": "分析当前BTC市场"}
    ],
    temperature=0.5,
    max_tokens=2000
)

# 流式输出
stream = client.chat.completions.create(
    model="qwen-plus",
    messages=[{"role": "user", "content": "讲一个故事"}],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

---

## 三、Function Calling / 工具调用

### 3.1 定义工具
```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": "获取市场行情数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "交易对，如 BTC-USDT"
                    },
                    "interval": {
                        "type": "string",
                        "enum": ["1m", "5m", "1h", "4h", "1d"],
                        "description": "时间周期"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_orderbook",
            "description": "获取订单簿数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "交易对"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "订单数量",
                        "default": 20
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]
```

### 3.2 调用带工具的模型
```python
response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "user", "content": "BTC现在多少钱？"}
    ],
    tools=tools,
    tool_choice="auto"
)

# 处理工具调用
tool_calls = response.choices[0].message.tool_calls
for call in tool_calls:
    function_name = call.function.name
    arguments = json.loads(call.function.arguments)

    print(f"调用函数: {function_name}")
    print(f"参数: {arguments}")

    # 执行函数
    if function_name == "get_market_data":
        result = get_market_data(**arguments)
    elif function_name == "get_orderbook":
        result = get_orderbook(**arguments)

    # 返回结果给模型
    messages.append(response.choices[0].message)
    messages.append({
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(result)
    })

# 第二次调用获取最终回复
final_response = client.chat.completions.create(
    model="qwen-plus",
    messages=messages,
    tools=tools
)
```

### 3.3 工具调用完整示例
```python
import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-c233489e73e94b9591e4776d89ec8cb8",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 模拟数据源
def get_btc_price():
    return {"symbol": "BTC-USDT", "price": 95000.50, "change_24h": 2.5}

def get_eth_price():
    return {"symbol": "ETH-USDT", "price": 3500.00, "change_24h": -1.2}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_btc_price",
            "description": "获取BTC实时价格",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_eth_price",
            "description": "获取ETH实时价格",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

def call_with_tools(user_message):
    messages = [{"role": "user", "content": user_message}]

    # 第一次调用
    response = client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        tools=TOOLS
    )

    assistant_message = response.choices[0].message
    messages.append(assistant_message)

    # 处理工具调用
    if assistant_message.tool_calls:
        for call in assistant_message.tool_calls:
            if call.function.name == "get_btc_price":
                result = get_btc_price()
            elif call.function.name == "get_eth_price":
                result = get_eth_price()
            else:
                result = {"error": "Unknown function"}

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result)
            })

        # 第二次调用
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            tools=TOOLS
        )

    return response.choices[0].message.content

# 测试
print(call_with_tools("BTC现在多少钱？"))
```

---

## 四、向量化 API

### 4.1 请求格式
```http
POST /embeddings
Authorization: Bearer {API_KEY}
Content-Type: application/json

{
    "model": "text-embedding-v3",
    "input": "要向量化的文本"
}
```

### 4.2 Python 调用
```python
response = client.embeddings.create(
    model="text-embedding-v3",
    input="这是一段需要向量化的文本"
)

embedding = response.data[0].embedding
print(f"向量维度: {len(embedding)}")
print(f"前5个值: {embedding[:5]}")
```

### 4.3 批量向量化
```python
response = client.embeddings.create(
    model="text-embedding-v3",
    input=[
        "第一个文本",
        "第二个文本",
        "第三个文本"
    ]
)

for item in response.data:
    print(f"Index: {item.index}, Embedding length: {len(item.embedding)}")
```

---

## 五、图像生成 API

### 5.1 请求格式
```http
POST /images/generations
Authorization: Bearer {API_KEY}
Content-Type: application/json

{
    "model": "wanx-plus",
    "prompt": "一个交易K线图的插画风格图片",
    "n": 1,
    "size": "1024*1024"
}
```

### 5.2 Python 调用
```python
response = client.images.generate(
    model="wanx-plus",
    prompt="一个现代风格的量化交易Dashboard界面",
    n=1,
    size="1024x1024"
)

image_url = response.data[0].url
print(f"生成图片: {image_url}")
```

---

## 六、错误处理

### 6.1 错误码说明
| 错误码 | 说明 | 处理建议 |
|:---|:---|:---|
| 400 | 请求参数错误 | 检查参数格式 |
| 401 | 认证失败 | 检查API Key |
| 403 | 权限不足 | 检查账户状态 |
| 429 | 请求过多 | 降低频率，等待重试 |
| 500 | 服务器错误 | 重试或联系支持 |
| 503 | 服务不可用 | 稍后重试 |

### 6.2 错误处理代码
```python
from openai import OpenAI
from openai import RateLimitError, APIError

client = OpenAI(
    api_key="sk-c233489e73e94b9591e4776d89ec8cb8",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

def call_with_retry(messages, max_retries=3, backoff=1):
    for i in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="qwen-plus",
                messages=messages
            )
            return response

        except RateLimitError:
            # 限流，等待后重试
            wait_time = backoff * (2 ** i)
            print(f"限流，等待 {wait_time}s...")
            time.sleep(wait_time)

        except APIError as e:
            if e.status_code == 429:
                wait_time = backoff * (2 ** i)
                print(f"请求过多，等待 {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"API错误: {e}")
                raise

    raise Exception("重试次数耗尽")
```

### 6.3 完整错误处理示例
```python
import time
import json
from openai import OpenAI, RateLimitError, APIError

class BailianClient:
    def __init__(self, api_key):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

    def call(self, messages, model="qwen-plus", **kwargs):
        """带完整错误处理的调用"""
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            return {
                "success": True,
                "data": response
            }

        except RateLimitError as e:
            return {
                "success": False,
                "error": "rate_limit",
                "message": "请求频率超限",
                "retry_after": getattr(e, 'retry_after', 60)
            }

        except APIError as e:
            error_body = json.loads(e.response.text) if e.response else {}
            return {
                "success": False,
                "error": error_body.get("code", "api_error"),
                "message": error_body.get("message", str(e)),
                "status_code": e.status_code
            }

        except Exception as e:
            return {
                "success": False,
                "error": "unknown",
                "message": str(e)
            }

    def call_with_retry(self, messages, model="qwen-plus", max_retries=3):
        """带重试的调用"""
        for i in range(max_retries):
            result = self.call(messages, model)

            if result["success"]:
                return result

            if result["error"] in ["rate_limit"]:
                wait_time = result.get("retry_after", 60) * (2 ** i)
                print(f"重试 {i+1}/{max_retries}，等待 {wait_time}s...")
                time.sleep(wait_time)
                continue

            # 其他错误不重试
            return result

        return {
            "success": False,
            "error": "max_retries_exceeded",
            "message": "重试次数耗尽"
        }

# 使用示例
client = BailianClient("sk-c233489e73e94b9591e4776d89ec8cb8")

result = client.call_with_retry([
    {"role": "user", "content": "分析BTC当前趋势"}
])

if result["success"]:
    print(result["data"].choices[0].message.content)
else:
    print(f"调用失败: {result['message']}")
```

---

## 七、最佳实践

### 7.1 成本优化
```python
# 1. 设置合理的 max_tokens
response = client.chat.completions.create(
    model="qwen-plus",
    messages=messages,
    max_tokens=500  # 根据实际需求设置
)

# 2. 使用批量处理
# 避免多次小调用，合并为一次大调用

# 3. 缓存常用结果
cache = {}

def cached_call(prompt_hash, messages):
    if prompt_hash in cache:
        return cache[prompt_hash]
    response = client.chat.completions.create(...)
    cache[prompt_hash] = response
    return response
```

### 7.2 性能优化
```python
# 1. 使用连接池
import httpx

client = OpenAI(
    api_key="sk-c233489e73e94b9591e4776d89ec8cb8",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    http_client=httpx.Client(
        timeout=httpx.Timeout(60.0),
        limits=httpx.Limits(max_keepalive_connections=20)
    )
)

# 2. 异步调用
import asyncio
from openai import AsyncOpenAI

async_client = AsyncOpenAI(
    api_key="sk-c233489e73e94b9591e4776d89ec8cb8",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

async def async_call(messages):
    response = await async_client.chat.completions.create(
        model="qwen-plus",
        messages=messages
    )
    return response

# 并发调用
tasks = [async_call([{"role": "user", "content": f"问题{i}"}]) for i in range(10)]
results = await asyncio.gather(*tasks)
```

### 7.3 安全性
```python
# 1. 不在日志中打印敏感信息
def log_request(messages):
    # 脱敏处理
    safe_messages = []
    for msg in messages:
        safe_msg = {
            "role": msg["role"],
            "content": msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
        }
        safe_messages.append(safe_msg)
    print(f"Request: {safe_messages}")

# 2. 环境变量存储 Key
import os
client = OpenAI(
    api_key=os.environ.get("BAILIAN_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
```

---

*本文档提供百炼API的完整调用参考，用于Dream-MultiSkill系统集成。*
