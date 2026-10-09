# Phase 1 部署检查清单

> 云端核心上线：腾讯云轻量 4C8G 香港 → 前端 + V15 + 数据层 + Nginx SSL + Hermes 飞书网关

## 部署前准备

- [ ] 购买腾讯云轻量 4C8G（香港节点），记录公网 IP
- [ ] 域名解析：A 记录指向服务器公网 IP
- [ ] SSH 密钥配置：本地 → 云服务器免密登录
- [ ] 准备 OKX API 凭据（或使用 Hyperliquid paper 模式）

## Step 0: 上传代码

```bash
# 本地执行
scp -r ~/WorkBuddy/dreambuddy-v2 luke@<云IP>:~/dreambuddy
```

## Step 1: 环境初始化

```bash
ssh luke@<云IP>
cd ~/dreambuddy
sudo bash 31-分布式计算部署/phase1/01-cloud-init.sh
```

验证：
- [ ] `docker --version` 正常
- [ ] `docker compose version` 正常
- [ ] `node -v` ≥ 22
- [ ] `pnpm --version` 正常
- [ ] `pm2 --version` 正常
- [ ] `python3 --version` ≥ 3.12
- [ ] `ufw status` 显示 22/80/443 开放

## Step 2: 配置 .env.cloud

```bash
cp 31-分布式计算部署/phase1/.env.cloud.example ~/.config/dreambuddy/.env.cloud
vim ~/.config/dreambuddy/.env.cloud
```

必填项：
- [ ] `DOMAIN` = 你的域名
- [ ] `POSTGRES_PASSWORD` = 强密码（≥24位）
- [ ] `MINIO_ROOT_PASSWORD` = 强密码（≥24位）
- [ ] `NEXTAUTH_SECRET` = `openssl rand -base64 32` 生成
- [ ] `AUTH_SECRET` = `openssl rand -base64 32` 生成
- [ ] `ENCRYPTION_KEY` = `openssl rand -base64 32` 生成（API 凭证加密）
- [ ] `DEEPSEEK_API_KEY` = DeepSeek LLM API Key
- [ ] `TAVILY_API_KEY` = Tavily 搜索 API Key
- [ ] `V15_DATA_SOURCE` = hyperliquid 或 okx
- [ ] OKX 凭据（实盘时）或 HL wallet（paper 时）
- [ ] `LARK_APP_ID` = 飞书应用 ID (Hermes 网关)
- [ ] `LARK_APP_SECRET` = 飞书应用密钥 (Hermes 网关)

可选（Phase 1 默认 127.0.0.1，后续迁移后更新）：
- [ ] `NEXT_PUBLIC_BRIDGE_URL` = http://127.0.0.1:3847（Bridge 层，尚未部署）
- [ ] `HUB_BASE_URL` = http://127.0.0.1:8787（Hub 服务，尚未部署）
- [ ] `WORKBUDDY_API_URL` / `WORKBUDDY_WS_URL` = http://127.0.0.1:8080（尚未部署）
- [ ] `NEXT_PUBLIC_TREND_SYSTEM_URL` = http://127.0.0.1:8765（11-易经推理系统，后续迁移）

## Step 3: 数据层部署

```bash
bash 31-分布式计算部署/phase1/02-deploy-data.sh
```

验证：
- [ ] `docker ps` 显示 3 个容器 running
- [ ] PostgreSQL `pg_isready` 返回 OK
- [ ] Redis `redis-cli ping` 返回 PONG
- [ ] MinIO `curl http://127.0.0.1:9000/minio/health/live` 返回 200
- [ ] MinIO buckets: models, backtest-results, data-cache 已创建

## Step 4: 前端部署

```bash
bash 31-分布式计算部署/phase1/03-deploy-frontend.sh
```

验证：
- [ ] `.env.production` 包含全部变量（DATABASE_URL / NextAuth / ENCRYPTION_KEY / DeepSeek / Tavily / 外部服务URL）
- [ ] `pnpm install` 无错误
- [ ] `prisma migrate deploy` 成功（5 个迁移）
- [ ] `prisma db seed` 执行成功（初始用户）
- [ ] `pnpm build` 无错误
- [ ] `pm2 list` 显示 dreambuddy-frontend online
- [ ] `curl http://127.0.0.1:3001` 返回 200/307
- [ ] 前端登录页可访问（NextAuth 正常）

## Step 5: V15 策略部署

```bash
bash 31-分布式计算部署/phase1/04-deploy-v15.sh
```

