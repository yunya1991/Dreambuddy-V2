#!/usr/bin/env bash
# ============================================================
#  dream-product-hub · 一键部署启动脚本
# ------------------------------------------------------------
#  用途：
#    1) 安装 npm 依赖（如 node_modules 缺失）
#    2) 兜底创建 .env（未设置 DATABASE_URL 时）
#    3) prisma generate + 校验 admin_operation_logs 表存在（缺表直接失败）
#    4) 清理 .next 缓存，避免历史 chunk 与 runtime 不一致
#    5) 生产模式 next build，通过 PM2（ecosystem.config.js，instances=1）
#       拉起 next start
#    6) 等待服务就绪并对核心页面做 HTTP 冒烟验证
#
#  用法：
#    cd "$(dirname "$0")"
#    bash deploy.sh
#    # 或只做部分步骤：
#    bash deploy.sh --skip-install   # 跳过依赖安装
#
#  环境变量（可选项）：
#    PM2_APP_NAME   进程名，默认：product-hub
#    PORT           监听端口，默认：3456
#    DATABASE_URL   Prisma 数据源（必填，postgresql://）
#
#  硬约束（SPEC-7 §12.3）：
#    - 不再支持开发模式（dev server 常驻 300-800MB，云端不可接受）
#    - 不再执行数据库结构推送（库存在 drift，DDL 只能由云端 DBA 执行）
# ============================================================
set -euo pipefail

# --------- 基础配置 ---------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

PM2_APP_NAME="${PM2_APP_NAME:-product-hub}"
PORT="${PORT:-3456}"
DEFAULT_DATABASE_URL=""

SKIP_INSTALL=0
for arg in "$@"; do
  case "${arg}" in
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help)
      sed -n '2,32p' "$0"
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
INFO "端口：${PORT} | PM2 进程：${PM2_APP_NAME} | 实例数：1（强制）"

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

# --------- 2) .env 检查（不再自动生成，避免写入错误的数据库地址）---------
if [[ ! -f .env ]] || ! grep -qE '^DATABASE_URL=' .env 2>/dev/null; then
  FAIL ".env 缺少 DATABASE_URL；请先按 docs/SPEC-7 手动配置（云端需同时配置 ADMIN_AUTH_SECRET 等）"
fi
OK ".env 已存在且包含 DATABASE_URL"

# --------- 3) Prisma：只 generate + 校验表存在（禁止 db push）---------
if [[ ! -d prisma || ! -f prisma/schema.prisma ]]; then
  FAIL "未发现 prisma/schema.prisma"
fi
INFO "执行 prisma generate（不触碰数据库结构）……"
npx --yes prisma generate 2>&1 | tail -n 5 || FAIL "prisma generate 失败"

INFO "校验 admin_operation_logs 表是否存在（DDL 由云端 DBA 执行）……"
node -e '
const { PrismaClient } = require("@prisma/client");
const p = new PrismaClient({ log: [] });
p.$queryRawUnsafe("SELECT to_regclass($1) AS t", "public.admin_operation_logs")
  .then((rows) => {
    if (!rows || !rows[0] || !rows[0].t) {
      console.error("[FAIL] 缺少 admin_operation_logs 表：请由云端 DBA 执行 prisma/ddl/20261115_admin_operation_logs.sql");
      process.exit(1);
    }
    console.log("[OK] admin_operation_logs 已就绪");
  })
  .catch((e) => {
    console.error("[FAIL] 数据库不可用：" + e.message);
    process.exit(1);
  })
  .finally(() => p.$disconnect());
' || FAIL "数据库表校验失败"
OK "Prisma 就绪"

# --------- 4) 清理 .next 缓存 ---------
if [[ -d .next ]]; then
  INFO "清理 .next 缓存，避免历史 chunk 与 runtime 不一致……"
  rm -rf .next
  OK ".next 已清理"
fi

# --------- 5) PM2 拉起服务（生产模式，instances=1）---------
INFO "停止旧的 PM2 进程（如存在）……"
pm2 delete "${PM2_APP_NAME}" >/dev/null 2>&1 || true

INFO "执行 next build……"
npm run build --loglevel=error || FAIL "next build 失败"

INFO "PM2 启动：ecosystem.config.js（instances=1 / max_memory_restart=600M）"
PM2_APP_NAME="${PM2_APP_NAME}" PORT="${PORT}" pm2 start ecosystem.config.js \
  || FAIL "pm2 start 失败"

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

smoke() {
  local path="$1" min="$2" max="$3"
  TOTAL=$((TOTAL+1))
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}${path}" 2>/dev/null || true)
  if [[ "${code}" -ge "${min}" && "${code}" -le "${max}" ]]; then
    printf "  \033[1;32m✓\033[0m  %-32s HTTP %s\n" "${path}" "${code}"
    PASS=$((PASS+1))
  else
    printf "  \033[1;31m✗\033[0m  %-32s HTTP %s（期望 %s-%s）\n" "${path}" "${code}" "${min}" "${max}"
  fi
}

# 只读页
smoke /ui-map 200 299
smoke /recommendation-engine/library 200 299
# 管理台：未登录必须重定向到登录页（middleware 生效）
smoke /admin 300 399
smoke /admin/login 200 299
# 管理台 API：未登录必须 401（跨应用隔离）
smoke /api/admin/users 401 401

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
