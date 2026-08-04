# Hermes Agent 参考研究报告

> 研究目标：为「思维链压缩 + A/B 评测 + 学习循环」的认知系统设计提供工程借鉴。
> 研究对象：Hermes Agent 仓库（位于 `/tmp/superpowers-research/hermes-agent`）。
> 研究方法：用 Read 工具读取实际代码，引用均带 file 链接与行号范围。

---

## 1. 仓库概览

### 1.1 定位与核心特性

Hermes Agent 由 Nous Research 开源（MIT License），是一个**自我改进型 AI Agent**。其官方 README 用一段话精准概括了它的差异化能力：

> "The self-improving AI agent built by Nous Research. It's the only agent with a built-in learning loop — it creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations, and builds a deepening model of who you are across sessions."

四张核心能力牌：

| 能力 | 描述 |
|------|------|
| **闭环学习循环** | Agent-curated memory with periodic nudges；任务结束后自主创建技能；技能在使用中自我改进；FTS5 session search + LLM 摘要实现跨会话召回 |
| **定时自动化** | 内建 cron 调度器，自然语言描述任务即可无人值守运行 |
| **委派与并行** | 派生隔离子 agent 并行处理；通过 RPC 调用工具，把多步管线压成零上下文成本的一轮 |
| **研究就绪** | 批量轨迹生成 + 轨迹压缩，用于训练下一代 tool-calling 模型 |

仓库同时提供 ACP adapter（IDE 集成）、Gateway（多平台消息路由）、TUI/Web/Desktop 多端 UI，以及 LSP 集成。

### 1.2 与我们系统的对应关系

| 我们的组件 | Hermes Agent 中的对应物 | 价值 |
|------------|------------------------|------|
| 思维链压缩 | trajectory_compressor.py + agent/conversation_compression.py | 直接可借鉴的算法骨架 |
| A/B 评测 | batch_runner.py + mini_swe_runner.py + 工具/推理统计 | 批量评测 + 影子运行 + 工具成功率聚合 |
| 学习循环 | agent/curator.py + agent/background_review.py + tools/skill_usage.py | 自我评估到技能沉淀到策展式记忆的完整闭环 |
| 跨会话召回 | hermes_state_search.py（FTS5 + CJK trigram + bigram） | 多路 FTS 索引与降级策略 |

### 1.3 仓库布局速览

仓库根目录关键 Python 入口：

- cli.py、run_agent.py、hermes_bootstrap.py —— CLI 主入口与 AIAgent 运行器
- trajectory_compressor.py —— 训练数据压缩（本报告第 2 节）
- batch_runner.py —— 批量轨迹生成（本报告第 3 节）
- mini_swe_runner.py —— 影子运行 + 单 agent 评测（本报告第 4 节）
- hermes_state.py + hermes_state_search.py —— SQLite + FTS5 会话状态库
- toolsets.py + toolset_distributions.py —— 工具集分布采样

agent 目录是核心运行时（200+ 文件），本报告重点研读：curator.py、background_review.py、memory_manager.py、memory_provider.py、learn_prompt.py、turn_finalizer.py、conversation_compression.py。

skills 是技能包目录（14 个顶层分类），机制详见第 5 节。

## 2. trajectory_compressor.py 深度分析

文件路径：file:///tmp/superpowers-research/hermes-agent/trajectory_compressor.py，共 1598 行。这是仓库里最贴近我们「思维链压缩」组件的工程实现，可直接借鉴算法骨架。

### 2.1 数据结构

#### 2.1.1 输入：trajectory（OpenAI ShareGPT 兼容格式）

输入是一条 JSONL，每行是一个 entry，必须包含 conversations 字段（见 #L1021-L1025）：

```python
if "conversations" not in entry:
    metrics = TrajectoryMetrics()
    return entry, metrics
trajectory = entry["conversations"]
```

trajectory 是一个 turn 列表，每个 turn 是 Dict[str, str]，关键字段：

- from：角色，取值为 system / human / gpt / tool
- value：消息内容字符串。tool call 与 tool response 各用一对 XML 标签包裹（tool_call 对与 tool_response 对，其内是 JSON）

这是 ShareGPT 的 from/value 格式，区别于 OpenAI 的 role/content 格式（mini_swe_runner.py 负责两者转换，见第 4 节）。

#### 2.1.2 CompressionConfig（配置数据类）

定义在 #L82-L118，用 @dataclass 声明，关键字段分四组：

