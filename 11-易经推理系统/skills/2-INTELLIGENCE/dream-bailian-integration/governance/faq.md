# Dream-MultiSkill 常见问题 (FAQ)

**版本**: v1.0
**日期**: 2026-05-07

---

## 一、API调用相关

### Q1: 如何配置百炼API Key？
**A:** 将以下内容添加到环境配置或代码中：

```python
API_KEY = "sk-c233489e73e94b9591e4776d89ec8cb8"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

推荐将 Key 存储在 `~/.env` 文件中，通过环境变量读取。

### Q2: 免费额度用完了怎么办？
**A:** 
1. 登录 [百炼控制台](https://bailian.console.aliyun.com)
2. 进入「API-KEY 管理」
3. **关闭**「仅使用免费额度」开关
4. 充值一定金额 (建议 ¥100-500)
5. 重新测试调用

### Q3: 如何选择合适的模型？
**A:** 参考以下决策矩阵：

| 场景 | 推荐模型 | 原因 |
|:---|:---|:---|
| 快速测试 | qwen-plus | 响应快，免费额度充足 |
| 复杂推理 | qwen-max | 能力最强，成本最高 |
| 成本优先 | qwen3.6-35b-a3b | 高性能低成本 |
| 多模态 | qwen-vl-plus | 支持视觉理解 |

### Q4: 调用返回 403 错误怎么解决？
**A:** 这是典型的「免费额度用完」错误：
```
{"code":"AllocationQuota.FreeTierOnly","message":"The free tier of the model has been exhausted..."}
```
**解决方案**：
1. 关闭「仅使用免费额度」开关
2. 或切换到其他有免费额度的模型

### Q5: 如何实现指数退避重试？
**A:**
```python
import time

def call_with_retry(func, max_retries=3, base_delay=1):
    for i in range(max_retries):
        try:
            return func()
        except Exception as e:
            if i == max_retries - 1:
                raise
            delay = base_delay * (2 ** i)  # 1, 2, 4, 8...
            print(f"Retry {i+1}/{max_retries} after {delay}s...")
            time.sleep(delay)
```

---

## 二、知识库RAG相关

### Q6: 如何构建自定义知识库？
**A:** 标准流程：
1. 准备数据 (Markdown/JSON/TXT)
2. 数据清洗 (去重/格式化)
3. 分块处理 (500-1000 tokens)
4. 向量化 (text-embedding-v3)
5. 构建索引 (FAISS/Milvus)
6. 质量验证

### Q7: RAG检索结果不准确怎么办？
**A:** 检查以下维度：
1. **数据质量**: 原始数据是否准确、完整
2. **分块策略**: 块大小是否合适 (太大/太小都不好)
3. **向量化模型**: 是否选择合适的 embedding 模型
4. **检索参数**: top_k、similarity_threshold 是否合理
5. **重排序**: 是否需要添加 rerank 步骤

### Q8: 如何实现多语言知识库检索？
**A:**
```python
EMBEDDING_CONFIG = {
    "model": "text-embedding-v3",
    "normalize": True,
    "workspace": "multi_lang_workspace"  # 多语言工作空间
}
```

---

## 三、工作流编排相关

### Q9: 如何设计可重试的工作流？
**A:** 关键设计原则：
1. **无状态节点**: 每步执行结果存储到外部
2. **幂等操作**: 重复执行不产生副作用
3. **检查点**: 定期保存执行快照
4. **重试队列**: 失败操作进入重试队列

```yaml
node_example:
  id: "process_order"
  retry:
    max_attempts: 3
    backoff: "exponential"
    retry_on: ["timeout", "connection_error"]
  checkpoint: "order_processed"
```

### Q10: 如何监控工作流执行状态？
**A:** 实现监控三要素：
1. **心跳**: 每分钟发送心跳到监控系统
2. **指标**: 记录执行时长、成功率、错误率
3. **告警**: 异常时触发告警 (P0/P1 → 立即通知)

```python
def monitor_workflow(workflow_id, trace_id):
    """工作流监控"""
    while True:
        status = get_workflow_status(workflow_id)
        report_heartbeat(trace_id, status)
        if status in ["completed", "failed"]:
            break
        time.sleep(60)
