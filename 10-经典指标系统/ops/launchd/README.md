# macOS launchd 自启动与自动重启（多实例：后端 8092/8093/8094 + 前端）

launchd 是 macOS 自带的进程管理器，不需要安装。

## 目标

- 后端服务自动启动（登录后）
- 进程异常退出或收到受控自重启指令后自动拉起
- 可选：前端 Dashboard 也交给 launchd 托管（便于三套环境并存）

## 安装（当前用户）

1) 一键安装（推荐）

```bash
bash "__PROJECT_DIR__/ops/launchd/install_8092.sh" 8092 prod
bash "__PROJECT_DIR__/ops/launchd/install_8092.sh" 8093 explore
bash "__PROJECT_DIR__/ops/launchd/install_8092.sh" 8094 pilot
```

2) 手动安装（等价于一键脚本）

复制模板到用户 LaunchAgents

```bash
mkdir -p "$HOME/Library/LaunchAgents"
cp "__PROJECT_DIR__/ops/launchd/com.ft.ml_trade_service.8092.plist" "$HOME/Library/LaunchAgents/com.ft.ml_trade_service.8092.plist"
```

替换 plist 内的 `__PROJECT_DIR__` 为项目绝对路径（例如：`/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统`）

```bash
perl -pi -e 's#__PROJECT_DIR__#/ABSOLUTE/PATH/TO/PROJECT#g' "$HOME/Library/LaunchAgents/com.ft.ml_trade_service.8092.plist"
perl -pi -e 's#__PORT__#8092#g; s#__LABEL__#com.ft.ml_trade_service.prod#g; s#__PROFILE__#prod#g; s#__ML_USER_DATA_DIR__#/ABSOLUTE/PATH/TO/PROJECT/user_data_prod#g; s#__LOG_DIR__#/ABSOLUTE/PATH/TO/PROJECT/user_data_prod/logs#g' "$HOME/Library/LaunchAgents/com.ft.ml_trade_service.8092.plist"
```

创建日志目录

```bash
mkdir -p "/ABSOLUTE/PATH/TO/PROJECT/user_data_prod/logs"
```

启动并设为开机/登录自启

```bash
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.ft.ml_trade_service.8092.plist"
launchctl enable "gui/$(id -u)/com.ft.ml_trade_service.prod"
launchctl kickstart -k "gui/$(id -u)/com.ft.ml_trade_service.prod"
```

## 前端 Dashboard（可选）

```bash
bash "__PROJECT_DIR__/ops/launchd/install_dashboard.sh" 3001 8092
bash "__PROJECT_DIR__/ops/launchd/install_dashboard.sh" 3002 8093
bash "__PROJECT_DIR__/ops/launchd/install_dashboard.sh" 3003 8094
```

## 基本面研究→交易 同步任务（建议）

```bash
bash "__PROJECT_DIR__/ops/launchd/install_fundamental_sync.sh" 600 "/Users/zhangjiangtao/ft_userdata/基本面分析_fundamental" "/usr/bin/python3" 28800 900 7200 900
```

查看同步日志：

```bash
tail -n 200 "__PROJECT_DIR__/user_data/logs/fundamental_sync.log"
tail -n 200 "__PROJECT_DIR__/user_data/logs/fundamental_research_sync.err.log"
```

## 查看状态与日志

```bash
launchctl print "gui/$(id -u)/com.ft.ml_trade_service.prod" | head -n 80
tail -n 200 "/ABSOLUTE/PATH/TO/PROJECT/user_data_prod/logs/ml_trade_service_prod_8092.out.log"
tail -n 200 "/ABSOLUTE/PATH/TO/PROJECT/user_data_prod/logs/ml_trade_service_prod_8092.err.log"
```

## 停止/卸载

```bash
bash "__PROJECT_DIR__/ops/launchd/uninstall_8092.sh" 8092 prod
bash "__PROJECT_DIR__/ops/launchd/uninstall_8092.sh" 8093 explore
bash "__PROJECT_DIR__/ops/launchd/uninstall_8092.sh" 8094 pilot
bash "__PROJECT_DIR__/ops/launchd/uninstall_dashboard.sh" 3001
bash "__PROJECT_DIR__/ops/launchd/uninstall_dashboard.sh" 3002
bash "__PROJECT_DIR__/ops/launchd/uninstall_dashboard.sh" 3003
bash "__PROJECT_DIR__/ops/launchd/uninstall_fundamental_sync.sh"
```

## 触发“受控自重启”（由 launchd 自动拉起）

后端新增接口（仅本机可用）：

```bash
curl -sS -X POST "http://127.0.0.1:8092/ops/restart" \
  -H "Content-Type: application/json" \
  -d '{"reason":"ops_manual","delay_sec":2}'
```

调试模式（不退出，仅写入 tracker 状态）：

```bash
curl -sS -X POST "http://127.0.0.1:8092/ops/restart" \
  -H "Content-Type: application/json" \
  -d '{"reason":"dry_run","delay_sec":2,"dry_run":true}'
```