| 分组 | 字段 | 默认值 | 作用 |
|------|------|--------|------|
| Tokenizer | tokenizer_name | moonshotai/Kimi-K2-Thinking | 用真实模型 tokenizer 计数，避免估算偏差 |
| 压缩目标 | target_max_tokens / summary_target_tokens | 15250 / 750 | 压缩上限与摘要目标长度 |
| 受保护 turn | protect_first_{system,human,gpt,tool} / protect_last_n_turns | True / 4 | 头尾不动，只压中段 |
| 并发 | num_workers / max_concurrent_requests / per_trajectory_timeout | 4 / 50 / 300s | asyncio 信号量限流 + 单条超时 |

配置可通过 CompressionConfig.from_yaml() 从 YAML 加载（#L126），实现配置与代码分离。

#### 2.1.3 TrajectoryMetrics 与 AggregateMetrics

- TrajectoryMetrics（#L183-L224）：单条轨迹的压缩指标，含 original_tokens / compressed_tokens / tokens_saved / compression_ratio、压缩区间的 [start_idx, end_idx]、was_compressed / still_over_limit / skipped_under_target 状态标记，以及 summarization_api_calls / summarization_errors 调用统计。to_dict() 输出结构化 JSON，便于落盘分析。
- AggregateMetrics（#L228-L302）：跨所有轨迹的聚合，通过 add_trajectory_metrics() 累加，最终计算 compression_rate、平均压缩比、平均节省 token 等分布统计。

### 2.2 核心算法：保护头尾、压缩中段

压缩策略在模块 docstring（#L8-L15）中概括为六步，核心实现在 compress_trajectory()（#L743-L889）。

#### 2.2.1 _find_protected_indices：定位受保护区间

#L477-L523。记录首次出现的 system/human/gpt/tool 位置，保护首部各类首个 turn + 尾部 N 个 turn。可压缩区 = 头部保护之后到尾部保护之前。以中点 n//2 划分头尾保护集，保证系统提示、首条用户指令、首次模型动作、首次工具响应、以及最后几轮收尾动作全部原样保留——这些是训练信号最关键的部分。

#### 2.2.2 _is_boundary_clean 与 _snap_boundary：边界对齐

#L525-L562。这是最值得借鉴的工程细节。在 from/value 格式中，tool turn（携带 tool_response 标签）总是紧跟在发起 tool_call 的 gpt turn 之后。如果压缩边界刚好落在 tool turn 上，就会把「工具调用」与「工具响应」切成两半，破坏训练数据的结构完整性。

_is_boundary_clean 判断边界是否干净：位于轨迹末尾或落在非 tool turn 上即为干净。_snap_boundary 优先向前 snap（把孤立的 tool turn 折入持有其 gpt 的区间），向前找不到干净边界则向后退。compress_trajectory 在确定头尾边界后各调用一次 _snap_boundary（#L786 与 #L826），确保摘要替换区间不会把 tool call/response 对拆开。

#### 2.2.3 compress_trajectory 主流程

#L743-L889，十步：

1. count_turn_tokens 统计每 turn token 数
2. 若 total_tokens 小于等于 target：skip（skipped_under_target=True）
3. _find_protected_indices 找可压缩区 [start, end)
4. _snap_boundary（头）对齐头边界
5. 累加 turn token 直到 accumulated_tokens 大于等于 tokens_to_save + summary_target_tokens
6. _snap_boundary（尾）对齐尾边界
7. 安全检查：若压缩区不大于摘要长度则放弃（避免越压越大，#L837-L844）
8. _extract_turn_content_for_summary 抽取待压缩内容（长 value 截断为首 1500 + 尾 500）
9. _generate_summary 用 LLM 生成摘要（带 [CONTEXT SUMMARY]: 前缀）
10. 重组：head + 单条 human 摘要 turn + tail（system turn 追加 notice 文本）

关键的安全检查在 #L837-L844：如果可安全压缩的区间 token 数小于等于摘要目标 token，压缩反而会让轨迹变大，此时放弃压缩但仍记录 still_over_limit。

#### 2.2.4 摘要生成与重试

_generate_summary / _generate_summary_async（#L605-L741）调用 OpenRouter（默认 google/gemini-3-flash-preview），摘要 prompt 要求包含：执行的动作、关键结果、重要决策、相关文件名/数值。重试机制用 agent.retry_utils.jittered_backoff（#L738），最多 max_retries=3 次；全部失败后降级为一句兜底摘要（#L740-L741），保证压缩流程不中断。摘要内容会被 _ensure_summary_prefix（#L598-L603）统一加上 [CONTEXT SUMMARY]: 前缀，便于下游识别。

