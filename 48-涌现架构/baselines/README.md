# 48 涌现基线（P0）

> 状态：🟡 P0 基线生成器 + 本地快照（2026-11-09）
>
> ⚠️ **2026-11-09 复审确认**：本目录的生成脚本与 artifacts **当前未入库**（目录内仅含本 README）。SPEC §12 P0-2/P0-3 状态已同步修正为「未入库」；脚本与产物入库并附运行证据前，P0-2/P0-3 不得标 closed，sha256 暂不可核验。
> 归属：48-涌现架构；只读消费 33-REA / `.cognitive/sessions`，不改既有域代码。
> 关联：[SPEC-EMERGENCE-3D-v0.1](../docs/tech/SPEC-EMERGENCE-3D-v0.1.md) §12 P0-2/P0-3

## 目录

| 路径 | 用途 |
|---|---|
| `build_d2_architecture_graph.py` | 生成 D2 统一 `ArchitectureGraph` 基线 |
| `build_d3_intent_events.py` | 从 `.cognitive/sessions` 生成 D3 意图事件代理基线 |
| `artifacts/d2_architecture_graph/` | 图基线产物（`architecture_graph.json` + summary/manifest） |
| `artifacts/d3_intent_events/` | 意图事件产物（`intent_events.jsonl` + summary/split/manifest） |

## 当前产物状态（2026-11-09）

| 基线 | 状态 | 关键数字 |
|---|---|---|
| D2 架构图 | ✅ 已生成（待人工复核） | 574 nodes（420 Python / 124 docs / 30 other；146 external）、3522 edges（2578 call / 704 import / 240 doc_ref）、parse_errors=0、闭合校验 0 悬挂边、1,031,413 bytes、sha256 `89aeab3b828a...` |
| D3 意图事件 | 🟡 生成器就绪，产物待执行 | 合成会话冒烟通过（2/2）；本地 Bash 安全分类器拦截 `.cognitive/sessions` 读取；已知 365 non-empty sessions，75/25 → 92 test <200，session 级 D3-A 会 `insufficient_data`；需授权环境运行 `python 48-涌现架构/baselines/build_d3_intent_events.py` |

> D3 产物含 session id/task_type/文件路径，属内部 runtime 数据；生成后请先确认访问策略，不要直接提交原始 JSONL。P0-2 在直接意图标签补采前不能标 `closed`。

## 运行

```bash
python 48-涌现架构/baselines/build_d2_architecture_graph.py
python 48-涌现架构/baselines/build_d3_intent_events.py
```

可选参数：

```bash
# 只跑指定域
python 48-涌现架构/baselines/build_d2_architecture_graph.py \
  --scope 48-涌现架构 --scope 33-REA逆向解析工程

# 调整时序切分
python 48-涌现架构/baselines/build_d3_intent_events.py --train-ratio 0.8
```

## D2 图基线包含什么

- `python_file` / `markdown_doc` 节点；
- `import` 边：轻量 AST 解析器，文件级、跨 scope；
- `call` 边：33-REA `CallChainTracer` 的函数名级调用关系；
- `doc_ref` 边：Markdown 链接解析；
- `patterns`：33-REA `ArchitecturePatternDetector` 的架构模式 Evidence。

不包含：TS/JS import、运行时数据流、ADR 设计决策（v0.2 再补）。

## D3 事件基线包含什么

每个 session 一行：

- `session_id`、`ts`/`end_ts`、`status`、`action_count`；
- `intent_proxy` = `session.task_type`（**不是用户意图标签**）；
- `recalled_memory_ids`、`recalled_skills`、`files_touched`；
- `task_type_transitions`、`correction`；
- `actions`：只保留 `action_type`/`files`/`commit_hash`，**不复制用户原文**。

同时输出：

- `intent_summary.json`：session 数、task_type 分布、日期范围、局限；
- `split_manifest.json`：按时间 75/25 的 train/test session 清单；
- `manifest.json`：git commit、产物 sha256、字节数。

## 重要局限

1. **D3 没有直接意图标签**：本地只有 `task_type` 代理；D3-A 首轮只能做 task_type 预测，不能申报「意图涌现」。P0-2 仍需补采前端/DreamOS 结构化 intent 日志。
2. **D2 图不是完整架构图**：Python-only、函数名级调用边、无运行时数据流；D2-A 的 ground truth 需要人工复核后再用于 holdout。
3. **会话数据是 gitignored runtime data**：`.cognitive/sessions` 不在版本库；产物中的 session id/文件路径属于内部数据，提交前请确认访问策略。
4. **P0-1 OOD 未关闭**：本基线不改变 OOD 强制点缺失的事实；D2-A/D3-A 仍只能做探索性实验，不能申报候选。详见 [REVIEW-2026-11-09-main-spec-ood.md](../docs/tech/reviews/REVIEW-2026-11-09-main-spec-ood.md)。

## 更新 P0 状态

生成后把 `manifest.json` 的 `generated_at`/`git_commit`/`sha256` 填到
[SPEC-EMERGENCE-3D-v0.1.md](../docs/tech/SPEC-EMERGENCE-3D-v0.1.md) §12 的证据列，
P0-2/P0-3 最多标 `baseline-generated`，不能直接标 `closed`（直接意图标签/图人工复核仍是前置）。