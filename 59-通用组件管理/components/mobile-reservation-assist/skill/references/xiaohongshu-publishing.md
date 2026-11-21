# 小红书图文发布参考 — mobile-reservation-assist

把「爆款侦察 → 手机笔记本 → 千问分析 → 多篇采集 → 汇总 → 千问出图文 → 发布」做成一条可复跑链路。
命令入口是 `mra xhs`，全部动作经本地网关下发到手机端 Auto.js Agent 执行。

## 1. 定位与边界

| 项 | 说明 |
|---|---|
| 赛道 | 泛金融 / 经济 / 时事 / AI Agent / 数据服务（窄赛道靠泛金融与时事扩圈） |
| 输入 | 小红书爆款样本 + 财经 App 首页文章（≥3 篇）+ 云端数据面板摘要 |
| 中间态 | 手机笔记本（小米笔记）分步记录，避免长链路中途遗忘 |
| 输出 | 小红书图文：标题（≤20 字）、正文（≤1000 字）、话题、封面图 |
| 发布 | 默认停在「发笔记」前；显式 `--publish` 才点发布 |
| 内容来源 | 本地采集 + 云端正版数据 + 千问改写，不搬运他人图文 |

**合规红线**（额外于 [compliance.md](compliance.md)）：

- 不荐股、不给买卖点、不承诺收益、不晒虚假收益截图；
- 不制造焦虑式标题（"再不跑就完了"一类）；
- 引用数据必须来自云端面板或原文，不臆造数字；
- 爆款只借鉴主题与形式，不照抄标题/句子；
- 互动只做点赞/收藏，单次 ≤5 篇，**不自动评论**（不刷量、不控评）；
- 发布可执行；支付类动作仍需用户明确指令（本链路不涉及支付）。

## 2. 数据流

```
xhs scout   ──► 小红书搜索「财经 / 经济 / 时事 / AI Agent / 数据服务」→ 读前 N 篇 → 可选点赞/收藏
xhs memo    ──► 笔记本记录爆款清单（标题/互动量/关键词）
xhs trends  ──► 千问：主题 / 形式 / 可扩展方向 / 风格提示（只借鉴形式）
xhs memo    ──► 笔记本记录「发文模式 + 扩展方向」
xhs collect ──► 华尔街见闻 + 新浪财经多篇采集（默认 3 篇）
                 └─ 每采完一篇立即 xhs memo add（防中断丢失）
xhs memo    ──► 笔记本记录汇总：风格方向 + 素材清单
xhs compose ──► 千问：风格方向 + 多篇素材 + 云端数据 → 图文
xhs memo    ──► 笔记本记录定稿
xhs cover   ──► 千问生图 → 点卡片左下下载图标 → /sdcard/DCIM/QuarkAI/
xhs post    ──► 首页「发布」→ 最新素材 → 填标题正文 → 停在发布前（--publish 才点）
```

中间产物落 `$MRA_STATE_DIR/notes/`（`MRA_STATE_DIR` 未设时为 `~/.mobile-reservation-assist/notes/`），
scout→trend→article→note 按 `kind_时间戳.json` 命名，可随时从任一步复跑。

## 3. 命令表

```bash
# 一键完整链路（默认 3 篇素材，停在发布前）
python3 scripts/mra.py xhs chain --count 3
# 直接发布（用户明确说"发出去"时）
python3 scripts/mra.py xhs chain --count 3 --publish

# 分步执行
python3 scripts/mra.py xhs scout --track "财经,经济,时事,AI Agent,数据服务" --limit 3 --json
python3 scripts/mra.py xhs memo add --text "..." --tag 爆款
python3 scripts/mra.py xhs memo list --limit 5
python3 scripts/mra.py xhs trends --scout .mra_state/notes/scout_xxx.json --json
python3 scripts/mra.py xhs collect --sources wallstreetcn,sina --count 3 --memo --json
python3 scripts/mra.py xhs data --json
python3 scripts/mra.py xhs compose --article a.json --article b.json --article c.json \
    --trend trend.json --data data.json --extra "更口语化" --json
python3 scripts/mra.py xhs cover --note note.json --style "财经杂志封面" --json
python3 scripts/mra.py xhs post --note note.json [--image /sdcard/DCIM/QuarkAI/xxx.jpg] [--publish] --json

# 快速链路（不侦察爆款，旧用法保持兼容）
python3 scripts/mra.py xhs run --source wallstreetcn --count 1
```

参数要点：

| 参数 | 含义 | 默认 |
|---|---|---|
| `--track` | 赛道关键词（逗号分隔，保留 "AI Agent" 空格） | 财经,经济,时事,AI Agent,数据服务 |
| `--scout-limit` | 爆款读取篇数（1-5） | 3 |
| `--no-interact` | 只浏览，不点赞/收藏 | 关 |
| `--sources` | 资讯源，逗号分隔 | wallstreetcn,sina |
| `--count` | 采集总篇数，按源轮转分配 | chain=3 / run=1 |
| `--publish` | 人工授权点发布 | 关 |

退出码沿用全局约定：`0` 成功 / `2` 参数错 / `3` 门禁拒绝（含停在发布前）/ `5` 网络或上游不可达。

## 4. 真机选择器与已知坑

设备：Xiaomi 2211133C / Android 16，Auto.js 6 无障碍模式；笔记 App 默认 `com.miui.notes`。