### 2.3 并发与容错

_process_directory_async（#L1076-L1270）是批量处理的并发骨架：

- 信号量限流：asyncio.Semaphore(max_concurrent_requests=50)（#L1121）控制摘要 API 并发。
- 单条超时：asyncio.wait_for(process_entry_async, timeout=per_trajectory_timeout)（#L1148），超时则记 trajectories_failed 并跳过该条（#L1174-L1188），不影响其它轨迹。
- 线程安全聚合：progress_lock = asyncio.Lock()（#L1124）保护 compressed_count / api_calls / in_flight 等共享计数器。
- 结果按文件分组：results = {f: {} for f in jsonl_files}（#L1131），保证输出与输入文件一一对应，不串行。

### 2.4 借鉴要点（思维链压缩）

1. 头尾保护 + 中段压缩是 token 预算约束下保训练信号的经典策略，直接可复用。
2. 边界对齐（boundary snapping）防止拆散 tool call/response 对——我们的认知系统若有工具调用链，必须实现等价机制。
3. 安全检查「压缩区小于等于摘要长度则放弃」避免了负优化。
4. 降级兜底摘要保证管线永不被摘要 API 故障卡死。
5. asyncio 信号量 + 单条超时 + 锁保护计数器是批量 LLM 调用的成熟并发模式。

## 3. batch_runner.py 深度分析

文件路径：file:///tmp/superpowers-research/hermes-agent/batch_runner.py，共 1321 行。这是「批量评测 + A/B 对比」的工程骨架：并行执行多 prompt、断点续跑、工具成功率聚合。

### 3.1 工具与推理统计提取

#### 3.1.1 _extract_tool_stats

#L125-L205。遍历消息历史，通过 tool_call_id 关联「assistant 发起的调用」与「tool 返回的响应」，统计每个工具的 count / success / failure。成败判定逻辑（#L165-L195）值得借鉴：

- 解析 tool response 的 JSON，检查 error 字段是否非 null；
- 对 terminal 工具特别处理内层 content 字段；
- 检查 success: false 模式；
- 非 JSON 内容：空内容视为失败，以 error: 开头视为失败；
- 非零退出码不算失败（#L180 注释）——因为模型可以自我纠正，这是对 agent 行为的准确建模。

#### 3.1.2 _extract_reasoning_stats

#L208-L241。统计 assistant turn 中带推理的比例，检查两种推理标记：REASONING_SCRATCHPAD 标签（文本内）和原生 reasoning 字段。返回 total_assistant_turns / turns_with_reasoning / turns_without_reasoning / has_any_reasoning。这为「思维链覆盖率」评测提供了量化指标。

#### 3.1.3 schema 归一化

_normalize_tool_stats（#L71-L98）和 _normalize_tool_error_counts（#L101-L120）确保所有工具（含未使用的）都在输出中占位并补零。注释（#L62-L68）说明这是为了 HuggingFace datasets 加载 JSONL 时不报 schema mismatch——评测产物要对齐数据集标准格式，这是工业级评测管线的细节。

### 3.2 单 prompt 处理与隔离

_process_single_prompt（#L244-L398）：

- 每 prompt 容器镜像覆盖（#L266-L314）：数据集行可带 image 字段，注册到该任务的沙箱；Docker 模式下先 docker image inspect 再按需 docker pull，拉取失败直接返回错误，不浪费 token 跑 agent 循环。
- 工具集分布采样（#L318）：sample_toolsets_from_distribution 从分布中为该 prompt 抽样工具集——这是 A/B 评测的关键：不同 prompt 用不同工具集组合，对比成功率。
- 日志前缀 [B{batch_num}:P{prompt_index}]（#L323）便于多进程日志归因。

### 3.3 批 worker 与质量过滤

_process_batch_worker（#L400-L524）是单 batch 的串行处理器：

- 过滤已完成 prompt（#L419-L422）：按 completed_prompts_set 跳过已完成的，支持断点续跑。
- 丢弃无推理样本（#L454-L460）：若整条轨迹所有 turn 都没有推理（has_any_reasoning=False），直接丢弃并记 discarded_no_reasoning——这是质量门禁，保证训练数据含思维链。
- 轨迹条目结构（#L473-L483）：prompt_index / conversations / metadata / completed / partial / api_calls / toolsets_used / tool_stats / tool_error_counts，其中 partial=True 表示因非法工具调用而提前停止。
- 聚合工具统计（#L490-L504）：跨 prompt 累加工具的 count/success/failure。
- 完成标记策略（#L506-L512）：只有成功且保存了轨迹的才标记完成；失败的可在 resume 时重试。

