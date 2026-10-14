#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2: 经典系统模块化服务部署 (M25/M26/M27/M28)
# 作用: 通过 PM2 启动/重启 4 个经典模块 Flask 服务
# 用法: sudo bash 05-deploy-classic-modules.sh
#
# 模块与端口:
#   M25 策略生成 → 8095 (25-用户策略生成系统/app.py)
#   M26 策略管理 → 8093 (26-策略管理模块/app.py)
#   M27 治理审批 → 8094 (27-策略治理审批系统/app.py)
#   M28 信号触发 → 8096 (28-策略信号触发模块/app.py)
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "============================================"
echo "  Phase 2 — 经典模块部署 (M25/M26/M27/M28)"
echo "============================================"

# ── 检查 PM2 ──
if ! command -v pm2 &>/dev/null; then
    echo "ERROR: pm2 未安装，请先安装: npm install -g pm2"
    exit 1
fi
echo "✓ PM2 可用"

# ── 定义模块 ──
declare -A MODULE_DIRS=(
    [m25]="25-用户策略生成系统"
    [m26]="26-策略管理模块"
    [m27]="27-策略治理审批系统"
    [m28]="28-策略信号触发模块"
)
declare -A MODULE_PORTS=(
    [m25]="8095"
    [m26]="8093"
    [m27]="8094"
    [m28]="8096"
)
MODULE_ORDER=(m26 m27 m28 m25)  # M25 依赖 M26，最后启动

# ── 部署每个模块 ──
for mod in "${MODULE_ORDER[@]}"; do
    dir="${MODULE_DIRS[$mod]}"
    port="${MODULE_PORTS[$mod]}"
    app_dir="${REPO_DIR}/${dir}"

    echo ""
    echo ">>> [${mod}] ${dir} (port ${port})"

    if [ ! -f "${app_dir}/app.py" ]; then
        echo "  ✗ ${app_dir}/app.py 不存在，跳过"
        continue
    fi

    # 停止旧进程
    pm2 delete "${mod}" 2>/dev/null || true

    # 启动
    pm2 start "${app_dir}/app.py" \
        --name "${mod}" \
        --interpreter "${PYTHON_BIN}" \
        --cwd "${app_dir}" \
        --exp-backoff-restart-delay=10 \
        2>&1 | tail -3

    echo "  ✓ ${mod} 已启动"
done

# ── 保存 PM2 状态 ──
echo ""
echo ">>> 保存 PM2 状态"
pm2 save 2>/dev/null || true

# ── 健康检查 ──
echo ""
echo ">>> 健康检查 (等待 5s 启动)"
sleep 5

ALL_OK=true
for mod in "${MODULE_ORDER[@]}"; do
    port="${MODULE_PORTS[$mod]}"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:${port}/health" 2>/dev/null || echo "000")
    if [ "${HTTP_CODE}" = "200" ]; then
        echo "  ✓ ${mod} (port ${port}): HTTP ${HTTP_CODE}"
    else
        echo "  ✗ ${mod} (port ${port}): HTTP ${HTTP_CODE}"
        ALL_OK=false
    fi
done

echo ""
pm2 list | grep -E "m2[5-8]|name" || true

echo ""
if [ "${ALL_OK}" = true ]; then
    echo "✓ 全部经典模块健康检查通过"
else
    echo "⚠ 部分模块未通过健康检查，请查看日志: pm2 logs <模块名>"
fi

echo ""
echo "============================================"
echo "  经典模块部署完成"
echo "============================================"
echo "  管理命令:"
echo "    pm2 list                    # 查看状态"
echo "    pm2 logs m25                # 查看 M25 日志"
echo "    pm2 restart m25             # 重启 M25"
echo "    pm2 restart m25 m26 m27 m28 # 重启全部"
echo "============================================"
