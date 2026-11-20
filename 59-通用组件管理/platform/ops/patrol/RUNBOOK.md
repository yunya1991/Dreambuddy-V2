# 巡检事件接管手册（Agent Runbook）

巡检每 5 分钟跑一次，只负责「发现 + 诊断 + 受限重启」。代码级修复与部署由 Agent 按本手册接管。

## 触发条件（任一满足即接管）

- `python3 platform/ops/patrol/incident.py list` 有未关闭事件
- macOS 弹出「付费服务巡检异常」通知
- `~/.local/share/dreambuddy/patrol/latest.json` 中 `ok=false`

## 接管流程

### S1 认领
```bash
python3 platform/ops/patrol/incident.py show <id>      # 看证据：issues / billing / upstream / diagnosis
python3 platform/ops/patrol/incident.py ack <id> --note "开始定位"
```
先读 `evidence.diagnosis`（千问初诊），它只是线索，不是结论。

### S2 复现与定位
- 计费入口异常：直接打 `https://www.neodrm.com/api/paid/{data|cogsteward}`，确认 HTTP 与金额
- 上游异常：在服务器带 token 复现
  ```bash
  ssh tencent-cloud "sudo -n bash -c 'set -a; . /etc/skillhub-audit/audit.env; set +a; \
    curl -sS -m 30 -H \"X-Partner-Token: \$PARTNER_TOKEN\" \
    \"https://www.neodrm.com/api/partner/v1/run?skill=market-data-pro&cmd=macro&series=DGS10\"'"
  ```
- 进程异常：`ssh tencent-cloud 'systemctl status skillhub-audit-api --no-pager -n 30'`

定位到「代码 / 配置 / 上游 / 网络」四类之一，再决定动作。**不要跳过定位直接重启。**

### S3 本地修复
- 只改本仓库代码，仓库是唯一事实源
- 后端改动先跑测试（在 /tmp 副本里跑，避免污染工作区）：
  ```bash
  rm -rf /tmp/audit-test && cp -R services/skillhub-audit-api /tmp/audit-test
  cd /tmp/audit-test && node --test test/app.test.js
  ```
- 技能包改动：`python3 -c "import ast;ast.parse(open('scripts/xxx.py').read())"` + 实跑一次

### S4 回归
```bash
python3 platform/ops/patrol/patrol.py            # 期望 exit=0，三个入口 402、上游 200
```
若事件未自动关闭，说明异常仍在，回到 S2。

### S5 部署（工程化：备份 → 安装 → 重启 → 回归 → 回滚）

统一走部署脚本，不再手写 scp + restart：

```bash
bash platform/tools-skills/skillpay-workflow/scripts/audit.sh deploy
```

脚本行为：

1. 远端 `/opt/skillhub-audit/backups/app-<时间戳>/` 备份现有 `src/` 与 `package.json`；
2. 同步新 `src/` 与 `package.json` 并重启 `skillhub-audit-api`；
3. 回归：`systemctl is-active` + 本地 `/health` + `/api/cogsteward` 期望 402；
4. 任一步失败自动用备份回滚并重启，退出码非 0。

发布前先跑一致性闸门与测试（都在本地）：

```bash
python3 cognition-manager/scripts/release_check.py      # 三端契约 / 版本 / 口径
```

> 现状说明：远端 `/home/luke/dreambuddy` 已不是 git 仓库，RUNBOOK 早期的「GitHub 三段式」不再可用。本地提交仅用于留痕；若模块目录未被 git 跟踪，先 `git add` 再 commit，否则不会产生提交。禁止用 rsync 覆盖整个 `/opt/skillhub-audit/app`，只允许同步 `src/`（部署脚本已限定）。

### S6 关闭事件
```bash
python3 platform/ops/patrol/incident.py close <id> --note "根因:xxx; 修复:xxx; 证据:patrol 03:15 恢复正常"
```
`close_reason` 必须能回答「为什么不会再发生」，否则保持 open。

## 红线

1. 不改生产库、不跑破坏性 SQL
2. 不跳过 S4 直接上线
3. 不用 rsync/scp 覆盖整个 app 目录（部署脚本只同步 `src/` 与 `package.json`，并自带备份与回滚）
4. 不在未定位根因时关闭事件
5. 密钥、Token 不出现在命令输出与日志里

## 文件说明

| 路径 | 作用 |
|---|---|
| `patrol.py` | 巡检主程序，5 分钟一次 |
| `incident.py` | 事件台账（list/show/ack/close/stats） |
| `com.dreambuddy.patrol.plist` | LaunchAgent 定义（StartInterval=300） |
| `~/.local/share/dreambuddy/patrol/incidents/` | 事件文件，一事件一 JSON |
| `~/.local/share/dreambuddy/patrol/patrol-YYYYMMDD.jsonl` | 每轮巡检原始记录 |
| `~/.local/share/dreambuddy/patrol/latest.json` | 最近一轮结果 |
