#!/bin/bash
# 移动止盈调度器 — launchd / systemd 通用入口
# 本地：com.dreambuddy.trailing-stop-runner (launchd) 常驻 --real
# 云端：trailing-stop-runner.service (systemd) 常驻 --real
#
# 用法:
#   bash scripts/run_trailing_stop_runner.sh                    # 常驻实盘（默认 300s）
#   bash scripts/run_trailing_stop_runner.sh --once --dry-run   # 单次冒烟（不下单）
#   TRAILING_INTERVAL=180 bash scripts/run_trailing_stop_runner.sh
#
# 环境变量（均可由调用方注入）:
#   PYTHON_BIN          指定解释器（默认 command -v python3）
#   TRAILING_INTERVAL   常驻模式轮询间隔秒数（默认 300）
#   EXIT_MODE           执行模式（默认 real）
set -e

# 脚本位于 <repo>/16-调控系统/scripts/，据此推导工程目录（去硬编码）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTRL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${CTRL_DIR}/.." && pwd)"

cd "${CTRL_DIR}"

export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# 加载 OKX 凭据（real 模式必需）；文件不存在时静默跳过
ENV_FILE="${REPO_ROOT}/14-V15经典马丁策略/config/.env.local"
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}" || true
    set +a
fi

# 核心模块 + 执行器依赖的 V15 lib（okx_client）
export PYTHONPATH="${CTRL_DIR}/core:${CTRL_DIR}/scripts:${REPO_ROOT}/14-V15经典马丁策略/lib${PYTHONPATH:+:${PYTHONPATH}}"
export EXIT_MODE="${EXIT_MODE:-real}"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
if [ -z "${PYTHON_BIN}" ]; then
    echo "ERROR: python3 not found (set PYTHON_BIN or PATH)" >&2
    exit 1
fi

# 无参 → 常驻实盘；有参 → 原样透传（支持 --once --dry-run 冒烟）
if [ "$#" -gt 0 ]; then
    ARGS=("$@")
else
    ARGS=(--real --interval "${TRAILING_INTERVAL:-300}")
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/trailing_stop_runner.py" "${ARGS[@]}"
