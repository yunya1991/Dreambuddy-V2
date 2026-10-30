#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 10: 云端补齐 etl-worker（7-产物中台 L1 可观测性 ETL）
# 用法: sudo bash 10-deploy-etl-worker.sh
# 前置: 仓库已 git pull 到最新（含 phase10/observability_tables.sql）
# 说明:
#   1) 建 events/ 数据源目录(dreamos/dsh/frontend/hub) —— 远端 dreamos-scheduler 的
#      event_writer 默认写入(路径 parents[3]/events = /home/luke/dreambuddy/events)
#   2) venv 补 psycopg2-binary（wheel，免编译）
#   3) 幂等建 observability 三表（docker exec dreambuddy-pg，不用 prisma migrate）
#   4) 新增 etl-worker.service（systemd, User=luke, --daemon --interval 60）
#   5) product-hub 加 drop-in: WORKBUDDY_EVENTS_ROOT 对齐（JSONL fallback 路径一致）
# 注: etl_worker.py 读的是环境变量 EVENTS_ROOT（非 WORKBUDDY_EVENTS_ROOT），故二者都设。
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
PY="${DEPLOY_HOME}/venv-trading/bin/python"
PIP="${DEPLOY_HOME}/venv-trading/bin/pip"
ETL_DIR="${REPO_DIR}/7-产物中台/系统研究索引体系/prisma/scripts"
ETL_SCRIPT="${ETL_DIR}/etl_worker.py"
SQL_FILE="${REPO_DIR}/31-分布式计算部署/phase10/observability_tables.sql"
EVENTS_ROOT="${REPO_DIR}/events"
LOG_DIR="${DEPLOY_HOME}/logs/etl-worker"
PG_CONTAINER="dreambuddy-pg"
DB_URL="${ETL_DATABASE_URL:?ETL_DATABASE_URL env required (see /etc/dreambuddy-pg.env)}"
# 注意: etl_worker.py 用 psycopg2, 不接受 Prisma 专有的 ?schema=public 查询参数
#       (---> "invalid URI query parameter: schema"), 故此处为纯 DSN。

echo "============================================"
echo "  Phase 10 — 云端补齐 etl-worker"
echo "============================================"

# 0. 校验
for p in "${ETL_SCRIPT}" "${SQL_FILE}" "${PY}" "${PIP}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done
if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] 未找到 docker —— 无法建表"
    exit 1
fi

# 1. events/ 数据源目录
echo ">>> [1/6] 建 events/ 数据源目录"
mkdir -p "${EVENTS_ROOT}"/{dreamos,dsh,frontend,hub}
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${EVENTS_ROOT}"
ls -la "${EVENTS_ROOT}"

# 2. venv 补 psycopg2-binary
echo ">>> [2/6] venv 补 psycopg2-binary"
if "${PY}" -c "import psycopg2" >/dev/null 2>&1; then
    echo "    psycopg2 已存在，跳过"
else
    "${PIP}" install -q psycopg2-binary
    "${PY}" -c "import psycopg2; print('    psycopg2', psycopg2.__version__)"
fi

# 3. 幂等建 observability 三表
echo ">>> [3/6] 幂等建 observability 三表"
docker exec -i "${PG_CONTAINER}" psql -U dreambuddy -d dreambuddy -v ON_ERROR_STOP=1 < "${SQL_FILE}"
echo "    --- 表清单校验 ---"
docker exec "${PG_CONTAINER}" psql -U dreambuddy -d dreambuddy -tAc \
    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('dreamos_sessions','dreamos_spans','dsh_subagent_calls') ORDER BY tablename;"

# 3.5 冒烟测试（单次 ETL，验证 DATABASE_URL/psycopg2/建表三件套连通）
#    硬约束（phase9 同源约定）：禁止未经冒烟直接 enable 常驻单元
echo ">>> [4/6] 冒烟测试：单次 ETL（--date \$(date +%F)）"
EVENTS_ROOT="${EVENTS_ROOT}" DATABASE_URL="${DB_URL}" \
    "${PY}" "${ETL_SCRIPT}" --date "$(date +%F)"
echo "    冒烟通过（空 events 亦应输出 'Skipping .../ETL complete' 且无异常）"

# 4. 写 etl-worker.service
echo ">>> [5/6] 写 etl-worker.service"
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"
cat > /etc/systemd/system/etl-worker.service <<EOF
[Unit]
Description=Dreambuddy 7-product-hub L1 observability ETL worker (JSONL -> PostgreSQL)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${ETL_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="EVENTS_ROOT=${EVENTS_ROOT}"
Environment="WORKBUDDY_EVENTS_ROOT=${EVENTS_ROOT}"
Environment="DATABASE_URL=${DB_URL}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=${PY} ${ETL_SCRIPT} --daemon --interval 60
Restart=always
RestartSec=30
StandardOutput=append:${LOG_DIR}/etl-worker.log
StandardError=append:${LOG_DIR}/etl-worker.err.log

[Install]
WantedBy=multi-user.target
EOF

# 5. product-hub drop-in（JSONL fallback 路径对齐）
echo ">>> [6/6] product-hub drop-in + 启用"
mkdir -p /etc/systemd/system/product-hub.service.d
cat > /etc/systemd/system/product-hub.service.d/events-root.conf <<EOF
[Service]
Environment="WORKBUDDY_EVENTS_ROOT=${EVENTS_ROOT}"
EOF

systemctl daemon-reload
systemctl enable --now etl-worker.service
systemctl restart product-hub.service

echo ""
echo "=== 状态 ==="
echo -n "etl-worker.service: "; systemctl is-active etl-worker.service || true
echo -n "product-hub.service: "; systemctl is-active product-hub.service || true
sleep 3
echo "--- etl-worker 日志(尾 20) ---"
tail -n 20 "${LOG_DIR}/etl-worker.log" 2>/dev/null || echo "(暂无日志)"
if [ -s "${LOG_DIR}/etl-worker.err.log" ]; then
    echo "--- error 日志(尾 10) ---"; tail -n 10 "${LOG_DIR}/etl-worker.err.log"
fi
echo "--- events/ 现有文件 ---"
find "${EVENTS_ROOT}" -type f -name "*.jsonl" 2>/dev/null | head -10 || echo "(暂无事件文件，等待 event_writer 产出)"
echo ""
echo "============================================"
echo "  ✓ Phase 10 部署完成"
echo "  日志: ${LOG_DIR}/etl-worker.log"
echo "  验证: systemctl status etl-worker"
echo "        docker exec ${PG_CONTAINER} psql -U dreambuddy -d dreambuddy -c \"SELECT count(*) FROM dreamos_sessions;\""
echo "  手动单次: EVENTS_ROOT=${EVENTS_ROOT} ${PY} ${ETL_SCRIPT} --date \$(date +%F)"
echo "============================================"
