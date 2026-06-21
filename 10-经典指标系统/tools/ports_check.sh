set -e

echo "[prod] backend 8092 /health"
curl -fsS -m 10 http://127.0.0.1:8092/health | head -c 200
echo
echo "[prod] ui 3001 /api/health"
curl -fsS -m 10 http://127.0.0.1:3001/api/health | head -c 200
echo

echo "[ai_ex] backend 8093 /health"
curl -fsS -m 10 http://127.0.0.1:8093/health | head -c 200
echo
echo "[ai_ex] ui 3002 /api/health"
curl -fsS -m 10 http://127.0.0.1:3002/api/health | head -c 200
echo
