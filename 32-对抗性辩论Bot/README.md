# 32-对抗性辩论Bot

> 正/反方 AI 辩手 + 中立裁判的结构化对抗评审引擎。既可用于营销内容，也可作为技术方案的红队评审。

## 开发状态（2026-11-08）

| 范围 | 状态 | 说明 |
|---|---|---|
| 核心辩论（v0.5） | ✅ 已实现 | Telegram 编排、立场锁、裁判、营销/质量、管理员命令 |
| v0.6 工程化 | ✅ 已实现 | `llm_compat` / `robust_json` / CLI / review_runner / MCP 壳 |
| Research Prepass P0 | ✅ 已实现 | `recall` / `unified_search` / `code_search` + `l1_signal` / `l1_bus` / `l1_cycle`（signal profile）+ citations + fail-open |
| P1 fast/deep | ✅ 已实现 | DSH `run_fast` / `run_deep` + 6 维 adjudication |
| P2（32 模块内） | ✅ 已实现 | 频控/并发/TTL/结果截断 + DSH JSON 解析收敛 |
| 交叉质询阶段（v2.0-rc3） | ✅ 已实现 | `core/cross_exam.py` + 双向 Q&A；`debate.cross_examination` / CLI `--cross-exam` / MCP `cross_examination` |
| 业务 Profile 层 | ✅ 已实现 | `core/profiles/`：`marketing`（默认）/ `technical`（技术红队）/ `signal`（交易信号识别） |
| review 模式 adjudication | ✅ 已实现 | `review_runner` 默认产出 6 维评分；`adjudication=false` 可关闭 |
| C-Drive v1→MCP 迁移 | ✅ 已实现（灰度） | `DEBATE_MCP_ENABLED=true` 启用；`DEBATE_MCP_GRAY_PERCENT` 灰度；连续失败自动回退本地 |
| `l1.trading.mcp` | ✅ 已实现 | 10 工具（9 只读 + `forward_signal`）；L2 `l2_trading_analysis` 角色已注册 |
| TokenBudget（SPEC 5.6） | ⏳ 未实现 | 配置项保留，无预算追踪/降级逻辑 |

> 结论：**32 模块 P0/P1/P2、三项跨模块集成与 Profile 分层均已落地**；仅 TokenBudget 仍为设计稿遗留。C-Drive MCP 迁移默认关闭，生产启用前需按灰度比例观察。

### 业务 Profile

| profile | 用途 | 角色设定 | 输出 |
|---|---|---|---|
| `marketing`（默认） | 社群营销辩论 | 营销辩手 + 中立裁判 | 金句/标签/精华/短文案 + 传播力评分 |
| `technical` | 技术方案/架构红队 | 技术评审员 + 技术裁判 | 证据引用 + 可行性/风险/证据缺口/建议 |
| `signal` | C-Drive 交易信号识别 | 多头/空头信号评审员 + 信号裁判 | `verdict.signal`：方向/置信度/风险标记/证据/反证 |

入口：`debate.profile`（配置）/ `--profile`（CLI）/ `profile`（MCP `start_debate`）/ `profile`（`run_review_sync`）。C-Drive 经 MCP 固定传 `profile=signal`；49/架构评审传 `profile=technical`。

> 真实 LLM 实跑（2026-11-08）：`DebateMCPClient → agent.debate.mcp(mode=fast, profile=signal)` 返回 `status=completed`、2 turns、`signal.direction/confidence/risk_flags`；C-Drive 映射得到 bull=0.74 / bear=0.60、signal=long/0.65、5 条 risk_flags，MCP 错误计数 0。

## 快速开始

```bash
cd 32-对抗性辩论Bot

# 1) LLM 连通性自检
python cli.py --doctor

# 2) 结构化对抗评审（推荐给其他 Agent）
python cli.py "命题：双链架构应进入 R0" \
  --rounds 2 \
  --background-file path/to/background.md \
  --json \
  --output result.json

# 3) 传统营销辩论（含营销素材/质量评分）
python cli.py "BTC 是数字黄金" --rounds 2 --output result.json

# 4) 开启双向交叉质询 + review adjudication
python cli.py "命题" --rounds 2 --json --cross-exam
```

