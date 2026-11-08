# AI 宿主快速接入 — 广义认知系统 MCP

> **版本**: v1.0 | **更新日期**: 2026-11-08
> **适用**: Claude Code / TRAE / Cursor / Windsurf / Continue / 任意支持 stdio MCP 的宿主
> **目标**: 换 AI 工具时 3 分钟内接入 `recall / record / verify / unified_search / l4_status` 等 7 个工具，并避免重复踩坑。

---

## 1. 三条命令

### 1.1 安装到 Claude Code（推荐）

从任意目录运行，**使用脚本绝对路径**：

```powershell
# Windows PowerShell
python "C:\Users\luke.zhang\Desktop\dreambuddy\4-MEMORY\9-工具与接口\deploy\install_cognitive_mcp.py" --target claude
```

```bash
# macOS / Linux
python3 "/path/to/dreambuddy/4-MEMORY/9-工具与接口/deploy/install_cognitive_mcp.py" --target claude
```

安装器会：检查 Python → 启动 stdio 验证 `initialize/tools/list` → 备份宿主配置 → 写入
`mcpServers.cognitive`（含写治理 env）。

### 1.2 宿主禁止写配置时：只打印 JSON

```bash
python "…/deploy/install_cognitive_mcp.py" --print-config --target claude
```

把输出粘贴到宿主的 MCP 配置文件中即可。输出使用 `ensure_ascii=True`，中文路径不会因控制台编码损坏。

### 1.3 只验证、不写配置

```bash
python "…/deploy/install_cognitive_mcp.py" --verify-only --target claude
```

---

## 2. 配置矩阵

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `PYTHONPATH` | 认知工具目录 | 保证 `cognitive_loop_entry` 等模块可 import |
| `PYTHONUTF8` | `1` | Windows UTF-8 模式，避免 GBK 编解码故障 |
| `PYTHONIOENCODING` | `utf-8` | stdio/日志统一 UTF-8 |
| `COGNITIVE_MCP_MODE` | `ssh` | `local` = 只读降级；`ssh` / 未设 = 可写（受写 scope 约束） |
| `COGNITIVE_MCP_WRITE_ENABLED` | `false` | 写工具总开关；安装器默认写 `true` 作为宿主 Mandate |
| `COGNITIVE_MCP_DEFAULT_PRINCIPAL` | 空 | 写主体；允许 `orchestrator` / `verifier` / `admin`，`worker` 只读 |
| `COGNITIVE_MCP_ALLOW_CALLER_PRINCIPAL` | `false` | 是否信任调用方自声明 `principal`（默认不信任） |
| `COGNITIVE_MCP_EVAL_GATE_MODE` | `shadow` | 45 门禁：`off` / `shadow`（仅记录）/ `enforce`（无 `eval_id` 拒绝） |
| `COGNITIVE_MCP_DB_PATH` | 空 | 指定共享认知库；多宿主/多进程务必指向同一路径，避免分叉 |
| `MCP_TRACE_ID` | 空 | 宿主导入的 trace_id，供信封贯穿 |

> **只读接入**：加 `--read-only`，安装器会写 `COGNITIVE_MCP_MODE=local` +
> `COGNITIVE_MCP_WRITE_ENABLED=false` + `worker` 主体。

---

## 3. 宿主配置路径与重载

| 宿主 | 配置位置 | 生效方式 |
|---|---|---|
| Claude Code | `~/.claude.json`（user scope）或项目 `.mcp.json` | 重启 Claude Code / `/mcp` |
| TRAE | `<project>/.trae/mcp.json` | 重启会话 / 命令面板 MCP:Reload |
| Cursor | `~/.cursor/mcp.json` | 重启 Cursor / `Cmd+Shift+P → MCP: Reload` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | 重启 Windsurf |
| Continue.dev | `~/.continue/config.json` | 重启 Continue.dev |

---

## 4. 接入后自检（4 步）

```bash
# 1) 宿主是否连上
claude mcp list
# 期望：cognitive: ... cognitive_mcp_server.py - ✓ Connected

# 2) 工具是否暴露（应 7 个）
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python "…/cognitive_mcp_server.py"

# 3) 读工具是否可用
#    在会话中调用 recall(context="smoke test", top_k=1, min_quality="C")
#    空库返回 count=0 + ok=true 属正常

# 4) 写治理是否可见
#    调用 stats 或 health，检查 data.mcp_policy.write_enabled / principal / eval_gate_mode
```

写工具被拒时，返回 `error_code`：

| error_code | 含义 | 处理 |
|---|---|---|
| `scope_denied` | `COGNITIVE_MCP_WRITE_ENABLED != true` | 宿主 env 打开写 scope |
| `principal_denied` | principal 为空或 `worker` | 设置 `admin`/`orchestrator`/`verifier` |
| `eval_gate_denied` | enforce 模式缺 `eval_id` 或门禁不可用 | 传 `eval_id` 或切回 `shadow` |
| `conflict` | `COGNITIVE_MCP_MODE=local` 只读降级 | 改用可写 profile |

---

## 5. 本次接入踩坑与固化

