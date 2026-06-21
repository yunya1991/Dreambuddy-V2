#!/usr/bin/env bash
# ============================================================
#  dream-product-hub · 一键部署启动脚本
# ------------------------------------------------------------
#  用途：
#    1) 安装 npm 依赖（如 node_modules 缺失）
#    2) 兜底创建 .env（未设置 DATABASE_URL 时）
#    3) 初始化 Prisma / SQLite（schema 未应用时自动 push）
#    4) 清理 .next 缓存，避免历史 chunk 与 runtime 不一致
#    5) 通过 PM2 拉起 next dev（如已运行则先停止再启动）
#    6) 等待服务就绪并对核心页面做 HTTP 冒烟验证
#
#  用法：
#    cd "$(dirname "$0")"
#    bash deploy.sh
#    # 或只做部分步骤：
#    bash deploy.sh --skip-install   # 跳过 npm ci
#    bash deploy.sh --mode build     # 生产模式：npm run build + start
#
#  环境变量（可选项）：
#    PM2_APP_NAME   进程名，默认：product-hub
#    PORT           监听端口，默认：3456
#    DATABASE_URL   Prisma 数据源，默认：file:./prisma/dev.db
#    MODE           dev | build，默认：dev
# ============================================================
set -euo pipefail

# --------- 基础配置 ---------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

PM2_APP_NAME="${PM2_APP_NAME:-product-hub}"
PORT="${PORT:-3456}"
DEFAULT_DATABASE_URL="file:./prisma/dev.db"
MODE="${MODE:-dev}"

SKIP_INSTALL=0
for arg in "$@"; do
  case "${arg}" in
    --skip-install) SKIP_INSTALL=1 ;;
    --mode=*)       MODE="${arg#*=}" ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
  esac
done

# --------- 日志工具 ---------
INFO()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
OK()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
WARN()  { printf "\033[1;33m[WARN]\033[0m  %s\n" "$*"; }
FAIL()  { printf "\033[1;31m[FAIL]\033[0m  %s\n" "$*" >&2; exit 1; }

# --------- 环境检查 ---------
INFO "工作目录：${SCRIPT_DIR}"
INFO "模式：${MODE} | 端口：${PORT} | PM2 进程：${PM2_APP_NAME}"

command -v node >/dev/null 2>&1 || FAIL "node 未安装"
command -v npm  >/dev/null 2>&1 || FAIL "npm 未安装"
command -v pm2  >/dev/null 2>&1 || FAIL "pm2 未安装（npm i -g pm2）"

NODE_V="$(node -v | sed 's/^v//')"
INFO "Node 版本：node ${NODE_V} / npm $(npm -v)"

# --------- 1) 依赖安装 ---------
if [[ "${SKIP_INSTALL}" -eq 1 ]]; then
  WARN "已跳过 npm 依赖安装（--skip-install）"
elif [[ -d node_modules && -f package-lock.json ]]; then
  INFO "检测到 node_modules，按需重新安装缺失依赖……"
  npm install --no-audit --no-fund --loglevel=error || WARN "npm install 非零退出，尝试继续"
else
  INFO "首次安装依赖……"
  npm install --no-audit --no-fund --loglevel=error || FAIL "npm install 失败"
fi
OK "依赖就绪"

# --------- 2) .env 兜底 ---------
ENV_NEEDS_WRITE=0
if [[ ! -f .env ]]; then
  ENV_NEEDS_WRITE=1
elif ! grep -qE '^DATABASE_URL=' .env 2>/dev/null; then
  ENV_NEEDS_WRITE=1
fi
if [[ "${ENV_NEEDS_WRITE}" -eq 1 ]]; then
  INFO "写入 .env：DATABASE_URL=${DEFAULT_DATABASE_URL}"
  cat > .env <<-EOF
	# 由 deploy.sh 自动创建 · Prisma SQLite 数据库（相对于 prisma/schema.prisma）
	DATABASE_URL="${DATABASE_URL:-${DEFAULT_DATABASE_URL}}"
	EOF
  OK ".env 已创建"
else
  OK ".env 已存在且包含 DATABASE_URL"
fi

# --------- 3) Prisma 初始化 ---------
if [[ ! -d prisma || ! -f prisma/schema.prisma ]]; then
  WARN "未发现 prisma/schema.prisma，跳过 Prisma 初始化"
