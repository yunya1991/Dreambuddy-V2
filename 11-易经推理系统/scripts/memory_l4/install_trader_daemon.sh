#!/bin/bash
# =============================================================
#  一键安装 & 启动 macOS launchd 守护的 polling_trader
#  - 首次：复制 plist → 加载 → 自动启动
#  - 重复执行：卸载 → 覆盖 → 重新加载（等价于重启守护）
#  - 卸载：./install_trader_daemon.sh --uninstall
# =============================================================
set -euo pipefail

PROJ="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统"
SCRIPTS_DIR="$PROJ/scripts/memory_l4"
SRC_PLIST="$SCRIPTS_DIR/dreambuddy.yijing.polling-trader.plist"
SRC_WATCH="$SCRIPTS_DIR/polling_trader_watch.sh"
AGENTS_DIR="$HOME/Library/LaunchAgents"
DST_PLIST="$AGENTS_DIR/dreambuddy.yijing.polling-trader.plist"
LABEL="dreambuddy.yijing.polling-trader"
MY_UID=$(id -u)

chmod +x "$SRC_WATCH"
mkdir -p "$AGENTS_DIR"

# -------- 卸载分支 --------
if [ "${1:-}" = "--uninstall" ]; then
  echo ">>> [uninstall] unload launchd $LABEL"
  launchctl unload "$DST_PLIST" 2>/dev/null || true
  rm -f "$DST_PLIST"
  # 清旧进程/锁
  for pid in $(pgrep -f polling_trader 2>/dev/null); do
    kill -KILL "$pid" 2>/dev/null || true
  done
  rm -f "$PROJ/.workbuddy/memory_l4/guardian/heartbeat.json"
  echo "✅ uninstall done."
  exit 0
fi

# -------- 先确认 launchd 当前是否已加载 → 是则先卸载（干净）--------
if launchctl print "gui/$MY_UID/$LABEL" >/dev/null 2>&1; then
  echo ">>> [reload] 旧服务已在，先 unload"
  launchctl unload "$DST_PLIST" 2>/dev/null || true
fi

# -------- 复制 plist 到 LaunchAgents --------
cp -f "$SRC_PLIST" "$DST_PLIST"
chmod 644 "$DST_PLIST"
echo "✅ cp $SRC_PLIST -> $DST_PLIST"

# -------- 加载 launchd（RunAtLoad=true 会自动起 watch.sh）--------
echo ">>> launchctl load $DST_PLIST"
launchctl load "$DST_PLIST"
sleep 2

# -------- 状态 + 日志预览 --------
echo
echo "======================================================================"
echo "   launchd service status:"
launchctl print "gui/$MY_UID/$LABEL" 2>&1 | /usr/bin/head -30
echo
echo "   last launchd wakeup log events (system.log -1m):"
/usr/bin/log show --last 2m --style compact --predicate 'subsystem == "com.apple.xpc.launchd"' 2>/dev/null \
  | /usr/bin/grep -E "(dreambuddy|polling_trader)" | /usr/bin/tail -n 15 || echo "(no xpc launchd events captured)"
echo
echo "   polling_trader 最新日志（前 20 + 末 30 行）:"
LOG="$PROJ/logs/polling_trader_stdout.log"
if [ -f "$LOG" ]; then
  echo "--- head -20 ---"
  /usr/bin/head -20 "$LOG"
  echo
  echo "--- tail -30 ---"
  /usr/bin/tail -30 "$LOG"
else
  echo "  (尚未生成 $LOG，等 launchd 启动 watch.sh 后会有)"
fi
echo
echo "======================================================================"
echo "✅ 守护已安装 + 启动。后续操作："
echo "    状态 ： launchctl print gui/$MY_UID/dreambuddy.yijing.polling-trader"
echo "    人工重启： launchctl kickstart -k gui/$MY_UID/dreambuddy.yijing.polling-trader"
echo "    卸载 ： cd $SCRIPTS_DIR && ./install_trader_daemon.sh --uninstall"
echo "    看日志： tail -f $PROJ/logs/polling_trader_stdout.log"
