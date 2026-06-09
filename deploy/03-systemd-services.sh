#!/bin/bash
# ============================================================
# 6-TRADING 腾讯云部署 — 03 systemd 服务注册
# 用法: sudo bash 03-systemd-services.sh
# ============================================================
set -e

echo "=== 注册 systemd 服务 ==="

# 复制服务文件
cp /home/luke/tmp/deploy/hermes-gateway.service /etc/systemd/system/
cp /home/luke/tmp/deploy/group-poller.service /etc/systemd/system/
cp /home/luke/tmp/deploy/hermes-dashboard.service /etc/systemd/system/

systemctl daemon-reload

# 启动
systemctl enable --now hermes-gateway
systemctl enable --now group-poller
systemctl enable --now hermes-dashboard

sleep 5

echo ""
echo "=== 服务状态 ==="
systemctl status hermes-gateway --no-pager -l | head -10
echo "---"
systemctl status group-poller --no-pager -l | head -10
echo "---"
systemctl status hermes-dashboard --no-pager -l | head -10

echo ""
echo "=== 端口检查 ==="
ss -tlnp | grep -E '9119|hermes'

echo ""
echo "=== 部署完成 ==="
echo "Gateway:  systemctl status hermes-gateway"
echo "Poller:   systemctl status group-poller"
echo "Dashboard: http://<公网IP>:9119  (或 SSH tunnel)"
echo "日志:     tail -f /home/luke/.hermes/logs/gateway.log"
