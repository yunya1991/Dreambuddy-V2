# 记忆准入四问（默认拒绝）

> 原则：答不出「不可再推导」就不写。记忆只存指针，不复制正文。
> 实现：`scripts/core/admission.py`；`cm route --facts` 传入判定，未提供一律 `pending`。

| # | 问题 | 允许的判定结果 | 不通过的处理 |
|---|---|---|---|
| A1 | 模型 + 现有文档 + 一次检索能否推导？ | `derivable_from:[paths]` + 推导结果，或 `not_derivable` | `not_derivable` → 拒写 |
| A2 | 是否已有 SSoT？ | `ssot_path` 或 `none` | 有 SSoT → 只写指针，不复制内容 |
| A3 | 是否有可验证落点（文件 / 测试 / 指标）？ | `evidence_ref` 或 `none` | `none` → 降级 `observation`，置信度上限 0.5 |
| A4 | 六个月后是否仍有价值？ | `yes` / `no` / `unknown` | `no` → 不写；`unknown` → TTL ≤ 30 天 |

## A1 硬约束

- 只接受 `derivable_from` 或 `not_derivable`，不接受自由文本
- `derivable_from` 必须给出真实存在、可被索引校验的路径，否则视为无效判定
- 判定不确定一律记 `unknown`，进入 `pending`，不写入检索
- 禁止以「我认为可以推导」作为唯一证据

## 反例

| 反例 | 为什么拒绝 |
|---|---|
| 「项目使用 Python 3.12」 | 从 `pyproject.toml` / 运行环境可推导，A1 不通过 |
| 「用户偏好简洁回复」 | 无文件落点，A3 不通过；如确需保存，降级为 `observation` |
| 「上次讨论过方案 B」 | 属于会话，不是稳定事实，应走 session |
| 「这个坑很关键」 | 无证据引用，A3 不通过；补齐复现路径后才可写入 |

## 状态与清理

- `pending` 超过 3 次复核仍为 `unknown` → 丢弃，只保留计数痕迹
- 记忆被取代 → `superseded`，保留证据链，不物理擦除
- 遗忘 = 移出检索 + 保留痕迹，不等于删除文件
