#!/bin/bash
# 44304 → 6-TRADING 同步脚本
# 用途: 将44304内部系统的核心代码同步到6-TRADING对外服务系统
# 来源: /Users/zhangjiangtao/WorkBuddy/20260415144304
# 目标: /Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING

SOURCE="/Users/zhangjiangtao/WorkBuddy/20260415144304"
TARGET="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/6-TRADING"

echo "=== 44304 → 6-TRADING 同步脚本 ==="
echo "来源: $SOURCE"
echo "目标: $TARGET"
echo ""

# 1. A系列核心脚本
echo "[1/6] 同步A系列核心脚本..."
rsync -av --include='a1_*.py' \
      --include='a2_*.py' \
      --include='a4_validation_executor.py' \
      --include='a5_guards.py' \
      --include='dream_trade_exec.py' \
      --include='dream_strategy_pipeline.py' \
      --include='master_strategy_retriever.py' \
      --include='dream_stop_loss_monitor.py' \
      --include='okx_cli.py' \
      --include='okx_unified_toolkit.py' \
      --exclude='*' \
      "$SOURCE/scripts/" "$TARGET/scripts/"

# 2. SKILL模块
echo "[2/6] 同步SKILL模块..."
rsync -av "$SOURCE/1-TRADE/" "$TARGET/skills/"
rsync -av "$SOURCE/2-INTELLIGENCE/" "$TARGET/skills/"

# 3. 配置文件
echo "[3/6] 同步配置文件..."
rsync -av "$SOURCE/strategy_library.yaml" "$TARGET/config/"
rsync -av "$SOURCE/config/" "$TARGET/config_44304/"

# 4. 自动化脚本
echo "[4/6] 同步自动化脚本..."
rsync -av "$SOURCE/automation_prompts/" "$TARGET/automation/"

# 5. Episodes数据
echo "[5/6] 同步Episodes数据..."
rsync -av "$SOURCE/episodes/" "$TARGET/data/episodes/"

# 6. Reports样本
echo "[6/6] 同步Reports样本..."
rsync -av --include='*.md' --exclude='archive/*' \
      "$SOURCE/reports/" "$TARGET/data/reports/"

echo ""
echo "=== 同步完成 ==="
echo "注意: config_44304/ 目录包含原始44304配置，仅供参照"
