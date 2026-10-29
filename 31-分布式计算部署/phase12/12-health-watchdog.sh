#!/bin/bash
# ============================================================
# 12-health-watchdog.sh — 安装 G6 健康检查 timer（云端，SPEC P1-1）
# 用法: sudo bash 12-health-watchdog.sh [--uninstall]
# 幂等：重复执行只做 daemon-reload + enable
# ============================================================
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
UNIT_DIR="/etc/systemd/system"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS=(dreambuddy-healthcheck.service dreambuddy-healthcheck.timer)

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 执行: sudo bash $0"
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now dreambuddy-healthcheck.timer 2>/dev/null || true
    for u in "${UNITS[@]}"; do rm -f "${UNIT_DIR}/${u}"; done
    systemctl daemon-reload
    echo "✓ 已卸载 G6 健康检查 timer"
    exit 0
fi

if [ ! -x "${REPO_DIR}/37-一键启动脚本/health-check.sh" ]; then
    echo "⚠ 缺少 ${REPO_DIR}/37-一键启动脚本/health-check.sh，请先 git pull"
    exit 2
fi

for u in "${UNITS[@]}"; do
    install -m 644 -o root -g root "${SRC_DIR}/${u}" "${UNIT_DIR}/${u}"
done
systemctl daemon-reload
systemctl enable --now dreambuddy-healthcheck.timer

echo "✓ 已安装并启动"
systemctl list-timers dreambuddy-healthcheck.timer --no-pager | head -3
echo "首次手动校验: bash ${REPO_DIR}/37-一键启动脚本/health-check.sh --dry-run"