### 3.4 BatchRunner：并行与断点续跑

BatchRunner.run()（#L810-L1147）是批量评测的编排核心。

#### 3.4.1 内容匹配式 resume

_scan_completed_prompts_by_content（#L732-L774）是最稳健的续跑机制：扫描所有 batch_*.jsonl，提取每条成功轨迹的首条 human 消息文本作为完成指纹。按 prompt 文本匹配而非索引，即使数据集顺序变化或索引错位也能正确恢复。失败的条目（failed=True）被跳过以允许重试。

_filter_dataset_by_completed（#L776-L808）兼容两种 prompt 来源：顶层 prompt 字段或 conversations 内的 user/human 角色。

#### 3.4.2 多进程并行

#L918-L985：

- multiprocessing.Pool + imap_unordered 实现批次级并行，结果乱序返回。
- 增量 checkpoint（#L963-L980）：每个 batch 完成立即写 checkpoint，崩溃后损失最多一个 batch。
- _save_checkpoint 用 utils.atomic_json_write（#L725-L730）保证原子写入，配合 Lock() 做线程安全。
- Azure Entra ID bearer provider 不可 pickle（#L875-L883），跨进程时丢弃 callable，由 worker 从 config.yaml 重建凭证——这是凭据隔离的工程细节。

#### 3.4.3 结果归并与脏数据过滤

#L1026-L1090：把所有 batch_*.jsonl（含历史 resume 的旧文件）合并为 trajectories.jsonl，同时用 ALL_POSSIBLE_TOOLS（#L65，自动派生自 model_tools.TOOL_TO_TOOLSET_MAP）过滤模型生成非法工具名的损坏条目。最终计算每个工具的 success_rate / failure_rate。

### 3.5 借鉴要点（A/B 评测）

1. 工具成功率 + 推理覆盖率双指标，分别评测「执行能力」与「思维质量」。
2. 非零退出码不算失败——尊重 agent 自我纠正能力，避免误判。
3. 内容匹配式 resume 比索引式更稳健，适合长时间批量评测。
4. 增量 checkpoint + 原子写入保证崩溃可恢复。
5. schema 归一化让评测产物直接可被 HuggingFace 加载，对接训练管线。
6. 工具集分布采样实现 A/B 对照（不同工具组合对比）。

## 4. mini_swe_runner.py 深度分析

文件路径：file:///tmp/superpowers-research/hermes-agent/mini_swe_runner.py，共 732 行。这是「影子运行（shadow running）」的轻量实现：隔离环境执行任务并产出 Hermes 格式轨迹。

### 4.1 环境工厂与隔离

create_environment（#L117-L155）支持三种环境类型：

| env_type | 隔离强度 | 适用场景 |
|----------|---------|---------|
| local | 最弱（本机） | 快速验证、可信任务 |
| docker | 中（容器） | 标准评测、可复现 |
| modal | 强（云端） | 大规模并行、免本地资源 |

MiniSWERunner._create_env / _cleanup_env（#L237-L255）保证每任务建环境、用完即清。_execute_command（#L257-L283）统一返回 {output, exit_code, error}，异常被捕获转为 error 字段而非抛出——影子运行不能因单命令失败而崩溃。

### 4.2 终端工具与完成信号

仅暴露一个 terminal 工具（TERMINAL_TOOL_DEFINITION，#L68-L110），描述中约定任务完成时输出 echo "MINI_SWE_AGENT_FINAL_OUTPUT"。这是基于约定信号的完成检测，无需额外判定逻辑。

run_task（#L408-L571）主循环：循环调用 LLM，若有 tool_calls 则执行每个命令，检测输出是否含完成信号字符串（#L524-L527）；若无 tool_calls 则视为最终回答，标记完成并跳出。max_iterations 兜底防止无限循环。

### 4.3 轨迹格式转换

_convert_to_hermes_format（#L298-L406）把 OpenAI 的 role/content 消息转为 Hermes 的 from/value 格式，这是与 trajectory_compressor.py / batch_runner.py 对接的关键：

