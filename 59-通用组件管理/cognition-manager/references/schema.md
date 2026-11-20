# 数据表与状态机

状态全部位于工作区 `.cm/`，默认不保存文档正文。SQLite 以 WAL 模式运行。

## 表结构（MVP）

| 表 | 字段 | 说明 |
|---|---|---|
| `docs` | `id, path, title, doc_type, module, tags, sha256, size, mtime, indexed_at, status` | 文本类入索引；二进制仅登记元数据 |
| `skills` | `id, name, path, version, triggers_json, depends_on_json, provides_json, sha256, indexed_at, status` | `path` 为 SKILL.md 路径 |
| `edges` | `src, dst, kind, created_at` | `kind` 固定枚举 |
| `executions` | `id, intent_signature, executed_at, source` | D1 唯一计数来源 |
| `runs` | `id, intent_signature, route, confidence, outcome, created_at` | 仅诊断，不参与 D1 |
| `intent_confirms` | `intent_signature, confirmed_at, expires_at` | 默认 90 天 |
| `sessions` | `id, content_ref, created_at, expires_at, triaged_at` | 会话 TTL |
| `pending` | `id, kind, payload_ref, created_at, review_count, state` | 待定积压 |
| `apply_runs` | `run_id, idempotency_key, created_at, mode, files_json, manifest_ref, rolled_back_at` | 写入幂等与回滚索引（schema v2） |
| `meta` | `key, value` | schema 版本等 |
| `docs_fts` | FTS5 虚表（`path, title`） | 不可用时自动降级 |

## edges 方向

| kind | src → dst |
|---|---|
| `references` | 引用方 → 被引用的文档 / 技能 |
| `implements` | 技能 → 它实现的规范 |
| `documented_by` | 技能 / 记忆 → 描述它的文档 |
| `derived_from` | 派生内容 → 来源 |
| `supersedes` | 新内容 → 被取代的旧内容 |

## 状态机

| 对象 | 状态 |
|---|---|
| doc | `active` → `stale` → `orphan` → `archived` |
| skill | `draft` → `active` → `deprecated` → `archived` |
| memory（Pro） | `observation` → `inferred` → `verified` → `superseded` → `trace_only` |
| pending | `open` → `reviewed` → `accepted` / `dropped` |
| session | `open` → `triaged` / `expired` |
| apply run | `prepared` → `applied` → `rolled_back` |

## 隐私约束

- `traces/` 只记录路径、哈希、路由结果与理由，默认不记录正文
- 如需记录摘要，上限 200 字，可在 `config.yaml` 关闭（`traces_summary: false`）
- `signature_salt` 每工作区独立生成，降低短文本字典反推风险
