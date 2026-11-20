#!/usr/bin/env bash
# 安装 dreambuddy 别名：终端里 `dreambuddy` 与 `/dreambuddy` 均可唤醒 59 域统一 CLI
set -euo pipefail

CLI="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/59-通用组件管理/tools/dreambuddy.py"
ZSHRC="$HOME/.zshrc"

touch "$ZSHRC"

if ! grep -qF "alias dreambuddy=" "$ZSHRC"; then
  printf "\nalias dreambuddy='python3 %s'\n" "$CLI" >> "$ZSHRC"
  echo "已添加：alias dreambuddy"
else
  echo "已存在：alias dreambuddy（跳过）"
fi

if ! grep -qF "/dreambuddy=" "$ZSHRC"; then
  printf "alias '/dreambuddy=python3 %s'\n" "$CLI" >> "$ZSHRC"
  echo "已添加：alias /dreambuddy"
else
  echo "已存在：alias /dreambuddy（跳过）"
fi

echo
echo "执行 source ~/.zshrc 或重开终端，然后：dreambuddy ls"
