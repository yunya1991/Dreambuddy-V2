#!/bin/bash
# ============================================================================
# 推荐策略引擎: 环境配置脚本
# ============================================================================
# 用途: 配置 cron 调度和环境变量
# 运行: bash setup.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENGINE_SCRIPT="$SCRIPT_DIR/engine.py"
LOG_DIR="${WORKBUDDY_LOGS_DIR:-~/.workbuddy/logs}"
CRON_TAG="# === DreamBuddy 推荐策略引擎调度 ==="

echo "============================================"
echo "推荐策略引擎 - 环境配置"
echo "============================================"

# 1. 确保日志目录存在
mkdir -p "$LOG_DIR"
echo "✅ 日志目录: $LOG_DIR"

# 2. 确保引擎脚本可执行
chmod +x "$ENGINE_SCRIPT"
echo "✅ 引擎脚本已设为可执行"

# 3. 创建环境变量文件
ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" << 'EOF'
# 推荐策略引擎配置
# 请复制为 .env 并填写真实值

# 内部 API 地址（产物中台服务）
RECOMMENDATION_ENGINE_API_URL=http://localhost:3456/api/recommendation-engine/internal

# API 密钥（用于认证，防止未授权调用）
# 推荐策略: openssl rand -hex 32
RECOMMENDATION_ENGINE_API_KEY=

# 6-TRADING 路径（可选，默认自动查找）
# WORKBUDDY_6TRADING_DIR=/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-TRADING

# 研报 artifacts 路径（可选，默认 ~/.workbuddy/artifacts）
# WORKBUDDY_ARTIFACTS_ROOT=~/.workbuddy/artifacts
EOF
  echo "✅ 环境变量文件已创建: $ENV_FILE"
  echo "   ⚠️  请编辑 $ENV_FILE 填入 RECOMMENDATION_ENGINE_API_KEY"
else
  echo "✅ 环境变量文件已存在: $ENV_FILE"
fi

# 4. 添加 cron 调度
CRON_ENTRY="0 6 * * * cd \"$SCRIPT_DIR\" && /usr/bin/python3 \"$ENGINE_SCRIPT\" --auto >> \"$LOG_DIR/engine_\$(date +\%Y\%m).log\" 2>&1"

# 检查是否已有该 cron 条目
if crontab -l 2>/dev/null | grep -q "recommendation-engine/engine.py"; then
  echo "✅ Cron 调度已配置"
else
  # 追加到 crontab
  (crontab -l 2>/dev/null; echo ""; echo "$CRON_TAG"; echo "$CRON_ENTRY") | crontab -
  echo "✅ Cron 调度已添加（每天 06:00 运行）"
fi

echo ""
echo "============================================"
echo "配置完成!"
echo "============================================"
echo ""
echo "📋 配置摘要:"
echo "   引擎脚本: $ENGINE_SCRIPT"
echo "   日志目录: $LOG_DIR"
echo "   Cron: 每天 06:00 运行"
echo ""
echo "🚀 手动运行测试:"
echo "   cd \"$SCRIPT_DIR\" && python3 engine.py"
echo ""
echo "🔑 获取 API 密钥:"
echo "   openssl rand -hex 32"
echo ""
echo "🔧 查看日志:"
echo "   tail -f \"$LOG_DIR/engine_$(date +%Y%m).log\""
echo ""
