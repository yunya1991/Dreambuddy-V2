---
name: cognitive-cli
description: 广义认知系统命令行调用技能（MCP 不可用时的等效方案）。触发词：认知系统、召回经验、记录经验、cognitive recall、cognitive record、认知记忆库、广义认知、经验检索、记忆召回。
version: 1.0.0
category: memory
---

# 认知系统命令行调用（cognitive-cli）

## 适用场景

- 新对话中需要召回历史经验（排查问题、修复故障、架构决策前先查历史经验）
- 任务完成后需要记录新经验到认知系统
- 无法接入认知 MCP 服务（cognitive_mcp_server.py）时的等效调用方案
- 验证记忆有效性并触发贝叶斯更新

## 背景

广义认知系统（4-MEMORY）的记忆持久化在服务器数据库中（cognitive_memory.db + evidence_ledger.db），与对话会话解耦。MCP 服务（cognitive-memory-server，5 工具：recall/record/verify/stats/health）是首选接入方式；当宿主环境无法注册 MCP 服务时，使用本技能的命令行等效方案。

## 命令用法

命令行工具位置：`/usr/local/bin/cognitive`（需用 luke 用户的 venv Python 执行）

### 1. 召回经验（任务前调用）

```bash
sudo -u luke /home/luke/venv-trading/bin/python /usr/local/bin/cognitive recall "关键词" --top-k 5
```

- 返回 JSON：`{ok, count, results: [{id, content, quality, tags}]}`
- 关键词建议用领域词（如『OKX 限频』『降级排查』『FSRS 遗忘』）

### 2. 记录经验（任务后调用）

```bash
sudo -u luke /home/luke/venv-trading/bin/python /usr/local/bin/cognitive record "经验内容" --tags "标签1,标签2" --quality A --confidence 0.9
```

- quality 可选 S/A/B/C/D；重要修复经验建议 A 级
- 返回 `{ok, memory_id}`，memory_id 可用于后续 verify

### 3. 验证记忆（经验被复用后调用）

```bash
sudo -u luke /home/luke/venv-trading/bin/python /usr/local/bin/cognitive verify <memory_id> true
```

- 触发贝叶斯更新，记忆质量随复用持续进化

### 4. 健康检查

```bash
sudo -u luke /home/luke/venv-trading/bin/python /usr/local/bin/cognitive health
```

## 标准工作流

1. **任务开始**：先 recall 相关关键词，检查是否有历史经验可复用
2. **任务执行**：引用召回的经验内容辅助分析
3. **任务完成**：record 新经验（含根因、方案、验证结果、方法论启示）
4. **经验复用后**：verify 对应 memory_id，强化有效记忆

## 注意事项

- 工具以 luke 用户执行（数据库文件属主是 luke），必须用 venv-trading 的 Python
- 所有命令 FAIL-OPEN：失败返回 `{ok: false, error: ...}`，不阻塞调用方
- 记忆库规模约 3.8 万条且持续增长，recall 用具体领域关键词效果更好
- 自动记录通道（git post-commit 钩子 + 认知守护进程）已独立运转，本工具用于手动补充和召回
- 若 MCP 服务可用，优先用 MCP（协议一致，能力相同）

## 相关文件

- 命令行工具源码：/usr/local/bin/cognitive（即 cognitive_cli.py）
- 认知循环入口：/home/luke/dreambuddy/4-MEMORY/9-工具与接口/cognitive_loop_entry.py
- MCP 服务：/home/luke/dreambuddy/4-MEMORY/9-工具与接口/cognitive_mcp_server.py
- 记忆库：/home/luke/dreambuddy/4-MEMORY/data/cognitive_memory.db
- 证据账本：/home/luke/dreambuddy/4-MEMORY/data/evidence_ledger.db
- 协作契约：/home/luke/dreambuddy/35-广义认知系统协作模块/COLLABORATION-CONTRACT.md
