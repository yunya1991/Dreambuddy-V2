#!/bin/bash
# ============================================================
# M25 用户策略生成系统 — 一键依赖安装脚本
# 用法: bash install.sh
#
# 自动处理:
#   1. 系统依赖 (ta-lib C 库)
#   2. Python 依赖 (freqtrade/ta-lib/technical/ccxt/flask 等)
#   3. 安装验证
# ============================================================
set -e

M25_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REQ_FILE="${M25_DIR}/requirements.txt"

echo "============================================"
echo "  M25 依赖一键安装"
echo "  Python: ${PYTHON_BIN}"
echo "  目录:   ${M25_DIR}"
echo "============================================"
echo ""

# ── 1. 检测操作系统 ──
OS="$(uname -s)"
echo "[1/4] 检测系统: ${OS}"

# ── 2. 安装 ta-lib 系统库 ──
echo ""
echo "[2/4] 安装 ta-lib 系统库 (C library)"

install_talib_system() {
    case "${OS}" in
        Darwin)
            # macOS: 优先用 Homebrew
            if command -v brew &>/dev/null; then
                echo "  → Homebrew 安装 ta-lib"
                brew install ta-lib 2>/dev/null || echo "  (ta-lib 可能已安装)"
            else
                echo "  ⚠ 未检测到 Homebrew，跳过系统库安装"
                echo "    请手动安装: brew install ta-lib"
            fi
            ;;
        Linux)
            # Linux: 检测包管理器
            if command -v apt-get &>/dev/null; then
                echo "  → apt 安装编译工具 + ta-lib 源码编译"
                sudo apt-get update -qq
                sudo apt-get install -y -qq build-essential wget libtool autoconf automake pkg-config
                # 从源码编译 ta-lib (Ubuntu apt 的 libta-lib 版本较旧)
                if ! ldconfig -p 2>/dev/null | grep -q "libta_lib"; then
                    echo "  → 编译安装 ta-lib 0.4.0"
                    cd /tmp
                    wget -q https://github.com/ta-lib/ta-lib/releases/download/v0.4.0/ta-lib-0.4.0-src.tar.gz -O ta-lib-src.tar.gz
                    tar -xzf ta-lib-src.tar.gz
                    cd ta-lib-0.4.0
                    ./configure --prefix=/usr/local 2>/dev/null
                    make -j"$(nproc)" 2>/dev/null
                    sudo make install 2>/dev/null
                    sudo ldconfig 2>/dev/null || true
                    cd /tmp && rm -rf ta-lib-0.4.0 ta-lib-src.tar.gz
                else
                    echo "  ✓ libta_lib 已存在，跳过"
                fi
            elif command -v yum &>/dev/null; then
                echo "  → yum 安装编译工具"
                sudo yum install -y -q gcc gcc-c++ make wget libtool autoconf automake
                if ! ldconfig -p 2>/dev/null | grep -q "libta_lib"; then
                    echo "  → 编译安装 ta-lib 0.4.0"
                    cd /tmp
                    wget -q https://github.com/ta-lib/ta-lib/releases/download/v0.4.0/ta-lib-0.4.0-src.tar.gz -O ta-lib-src.tar.gz
                    tar -xzf ta-lib-src.tar.gz
                    cd ta-lib-0.4.0
                    ./configure --prefix=/usr/local 2>/dev/null
                    make -j"$(nproc)" 2>/dev/null
                    sudo make install 2>/dev/null
                    sudo ldconfig 2>/dev/null || true
                    cd /tmp && rm -rf ta-lib-0.4.0 ta-lib-src.tar.gz
                else
                    echo "  ✓ libta_lib 已存在，跳过"
                fi
            else
                echo "  ⚠ 未识别的包管理器，请手动安装 ta-lib 系统库"
            fi
            ;;
        *)
            echo "  ⚠ 不支持的系统: ${OS}"
            ;;
    esac
}

# 检查是否已有 ta-lib Python 包可用（可能通过 conda 已安装）
if "${PYTHON_BIN}" -c "import talib" &>/dev/null; then
    echo "  ✓ ta-lib Python 包已存在，跳过系统库安装"
else
    install_talib_system
fi

# ── 3. 安装 Python 依赖 ──
echo ""
echo "[3/4] 安装 Python 依赖"

cd "${M25_DIR}"

# 升级 pip
"${PYTHON_BIN}" -m pip install --upgrade pip 2>/dev/null || true

# 安装依赖
if [ -f "${REQ_FILE}" ]; then
    echo "  → pip install -r requirements.txt"
    "${PYTHON_BIN}" -m pip install -r "${REQ_FILE}"
else
    echo "  ✗ requirements.txt 不存在: ${REQ_FILE}"
    exit 1
fi

# ── 4. 验证安装 ──
echo ""
echo "[4/4] 验证安装"

PASS=0
FAIL=0

check_dep() {
    local pkg="$1"
    if "${PYTHON_BIN}" -c "import ${pkg}" &>/dev/null; then
        local ver
        ver="$("${PYTHON_BIN}" -c "import ${pkg}; print(getattr(${pkg}, '__version__', '?'))" 2>/dev/null || echo "?")"
        printf "  ✓ %-12s %s\n" "${pkg}" "${ver}"
        PASS=$((PASS + 1))
    else
        printf "  ✗ %-12s 导入失败\n" "${pkg}"
        FAIL=$((FAIL + 1))
    fi
}

check_dep "flask"
check_dep "numpy"
check_dep "pandas"
check_dep "freqtrade"
check_dep "talib"
check_dep "technical"
check_dep "ccxt"

# 验证 M25 模块可导入
echo ""
if "${PYTHON_BIN}" -c "
import sys
sys.path.insert(0, '${M25_DIR}')
from strategy_gen.backtest_engine import run_backtest
from strategy_gen.baseline import baseline_list
from strategy_gen.intent import generate_from_intent
print('M25 strategy_gen 导入成功')
" 2>/dev/null; then
    echo "  ✓ M25 模块导入正常"
    PASS=$((PASS + 1))
else
    echo "  ✗ M25 模块导入失败"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "============================================"
if [ "${FAIL}" -eq 0 ]; then
    echo "  ✓ 全部依赖安装成功 (${PASS} 通过)"
    echo ""
    echo "  启动 M25:"
    echo "    cd ${M25_DIR} && ${PYTHON_BIN} app.py"
    echo "  健康检查:"
    echo "    curl http://127.0.0.1:8095/health"
else
    echo "  ⚠ ${FAIL} 项失败，请检查上方日志"
fi
echo "============================================"
