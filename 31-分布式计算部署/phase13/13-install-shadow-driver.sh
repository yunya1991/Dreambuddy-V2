#!/usr/bin/env bash
# 13-install-shadow-driver.sh — 云端安装 AgentMailShadow 壳驱动（α 接线）
#
# 作用：
#   1) 建运维开关 <repo>/.workbuddy/agent_mail/ENABLED（shell 内 observe_envelope 读它）
#   2) 安装 dreambuddy-shadow-driver.service/.timer（每 10min 经壳 JSON-RPC 驱动真实调用）
#   3) 立即首跑一次并打印 trajectory 落盘行数
#
# 必须 root 执行（systemctl）；脚本内写文件一律 sudo -u luke -H，避免 root 属主。
set -euo pipefail

REPO=/home/luke/dreambuddy
UNIT_SRC="$REPO/31-分布式计算部署/phase13"
PY=/home/luke/venv-trading/bin/python
STORE="$REPO/.workbuddy/agent_mail/trajectories.jsonl"

if [[ ! -x "$PY" ]]; then
  echo "missing python: $PY" >&2
  exit 1
fi

# 1) 运维开关 + 轨迹目录（luke 属主）
sudo -u luke -H mkdir -p "$REPO/.workbuddy/agent_mail"
sudo -u luke -H touch "$REPO/.workbuddy/agent_mail/ENABLED"

# 2) systemd 单元
install -m 644 "$UNIT_SRC/dreambuddy-shadow-driver.service" /etc/systemd/system/
install -m 644 "$UNIT_SRC/dreambuddy-shadow-driver.timer" /etc/systemd/system/
systemctl daemon-reload

# 3) 首跑（FAIL-OPEN：失败不阻断 timer 安装）
systemctl start dreambuddy-shadow-driver.service || true
systemctl enable --now dreambuddy-shadow-driver.timer

echo "timer: $(systemctl is-active dreambuddy-shadow-driver.timer)"
echo "store: $(wc -l < "$STORE" 2>/dev/null || echo 0) lines -> $STORE"