- system 转为 from=system, value=...
- user 转为 from=human, value=...
- assistant 带工具调用：把 reasoning 包进 think 推理标签，content 拼接，每个 tool call 转成 tool_call XML 块（其内是 JSON），整体作为 gpt turn（#L336-L362）。
- tool 响应：合并后续连续 tool 消息为 tool_response XML 块（其内是 JSON），作为单个 tool turn（#L364-L391）。
- assistant 无工具调用：reasoning + content 作为 gpt turn（#L393-L399）。

推理标记用 think 标签包裹（#L341、#L397），与 batch_runner._extract_reasoning_stats 检查的 REASONING_SCRATCHPAD 是两套标记——这里转换的是模型原生 reasoning 字段。

### 4.4 批量模式

run_batch（#L573-L623）串行处理多个 prompt，每条立即写文件 + flush（#L604-L605），保证部分崩溃不丢已完成结果。失败任务写入错误条目而非中断。

### 4.5 借鉴要点（影子运行）

1. 三档隔离环境按需选择，平衡速度与安全。
2. 约定式完成信号简单可靠，适合单 agent 评测。
3. 格式转换层让影子运行产物直接进入压缩/训练管线。
4. 命令执行异常转 error 字段保证影子运行永不崩溃。
5. 与 batch_runner 的差异：mini_swe_runner 是单进程串行轻量版，batch_runner 是多进程并行重器——两者互补，前者适合开发期快速验证，后者适合大规模评测。

---

## 5. skills/ 目录与技能机制

### 5.1 技能文件格式

skills/ 下按类目组织（14 个顶层分类），每个技能是一个目录，核心是 SKILL.md。

以 skills/autonomous-ai-agents/hermes-agent/SKILL.md 为例，frontmatter 字段：

```yaml
---
name: hermes-agent
description: "Use, configure, theme, extend, and orchestrate Hermes Agent."
version: 3.1.0
author: Hermes Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, setup, configuration, ...]
    related_skills: [claude-code, codex, opencode]
---
```

技能可携带三类支撑文件（在 background_review._SKILL_REVIEW_PROMPT 中明确，#L219-L237）：

| 目录 | 用途 |
|------|------|
| references/ | 会话级细节（错误转录、复现配方、provider 怪癖）+ 浓缩知识库 |
| templates/ | 可复制修改的脚手架（配置模板、已知良好示例） |
| scripts/ | 可直接运行的静态脚本（验证脚本、探针） |

「Hub skill」模式（#L29）值得借鉴：SKILL.md 只放身份、快速开始、硬不变量；细节全部下沉到 reference 文件，按需加载。这控制了常驻上下文体积。

### 5.2 技能创建：/learn 命令

agent/learn_prompt.py 的 build_learn_prompt（#L99-L150）构建 /learn 指令：

- 用户请求是开放的，可混合「待收集来源」与「作者要求」；
- 要求 agent 用现有工具收集所有来源（read_file / search_files / web_extract）；
- 作者一个 SKILL.md 并通过 skill_manage 工具保存；
- 若需脚本则放 scripts/ 下并相对引用。

这是「用户主导、agent 执行」的技能创建路径，与 background_review 的「agent 自主创建」互补。

### 5.3 技能使用遥测与生命周期

tools/skill_usage.py（1145 行）管理技能的状态与遥测。关键概念：

- 技能来源分类（#L427-L448）：is_agent_created（agent 创建）、is_hub_installed（hub 安装）、is_bundled（内置）。
- 策展资格（is_curation_eligible，#L455）：只有 agent 创建且非 pinned 的技能才可被 curator 自动处理。
- 状态机（STATE_ACTIVE / STATE_STALE / STATE_ARCHIVED）：基于使用活跃度自动流转。
- 领养机制（adopt_skill，#L596）：把非托管技能转为 curator 托管。
- 使用记录文件带文件锁（_usage_file_lock，#L90）保证并发安全。

## 6. 学习循环：background_review + curator

这是 Hermes 最核心的差异化能力，也是我们「学习循环」组件最直接的借鉴对象。它是一个两层闭环。

### 6.1 即时层：background_review（每轮后 fork agent）

agent/background_review.py 的 spawn_background_review_thread（#L974）在每轮对话后触发守护线程，fork 一个隔离子 agent 回放本轮快照并自问「是否需要保存技能/记忆」。

#### 6.1.1 运行时路由：同模型 vs 异模型

_resolve_review_runtime（#L46-L110）的核心策略：

- 默认（同模型）：继承父 agent 的 live runtime（provider/model/api_key/base_url），routed=False，复用父的热 prompt cache，成本极低（cache 读）。
- 异模型：当 auxiliary.background_review.{provider,model} 指定不同模型时，走 resolve_runtime_provider，routed=True。此时 cache 必然冷，故用 _digest_history（#L122-L163）回放压缩摘要（保留最近 24 turn 原文 + 旧轮摘要成一条 user 消息），减少冷写 token。

