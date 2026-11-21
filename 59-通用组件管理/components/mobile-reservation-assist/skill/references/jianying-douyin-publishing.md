# 剪映 → 抖音视频发布参考 — mobile-reservation-assist

把「小红书笔记文案 → 剪映 AI 文字成片 → 导出 1080P → 剪映「分享到抖音」→ 填标题描述 → 发布」
做成一条可复跑、可回放的链路。执行器为 uiautomator2 本地通道（adb，不依赖无障碍）。

## 1. 定位与边界

| 项 | 说明 |
|---|---|
| 输入 | 小红书笔记 JSON（`title` / `body` / `topics`），或任意文案 |
| 制作 | 剪映「图文成片」：文案 → 9:16 竖版视频 → 导出 1080P 到相册 |
| 发布 | 导出完成页「分享到抖音」→ 抖音编辑页「下一步」→ 发布页填标题/描述 →「发布」 |
| 驱动 | `phone_driver`（uiautomator2）+ `phone_flows`（剪映/抖音），**与 Auto.js 网关并存** |
| 红线 | 不买会员、不用付费素材；不搬运他人视频；内容须过 `content_guard` |

**内容风控**：发布前 `content_guard.scan_note` 必须返回 `block=false`，禁止个股代码、买卖动作、收益承诺。

## 2. 真机路径（1080x2400 已校准）

### 2.1 剪映（com.lemon.lv）

| # | 动作 ID | 页面 | 操作 | 关键文案 |
|---|---|---|---|---|
| 1 | `jy_open` | 冷启动剪映 | `app_restart` | — |
| 2 | `jy_entry` | 剪辑页 / 热门工具 | 点「图文成片」；找不到先按 back 回首页，必要时上滑 | 图文成片 / 开始创作 |
| 3 | `jy_input` | AI 文字成片 | 点输入框写入文案；若剪映恢复了上次任务且文案一致，直接复用 | 请输入创作想法 |
| 4 | `jy_apply` | 输入页 | 点右上「应用」 | 应用 |
| 5 | `jy_ratio` | 配置页 | 点「视频比例」展开 → 选「9:16」→ 点面板右上 ✓ | 视频比例 / 9:16 |
| 6 | `jy_generate` | 配置页 | 点「生成视频」；按钮不可见时上滑一次 | 生成视频 |
| 7 | `jy_wait_edit` | 生成队列 | 轮询等待编辑页出现「导出」，期间关弹窗 | 导出 |
| 8 | `jy_export` | 编辑页 | 点「导出」→ 选 1080P → 再点「导出」 | 1080P |
| 9 | `jy_wait_saved` | 导出完成页 | 等到「保存成功/已保存/分享到抖音」出现；**不能只看相册有新 mp4（旧文件会误判）** | 保存成功 / 分享到抖音 |
| 10 | `jy_share` | 导出完成页 | 点红色「分享到抖音」，允许跨应用唤醒 | 分享到抖音 |

### 2.2 抖音（com.ss.android.ugc.aweme）

| # | 动作 ID | 页面 | 操作 | 关键文案 |
|---|---|---|---|---|
| 11 | `douyin_compose` | 发布页 | 标题 ≤20 字；描述=正文+话题。先关输入法选择器，再逐个填 | 添加作品标题 / 添加作品描述 |
| 12 | `douyin_publish` | 发布页 | 收起键盘 → 点「发作品/发布/发布作品」→ 以「发布成功」或回到首页为成功 | 发布 / 发作品 |

## 3. 已知坑（真机踩过）

1. **Miui 输入法选择器**：u2 输入会切到 `AdbKeyboard`，MIUI 弹出选择器挡住「发布」。
   处理：输入后调用 `_dismiss_ime_picker()`；流程结束 `finally` 把默认输入法切回原输入法（默认讯飞）。
   另有常驻守护 `skill/scripts/ime_guard.py`：每 15s 检查，发现停在 AdbKeyboard 且无 `mra.py` 在跑就切回。
2. **剪映会恢复上次任务**：冷启动后可能直接停在配置页，入口检测要把「AI 文字成片」标题排除，
   并在入口点击后二次判断配置页，复用已填文案。
3. **比例面板会盖住「生成视频」**：必须先选 9:16 并点右上 ✓ 收起面板。
4. **相册旧视频导致误判导出完成**：`latest_media()` 只用于记录路径，不能当成功判据。
5. **分享到抖音后先进编辑页**：需再点一次「下一步」才到发布页。
6. **发布页有两个输入框**：只填描述会漏标题；标题限 20 字。
7. **发布成功的判定要严**：仅「发布成功/作品已发布/已发布」或回到带底部导航的首页才算成功。

## 4. 命令

```bash
cd mobile-reservation-assist
export MRA_STATE_DIR=/Users/zhangjiangtao/Documents/顺风车业务/.mra_state

# 只生成视频（导出到相册）
python3 skill/scripts/mra.py video make --note <note.json> --json

# 全链路：生成 → 导出 → 剪映分享 → 填标题描述 → 发布
python3 skill/scripts/mra.py video make --note <note.json> --publish --json

# 仅发布已有视频（抖音 + → 相册 → 选视频 → 发布）
python3 skill/scripts/mra.py douyin post --note <note.json> --media video --publish --json
```

驱动开关（默认 `auto`）：

```bash
MRA_PHONE_DRIVER=auto    # 剪映/抖音走 u2；顺风车/小红书仍走 Auto.js 网关
MRA_PHONE_DRIVER=gateway # 全部回退到旧通道
MRA_PHONE_DRIVER=u2      # 强制本地
```

## 5. 回放验证（行为可复现）

真实成功轨迹固化在 `tests/golden/jianying_douyin_publish.json`，
回放测试 `tests/test_replay_publish.py` 用 FakeDriver 按同一输入重跑流程，校验：

- 12 个动作 ID 的顺序与 golden 完全一致；
- 最终状态为 `done`；
- 文档第 2 节表格中的每一步都在代码里被执行到。

```bash
python3 -m unittest discover -s tests -p "test_replay_publish.py" -v
```
