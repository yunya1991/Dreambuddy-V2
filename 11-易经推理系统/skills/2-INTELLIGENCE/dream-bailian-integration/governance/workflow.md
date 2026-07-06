# Dream-MultiSkill 工作流程与规范 (百炼集成版)

**版本**: v1.0
**日期**: 2026-05-07
**状态**: 生效

---

## 一、百炼API调用流程

### 1.1 标准调用流程
```
[1] 准备请求 → [2] 参数校验 → [3] 发送请求 → [4] 响应处理 → [5] 错误恢复 → [6] 日志记录
```

### 1.2 调用前检查清单
- [ ] API Key 已配置
- [ ] 模型选择正确 (免费优先)
- [ ] 请求参数符合 schema
- [ ] 超时设置合理 (默认30s)
- [ ] trace_id 已生成

### 1.3 调用代码模板
```python
import urllib.request
import json
import time
from datetime import datetime

TRACE_ID = f"bailian_{int(time.time() * 1000)}"

def bailian_call(messages, model="qwen3.6-35b-a3b", trace_id=TRACE_ID):
    """百炼API标准调用"""
    api_key = "sk-c233489e73e94b9591e4776d89ec8cb8"
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    data = {
        "model": model,
        "messages": messages,
        "extra_headers": {"X-Trace-Id": trace_id}
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

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            log_bailian_call(trace_id, model, "success", resp.status)
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        log_bailian_call(trace_id, model, "error", e.code, error_body)
        handle_error(e, trace_id)
        raise
```

### 1.4 错误处理矩阵
| 错误码 | 含义 | 处理方式 |
|:---|:---|:---|
| 400 | 参数错误 | 检查schema，降级调用 |
| 401 | 认证失败 | 检查API Key |
| 403 | 权限不足/免费额度用完 | 充值或切换模型 |
| 429 | 请求过多 | 等待重试 (exponential backoff) |
| 500 | 服务器错误 | 重试3次，超过则降级 |
| 503 | 服务不可用 | 降级到备用模型 |

---

## 二、知识库RAG构建流程

### 2.1 RAG构建标准流程
```
[1] 数据采集 → [2] 数据清洗 → [3] 分块处理 → [4] 向量化 → [5] 索引构建 → [6] 质量验证
```

### 2.2 数据分类标准
| 数据类型 | 存储位置 | 访问权限 |
|:---|:---|:---|
| 交易数据 | `~/.workbuddy/artifacts/trading/` | A1-A9 |
| 治理数据 | `~/.workbuddy/artifacts/governance/` | A7/A8 |
| 知识数据 | `~/.workbuddy/artifacts/knowledge/` | ALL |
| 支撑数据 | `~/.workbuddy/artifacts/support/` | HR/OPS |

### 2.3 分块规范
- **标准块大小**: 500-1000 tokens
- **重叠率**: 10-20%
- **格式**: Markdown (保留标题结构)

### 2.4 向量化配置
```python
EMBEDDING_CONFIG = {
    "model": "text-embedding-v3",
    "dimension": 1536,
    "normalize": True
}
```

---

## 三、工作流编排流程

### 3.1 工作流设计原则
1. **节点化**: 每个步骤作为一个节点
2. **边连接**: 节点之间用条件边连接
3. **状态管理**: 每步执行后保存状态快照
4. **可重试**: 失败节点可从上次状态重试

### 3.2 工作流模板
```yaml
workflow_template:
  name: "百炼知识问答工作流"
  nodes:
    - id: "input"
      type: "start"
      output: "user_query"

    - id: "retrieve"
      type: "rag_retrieve"
      input: "user_query"
      output: "context_chunks"

    - id: "generate"
      type: "bailian_call"
      input: "user_query + context_chunks"
      output: "answer"

    - id: "quality_check"
      type: "gate"
      input: "answer"
      condition: "confidence > 0.7"

    - id: "output"
      type: "end"
      input: "answer"
```

### 3.3 工作流执行监控
- **开始**: 记录开始时间 + trace_id
- **进行中**: 每分钟记录心跳
- **完成**: 记录结束时间 + 结果摘要
- **失败**: 记录错误 + 回滚操作

---

## 四、Function Calling配置流程

### 4.1 函数定义规范
```python
TOOLS = [
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
                        "enum": ["1m", "5m", "1h", "4h", "1d"]
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]
```

