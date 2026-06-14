# OKR 管理 — 目标和关键结果

> 飞书OKR系统管理规范，涵盖结构定义、进展更新、API命令。
> 源：lark-okr, feishu-orchestrator

## OKR 结构

```
周期(周期ID) → 目标(O) → 关键结果(KR) → 量化指标
                          ↘ 对齐关系
```

| 层级 | 说明 | 飞书API资源 |
|:---|---|:---:|
| 周期 | 季度/月度时间范围 | okr.cycles |
| 目标(O) | 定性目标描述，可含量化指标 | okr.cycle.objectives |
| 关键结果(KR) | 可衡量的关键结果，属于某目标 | okr.objective.key_results |
| 进展记录 | 对O或KR的进展说明 | okr.progress_records |

## 进展更新方法

### 使用 Shortcut（推荐）

```bash
# 查看周期列表
lark-cli okr +cycle-list --user-id <open_id>

# 查看周期下的目标和KR
lark-cli okr +cycle-detail --cycle-id <id>

# 创建进展记录
lark-cli okr +progress-create \
  --target-id <objective_id> \
  --target-type 2 \
  --content '{"blocks":[{"type":"paragraph","paragraph":{"elements":[{"type":"textRun","textRun":{"text":"✅ 完成工作摘要"}}]}}]}'
```

### 使用原生API（绕过open_id跨App限制）

```bash
# 获取OKR
lark-cli api GET "/open-apis/okr/v1/users/{open_id}/okrs" \
  --params '{"offset":"0","limit":"10","period_ids":"{period_id}"}'

# 推送进展
lark-cli api POST /open-apis/okr/v1/progress_records \
  --data '{
    "source_title": "系统自动同步 — 摘要",
    "source_url": "https://feishu.cn",
    "target_id": "{objective_id}",
    "target_type": 2,
    "content": {"blocks": [...]}
  }'
```

**参数说明**：
- `target_type`: 2=Objective, 3=Key Result
- `content.blocks`: 富文本结构（paragraph内嵌textRun）

## 四组件同步铁律

每次本地变更后必须同步所有组件：

```
本地变更落地
   ↓
① 飞书 Base — 更新记录
② OKR 进度 — 推送进展记录
③ 审批 — 创建/更新审批实例
④ 知识库 — 更新飞书文档/Wiki节点
```

缺一不可。不更新飞书OKR = 工作没有被记录。

## 典型OKR字段

| 字段 | 类型 | 示例 |
|:---|---|:---|
| O 名称 | 文本 | 提高系统索引覆盖率至90% |
| KR 指标 | 百分比 | 覆盖率从72%提升到90% |
| 进展状态 | 单选 | 正常/延迟/停滞 |
| 负责人 | 用户 | owner open_id |
| 周期 | 关联周期 | 2026年Q2 |

_最后更新：2026-06-13 | 来源：lark-okr, feishu-orchestrator_
