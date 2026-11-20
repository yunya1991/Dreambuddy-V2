---
name: reservation-assist
slug: dreambuddy-reservation-assist
displayName: 预约助手 Reservation Assist
version: 0.11.2
summary: 本地常驻的余票/号源监控与通知工具：对时调度、命中去重、官方深链跳转，默认不自动提交。
license: MIT
allowed-tools: Bash, Read
---

# 预约助手（reservation-assist）

## 0. 一句话

**在本地常驻盯住用户自己账号可见的余票/号源页面，命中就通知并给出官方深链；默认不提交、不支付、不代抢。**

面向四类场景：铁路余票与候补、演出开票、医院放号、政务/签证/场馆预约。

---

## 1. 红线适用域

本组件遵循 [contracts/redlines.md](../../../contracts/redlines.md)：

| 红线 | 适用 | 本组件落实方式 |
|---|---|---|
| R1 禁方向词 | ✅ | 通知与报告文案过词表，不出现"机会/推荐/预计/有望"等 |
| R2 禁外推 | ✅ | 只报当前观测到的余票/号源，不预测能否抢到 |
| R3 缺失不填充 | ✅ | 探测失败写 `missing[]` 与原因码，不用 0 或上期值替代 |
| R4 每个数字可复核 | ⚠️ 部分 | 仅统计量（命中次数、平均探测延迟）带 `method_id` 与 `n`，见 `references/methods.md` |
| R5 数据源授权 | ✅ | 走 `contracts/data-sources.yaml` 的 DC-2 内部例外，不得扩大用途 |
| R6 禁再分发原始数据 | ✅ | 不存原始页面，只输出场次/票档摘要与官方深链 |
| R7 通道失败不静默降级 | ✅ | 通知失败重试 2 次后记 `missing[]` 并告警，不假装成功 |
| R8 跨组件边界 | ✅ | 不引用任何其它组件 |
| R9 不越界写盘 | ✅ | 只写 `~/.reservation-assist/` 与 `~/Library/LaunchAgents/` |
| R10 免责不可省 | ✅ | 报告 `limits` 非空 |

---

## 2. 命令表

```bash
# 新增监控任务（target / rule 可传 JSON 字符串或 @file）
python3 scripts/ra.py watch add --adapter railway \
  --target '{"target_id":"G1","from":"北京","to":"上海","session":"2026-12-01"}' \
  --rule '{"max_price":600}' \
  --window "2026-12-01T08:00:00+08:00/2026-12-01T08:10:00+08:00"

python3 scripts/ra.py watch list [--json]
python3 scripts/ra.py watch rm <task_id>
python3 scripts/ra.py watch grant <task_id>     # 必须 tty；签发 ≤2h 一次性 grant
python3 scripts/ra.py watch revoke <task_id>
python3 scripts/ra.py watch run [--task <task_id>] [--once] [--foreground]
python3 scripts/ra.py watch pause-all | resume-all

python3 scripts/ra.py notify test --channel local
python3 scripts/ra.py doctor [--json] [--purge]
python3 scripts/ra.py reconcile <task_id> [--close]
python3 scripts/ra.py report [--date YYYY-MM-DD] [--json]
python3 scripts/ra.py drill login --adapter <name> --state <ok|expired|unknown>
python3 scripts/ra.py drill submit --adapter <name> --result <ok|wrong_target|duplicate> [--captcha none|manual|blocked]
python3 scripts/ra.py drill check --adapter <name> [--json]
python3 scripts/ra.py auth set --adapter <name>      # 从 stdin 读 Cookie，值不回显
python3 scripts/ra.py auth status [--json]
python3 scripts/ra.py auth clear --adapter <name>
python3 scripts/ra.py auth feishu                   # 从 stdin 读 webhook，存 Keychain
python3 scripts/ra.py watch notify <task_id> --channels feishu_app,local
python3 scripts/ra.py notify test --channel feishu
python3 scripts/ra.py inbox pull [--minutes 60] [--no-notify]
python3 scripts/ra.py inbox show
python3 scripts/ra.py 开启预约 | 开始预约 | 关闭预约 | 停止预约 | 状态
python3 scripts/ra.py install | uninstall
```

退出码：`0` 成功 / `2` 参数错误 / `3` 门禁拒绝 / `4` 登录态失效 / `5` 平台不可达 / `6` 需人工对账。

---

## 3. 自动提交门禁

默认**不提交**。提交必须同时满足：

1. 非容器/云主机，且 `RA_ALLOW_SUBMIT != "0"`
2. 适配器 `SUBMIT_READY is True`（需通过 `references/adapters.md` 的就绪实验）
3. 任务 `submit_enabled=1`、`max_orders=1`、已填价格上限、已选观演人/就诊人
4. 存在未过期的 tty 一次性 grant，且指纹与当前目标一致
5. 该 `(task_id, fingerprint)` 没有 `submitted/unknown` 记录

launchd 无人值守时 `RA_ALLOW_SUBMIT=0`，因此**永不自动提交**。终态停在官方下单页并回填目标，不调用锁座/占座接口，不支付。

---

## 4. 数据与隐私

- 状态目录 `~/.reservation-assist/`（0700），SQLite 存任务、命中、事件、grant
- 凭据只放 Keychain：`security add-generic-password -U -s com.reservation-assist.<adapter> -a <adapter> -w '<cookie>'`；`ra watch run` 启动时读取一次，缺失写 `login_missing` 并通知，不发起未登录探测
- `doctor` 自检失败即禁用提交，不降级明文
- 日志/事件/报告/`--json` 输出统一 `redact()`：证件号、手机号（保留后 4）、cookie/token、地址
- 指纹 = `sha256(adapter|target_id|date|session|price_tier)`，日期按 Asia/Shanghai 归一

---

## 5. 边界

- 不代抢、不转售、不加价、不多账号、不破解验证码、不做代理池
- 不托管支付，不做 GUI，不做云端部署
- 平台协议变化只改 `scripts/adapters/<平台>.py`

免责声明：本工具仅做余票/号源监控与官方页面跳转，不构成任何购买建议，也不承诺成功率。
