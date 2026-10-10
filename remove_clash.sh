#!/bin/bash
# ============================================================
# 删除所有 Clash 相关应用和配置
# 执行：bash ~/WorkBuddy/dreambuddy-v2/remove_clash.sh
# ============================================================
set -e

echo "=== 1. 卸载 LaunchDaemons ==="
sudo launchctl unload /Library/LaunchDaemons/party.mihomo.helper.plist 2>/dev/null || true
sudo launchctl unload /Library/LaunchDaemons/com.west2online.ClashXPro.ProxyConfigHelper.plist 2>/dev/null || true
sudo launchctl unload /Library/LaunchDaemons/io.github.clash-verge-rev.clash-verge-rev.service.plist 2>/dev/null || true

echo "=== 2. 卸载 LaunchAgents ==="
launchctl unload ~/Library/LaunchAgents/io.github.clash-verge-rev.clash-verge-rev.plist 2>/dev/null || true

echo "=== 3. 杀残留进程 ==="
sudo killall mihomo 2>/dev/null || true
sudo killall "Clash Party" 2>/dev/null || true
sudo killall ClashXPro 2>/dev/null || true
sudo killall "clash-verge" 2>/dev/null || true
sudo killall party.mihomo.helper 2>/dev/null || true

echo "=== 4. 删除应用 ==="
sudo rm -rf "/Applications/Clash Party.app"
sudo rm -rf "/Applications/ClashX Pro.app" 2>/dev/null || true
sudo rm -rf "/Applications/Clash Verge.app" 2>/dev/null || true

echo "=== 5. 删除 PrivilegedHelperTools ==="
sudo rm -f /Library/PrivilegedHelperTools/party.mihomo.helper
sudo rm -f /Library/PrivilegedHelperTools/com.west2online.ClashXPro.ProxyConfigHelper
sudo rm -rf /Library/PrivilegedHelperTools/io.github.clash-verge-rev.clash-verge-rev.service.bundle

echo "=== 6. 删除 LaunchDaemons/Agents plists ==="
sudo rm -f /Library/LaunchDaemons/party.mihomo.helper.plist
sudo rm -f /Library/LaunchDaemons/com.west2online.ClashXPro.ProxyConfigHelper.plist
sudo rm -f /Library/LaunchDaemons/io.github.clash-verge-rev.clash-verge-rev.service.plist
rm -f ~/Library/LaunchAgents/io.github.clash-verge-rev.clash-verge-rev.plist

echo "=== 7. 删除 Application Support ==="
rm -rf ~/Library/Application\ Support/mihomo-party
rm -rf ~/Library/Application\ Support/com.west2online.ClashXPro
rm -rf ~/Library/Application\ Support/io.github.clash-verge-rev.clash-verge-rev

echo "=== 8. 删除其他残留 ==="
rm -rf ~/.config/mihomo-party 2>/dev/null || true
rm -rf ~/.config/clash-verge 2>/dev/null || true

echo "=== 9. 刷新 DNS ==="
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder 2>/dev/null || true

echo "=== 10. 检查 shell proxy 配置 ==="
grep -n "proxy\|PROXY\|7890" ~/.zshrc ~/.bashrc ~/.zprofile ~/.bash_profile 2>/dev/null || echo "无 proxy 配置"

echo ""
echo "=== 清理完成，建议重启 Mac 确保 TUN 接口彻底清除 ==="