| 环节 | 做法 | 坑 |
|---|---|---|
| 爆款搜索 | 首页 `desc/text=搜索` → EditText 输入关键词 → 搜索 | 搜索入口可能匹配到「搜索历史」，优先 `desc=搜索` |
| 爆款卡片 | 内容区长度 8-80 的 TextView，按 y 排序 | 底部 tab 文案较短，用长度阈值过滤 |
| 打开笔记 | 点标题节点，失败再点卡片坐标 | 标题不一定可点，`clickNode` 会向上找可点父节点 |
| 读正文 | 只向上滑逐屏采集，按前 48 字去重 | **绝不"手指下拉回顶"**：会触发刷新/误触 |
| 互动 | 只点 `desc=赞` / `desc=收藏`，单次 ≤5 篇 | 不评论；识别不到按钮就跳过，不盲点 |
| 返回结果页 | `back()` 后确认能重新采到卡片，最多 3 次 | 详情页可能叠多层，返回不足会停在半路 |
| 笔记本新建 | `desc/text=新建` 或右下角浮钮 `(950,2180)` | 小米笔记首启有隐私弹窗，先点「同意」 |
| 笔记本校验 | 写入后 `back()`，列表页回显前 12 字才算成功 | 未回显判 `needs_human`，不假装成功 |
| 多篇采集 | 采完一篇 `back()` 回列表，按未读标题取下一篇 | 卡片标题带「头条/置顶」前缀，入稿前剥离 |
| 千问生图 | 只认竖版大图（宽高≥600，高≥宽×1.05） | 生成中有 99% 进度与装饰小图，连续两次就绪才动手 |
| 保存图片 | 点卡片左下角小图标直接下载 | 下载后确认 `/sdcard/DCIM/QuarkAI` 出现新文件 |
| 找最新素材 | `ls -t` 扫 QuarkAI → Camera → Pictures | App 无 `content query` 权限，不用 MediaStore |
| 小红书首页 | 必须有 `desc=发布` 的底部 tab | 盲坐标点「发布」会落到「我」页签（已复现） |
| 选图 | 发布弹层 →「从相册选择」→ 左上角第一张 | 相册权限弹窗先点「允许访问全部」 |
| 编辑页 | 两个 EditText（标题/正文）；只有一个时标题+正文合并首行 | 填完要 `back()` 收键盘，否则「发笔记」被遮住 |
| 发布校验 | 页面出现「发布成功」或「已发布」才算 done | 只点到按钮不算成功 |

## 5. 失败处置

| 现象 | 原因 | 处置 |
|---|---|---|
| 爆款侦察 `needs_human` | 搜索页改版/未登录/网络差 | 链路降级继续（无风格参考），人工确认后重跑 `xhs scout` |
| 笔记本 `needs_human` | 未进编辑页/未回显 | 不阻断出稿；可 `xhs memo list` 人工核对 |
| 单篇采集失败 | 首页无更多文章/网络差 | 其余篇继续；少于 3 篇时 WARN，不伪造素材 |
| `E_ENV：未找到 QWEN 配置` | 缺 `~/.local/share/dreambuddy/qwen.env` | 配好千问 Key 后重跑 |
| `WARN：千问爆款分析失败` | 模型超时/返回非 JSON | 跳过风格参考继续采集写稿 |
| 生图超时 | 千问排队或需登录 | 重跑 `xhs cover`，或 `--image` 指定现成图 |
| `未找到首页「发布」入口` | App 停在子页面或改版 | `ensureXhsHome` 已做 4 次回退；仍失败则人工回首页 |
| 已点发布但未捕获成功提示 | 网络慢/文案改版 | 回执 `needs_human`，人工到「我 → 笔记」确认 |

## 6. 验收清单

1. 侦察篇数 ≥1，素材篇数 ≥3，且标题与最近已发内容不同；
2. 笔记本有「爆款 / 方向 / 素材 / 汇总 / 定稿」记录（长链路任一中断可回看）；
3. 回执 `state=done`，`xhs_compose`、`xhs_publish` 步骤为 ok；
4. 素材路径存在（`/sdcard/DCIM/QuarkAI/*.jpg`），标题 ≤20 字、正文 ≤1000 字；
5. 发布后在小红书「我 → 笔记」能看到新笔记；
6. 正文不含荐股/收益承诺；数字能追溯到原文或云端面板；无爆款原文照抄。

## 7. 真机实测补充（2026-11-21）

- 千问分析额外产出：标题句式、内容风格（语气/结构/密度/钩子）、如何学习、今日推荐选题；链路取推荐第 1 条作为采集 focus。
- 财经 App 搜索入口实测：

| App | 入口 | 输入框 | 提交 |
|---|---|---|---|
| 华尔街见闻 | 首页左上第二个图标（约 195,190），无文字 | AutoCompleteTextView | 回车无效，点搜索页右侧图标（约 1015,300） |
| 新浪财经 | 首页右上「搜索」（约 755,182） | EditText | 回车可出结果；结果页需切「资讯」标签 |

- 新浪启动可能弹「新版本安装」，Agent 会点「取消」两次。
- 采集去重：跨源按标题前 40 字去重，重复记入 `duplicates`；空态卡片（请刷新/检查网络等）跳过。
- 搜索失败不阻断：步骤 `news_search=false`，降级读首页，并在 `degraded` 中标注。
- 笔记本：小米笔记编辑页有两个 EditText，写高度最大的正文框；退回列表未回显时，重开首条回读校验。

免责声明：本链路仅做内容采集、分析、改写与发布编排，不构成投资建议。
