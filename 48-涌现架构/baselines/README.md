# 48 涌现基线（P0）

> 状态：✅ 生成器与产物已入库（2026-11-09，feat/48-baselines-p0@local）
>
> 2026-11-09 复审曾确认「脚本与产物未入库」；本次实施已将两生成器入库（测试 7 项），并真实运行产出 artifacts（D3 raw JSONL 按隐私约束不入库）。P0-2/P0-3 状态升级为 **baseline-generated**（≠ closed：直接意图标签 / 图人工复核仍是前置）。
> 归属：48-涌现架构；只读消费 33-REA / `.cognitive/sessions`，不改既有域代码。
> 关联：[SPEC-EMERGENCE-3D-v0.1](../docs/tech/SPEC-EMERGENCE-3D-v0.1.md) §12 P0-2/P0-3

## 目录

| 路径 | 用途 |
|---|---|
| `build_d2_architecture_graph.py` | 生成 D2 统一 `ArchitectureGraph` 基线 |
| `build_d3_intent_events.py` | 从 `.cognitive/sessions` 生成 D3 意图事件代理基线 |
| `artifacts/d2_architecture_graph/` | 图基线产物（`architecture_graph.json` + summary/manifest） |
| `artifacts/d3_intent_events/` | 意图事件产物（`intent_events.jsonl` + summary/split/manifest） |

## 当前产物状态（2026-11-09 真实运行）

| 基线 | 状态 | 关键数字 |
|---|---|---|
| D2 架构图 | ✅ 已入库（待人工复核） | 7859 nodes（4110 python_file / 3303 markdown_doc / 446 external）、53959 edges（24640 import / 27563 call / 1756 doc_ref）、闭合校验 0 悬挂边、parse_errors=97（FileNotFoundError 为主，FAIL-OPEN 计数）、9,494,459 bytes、sha256 `3b95a04a3f9e...`（结构哈希，剔除 generated_at，可复现核验） |
| D3 意图事件 | ✅ 已执行（raw JSONL 不入库） | 1089 sessions（0 解析错误），时序 75/25 → train=816 / test=273（≥200 达标）；task_type 12 类（configuration 392 / strategy-execution 259 / architecture-design 131 / python-development 128 / 其余 179）；日期范围 2026-08-09 → 2026-11-09；sha256 `44bd72e4bd91...` |

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

- `python_file` / `markdown_doc` / `external` 节点；
- `import` 边：轻量 AST 解析器，文件级；未解析的外部依赖吸收为 `external:<top>` 节点（保证 0 悬挂边）；
- `call` 边：AST 函数名级调用关系（重名取路径排序首个，确定性）；
- `doc_ref` 边：Markdown 相对链接解析（doc→doc）。

不包含：TS/JS import、运行时数据流、ADR 设计决策、33-REA 架构模式 Evidence（v0.2 再补）。

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