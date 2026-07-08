# Dream-MultiSkill 工程索引 (百炼集成版)

**版本**: v1.0
**日期**: 2026-05-07

---

## 一、文档索引

### 1.1 核心文档
| 文档 | 路径 | 说明 |
|:---|:---|:---|
| SKILL.md | `SKILL.md` | 主入口文档 |
| 宪法 | `governance/constitution.md` | 最高指导原则 |
| 工作流程 | `governance/workflow.md` | 标准化流程 |
| FAQ | `governance/faq.md` | 常见问题 |
| 工程索引 | `governance/engineering_index.md` | 本文档 |

### 1.2 技术文档
| 文档 | 路径 | 说明 |
|:---|:---|:---|
| 平台概览 | `docs/bailian_platform_overview.md` | 百炼能力概览 |
| API参考 | `docs/api_reference.md` | API调用参考 |
| Function Calling | `docs/function_calling_guide.md` | 工具调用指南 |
| 知识库RAG | `docs/rag_knowledge_base.md` | RAG构建指南 |

### 1.3 SKILL模板
| 文档 | 路径 | 说明 |
|:---|:---|:---|
| AAM SKILL | `skill_templates/aam_skill.md` | 产物对齐管理器 |
| 合规SKILL | `skill_templates/compliance_skill.md` | 合规审查 |

---

## 二、代码索引

### 2.1 核心模块
| 模块 | 路径 | 功能 |
|:---|:---|:---|
| bailian_client | `src/bailian_client.py` | 百炼API客户端 |
| rag_engine | `src/rag_engine.py` | 知识库RAG引擎 |
| workflow_engine | `src/workflow_engine.py` | 工作流编排引擎 |
| function_caller | `src/function_caller.py` | Function Calling管理器 |
| aam_deliverer | `src/aam_deliverer.py` | 产物传递管理器 |

### 2.2 工具脚本
| 脚本 | 路径 | 功能 |
|:---|:---|:---|
| verify_api | `scripts/verify_api.py` | API验证脚本 |
| build_knowledge | `scripts/build_knowledge.py` | 知识库构建脚本 |
| test_workflow | `scripts/test_workflow.py` | 工作流测试脚本 |

### 2.3 配置文件
| 配置 | 路径 | 说明 |
|:---|:---|:---|
| api_config | `config/api_config.yaml` | API配置 |
| rag_config | `config/rag_config.yaml` | RAG配置 |
| workflow_config | `config/workflow_config.yaml` | 工作流配置 |

---

## 三、目录结构

```
dream-bailian-integration/
├── SKILL.md                          # 主入口
├── src/
│   ├── __init__.py
│   ├── bailian_client.py             # 百炼API客户端
│   ├── rag_engine.py                 # RAG引擎
│   ├── workflow_engine.py            # 工作流引擎
│   ├── function_caller.py            # Function Calling
│   └── aam_deliverer.py              # AAM投递
├── config/
│   ├── api_config.yaml              # API配置
│   ├── rag_config.yaml              # RAG配置
│   └── workflow_config.yaml         # 工作流配置
├── scripts/
│   ├── verify_api.py                # API验证
│   ├── build_knowledge.py           # 知识库构建
│   └── test_workflow.py             # 工作流测试
├── docs/
│   ├── bailian_platform_overview.md # 平台概览
│   ├── api_reference.md             # API参考
│   ├── function_calling_guide.md    # Function Calling
│   └── rag_knowledge_base.md        # RAG指南
├── governance/
│   ├── constitution.md              # 宪法
│   ├── workflow.md                  # 工作流程
│   ├── faq.md                       # FAQ
│   └── engineering_index.md         # 工程索引
├── skill_templates/
│   ├── aam_skill.md                 # AAM SKILL
│   └── compliance_skill.md          # 合规SKILL
├── logs/                            # 日志目录
└── data/                            # 数据目录
```

---

## 四、API端点索引