验证：
- [ ] `python3 run.py signal BTC` 正常输出信号
- [ ] `systemctl list-timers v15-*` 显示两个 timer active
- [ ] `v15-orchestrator.service` 手动触发无报错
- [ ] `v15-poll-light.service` 手动触发无报错
- [ ] 日志文件在 `~/logs/v15/` 下正常写入
- [ ] `systemctl status v15-api` 运行中 (端口 8771 决策 API)
- [ ] `curl http://127.0.0.1:8771/health` 返回 200
- [ ] `systemctl status v15-capital-api` 运行中 (端口 8770 资金管理 API)
- [ ] `curl http://127.0.0.1:8770/status` 返回 200
- [ ] PM2 持久化: `pm2 startup` 已注册 (服务器重启自动恢复)

## Step 6: Nginx + SSL

```bash
sudo bash 31-分布式计算部署/phase1/05-nginx-ssl.sh
```

验证：
- [ ] `nginx -t` 测试通过
- [ ] `curl https://<域名>/health` 返回 200
- [ ] HTTP 自动重定向到 HTTPS
- [ ] `certbot renew --dry-run` 成功

## Step 7: 飞书网关 (Hermes) 部署

```bash
sudo bash 31-分布式计算部署/phase1/06-deploy-hermes.sh
```

验证：
- [ ] `~/.hermes/config.yaml` 已复制
- [ ] `~/.hermes/.env` 已填写飞书凭据 (LARK_APP_ID / LARK_APP_SECRET)
- [ ] `lark-cli auth login` 已绑定
- [ ] `systemctl status hermes-gateway` 运行中
- [ ] `tail -f ~/.hermes/logs/gateway.log` 有 WebSocket 连接日志
- [ ] 飞书群消息可正常收发

## Step 8: 日志轮转 + 健康检查

```bash
# 安装 logrotate
sudo cp 31-分布式计算部署/phase1/logrotate-dreambuddy.conf /etc/logrotate.d/dreambuddy
sudo logrotate -d /etc/logrotate.d/dreambuddy  # dry-run 验证

# 运行健康检查
bash 31-分布式计算部署/phase1/healthcheck.sh
```

验证：
- [ ] `logrotate -d` 无错误
- [ ] `healthcheck.sh` 全部 ✓ 通过 (或仅 ⚠ 警告)
- [ ] 磁盘空间 < 80%
- [ ] 内存使用 < 80%

## Step 9: 最终验收

- [ ] 浏览器访问 `https://<域名>` 前端页面正常
- [ ] 前端可登录（NextAuth 正常）
- [ ] `systemctl list-timers v15-*` timer 运行中
- [ ] V15 orchestrator 日志有正常输出
- [ ] `curl http://127.0.0.1:8771/api/v15-ct/decision?coin=BTC` 返回决策 JSON
- [ ] `curl http://127.0.0.1:8770/status` 返回资金管理状态
- [ ] 飞书消息正常（hermes-gateway 运行中）
- [ ] `pm2 list` 前端进程 stable（无频繁重启）
- [ ] `docker ps` 三个数据容器 healthy
- [ ] `healthcheck.sh` 通过

## 日常运维

### 代码更新
```bash
bash 31-分布式计算部署/phase1/update.sh
# 可选参数: --skip-frontend --skip-v15 --skip-deps
```

### 健康检查
```bash
bash 31-分布式计算部署/phase1/healthcheck.sh        # 文本模式
bash 31-分布式计算部署/phase1/healthcheck.sh --json  # JSON 模式 (适合监控)
```

### 日志查看
```bash
# 前端
pm2 logs dreambuddy-frontend --lines 50

# V15
tail -50 ~/logs/v15/orchestrator.log
tail -50 ~/logs/v15/api.log
tail -50 ~/logs/v15/capital-api.log

# Hermes
journalctl -u hermes-gateway -f

# Nginx
tail -50 /var/log/nginx/dreambuddy-access.log
```

## 常见问题

### Q: pnpm install 失败 (网络问题)
```bash
# 使用国内镜像
pnpm config set registry https://registry.npmmirror.com
pnpm install
```

### Q: Docker pull 超时
```bash
# 配置 Docker 镜像加速
sudo mkdir -p /etc/docker
echo '{"registry-mirrors":["https://mirror.ccs.tencentyun.com"]}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
```

### Q: Let's Encrypt 申请失败
```bash
# 确认域名解析
dig <域名> +short  # 应返回服务器 IP
# 确认 80 端口可达
curl -I http://<域名>
# 手动申请
certbot --nginx -d <域名> --verbose
```

### Q: V15 信号模块报错
```bash
cd ~/dreambuddy/14-V15经典马丁策略
python3 run.py signal BTC 2>&1  # 查看完整错误
# 常见: 缺少 .env.local 凭据, 或 Python 依赖未安装
```
