# 主云端部署核对清单

> **版本**：v1.0 | **更新日期**：2026-11-13
> **对象**：`43.160.201.117`（`dreambuddy-remote`）
> **当前边界**：单机部署；不执行分布式 Worker、训练下沉或多节点迁移。

## 1. 当前部署前阻断项

以下问题来自 2026-11-13 只读核查。未明确处置前，不应执行全量更新或宣称“全量健康”：

- [ ] `yijing-polling-trader.service` 持续重启失败（exit 1）已定位并处理。
- [ ] `dreambuddy-healthcheck.service` failed 的具体原因已查明。
- [ ] `v15-capital-api.service /status` 空响应已查明。
- [ ] 云端 HEAD 与 `origin/main` 的差异已审查；云端工作区中的源码修改已逐项决定保留、提交或回退。
- [ ] `dreamos-scheduler`、`hermes-dashboard` 的 disabled + inactive 已确认符合当前预期。

这些是当前运行风险记录，不是本次文档更新已修复的事项。

## 2. 部署前检查

### 2.1 代码与配置

- [ ] 明确本次部署的 commit、变更文件和影响服务。
- [ ] 本地已完成要求的评审与测试；GitHub 推送不被当作云端部署。
- [ ] 云端执行 `git status --short` 并保存结果；没有未审查的源码修改。
- [ ] 不使用 `git reset --hard`、`git clean` 或自动 stash 来掩盖未知差异。
- [ ] 核对云端仓库操作身份和文件属主，避免 root/ubuntu/luke 混用导致权限问题。
- [ ] 凭据只通过受控环境文件提供，不写入文档、命令输出或 Git。

### 2.2 运行态与变更窗口

- [ ] 保存关键 unit、timer、端口和 Docker 状态作为变更前基线。
- [ ] 阅读 `phase1/update.sh` 的实际版本，确认其交互、stash、构建和重启范围。
- [ ] 按当前部署制度完成 G4/评测门禁；不通过参数随意绕过。
- [ ] 只重启本次变更影响的服务，并明确回滚 commit 和验证方法。
- [ ] 不重跑历史全量 `deploy/migrate/install` 脚本替代增量部署。

## 3. 部署后验证

### 3.1 代码一致性

- [ ] 云端 HEAD 等于本次目标 commit。
- [ ] 云端工作区状态已解释，目标源码与交付版本一致。
- [ ] 若前端变更，构建成功；若 Python 依赖变更，目标 unit 使用的 venv 已安装对应依赖。

### 3.2 服务与接口

- [ ] 变更涉及的常驻 unit 为 active/running，且 `NRestarts` 不持续增长。
- [ ] oneshot 最近执行 `Result=success`、退出码为 0；不能因 inactive/dead 误判失败。
- [ ] timer 有 NEXT，且对应 service 最近执行成功。
- [ ] 核心接口实测：前端 `/` 返回 200/307/308；易经 `/` 200；V15 `/health` 200。
- [ ] 资金 API `/status` 返回符合契约的内容，而非空响应。
- [ ] 查看变更服务最近日志，无持续异常或崩溃循环。

### 3.3 数据与网络

- [ ] `dreambuddy-pg`、`dreambuddy-redis`、`dreambuddy-minio` healthy。
- [ ] PG/Redis/MinIO 与业务服务仍只绑定 `127.0.0.1`，未因部署暴露公网。
- [ ] Nginx 路由与目标 unit 端口一致。
- [ ] 关键数据文件的更新时间和业务语义正常，不能仅以 HTTP 200 验收。

## 4. 当前只读核查命令

```bash
ssh dreambuddy-remote 'git -C /home/luke/dreambuddy rev-parse HEAD; git -C /home/luke/dreambuddy status --short'
ssh dreambuddy-remote 'systemctl list-units --type=service --all --no-pager; systemctl list-timers --all --no-pager'
ssh dreambuddy-remote 'ss -tln; sudo -n docker ps'
ssh dreambuddy-remote 'journalctl -u yijing-polling-trader.service -u dreambuddy-healthcheck.service -n 50 --no-pager'
```

## 5. 历史记录使用规则

2026-10-14 的“全量已上线”“19 服务全 active”“PM2 已清空”等记录只代表当时观察，不再作为当前验收证据。当前服务和异常以 [SERVICE_INVENTORY.md](./SERVICE_INVENTORY.md) 及新的只读实测为准；分布式阶段任务全部暂停。
