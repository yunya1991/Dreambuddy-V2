# 监控栈部署检查清单（云端 43.160.201.117）

> 适用：`docker-compose.monitoring.yml` / `prometheus/prometheus.yml` / `blackbox/blackbox.yml` 任何变更后的部署。
> 核心约束：**云端业务端口只绑 `127.0.0.1`，探针必须在宿主网络命名空间内探测**，禁用 `host.docker.internal`。

---

## 0. 前置约束（不满足则必然误报 TargetDown）

| 项 | 要求 | 校验方式 |
|---|---|---|
| 探针网络 | `blackbox-exporter` 必须 `network_mode: host`，监听 `127.0.0.1:9115` | `docker inspect dreambuddy-monitoring-blackbox-exporter-1 --format '{{.HostConfig.NetworkMode}}'` → `host` |
| 探针目标 | `prometheus.yml` 中 targets 一律 `127.0.0.1:<port>`，`replacement` 为 `127.0.0.1:9115` | `grep -n "host.docker.internal" prometheus/prometheus.yml` → 应无输出 |
| 业务绑定 | 被探服务绑定 `127.0.0.1`（V15 `run.py api` 即绑回环，`v15_api_server.py` 直跑才绑 `0.0.0.0`） | `ss -ltnp \| grep -E ':8771\|:8770\|:8765'` |
| 端口矩阵 | 探针 targets 与 `31-分布式计算部署/docs/SERVICE_INVENTORY.md` 保持一致，端口下线需同步删目标 | 人工比对 |
| 协议版本 | `blackbox.yml` 的 `valid_http_versions` 必须包含 `HTTP/1.0`（V15 API 基于 BaseHTTPRequestHandler，响应头为 HTTP/1.0） | `grep valid_http_versions blackbox/blackbox.yml` |
| 探针路径 | 每个目标的健康路径逐个实测过（8765 用根路径，8093/8099/8771 用 `/health`），不可套用统一后缀 | 见第 3 节 |

## 1. 部署前

- [ ] `docker compose -f docker-compose.monitoring.yml config >/dev/null` 通过（无 `ports`/`network_mode` 冲突）
- [ ] `promtool check config prometheus/prometheus.yml` 通过（本机或容器内）
- [ ] `promtool check rules prometheus/rules/dreambuddy-monitoring.yml` 通过
- [ ] 变更已 commit（重启前后代码一致，禁止用未提交配置上线）

## 2. 启动后（5 分钟内）

- [ ] 容器全部 running：`docker compose ps`
- [ ] Prometheus：`curl -s 127.0.0.1:9090/-/ready` → `Prometheus Server is Ready.`
- [ ] Alertmanager：`curl -s 127.0.0.1:9093/-/ready` → `OK`
- [ ] Blackbox：`curl -s 127.0.0.1:9115/-/healthy` → `Blackbox Exporter is healthy.`
- [ ] 9115 未对外暴露：`ss -ltnp | grep 9115` → 仅 `127.0.0.1:9115`

## 3. 探针连通性直验（逐目标，绕过 Prometheus）

```bash
for t in http://127.0.0.1:3001 http://127.0.0.1:3002 http://127.0.0.1:8765/health \
         http://127.0.0.1:8771/health http://127.0.0.1:8093 http://127.0.0.1:8099; do
  printf '%-40s ' "$t"
  curl -s "http://127.0.0.1:9115/probe?module=http_2xx&target=$t" | awk '/^probe_success/{print $2}'
done
```

- [ ] 每个目标 `probe_success 1`；为 0 时先 `curl -sS <target>` 确认服务自身状态，再查绑定地址；
      `curl -sS -i <target>` 若响应头是 `HTTP/1.0`，须确认 `valid_http_versions` 已包含 `HTTP/1.0`
- [ ] TCP 探针：`curl -s "http://127.0.0.1:9115/probe?module=tcp_connect&target=127.0.0.1:5432" | grep '^probe_success'` → `1`

## 4. Prometheus 目标状态

- [ ] `curl -s 'http://127.0.0.1:9090/api/v1/query?query=up==0' | jq '.data.result'` → 空数组（或仅预期内下线目标）
- [ ] `curl -s 'http://127.0.0.1:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.health!="up") | {scrapeUrl,lastError}'` → 无输出
- [ ] 规则已加载：`curl -s 127.0.0.1:9090/api/v1/rules | jq '.data.groups[].name'`

## 5. 告警链路

- [ ] `curl -s -XPOST 127.0.0.1:9093/-/reload` 或配置变更后重启 Alertmanager
- [ ] 告警可达：`curl -s 127.0.0.1:9093/api/v2/alerts | jq length` 正常返回
- [ ] 旧误报已消解：变更前已 firing 的 TargetDown 在目标转 `up` 后应收到「已恢复」卡片；如仍持续，检查是否存在历史 silence 或 repeat 窗口

## 6. 变更后观察（10 分钟）

- [ ] 无新增 `TargetDown`（`for: 2m`，部署后 3 分钟内即可判定）
- [ ] Grafana `/monitor/` 可登录，`up` 面板全绿
- [ ] 若出现误报，先 `amtool silence add alertname=TargetDown instance=...` 止血，再按第 0 节逐项排查

## 7. 回滚

```bash
git revert <commit> && rsync 配置到 /home/luke/dreambuddy/15-监控告警系统/deploy/ \
  && docker compose -f docker-compose.monitoring.yml up -d --force-recreate blackbox-exporter prometheus
curl -s -XPOST 127.0.0.1:9090/-/reload
```