`--provider` / `--model` 可覆盖配置：`auto | anthropic | openai_compat | langchain`。

## 环境变量

| 变量 | 用途 |
|---|---|
| `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` | Anthropic（含 Claude Code 代理） |
| `DASHSCOPE_API_KEY` | DashScope OpenAI 兼容接口（qwen） |
| `OPENAI_API_KEY` | OpenAI 兼容接口 |
| `DEBATE_PROVIDER` / `DEBATE_MODEL` | 覆盖 provider/model |
| `DEBATE_MAX_ROUNDS` | MCP 壳最大轮次（默认 3） |

未显式配置时按 `anthropic → openai_compat` 自动探测；依赖缺失会给出明确错误，不会静默失败。

## Python API（其他 Agent 直接复用）

```python
from core.review_runner import run_review_sync

result = run_review_sync(
    "命题",
    background="背景材料",
    rounds=2,
    judge=True,
)
data = result.to_dict()
# data = {schema_version, debate_id, status, mode, topic, rounds,
#         transcript, verdict, adjudication, research, meta}
# status 固定为 completed/error；降级信息见 meta.degraded / meta.degraded_turns
```

也可注入自定义 LLM 客户端（测试/复用）：

```python
result = run_review_sync("命题", debater_llm=my_llm, judge_llm=my_llm)
```

## MCP 壳（47 注册表：`agent.debate.mcp`）

已注册到 `47-MCP管理系统/registry/mcp_capabilities.yaml`，profile：`debate-local`。

| 工具 | 说明 |
|---|---|
| `start_debate` | 启动异步评审，立即返回 `debate_id`；`mode=review\|fast\|deep`，`profile=auto\|marketing\|technical\|signal`，`research=true` 启用调研预检，`cross_examination=true` 启用交叉质询，`adjudication=false` 关闭 6 维评分 |
| `get_debate_result` | 按 `debate_id` 轮询 `queued/running/completed/error`；已完成 job 的完整结果在 `data.result` |
| `debate_health` | 配置/LLM 连通性自检（`deep=true` 触发 LLM ping），并暴露 M10 频控/TTL 参数 |

`mode` 后端映射：`review` → 32 `review_runner`；`fast` → DSH `run_fast`（1 轮并行）；`deep` → DSH `run_deep`（2 轮 + Judge + 6 维 adjudication）。fast/deep 的 P1 实现已完成。

stdio 手测：

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"debate_health","arguments":{"deep":false}}}' \
  | python mcp_shells/debate_adversarial/server.py
```

## 调研预检（Research Prepass，P0 + L1 signal 已实现）

辩论前自动检索 L0 MCP 只读能力，把“文档/记忆/代码”整理成带引用的 ResearchBrief：

```bash
python cli.py "命题" --rounds 2 --json --research \
  --research-sources unified_search,recall,code \
  --research-max-items 8
