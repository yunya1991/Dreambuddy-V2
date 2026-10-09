#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 数据层部署
# PostgreSQL + Redis + MinIO (Docker Compose)
# 用法: bash 02-deploy-data.sh
# 前置: 01-cloud-init.sh 已完成, .env.cloud 已配置
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
COMPOSE_FILE="${REPO_DIR}/31-分布式计算部署/phase1/docker-compose.yml"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

echo "============================================"
echo "  Phase 1 — 数据层部署 (PG + Redis + MinIO)"
echo "============================================"

# ── 检查 .env.cloud ──
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} 不存在"
    echo "请先复制并填写:"
    echo "  cp ${REPO_DIR}/31-分布式计算部署/phase1/.env.cloud.example ${ENV_FILE}"
    echo "  vim ${ENV_FILE}  # 填写 POSTGRES_PASSWORD, MINIO_PASSWORD 等"
    exit 1
fi
echo "✓ .env.cloud found"

# ── 启动数据层 ──
echo ">>> 启动 Docker Compose..."
cd "$(dirname "$0")"

# 导入环境变量
set -a
source "${ENV_FILE}"
set +a

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d

echo ""
echo ">>> 等待容器健康检查..."
sleep 10

# ── 验证 ──
echo ""
echo ">>> 容器状态:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "dreambuddy|NAMES"

# PostgreSQL 连通性
if docker exec dreambuddy-pg pg_isready -U "${POSTGRES_USER:-dreambuddy}" &>/dev/null; then
    echo "✓ PostgreSQL ready"
else
    echo "⚠ PostgreSQL not ready yet, check logs: docker logs dreambuddy-pg"
fi

# Redis 连通性
if docker exec dreambuddy-redis redis-cli ping &>/dev/null; then
    echo "✓ Redis ready: $(docker exec dreambuddy-redis redis-cli ping)"
else
    echo "⚠ Redis not ready, check logs: docker logs dreambuddy-redis"
fi

# MinIO 连通性
if curl -s http://127.0.0.1:9000/minio/health/live &>/dev/null; then
    echo "✓ MinIO ready"
else
    echo "⚠ MinIO not ready yet, check logs: docker logs dreambuddy-minio"
fi

# ── MinIO 初始化 bucket ──
echo ""
echo ">>> 创建 MinIO buckets..."
docker exec dreambuddy-minio mc alias set local http://127.0.0.1:9000 \
    "${MINIO_ROOT_USER:-dreambuddy}" "${MINIO_ROOT_PASSWORD:-change_me_in_production}" 2>/dev/null || true

for bucket in models backtest-results data-cache; do
    docker exec dreambuddy-minio mc mb "local/${bucket}" 2>/dev/null || \
        echo "  ${bucket} already exists"
    docker exec dreambuddy-minio mc anonymous set download "local/${bucket}" 2>/dev/null || true
done
echo "✓ MinIO buckets: models, backtest-results, data-cache"

# ── 前端数据库初始化 ──
echo ""
echo ">>> 初始化前端数据库表 (Prisma)..."
# 注: 实际 migrate 在 03-deploy-frontend.sh 中执行, 此处仅确认 DB 可连接
echo "  PostgreSQL DB: ${POSTGRES_DB:-dreambuddy}"
echo "  (Prisma migrate 将在 03-deploy-frontend.sh 中执行)"

echo ""
echo "============================================"
echo "  数据层部署完成"
echo "============================================"
echo "  PostgreSQL:  127.0.0.1:5432  (DB: ${POSTGRES_DB:-dreambuddy})"
echo "  Redis:       127.0.0.1:6379"
echo "  MinIO S3:    127.0.0.1:9000"
echo "  MinIO Console: 127.0.0.1:9001"
echo ""
echo "  下一步: bash 03-deploy-frontend.sh"
echo "============================================"
