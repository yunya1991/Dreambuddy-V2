#!/bin/bash
# 前端同步脚本 - 6-TRADING 与 3-FRONTEND 同步
# 用途: 将 dream-universal-gateway 前端同步到 6-TRADING
# 来源: ../3-FRONTEND/dream-universal-gateway/
# 目标: ./frontend/

SOURCE="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/3-FRONTEND/dream-universal-gateway"
TARGET="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING/frontend"

echo "=== 3-FRONTEND → 6-TRADING 前端同步 ==="
echo "来源: $SOURCE"
echo "目标: $TARGET"
echo ""

# 检查来源目录
if [ ! -d "$SOURCE" ]; then
    echo "❌ 错误: 来源目录不存在: $SOURCE"
    exit 1
fi

# 创建目标目录
mkdir -p "$TARGET"

# 同步文件
echo "[1/2] 同步前端文件..."
rsync -av --exclude='node_modules' \
          --exclude='.next' \
          --exclude='.git' \
          --exclude='dist' \
          "$SOURCE/" "$TARGET/"

echo ""
echo "[2/2] 创建符号链接 (可选)..."
# 可选: 创建符号链接到3-FRONTEND，方便开发时同步
# ln -sf "$SOURCE" "$TARGET/link_to_3front"

echo ""
echo "=== 同步完成 ==="
echo "前端目录: $TARGET"
echo ""
echo "启动前端:"
echo "  cd $TARGET && pnpm dev"
echo ""
echo "或使用完整路径:"
echo "  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/3-FRONTEND/dream-universal-gateway && pnpm dev"