```

---

## 四、Function Calling相关

### Q11: 如何定义自定义函数？
**A:**
```python
def get_market_data(symbol: str, interval: str = "1h") -> dict:
    """
    获取市场行情数据
    Args:
        symbol: 交易对，如 BTC-USDT
        interval: 时间周期
    Returns:
        市场数据字典
    """
    # 实现逻辑...
    return {"symbol": symbol, "price": 95000, "volume": 1234}
```

### Q12: 函数调用失败如何处理？
**A:** 标准错误处理流程：
```python
try:
    result = call_function(tool_name, parameters)
except ValueError as e:
    # 参数错误，返回明确的修正建议
    return {"error": "参数校验失败", "detail": str(e), "suggestion": "..."}
except PermissionError as e:
    # 权限错误，需要升级权限
    return {"error": "权限不足", "detail": str(e), "escalation": True}
except Exception as e:
    # 其他错误，降级处理
    return {"error": "执行失败", "fallback": "use_cache"}
```

---

## 五、产物传递(AAM)相关

### Q13: frontmatter 哪些字段是强制的？
**A:** 以下7个字段必须完整：
1. `title` - 产物标题
2. `department` - 部门
3. `chain_phase` - A系列阶段
4. `date` - 日期时间 (YYYY-MM-DDTHH:MM:SS+08:00)
5. `type` - 产物类型
6. `status` - 状态
7. `tags` - 标签 (空格分隔)
8. `by_a_phase` - 生成来源 (A1-A9)

### Q14: 投递后如何验证？
**A:** 验证三步骤：
```bash
# 1. 检查秘书邮箱
ls -la ~/.workbuddy/skills/boss-secretary/reports/{department}/*.md

# 2. 检查前端产物中心
ls -la ~/.workbuddy/artifacts/{department}/*.md

# 3. curl 验证
curl -s -o /dev/null -w "%{http_code}" http://localhost:3456/feed/{department}/{filename}
# 期望返回: 200
```

### Q15: index.json 更新失败怎么办？
**A:** 手动修复流程：
1. 读取当前 index.json
2. 追加新条目
3. 校验 JSON 格式
4. 写回文件
5. 重新验证

```python
def fix_index(department, filename, metadata):
    index_path = f"~/.workbuddy/artifacts/{department}/index.json"
    with open(os.path.expanduser(index_path), 'r') as f:
        index = json.load(f)
    index['artifacts'].append(metadata)
    with open(os.path.expanduser(index_path), 'w') as f:
        json.dump(index, f, indent=2)
```

---

## 六、合规审查相关

### Q16: P0 变更一定要人工确认吗？
**A:** 是的。P0 变更必须：
1. 触发合规审查
2. 等待人工确认
3. 影子验证通过
4. 才能执行

### Q17: 如何生成 rollback_plan_id？
**A:**
```python
import uuid
from datetime import datetime

def generate_rollback_plan(change_description):
    plan_id = f"rollback_{uuid.uuid4().hex[:8]}"
    plan = {
        "plan_id": plan_id,
        "created_at": datetime.now().isoformat(),
        "change_description": change_description,
        "rollback_steps": [
            # 具体回滚步骤...
        ]
    }
    save_rollback_plan(plan)
    return plan_id
```

---

## 七、调试与故障排除

### Q18: 如何启用调试日志？
**A:**
```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("bailian")
logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
```

### Q19: 百炼调用超时如何排查？
**A:** 检查清单：
1. 网络连接是否正常
2. API Key 是否有效
3. 请求参数是否过大
4. 服务器是否限流
5. 尝试切换到其他地域节点

### Q20: 如何获取 trace_id 进行问题追踪？
**A:**
```python
import time
TRACE_ID = f"bailian_{int(time.time() * 1000)}"
# 在请求头中传递
headers = {"X-Trace-Id": TRACE_ID}
```

---

*持续更新中，如有问题请联系系统管理员。*
