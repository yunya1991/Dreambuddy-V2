#!/bin/bash
# ============================================================
# Hermes 一键还原/部署脚本
# 用法:
#   本机还原:  bash hermes-restore.sh
#   远程部署:  scp hermes-deploy-bundle.tar.gz hermes-config-snapshot.tar.gz hermes-restore.sh user@host:~/
#              ssh user@host "bash hermes-restore.sh"
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_BUNDLE="$SCRIPT_DIR/hermes-deploy-bundle.tar.gz"
CONFIG_SNAPSHOT="$SCRIPT_DIR/hermes-config-snapshot.tar.gz"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_VENV="$HERMES_HOME/.venv"
HERMES_BIN="$HERMES_VENV/bin/hermes"

echo "============================================"
echo "  Hermes 一键还原/部署"
echo "  HERMES_HOME: $HERMES_HOME"
echo "============================================"
echo ""

# ── Step 1: 检查压缩包 ──
echo ">>> Step 1/5: 检查压缩包"
if [ ! -f "$DEPLOY_BUNDLE" ]; then
    echo "  ✗ 缺少 $DEPLOY_BUNDLE"
    exit 1
fi
if [ ! -f "$CONFIG_SNAPSHOT" ]; then
    echo "  ✗ 缺少 $CONFIG_SNAPSHOT"
    exit 1
fi
echo "  ✓ deploy bundle:   $(du -h "$DEPLOY_BUNDLE" | cut -f1)"
echo "  ✓ config snapshot: $(du -h "$CONFIG_SNAPSHOT" | cut -f1)"

# ── Step 2: 解压 deploy/ ──
echo ""
echo ">>> Step 2/5: 解压 deploy/ 到 $SCRIPT_DIR"
tar -xzf "$DEPLOY_BUNDLE" -C "$SCRIPT_DIR"
echo "  ✓ deploy/ 已还原"

# ── Step 3: 还原 hermes 配置 ──
echo ""
echo ">>> Step 3/5: 还原 hermes 配置到 $HERMES_HOME"
mkdir -p "$HERMES_HOME"
cd "$HOME"
tar -xzf "$CONFIG_SNAPSHOT"
echo "  ✓ 配置已还原"

# ── Step 4: 检查/安装 hermes 本体 ──
echo ""
echo ">>> Step 4/5: 检查 Hermes 本体"
if [ -f "$HERMES_BIN" ]; then
    echo "  ✓ hermes 已安装: $HERMES_BIN"
else
    echo "  ⚠ hermes 未安装，开始安装..."
    if ! command -v pip3 &>/dev/null; then
        echo "  ✗ 需要 python3 和 pip3"
        exit 1
    fi
    python3 -m venv "$HERMES_VENV"
    "$HERMES_VENV/bin/pip" install --upgrade pip
    "$HERMES_VENV/bin/pip" install hermes-cli
    echo "  ✓ hermes-cli 已安装到 $HERMES_VENV"
fi

# ── Step 5: 安装 sitecustomize.py (TLS补丁) ──
echo ""
echo ">>> Step 5/5: 安装 TLS 补丁"
SITECUSTOMIZE_SRC="$SCRIPT_DIR/deploy/hermes/sitecustomize.py"
PYTHON_VERSION=$("$HERMES_VENV/bin/python" -c "import sys; print(f'python{sys.version_info.major}.{sys.version_info.minor}')")
SITE_PACKAGES="$HERMES_VENV/lib/$PYTHON_VERSION/site-packages"
if [ -f "$SITECUSTOMIZE_SRC" ]; then
    cp "$SITECUSTOMIZE_SRC" "$SITE_PACKAGES/sitecustomize.py"
    echo "  ✓ sitecustomize.py → $SITE_PACKAGES"
else
    echo "  ⚠ sitecustomize.py 不存在，跳过（可能影响 macOS TLS）"
fi

# ── 完成 ──
echo ""
echo "============================================"
echo "  ✅ 还原完成！"
echo "============================================"
echo ""
echo "配置文件:"
echo "  config.yaml:          $([ -f $HERMES_HOME/config.yaml ] && echo '✓' || echo '✗')"
echo "  .env:                 $([ -f $HERMES_HOME/.env ] && echo '✓' || echo '✗')"
echo "  auth.json:            $([ -f $HERMES_HOME/auth.json ] && echo '✓' || echo '✗')"
echo "  SOUL.md:              $([ -f $HERMES_HOME/SOUL.md ] && echo '✓' || echo '✗')"
echo "  skills:               $(find $HERMES_HOME/skills -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ') 个"
echo "  cron jobs:            $([ -f $HERMES_HOME/cron/jobs.json ] && echo '✓' || echo '✗')"
echo ""
echo "启动服务:"
echo "  Gateway:   $HERMES_VENV/bin/python -m hermes_cli.main gateway start"
echo "  Dashboard: $HERMES_VENV/bin/python -m hermes_cli.main dashboard"
echo ""
echo "macOS launchd 一键安装:"
echo "  python3 $SCRIPT_DIR/deploy/ops/launchd_manage.py install"
echo ""
echo "Linux systemd 部署:"
echo "  cd $SCRIPT_DIR/deploy && sudo bash deploy.sh"