```

输出 `research.citations[]`（`source/ref/quote`）、`research.source_stats[]`（ok/degraded/reason）、`research.degraded`；源失败 fail-open，全部失败退回 background。代码检索优先 `rg`，无 `rg` 时用 `git grep` 兜底（6s/5000 文件预算），带 `.env/密钥/凭证` 排除与脱敏。

调试/调优环境变量：

| 变量 | 默认 | 作用 |
|---|---|---|
| `RESEARCH_DEBUG=1` | off | 输出 `research.debug`（cwd/repo_root/git/keywords/code_hits_probe） |
| `RESEARCH_CODE_BUDGET_SEC` | 6 | 无 rg 时 Python 扫描预算 |
| `RESEARCH_CODE_MAX_FILES` | 5000 | 无 rg 时最大扫描文件数 |
| `DEBATE_JOB_TIMEOUT_SEC` | 180 | MCP job 总超时 |

| 来源 | 工具 | 状态 |
|---|---|---|
| 认知记忆 | `recall` | ✅ P0 |
| 统一检索 | `unified_search`（41 文档 + Chroma RAG + recall） | ✅ P0 |
| 代码 | `code_search`（rg → git grep → Python 预算扫描） | ✅ P0 |
| L1 交易状态 | `l1.trading.mcp`：`get_signal_state` / `get_bus_state` / `get_cycle_state` | ✅ signal profile（默认纳入） |
| 语义 | `query_entity` / `semantic_lookup` | ⏳ 未接入 |
| 数据 | `data_fetch` / `data_store_read` | ⏳ 未接入 |
| 评测 | `eval_analyze` / `eval_report` | ⏳ 未接入 |

`profile=signal` 的默认来源为 `unified_search` / `recall` / `code` / `l1_signal` / `l1_bus` / `l1_cycle`；C-Drive 的 `_mcp_debate` 显式传 `research=True` 并带上 L1 三个来源。`l1_signal` 依赖 `23-四层闭环自进化交易架构/runtime/signals/23_signal_state.json`（缺失时回退 11 `event_driven_state.json`）；两者都不存在时该源标为 `source_unavailable`，`l1_bus`/`l1_cycle` 仍正常产出 citation。

原则：只读白名单、citation 必填、`<untrusted_source>` 防注入、源失败 fail-open、字符/来源/超时预算。
完整契约见 [Debate MCP × C-Drive × L2 集成 SPEC](../1-ARCHITECTURE/dream-harness-bridge/docs/SPEC-DEBATE-MCP-L2-INTEGRATION-v0.1.md)。

## C-Drive / L2 复用

- DSH `debate_engine.py` 的 `run_fast` / `run_deep` 已通过 MCP `mode=fast/deep` 暴露；32 Bot `review` 模式走 `review_runner`；
- C-Drive 反思推理按 HC-2 四档触发（>0.75 跳过 / 0.65-0.75 recall / 0.50-0.65 辩论 / <0.50 全链路）；结果进入 `_reflect_after_debate`。**C-Drive 已支持经 `agent.debate.mcp` 的 `profile=signal` 辩论（`DEBATE_MCP_ENABLED=true` + `DEBATE_MCP_GRAY_PERCENT` 灰度），默认仍走本地 v1，连续失败自动回退**；
- L2 Worker 已在 47 `worker_roles.l2_analysis` 注册 `agent.debate.mcp`，`worker_roles.l2_trading_analysis` 注册 `l1.trading.mcp` 只读工具，不触发信号/执行/训练；
- MCP `start_debate` 已支持 `mode=review|fast|deep` + `research` + `cross_examination` + `adjudication`；`trace_id`/`client`/`context_refs`/`budget` 尚未暴露为工具参数。

## 已修复的调用问题

1. **LangChain 强依赖**：`core/llm_compat.py` 新增 Anthropic / OpenAI 兼容适配，`langchain` 仅作可选后端。
2. **JSON 解析脆弱**：`core/robust_json.py` 支持代码围栏、前后散文、嵌套对象；旧 `{[^{}]*}` 截断问题已修。
3. **输出截断**：辩手 `max_tokens=2000`、裁判 `1600`；裁判 prompt 压缩为“最后一轮 + 前 2 条论据”，避免网关截断。
4. **重试/超时**：LLM 调用带超时与指数退避重试。
5. **CLI 可用性**：新增 `--doctor`、`--json/--review`、`--background-file`、`--provider/--model`。
6. **Agent/MCP 接入**：`run_review_sync` 统一入口 + `agent.debate.mcp` 异步 job 壳；`mode=review|fast|deep` 与 `research` 均可用（P1 已完成）。
7. **Windows 编码**：CLI/MCP 的 stdin/stdout/stderr 统一 UTF-8；修复中文 topic 被 GBK 解码成 `双决` 导致检索全空。

## 测试

```bash
python -m pytest 32-对抗性辩论Bot/tests -q
python -m pytest mcp_shells/debate_adversarial/tests -q
```

> 说明：`pytest-asyncio` 是测试依赖；未安装时先 `pip install pytest-asyncio`。当前基线：32 域 268 passed + debate MCP 壳 16 passed（2026-11-08）。