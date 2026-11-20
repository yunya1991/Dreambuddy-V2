# 黄金集目录（M2b 交付）

本目录用于放置：

- `dev.jsonl`：Dev 版黄金集，≥100 条，四类（skill / doc / memory / session）各 ≥20
- `office.jsonl`：Office 版黄金集，≥80 条
- 断链 / 孤儿 / 漂移 / 冲突固定 fixture（可放 `fixtures/`）
- `labeling-guide.md`：双人标注与分歧裁定规则

当前仅提供格式与标注规范；真实标注需人工完成，**不得用模型生成结果冒充标注**。

## 标注格式（JSONL）

```json
{"id": "g001", "content": "把发布检查做成清单", "label": "skill", "labeler": "A", "predicted": "skill", "confidence": 0.91}
{"id": "g001", "label": "skill", "labeler": "B"}
```

- `id`：样本唯一标识；同一 `id` 出现两次且 `labeler` 不同即为双人标注
- `label`：人工标注，取值 `skill / doc / memory / session`
- `predicted` / `confidence`：模型预测与置信度，可写在任意一行（同 id 后写覆盖先写）
- 也可用独立预测文件：`--pred pred.jsonl`（JSONL 或 `{"id": {...}}` JSON）

## 评估

```bash
python3 scripts/eval_golden.py --golden references/golden/dev.jsonl --json
```

指标：每类 P/R/F1、宏平均、准确率、高置信分组（`confidence ≥ 0.80`）精确率、ECE（10 桶）、Cohen's κ。

阈值：高置信分组精确率 ≥ 0.90 **或** ECE ≤ 0.15 视为达标。

退出码：0 达标 / 1 未达标 / 2 数据不足（需人工标注）/ 3 用法错误。

## 目录约束

平台包结构只允许 `SKILL.md / references / scripts / templates`，因此黄金集放在本目录，不新建 `assets/`。