| 症状 | 根因 | 已固化 |
|---|---|---|
| `can't open file '...4-MEMORY...'` | 在错误 cwd 用相对路径 | 文档统一用绝对路径；安装器自身路径解析稳定 |
| 宿主配置写不进去 | 宿主/安全策略禁止写 `~/.claude.json` | `--print-config` 输出 JSON 手工粘贴 |
| `record` 返回无 `memory_id` | 写工具默认禁用 | 安装器默认注入 `COGNITIVE_MCP_WRITE_ENABLED=true` + admin；`stats/health` 暴露 `mcp_policy` |
| 中文路径在终端乱码 | Windows GBK 控制台 | `--print-config` 用 `ensure_ascii=True`；MCP env 注入 `PYTHONUTF8/PYTHONIOENCODING` |
| `python3` 找不到 | Windows 无 `python3` 别名 | 安装器写绝对 `python.exe`；文档用 `python` |
| 测试报 GBK 编解码 | 文件读写未显式 UTF-8 | 认知 session/superpowers 统一 `encoding="utf-8"`；测试同步 |
| 各宿主各建一个空库 | 默认库路径未显式配置 | `COGNITIVE_MCP_DB_PATH` 共享库；安装器 `--db` |
| `l4_status` 调不到 | 只在 `TOOL_NAMES`，漏 `TOOL_DEFINITIONS` | 已补定义；新增 `TOOL_NAMES == definitions` 一致性测试 |
| RAG/GraphRAG 测试失败 | 缺 `networkx` / `chromadb` | `pyproject.toml` 增加 `knowledge` extra；测试缺依赖时 skip |
| 旧测试读不到业务字段 | 统一信封后字段在 `data` 内 | 测试统一 `result.get("data", result)` |
| `unified_search` 命中 `text` 为空 | Chroma 后端未适配 `IndexQueryService` 的 `title/path/description` 形状 | 后端统一归一化 text/ref/meta，新增测试 |
| 所有命中分数被压成 0 | min-max 归一化在同分时 `span=0` | 同分保留 1.0，新增测试 |
| `search41` 一直 degraded | 41 v0.6+ 已迁移 **PostgreSQL（fis 库）**，本地 `data/index.db` 不是事实源 | 云端配置 `FIS_PG_*` 并用 `41/api/search_api.py`；本地无 PG 时按 FAIL-OPEN degraded |

---

## 6. 可选依赖

```bash
pip install -e ".[knowledge]"   # networkx + chromadb（GraphRAG / 向量检索）
pip install scipy                # PSI/KS 漂移检测（缺失时 drift_detector 走纯 Python 回退）
pip install -e ".[embedding]"    # sentence-transformers（bge-small-zh 真语义嵌入；体积较大）
```

> **依赖冲突提示**：安装 `chromadb` 可能升级 `pydantic` / `python-dotenv` / `oauthlib`。
> 若同机使用 `hermes-agent`，安装后按其 pin 回退（`pydantic==2.12.5`、
> `python-dotenv==1.2.1`、`oauthlib<4`），再确认 `chromadb` 可正常 import。

### 6.1 知识库索引重建（换机/换 AI 宿主后必做）

```bash
# 常规增量重建
python "C:\Users\luke.zhang\Desktop\dreambuddy\2-KNOWLEDGE\9-RAG-INFRA\scripts\rebuild_indexes.py"

# 换机/删除过知识文件后：先清空集合与哈希账本，再全量重建
python "...\rebuild_indexes.py" --reset
```

一次重建三层索引：

| 索引 | 存储 | 规模（本机实测） |
|---|---|---|
| `dreambuddy_index` | `chroma_db/` | 962 条（INDEX.md + SKILL registry） |
| `dreambuddy_knowledge` | `chroma_db/` | 4,402 chunks（335 个 md） |
| `keyword_index` | `keyword_index/bm25_index.json` | 4,402 docs（BM25） |

> **嵌入说明**：装有 `sentence-transformers` 时自动使用 `BAAI/bge-small-zh-v1.5`；
> 未安装时 `embedder.py` 回退 TF-IDF，向量通道可能因阈值返回 0，此时混合检索由
> BM25 关键词通道承担。安装 `.[embedding]` 后重跑本脚本即可切换为真语义索引。

---

## 7. 多宿主 / 云端

- **多宿主共享**：所有宿主配置同一个 `COGNITIVE_MCP_DB_PATH`（如 `4-MEMORY/data/cognitive_memory.db`）。
- **云端单一事实源**：`--remote-ssh <alias>` 生成 ssh-stdio profile，`record/verify/recall` 全部落远端；
  本机只读快照。前置条件：`~/.ssh/config` 存在该 alias。
- **本地只读**：`--read-only`；适合桌面端浏览、训练数据读取。

---

## 8. 相关文件

- [COLLABORATION-CONTRACT.md](./COLLABORATION-CONTRACT.md) §5.4 治理实现映射
- [47-MCP管理系统/registry/mcp_profiles.json](../47-MCP管理系统/registry/mcp_profiles.json) 双模 profile 模板
- [4-MEMORY/9-工具与接口/deploy/install_cognitive_mcp.py](../4-MEMORY/9-工具与接口/deploy/install_cognitive_mcp.py) 安装器
- [4-MEMORY/9-工具与接口/cognitive_mcp_server.py](../4-MEMORY/9-工具与接口/cognitive_mcp_server.py) MCP server