借鉴要点：review 的模型选择直接影响成本——同模型走热 cache 全量回放，异模型走摘要回放，这是精细的成本优化。

#### 6.1.2 fork 隔离：保证主对话零副作用

_run_review_in_thread（#L635-L820）的隔离措施层层设防：

1. 工具白名单：fork 只暴露记忆与技能管理工具，其余运行时拒绝。
2. 危险命令自动拒绝（#L655-L664）：_bg_review_auto_deny 回调把任何危险命令审批导向 deny，避免死锁父 TUI（#15216）。
3. 线程级静默（thread_scoped_silence，#L677）：只静默本线程 stdout/stderr，不污染其它线程（如 gateway 事件循环，#55769）。
4. 记忆隔离（skip_memory=True，#L744）：fork 不触碰外部记忆插件，避免把 review harness prompt 泄漏进用户真实记忆命名空间；内置 MEMORY.md/USER.md 仍从父 re-bind，保证记忆写入落到正确磁盘。
5. 持久化隔离（_persist_disabled=True，#L772）：fork 共享父 session_id（为 cache 一致性），但硬阻断所有 DB 写入路径，否则会把 review 的 harness turn 注入用户真实会话，导致下轮 agent「变成 curator」拒绝真实任务。
6. 会话不终结（_end_session_on_close=False，#L814）：fork close 时不终结父的会话行。
7. cache 一致性（#L783-L807）：同模型路径下，fork 继承父的 _cached_system_prompt、session_start、session_id，并匹配工具集与 reasoning config，使出站请求 byte 级一致，命中同一 prefix cache（实测约 26% 端到端成本下降，#L792）。

这是「安全的自我修改」的工程范本：fork 既要复用父的运行时降低成本，又要绝对不污染父的状态。

#### 6.1.3 review prompt：主动而非被动

_SKILL_REVIEW_PROMPT（#L181-L265）强调「ACTIVE——大多数会话至少产生一次技能更新」。信号识别清单：用户纠正风格/语气/格式、纠正工作流、出现非平凡技巧、已加载技能有误。更新优先级：①更新已加载技能 → ②更新现有 umbrella → ③加支撑文件 → ④新建类级 umbrella。明确禁止编辑 bundled/hub/pinned/user-owned 技能。

### 6.2 周期层：curator（定期策展）

agent/curator.py（2018 行）是技能库的长期维护者，按 curator.interval_hours（默认周级）周期运行。

#### 6.2.1 纯状态机：apply_automatic_transitions

#L305-L383，无 LLM，基于使用活跃度自动流转：

- stale_cutoff / archive_cutoff 两个时间阈值；
- pinned 技能、cron 引用技能永不动；
- 首次见到的 built-in 锚定到现在（seed），避免立刻被归档；
- 从未使用的技能（use_count==0）有宽限期：不到 stale 窗口不动；
- active 到 stale 到 archived 单向流转，重新使用则 reactivated。

这是确定性、零成本的技能生命周期管理。

#### 6.2.2 LLM 策展：run_curator_review

#L1496-L1575：

1. 先跑纯状态机（apply_automatic_transitions）。
2. 若 consolidate=True 且有 agent 创建的技能，fork 一个 AIAgent 跑 LLM 策展 prompt，目标是 umbrella-building 合并（把数百个窄技能合并成类级技能库，而非被动审计）。
3. 运行前做预变异快照（curator_backup.snapshot_skills，#L1552-L1558），失败只 debug 日志不阻塞。
4. 支持 dry-run（#L1533-L1544）：只产出 REPORT.md，不实际变异，供人工审核。
5. 状态先落盘（#L1572），避免 LLM 阶段崩溃导致立即重触发。

CURATOR_REVIEW_PROMPT（#L417）明确目标：类级指令与经验知识库，而非一会话一技能的窄列表——这是技能库演化的方向指引。

#### 6.2.3 触发：maybe_run_curator

#L2000 基于 should_run_now（#L233，检查间隔与最小空闲小时数）决定是否触发，is_paused 可全局暂停。

### 6.3 nudge 机制

background_review 通过 _memory_nudge_interval / _skill_nudge_interval（fork 中设为 0，#L759-L760）控制 review 触发节奏。主 agent 在 turn_finalizer 收尾时触发 _should_review_memory 标志（见 agent/turn_finalizer.py 的 finalize_turn 参数），把「是否该 review」的决策与轮次收尾解耦。

