# intent_signature 规范

> **状态**: 已实现（M2 `cm route` / `cm mark-done`），契约 v0.5
> **对应 SPEC**: §5.3 / `executions` 表
> **实现**: `scripts/core/signature.py`（`SIGNATURE_VERSION = "1"`）

## 1. 目的

把同一意图的不同说法归一到同一指纹，用于 D1「近 90 天同指纹执行次数」计数。指纹只回答「是不是同一件事」，不回答「这件事该不该做」。

## 2. 归一化步骤

1. **清洗**：去首尾空白、全角转半角、统一小写英文、去除标点与不可见字符
2. **中文分词**：按**字 bigram** 切分（不依赖词典），单字保留
3. **英文分词**：按空白与连字符切分，小写化，去停用词
4. **动词归一**：按 §4 映射表替换为规范动词（如「搞一下」「弄个」→ `make`）
5. **去重排序**：token 去重后按字典序排序，用单个空格拼接
6. **加盐哈希**：`sha256(salt + ":" + normalized)`，取前 16 位十六进制

`salt` 来自工作区 `.cm/config.yaml` 的 `signature_salt`，每工作区独立生成，禁止跨工作区复用。

## 3. 停用词

中文：`的 了 着 过 一下 一个 这个 那个 请 帮我 麻烦 看看 如何 怎么 什么 需要 进行`

英文：`a an the to of for and or with on in at is are be do please help me`

停用词表随模式配置下发，允许按工作区追加；**不允许**在运行期用模型动态生成停用词，否则指纹不可复现。

## 4. 动词归一映射（50 条）

| 说法 | 规范动词 |
|---|---|
| 创建 / 新建 / 建一个 / 搞个 / 弄个 | `create` |
| 添加 / 新增 / 加一个 / 补一个 | `add` |
| 删除 / 删掉 / 移除 / 去掉 | `remove` |
| 清理 / 清空 / 收拾 | `clean` |
| 修改 / 更新 / 调整 / 改一下 | `update` |
| 重命名 / 改名 | `rename` |
| 移动 / 挪到 | `move` |
| 复制 / 拷贝 / 备份一份 | `copy` |
| 合并 / 并到 / 合起来 | `merge` |
| 拆分 / 拆开 / 分开 | `split` |
| 查询 / 查找 / 搜索 / 找一下 | `search` |
| 查看 / 看一下 / 瞧瞧 | `view` |
| 统计 / 算一下 / 计数 | `count` |
| 生成 / 产出 / 出一份 | `generate` |
| 编写 / 写一个 / 撰写 | `write` |
| 执行 / 运行 / 跑一下 | `run` |
| 启动 / 起服务 | `start` |
| 停止 / 关掉 / 停服务 | `stop` |
| 重启 / 重跑 | `restart` |
| 部署 / 上线 | `deploy` |
| 发布 / 发版 / 推上去 | `release` |
| 安装 / 装一下 | `install` |
| 卸载 / 删装 | `uninstall` |
| 升级 / 升一下 | `upgrade` |
| 回滚 / 退回去 | `rollback` |
| 推送 / push 上去 | `push` |
| 拉取 / pull 下来 | `pull` |
| 提交 / commit | `commit` |
| 检查 / 巡检 / 自查 | `check` |
| 校验 / 验证 / 核对 | `verify` |
| 修复 / 修正 / 改好 | `fix` |
| 记录 / 登记 / 记一下 | `record` |
| 总结 / 汇总 / 归纳 | `summarize` |
| 归档 / 存档 / 收起来 | `archive` |
| 导入 / 读进来 | `import` |
| 导出 / 导出去 | `export` |
| 同步 / 对齐 | `sync` |
| 配置 / 设置 / 配一下 | `configure` |
| 初始化 / 初始化一下 | `init` |
| 扫描 / 扫一遍 | `scan` |
| 体检 / 检查健康度 | `doctor` |
| 分拣 / 分类 / 归一下类 | `triage` |
| 评审 / 审阅 / 过一遍 | `review` |
| 分析 / 拆解 / 研究 | `analyze` |
| 对比 / 比较 / 比一下 | `compare` |
| 测试 / 跑测试 | `test` |
| 打包 / 打成一个包 | `package` |
| 分享 / 发出去 | `share` |
| 提醒 / 通知 / 告知 | `notify` |
| 安排 / 排期 | `schedule` |

## 5. 示例

输入 A：「帮我创建一份发布检查清单」

```
清洗   → 帮我创建一份发布检查清单
分词   → 帮 帮我 我创 创建 建一 一份 份发 发布 布检 检查 查清 清单
停用词 → 帮我 / 一份 移除
动词   → 创建 → create
结果   → create 发布 布检 查清 清单 建一 我创 份发 查清(去重)
```

输入 B：「新建发布检查清单，麻烦弄一下」

```
动词 → 新建 → create；弄一下 → create（去重）
结果 → create 发布 布检 查清 清单 建一 份发
```

A、B 归一后 token 集合一致，得到同一指纹。

## 6. 反例与约束

| 约束 | 说明 |
|---|---|
| 不做语义相似度 | 指纹只做字面归一，同义改写由 V4 同义表述召回验证，不在这里用模型兜底 |
| 不跨工作区比较 | `salt` 不同，指纹不可比 |
| 不用于路由判定 | 指纹只进 `executions` 计数；D1 仍需真实执行次数 |
| 用户确认不计入 | `intent_confirms` 只豁免确认，不增加执行计数 |
| 版本变更需重算 | 修改分词或映射表必须提升 `signature_version`，旧指纹标记 `legacy`，不静默混用 |

## 7. 存储

- `executions(intent_signature, executed_at, source)`：唯一计数来源
- `runs(intent_signature, route, confidence, outcome, created_at)`：仅诊断，不参与 D1
- `intent_confirms(intent_signature, confirmed_at, expires_at)`：默认 90 天
