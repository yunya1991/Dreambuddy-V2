# 手机预约助手 · 全链路运行手册

给 AI/工程师排障用：先看症状 → 查 stage → 按修复表处理 → 用验收清单确认。

## 1. 红线

- 默认只推进到「官方确认订单页」，**不提交订单、不锁票、不支付**
- 支付能力存在但默认关闭：仅当用户明确说「帮我买/直接付款」时，dispatch 带 `pay_authorized=true`
- 永不：代抢、锁座、破解验证码、修改价格

## 2. 拓扑

```
dream CLI (mra.py)
  └─ SQLite (.mra_state/state.db)
       └─ gateway :8765  (GET /commands 拉取 / POST /results 回执)
            └─ 手机 AutoJs6 脚本 (agent/reservation_agent.js)
                 └─ B站会员购 / 千问 App
```

手机连不上时优先用 USB 通道：
`adb reverse tcp:8765 tcp:8765` + 手机配置 `gateway=http://127.0.0.1:8765` + 当前 token。

## 3. stage 对照表

| stage | 含义 | 成功判据 |
|---|---|---|
| open_app | 拉起 App | currentPackage 正确 |
| dismiss_consent | 隐私弹窗 | 出现「会员购」入口 |
| goto_mall | 进入会员购 | 出现搜索条 |
| search_find_input / search_input_text | 搜索框与输入 | EditText 存在且已 setText |
| search_submit | 提交搜索 | 出现「综合/销量/价格」 |
| pick_product | 选品 | 进入详情页 |
| detail_buy | 点立即购票/购买 | 出现票档或订单页 |
| tier_select | 选票档 | 选中可售档位 |
| order_confirm | 确认订单页 | 出现支付方式或「提交订单」 |
| payment_pause | 支付前暂停 | 识别到支付宝/微信/花呗，未点击 |
| qw_open/qw_input/qw_send/qw_wait | 千问咨询 | 出现「复制回答」且抓到文本 |

## 4. 识别规则（易错点）

- **点击必须坐标手势优先**：B站「立即购票」是 clickable=false 的容器，`node.click()` 返回 true 但无响应
- **价格标签识别**：按 `¥38.8` 找可购买服务卡片，比标题匹配稳
- **预售可买**：只有「售罄/停售/无票」才拦；灰显「×月×日开售」的档位跳过
- **已结束识别**：`已结束/已停售/已取消/已过期` 直接跳过，不点进详情
- **支付词拦截**：含 `支付/付款/提交订单/结算/锁座/占座` 的节点默认不点
- **退出用 X**：先点 `关闭/×`，再返回

## 5. 千问咨询通道

```bash
MRA_STATE_DIR=<state> python3 skill/scripts/mra.py consult "问题" --timeout 150
```

链路：入队 qianwen 作业 → 手机打开千问 → 新建对话 → 输入 → 发送 → 抓取回答。
用途：出现选择器/流程异常时先问千问，再查代码验证，最后执行修复。
`patrol --consult` 会在仍有卡住作业时自动问一次。

## 6. 故障速查

| 症状 | 日志特征 | 根因 | 修复 |
|---|---|---|---|
| 手机一直没反应 | 无新日志 / 连接被拒 | 网关没起或 IP 不通 | 起网关；改 adb reverse |
| 401 | HTTP 401 | token 不一致 | 同步 .mra_state/gateway_token 到手机配置 |
| 点击无效 | step ok=true 但页面不动 | 无障碍 click 对容器无效 | 改坐标手势 tapNode |
| 重复点击 | 连续两次 operation_* | 点击后未等结果 | 点一次后轮询页面特征 |
| 搜索提交失败 | search_input_missing | 首页加载慢 | 5×2s 轮询；先点伪搜索条 |
| 找不到商品 | 未定位到目标商品 | 首个匹配是搜索框 | 遍历全部匹配并跳过顶部搜索区 |
| 已结束还进入 | 详情页无票档 | 未识别状态标签 | statusNear 过滤 |
| 支付页没有识别 | payment_pause 缺失 | 支付方式文案变体 | 扩充 PAY_TOKENS/渠道词 |
| 千问无回答 | qw_answer ok=false | 未登录/仍在生成 | 手动打开千问确认登录，重试 |

## 7. 排查命令

```bash
cd mobile-reservation-assist
export MRA_STATE_DIR=/Users/zhangjiangtao/Documents/顺风车业务/.mra_state
python3 skill/scripts/mra.py jobs
python3 skill/scripts/mra.py report
python3 skill/scripts/mra.py patrol --auto-fix --stuck-seconds 180 --max-retries 2
python3 skill/scripts/mra.py consult "问题"
adb -s ddad4c46 shell "tail -n 30 /sdcard/脚本/顺风车助手/autojs/agent_debug/agent.log"
adb -s ddad4c46 shell uiautomator dump /sdcard/ui.xml
```

## 8. 改完后的验收清单

1. `node --check agent/reservation_agent.js`
2. `adb push` 到 `/sdcard/脚本/顺风车助手/autojs/reservation_agent.js`
3. 重启脚本进程（force-stop AutoJs6 → 重开 → 恢复无障碍 → 点 RUN）
4. `python3 -m unittest discover -s tests` 全绿
5. 真机跑一条到 `order_confirm` / `payment_pause` 并看回执
6. 确认没有出现任何支付动作

## 9. 支付授权

- 默认：`pay_authorized=false`，到确认订单页即停
- 授权：用户明确说「帮我买/直接付款」→ 规划器置 `true` → 手机执行「提交订单 → 选支付方式 → 确认支付」，停在密码/指纹页
- 撤销：重新 dispatch 不带授权（或保持默认）