### 6.4 借鉴要点（学习循环）

1. 两层闭环：即时层（每轮 fork，快速沉淀单点经验）+ 周期层（周级 curator，合并去重、维护库结构）。即时层保证「学得快」，周期层保证「库不腐化」。
2. fork 隔离的七层防护是安全自我修改的范本，尤其「持久化隔离」防止 review 污染主会话。
3. 同模型走热 cache、异模型走摘要的成本路由，值得我们在 review 子系统复用。
4. 纯状态机 + LLM 策展分离：能用确定规则的不用 LLM，降低成本与不确定性。
5. dry-run + 预变异快照让策展可审计、可回滚。
6. umbrella-building 而非 duplicate-finding 的策展哲学，指引技能库向「类级知识库」演化。

---

## 7. 记忆系统

### 7.1 MemoryProvider 抽象基类

agent/memory_provider.py（#L43-L190）定义可插拔记忆后端的契约：

核心生命周期（必须实现）：
- is_available()：检查配置与依赖，不做网络调用。
- initialize(session_id, **kwargs)：建资源、连后端，kwargs 含 hermes_home / platform / agent_context / agent_identity / parent_session_id 等。
- get_tool_schemas()：返回 OpenAI function calling 格式的工具 schema。
- handle_tool_call(tool_name, args)：分发工具调用，返回 JSON 字符串。

核心钩子（默认实现或可选）：
- system_prompt_block()：静态系统提示文本。
- prefetch(query) / queue_prefetch(query)：轮前召回（应快，后台线程）。
- sync_turn(user, assistant)：轮后异步持久化。

可选钩子（override opt-in）：
- on_turn_start / on_session_end / on_session_switch / on_pre_compress / on_memory_write / on_delegation / backup_paths。

on_session_switch（#L176-L210）尤其重要：/resume、/branch、/reset、/new、上下文压缩都会重赋 session_id，provider 需在此更新或重置 per-session 缓存。reset=True 表示全新对话需 flush 累积缓冲；rewound=True 表示轨迹回退但 session_id 不变。

### 7.2 MemoryManager：编排内置 + 单外部 provider

agent/memory_manager.py 的 MemoryManager（#L364-L470）：

- 一外部 provider 限制（#L404-L425）：builtin 始终首位，最多一个外部 provider，防止工具 schema 膨胀与后端冲突。
- 工具名保留（#L437-L454）：核心工具名（如 clarify / delegate_task）不可被 provider 工具遮蔽，冲突时拒绝注册。
- 工具路由表 _tool_to_provider：工具名到 provider 映射，分发 handle_tool_call。
- 后台 sync 执行器（#L384-L390）：单 worker 串行化 provider 写入（turn N 必须先于 turn N+1 落盘），惰性创建避免 builtin-only 路径起多余线程。
- StreamingContextScrubber（#L182）：流式输出时洗脱敏感标签，防止部分标签泄露到用户可见流。
- on_pre_compress（#L974）：压缩前让 provider 抽取要保留的信息——与 trajectory_compressor 的压缩协同。

### 7.3 FTS5 多索引跨会话搜索

hermes_state_search.py（1907 行）实现 SQLite FTS5 全文检索，核心是多 tokenizer 索引 + 路由降级。

#### 7.3.1 三套索引

| 索引表 | tokenizer | 适用 | 行为 |
|--------|-----------|------|------|
| messages_fts | unicode61 | 拉丁文、默认 | 按词边界切分 |
| messages_fts_trigram | trigram | 子串匹配 | 重叠 3 字节序列，匹配子串无视词边界 |
| messages_fts_cjk | CJK bigram | 中文 | 为大于等于 2 字 CJK 串存 bigram，Latin 游程切分 |

trigram 索引排除 tool role 消息（#L109、#L206：role 不等于 tool），减少噪声。

#### 7.3.2 查询路由

_trigram_eligible_tokens（#L909-L923）：只有当所有非操作符 token 大于等于 3 字符时才走 trigram 路径——因为 trigram 对短 token 产生空索引，FTS5 隐式 AND 会导致整查询返回空。

_run_trigram_search（#L925-L983）：每个非操作符 token 加引号转义特殊字符，保留 AND/OR/NOT 布尔算符；用 snippet() 函数生成高亮片段。

#### 7.3.3 延迟重建与崩溃安全

fts_rebuild_step（#L162-L228）：