else
  DB_PATH_RAW="$(grep -E '^\s*DATABASE_URL=' .env | head -1 | sed -E 's/^[^=]+=//' | tr -d '"' | tr -d "'")"
  # 把 file:./xxx 转成绝对路径，便于提示
  case "${DB_PATH_RAW}" in
    file:*) DB_REL="${DB_PATH_RAW#file:}" ;;
    *)      DB_REL="${DB_PATH_RAW}" ;;
  esac
  DB_ABS="$(cd prisma && cd "$(dirname "${DB_REL}")" && pwd)/$(basename "${DB_REL}")"
  INFO "数据库目标：${DB_ABS}"

  if [[ ! -f "${DB_ABS}" ]]; then
    INFO "数据库文件不存在，执行 prisma db push 创建表……"
    npx --yes prisma db push --skip-generate 2>&1 | tail -n 10 || FAIL "prisma db push 失败"
  else
    INFO "数据库已存在，调用 prisma generate 确保客户端可用……"
    npx --yes prisma generate 2>&1 | tail -n 5 || true
  fi
  OK "Prisma 就绪"
fi

# --------- 4) 清理 .next 缓存 ---------
if [[ -d .next ]]; then
  INFO "清理 .next 缓存，避免历史 chunk 与 runtime 不一致……"
  rm -rf .next
  OK ".next 已清理"
fi

# --------- 5) PM2 拉起服务 ---------
# 确保 PM2 当前有正确的 cwd；先停止/删除同名进程再新建
INFO "停止旧的 PM2 进程（如存在）……"
pm2 delete "${PM2_APP_NAME}" >/dev/null 2>&1 || true

if [[ "${MODE}" == "build" ]]; then
  INFO "生产模式：执行 next build……"
  npm run build --loglevel=error || FAIL "next build 失败"
  INFO "PM2 启动：npm run start -p ${PORT}"
  pm2 start npm --name "${PM2_APP_NAME}" --cwd "${SCRIPT_DIR}" -- run start -- -p "${PORT}" \
    || FAIL "pm2 start 失败"
else
  INFO "PM2 启动：npm run dev -p ${PORT}"
  pm2 start npm --name "${PM2_APP_NAME}" --cwd "${SCRIPT_DIR}" -- run dev -- -p "${PORT}" \
    || FAIL "pm2 start 失败"
fi

pm2 save >/dev/null 2>&1 || true
OK "服务已通过 PM2 拉起"

# --------- 6) 等待服务就绪 + HTTP 冒烟 ---------
INFO "等待服务就绪（最长 60 秒）……"
READY=0
for i in $(seq 1 60); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/ui-map" 2>/dev/null || true)
  if [[ "${CODE}" == "200" ]]; then
    READY=1
    break
  fi
  sleep 1
done
if [[ "${READY}" -ne 1 ]]; then
  FAIL "服务未在 60 秒内就绪；查看日志：pm2 logs ${PM2_APP_NAME} --lines 80 --nostream"
fi
OK "服务就绪（http://127.0.0.1:${PORT}/ui-map → HTTP 200）"

INFO "开始 HTTP 冒烟验证……"
PASS=0
TOTAL=0
for path in /ui-map /admin / "/recommendation-engine/library"; do
  TOTAL=$((TOTAL+1))
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}${path}" 2>/dev/null || true)
  # / 根路径期望是 3xx 重定向；其他期望 2xx
  case "${path}" in
    /) EXPECT_MIN=300; EXPECT_MAX=399 ;;
    *) EXPECT_MIN=200; EXPECT_MAX=299 ;;
  esac
  if [[ "${CODE}" -ge "${EXPECT_MIN}" && "${CODE}" -le "${EXPECT_MAX}" ]]; then
    printf "  \033[1;32m✓\033[0m  %-30s  HTTP %s\n" "${path}" "${CODE}"
    PASS=$((PASS+1))
  else
    printf "  \033[1;33m?\033[0m  %-30s  HTTP %s（可能正常，需人工确认）\n" "${path}" "${CODE}"
  fi
done

echo ""
echo "============================================================"
echo " 部署完成：${PASS}/${TOTAL} 个页面通过冒烟验证"
echo " 访问地址：http://127.0.0.1:${PORT}/ui-map"
echo " 常用命令："
echo "   pm2 logs ${PM2_APP_NAME} --lines 100  # 查看日志"
echo "   pm2 status                           # 查看进程"
echo "   pm2 restart ${PM2_APP_NAME}          # 重启"
echo "   pm2 delete ${PM2_APP_NAME}           # 停止并删除"
echo "============================================================"
