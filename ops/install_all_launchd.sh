#!/bin/bash
# DreamBuddy 全系统 Launchd 一键安装脚本
# 此脚本需要在普通终端中运行（非 TRAE 沙箱环境）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
AB_DIR="${ROOT_DIR}/experiments/ab-trading"
YIJING_DIR="${ROOT_DIR}/11-易经推理系统"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
UID=$(id -u)

echo "============================================================"
echo "  DreamBuddy 全系统 Launchd 一键安装"
echo "============================================================"
echo ""

mkdir -p "${LAUNCH_AGENTS_DIR}"

# 定义所有服务
declare -A PLIST_SOURCES=(
    ["com.dreambuddy.ab_orchestrator"]="${AB_DIR}/com.dreambuddy.ab_orchestrator.plist"
    ["com.dreambuddy.screen_orchestrator"]="${AB_DIR}/com.dreambuddy.screen_orchestrator.plist"
    ["com.dreambuddy.ab_monitor"]="${AB_DIR}/com.dreambuddy.ab_monitor.plist"
    ["com.dreambuddy.screen_monitor"]="${AB_DIR}/com.dreambuddy.screen_monitor.plist"
    ["com.dreambuddy.yijing_monitor"]="${YIJING_DIR}/com.dreambuddy.yijing_monitor.plist"
    ["com.dreambuddy.yijing_trading"]="${YIJING_DIR}/com.dreambuddy.yijing_trading.plist"
)

declare -A SERVICE_NAMES=(
    ["com.dreambuddy.ab_orchestrator"]="Agent A/B 编排器"
    ["com.dreambuddy.screen_orchestrator"]="三屏马丁编排器"
    ["com.dreambuddy.ab_monitor"]="Agent A/B 监控自进化"
    ["com.dreambuddy.screen_monitor"]="三屏马丁监控自进化"
    ["com.dreambuddy.yijing_monitor"]="易经推理监控"
    ["com.dreambuddy.yijing_trading"]="易经推理交易"
)

# 清理旧服务
OLD_SERVICES=("com.yijing.trading")
for old in "${OLD_SERVICES[@]}"; do
    old_plist="${LAUNCH_AGENTS_DIR}/${old}.plist"
    if [ -f "$old_plist" ]; then
        echo "清理旧服务: ${old}"
        launchctl bootout "gui/${UID}/${old}" 2>/dev/null || true
        launchctl unload "$old_plist" 2>/dev/null || true
        rm -f "$old_plist"
        echo "  ✅ 已清理"
    fi
done

echo ""
i=1
for label in "${!PLIST_SOURCES[@]}"; do
    src="${PLIST_SOURCES[$label]}"
    dst="${LAUNCH_AGENTS_DIR}/${label}.plist"
    name="${SERVICE_NAMES[$label]}"

    echo "[${i}/6] 安装: ${name} (${label})"

    # 复制 plist
    cp "$src" "$dst"
    echo "    plist 已复制"

    # 验证
    plutil -lint "$dst" > /dev/null 2>&1 && echo "    语法验证通过"

    # 卸载旧的（如果有）
    launchctl bootout "gui/${UID}/${label}" 2>/dev/null || true
    launchctl unload "$dst" 2>/dev/null || true

    # 加载
    if launchctl bootstrap "gui/${UID}" "$dst" 2>/dev/null; then
        echo "    服务已加载"
    else
        echo "    ⚠️  bootstrap 返回警告（可能是首次加载）"
    fi

    # 启用
    launchctl enable "gui/${UID}/${label}" 2>/dev/null || true

    # 触发首次运行
    launchctl kickstart "gui/${UID}/${label}" 2>/dev/null || true
    echo "    已触发首次运行"

    echo "    ✅ 完成"
    echo ""
    i=$((i+1))
done

echo "============================================================"
echo "  ✅ 全部安装完成！"
echo "============================================================"
echo ""
echo "已安装的服务："
for label in "${!PLIST_SOURCES[@]}"; do
    name="${SERVICE_NAMES[$label]}"
    echo "  • ${name} (${label})"
done
echo ""
echo "管理命令："
echo "  查看所有服务状态:"
echo "    python3 ${ROOT_DIR}/ops/launchd_manage.py status"
echo ""
echo "  手动触发某个服务:"
echo "    launchctl kickstart gui/${UID}/<服务名>"
echo ""
echo "  查看实时日志:"
echo "    tail -f <日志文件路径>"
echo ""