- 分块回填：_FTS_REBUILD_CHUNK_ROWS 一批，按 id 区间 [progress, upper] 插入。
- 原子认领（#L180-L188）：在写事务内重读 fts_rebuild_progress，两个 worker 不会读到同值——并发安全。
- 进度与数据同事务（#L209-L215）：进度更新与行插入在同一事务，crash-atomic，要么都落要么都不落。
- trigram 不可用非致命（#L453），降级到 base 索引。

fts_cjk_rebuild_step（#L248）同理维护 CJK 索引。这种可恢复的增量索引构建适合大规模历史数据迁移。

### 7.4 借鉴要点（记忆系统）

1. 抽象 provider + 单外部限制平衡扩展性与简洁性，避免多后端冲突。
2. 生命周期钩子完备（尤其 on_session_switch 处理会话切换、on_pre_compress 与压缩协同），是我们记忆接口设计的参考。
3. 三套 FTS 索引 + 查询路由解决中英文混合检索，trigram 兜底子串匹配——我们做跨会话召回可借鉴。
4. 增量分块 + 原子认领的索引重建保证大规模数据迁移不阻塞、可恢复。
5. 后台单 worker 串行化写入保证 turn 顺序，惰性创建避免无外部 provider 时的线程浪费。

---

## 8. 借鉴总结

### 8.1 直接借鉴

| 我们的组件 | 借鉴 Hermes 的 | 具体做法 |
|-----------|---------------|---------|
| 思维链压缩 | trajectory_compressor | 头尾保护 + 中段 LLM 摘要 + 边界对齐 + 安全检查 + 降级兜底 + asyncio 信号量并发 |
| A/B 评测 | batch_runner | 工具成功率 + 推理覆盖率双指标、内容匹配 resume、增量 checkpoint、schema 归一化、工具集分布采样 |
| 影子运行 | mini_swe_runner | 三档隔离环境、约定式完成信号、格式转换层、异常转字段不崩溃 |
| 学习循环（即时） | background_review | 每轮 fork 隔离子 agent、同模型走热 cache/异模型走摘要、七层隔离防护 |
| 学习循环（周期） | curator | 纯状态机 + LLM 策展分离、umbrella-building、dry-run + 预变异快照 |
| 跨会话召回 | hermes_state_search | 多 tokenizer FTS 索引 + 查询路由 + 增量原子重建 |
| 记忆接口 | memory_provider | 完备生命周期钩子、单外部 provider 限制、后台串行写入 |

### 8.2 不借鉴的部分

1. ShareGPT from/value 格式：我们已有统一记忆接口规范（7 标准接口 + 2 便利方法），不必引入第二套消息格式；压缩层应直接操作我们的统一数据结构。
2. OpenRouter 强绑定：trajectory_compressor 默认依赖 OpenRouter 与特定 tokenizer（moonshotai/Kimi-K2-Thinking），我们应抽象成 provider 无关的压缩器。
3. 每轮 fork 的成本：即时层每轮都 fork 一个完整 agent 回放，对高频会话成本不低；我们可考虑「触发式 review」（仅当检测到学习信号时 fork），而非无差别每轮触发。
4. 技能库的 agent 自主写入：Hermes 让 fork agent 直接写技能库，依赖工具白名单与 pinned 保护；我们的记忆系统已规定被动更新机制（心跳上报、蒸馏候选上报、按需拉取），更强调自治与独立性，不宜让子 agent 直接改写主知识库。
5. 多 tokenizer FTS 的复杂度：trigram 索引对短查询失效需路由降级，维护成本高；若我们检索场景以中文为主，可优先 CJK bigram + unicode61 双索引，trigram 作为可选增强。
6. dry-run 的 LLM 成本：curator dry-run 仍跑完整 LLM 策展（仅禁止变异），成本未降；我们可考虑基于规则的预筛选 + 抽样 LLM 审计。

### 8.3 关键工程启示

- 能用确定规则的不用 LLM：状态机流转、完成信号检测、schema 归一化都用代码，LLM 只用于真正需要理解的摘要/策展。
- 隔离即安全：fork 的七层防护证明「自我修改」可安全实现，核心是「共享运行时降成本 + 阻断持久化防污染」。
- 可恢复优于防错：增量 checkpoint、原子写入、分块重建都假设崩溃会发生，重点是不丢已完成工作。
- 评测要对齐训练：schema 归一化、推理覆盖率门禁、工具成功率都服务于「产出可直接训练的数据」，评测与训练不应割裂。