### 4.1 百炼API端点
| 端点 | 方法 | 说明 |
|:---|:---|:---|
| `/compatible-mode/v1/chat/completions` | POST | 聊天补全 |
| `/api/v1/services/aigc/text-generation/generation` | POST | 文本生成 (旧版) |
| `/compatible-mode/v1/embeddings` | POST | 向量嵌入 |
| `/api/v1/services/aigc/images/generation` | POST | 图像生成 |

### 4.2 内部API端点
| 端点 | 方法 | 说明 |
|:---|:---|:---|
| `/bailian/call` | POST | 标准调用 |
| `/bailian/rag/retrieve` | POST | RAG检索 |
| `/bailian/workflow/execute` | POST | 工作流执行 |
| `/bailian/aam/deliver` | POST | 产物投递 |
| `/bailian/health` | GET | 健康检查 |

---

## 五、环境变量索引

| 变量 | 说明 | 示例 |
|:---|:---|:---|
| `BAILIAN_API_KEY` | 百炼API Key | `sk-xxx` |
| `BAILIAN_BASE_URL` | API Base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `BAILIAN_MODEL` | 默认模型 | `qwen3.6-35b-a3b` |
| `BAILIAN_TIMEOUT` | 超时时间(秒) | `30` |
| `BAILIAN_LOG_LEVEL` | 日志级别 | `DEBUG\|INFO\|WARN\|ERROR` |

---

## 六、数据库索引

### 6.1 日志库 (SQLite)
| 表名 | 说明 |
|:---|:---|
| `bailian_calls` | API调用日志 |
| `rag_queries` | RAG查询日志 |
| `workflow_runs` | 工作流运行日志 |
| `aam_deliveries` | 产物投递日志 |

### 6.2 索引定义
```sql
CREATE INDEX idx_calls_trace_id ON bailian_calls(trace_id);
CREATE INDEX idx_calls_timestamp ON bailian_calls(timestamp);
CREATE INDEX idx_rag_query_time ON rag_queries(query_time);
CREATE INDEX idx_workflow_status ON workflow_runs(status);
CREATE INDEX idx_delivery_dept ON aam_deliveries(department);
```

---

## 七、监控指标索引

### 7.1 核心指标
| 指标 | 说明 | 告警阈值 |
|:---|:---|:---|
| `bailian_api_calls_total` | API调用总数 | - |
| `bailian_api_errors_total` | API错误总数 | > 1% |
| `bailian_api_latency_seconds` | API延迟 | p99 > 5s |
| `bailian_cost_total` | 累计成本 | 日 > ¥100 |
| `rag_retrieval_accuracy` | RAG准确率 | < 80% |
| `workflow_success_rate` | 工作流成功率 | < 95% |

### 7.2 仪表盘
- Grafana: `dashboard/bailian_overview.json`
- 告警规则: `alerts/bailian_alerts.yaml`

---

## 八、故障排查索引

### 8.1 常见问题速查
| 问题 | 快速解决方案 |
|:---|:---|
| API 403 | 关闭「免费额度用完」开关 |
| 超时 | 增加 timeout 或切换模型 |
| RAG不准 | 检查分块和embedding配置 |
| 投递失败 | 检查文件权限和磁盘空间 |

### 8.2 日志定位
```bash
# 查看最近错误日志
tail -100 logs/bailian_*.jsonl | grep ERROR

# 查看特定trace_id
grep "trace_id_xxx" logs/bailian_*.jsonl

# 查看API调用日志
grep "bailian_call" logs/bailian_*.jsonl
```

---

## 九、依赖索引

### 9.1 Python依赖
| 包 | 版本 | 用途 |
|:---|:---|:---|
| requests | >= 2.28 | HTTP客户端 |
| faiss-cpu | >= 1.7 | 向量检索 |
| sqlalchemy | >= 2.0 | 数据库ORM |
| pydantic | >= 2.0 | 数据验证 |

### 9.2 系统依赖
| 依赖 | 说明 |
|:---|:---|
| Python | >= 3.10 |
| SQLite | >= 3.0 |

---

## 十、版本索引

| 版本 | 日期 | 主要变更 |
|:---|:---|:---|
| v1.0 | 2026-05-07 | 初始版本 |

---

*本索引是百炼集成的工程参考文档，定期更新。*