### 4.2 调用执行流程
```
[1] 模型推理 → [2] 函数选择 → [3] 参数提取 → [4] 参数校验 → [5] 执行函数 → [6] 返回结果 → [7] 模型汇总
```

### 4.3 安全检查清单
- [ ] 危险操作 (删除/修改) 需要二次确认
- [ ] 资金操作需要双签
- [ ] 敏感数据访问需要权限验证
- [ ] 操作结果需要审计日志

---

## 五、产物传递(AAM)流程

### 5.1 标准投递流程
```
[1] 生成产物 → [2] 添加frontmatter → [3] 双通道写入 → [4] 更新index.json → [5] 验证投递 → [6] 日志记录
```

### 5.2 frontmatter模板
```yaml
---
title: "产物标题 YYYY-MM-DD"
department: trading|governance|hr|knowledge|support|cfo
chain_phase: A1|A2|A3|A4|A5|A6|A7|A8|A9
date: "YYYY-MM-DDTHH:MM:SS+08:00"
type: report|analysis|decision|skill|artifact
status: draft|review|completed|archived
tags: "tag1 tag2 tag3"
by_a_phase: A1|A2|A3|A4|A5|A6|A7|A8|A9
---
```

### 5.3 双通道投递代码
```python
import os
import json
import shutil
from datetime import datetime

ARTIFACT_TEMPLATE = """---
title: "{title}"
department: {department}
chain_phase: {chain_phase}
date: "{date}"
type: {type}
status: {status}
tags: "{tags}"
by_a_phase: {by_a_phase}
---

{content}
"""

def deliver_artifact(artifact_name, content, config):
    """双通道产物投递"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{artifact_name}_{timestamp}"

    # 生成 frontmatter
    md_content = ARTIFACT_TEMPLATE.format(
        title=config['title'],
        department=config['department'],
        chain_phase=config['chain_phase'],
        date=datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        type=config['type'],
        status=config['status'],
        tags=config['tags'],
        by_a_phase=config['by_a_phase'],
        content=content
    )

    # 通道1: 秘书邮箱
    secretary_path = f"~/.workbuddy/skills/boss-secretary/reports/{config['department']}/{filename}.md"
    with open(os.path.expanduser(secretary_path), 'w') as f:
        f.write(md_content)

    # 通道2: 前端产物中心
    hub_path = f"~/.workbuddy/artifacts/{config['department']}/{filename}.md"
    with open(os.path.expanduser(hub_path), 'w') as f:
        f.write(md_content)

    # 更新 index.json
    update_index(config['department'], filename, config)

    # 验证
    verify_delivery(config['department'], filename)

    print(f"✅ 产物已投递: {filename}")
    return filename
```

### 5.4 验证检查清单
- [ ] `.md` 文件写入秘书邮箱
- [ ] `.md` 文件写入前端产物中心
- [ ] `index.json` 已更新
- [ ] frontmatter 完整 (7字段)
- [ ] curl 验证返回 200

---

## 六、合规审查流程

### 6.1 变更分类
| 分类 | 说明 | 审查级别 |
|:---|:---|:---:|
| P0 | 核心逻辑变更，重大风险 | 必须人工确认 |
| P1 | 重要功能变更 | 必须人工确认 |
| P2 | 一般功能变更 | 自动执行 |
| P3 | 小幅优化 | 自动执行 |

### 6.2 合规审查清单
- [ ] 变更描述完整
- [ ] rollback_plan_id 已生成
- [ ] evidence_refs 已关联
- [ ] 影子验证已通过 (P0/P1)
- [ ] 审计日志已记录

### 6.3 审查输出
```json
{
  "trace_id": "xxx",
  "decision": "pass|warn|fail",
  "reason_codes": [],
  "gate_report": {
    "contract_check": "pass",
    "evidence_check": "pass",
    "risk_check": "pass",
    "rollback_ready": "yes"
  },
  "release_advice": "publish|shadow_only|reject"
}
```

---

## 七、日志规范

### 7.1 日志格式
```json
{
  "timestamp": "2026-05-07T10:00:00+08:00",
  "level": "INFO|WARN|ERROR",
  "trace_id": "bailian_xxx",
  "action": "action_name",
  "detail": "...",
  "duration_ms": 123,
  "status": "success|error"
}
```

### 7.2 日志存储
- **本地**: `~/.workbuddy/skills/dream-bailian-integration/logs/`
- **格式**: JSONL (按天分割)
- **保留**: 30天自动清理

---

*本文档遵循宪法最高指导原则，是百炼集成的标准化工作流程。*
