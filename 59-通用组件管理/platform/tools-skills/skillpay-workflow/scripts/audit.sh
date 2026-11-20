#!/usr/bin/env bash
# skillhub-audit-api 运维封装：健康、402 冒烟、隧道地址、重启
set -euo pipefail

SSH="${AUDIT_SSH:-tencent-cloud}"
SVC="${AUDIT_SVC:-skillhub-audit-api}"
TUN="${AUDIT_TUN:-cloudflared-quick}"
die() { echo "ERR: $*" >&2; exit 1; }
sshx() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$SSH" "$@"; }

tunnel_url() {
  sshx "sudo journalctl -u $TUN --no-pager 2>/dev/null | grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1"
}

cmd="${1:-help}"

case "$cmd" in
  url)
    u="$(tunnel_url)"; [[ -n "$u" ]] || die "取不到隧道地址（$TUN 是否在跑？）"; echo "$u"
    ;;

  health)
    echo "local: $(sshx "curl -sS -m 5 http://127.0.0.1:8788/health" || echo down)"
    u="$(tunnel_url)"; [[ -z "$u" ]] && die "无隧道地址"
    echo "public: $(curl -sS -m 10 "$u/health" || echo down)"
    ;;

  probe)  # 无凭证请求，期望 402 + amount
    u="${2:-$(tunnel_url)}"; [[ -n "$u" ]] || die "无隧道地址"
    body='{"skill_md":"---\nname: smoke\n---\n# smoke"}'
    hdr=$(mktemp); out=$(mktemp)
    code=$(curl -sS -m 25 -o "$out" -D "$hdr" -w '%{http_code}' -X POST "$u/api/audit" \
      -H 'content-type: application/json' -d "$body" || echo 000)
    amt=$(python3 -c "import json;print(json.load(open('$out')).get('amount'))" 2>/dev/null || echo '?')
    has=$(grep -ci '^payment-needed:' "$hdr" || true)
    rm -f "$hdr" "$out"
    echo "http=$code amount=$amt payment_needed=$([[ "$has" -gt 0 ]] && echo yes || echo no) url=$u"
    [[ "$code" == "402" && "$has" -gt 0 ]] || die "402 冒烟失败"
    ;;

  env)
    sshx "sudo sed -e 's/^\(ALIPAY_PRIVATE_KEY=\).*/\1<redacted>/' /etc/skillhub-audit/audit.env"
    ;;

  restart)
    sshx "sudo systemctl restart $SVC && sleep 2 && systemctl is-active $SVC"
    ;;

  logs)
    sshx "sudo journalctl -u $SVC -n ${2:-40} --no-pager"
    ;;

  deploy)  # deploy [本地src目录]：备份 → 安装(src + package.json) → 重启 → 回归，失败自动回滚
    src="${2:-$(cd "$(dirname "$0")/../../.." && pwd)/services/skillhub-audit-api/src}"
    [[ -d "$src" ]] || die "找不到源码目录：$src"
    pkg="$(cd "$src/.." && pwd)/package.json"
    [[ -f "$pkg" ]] || die "找不到 package.json：$pkg"
    ts="$(date +%Y%m%d-%H%M%S)"
    sshx "rm -rf /tmp/audit-src /tmp/audit-package.json"
    scp -q -r "$src" "$SSH:/tmp/audit-src"
    scp -q "$pkg" "$SSH:/tmp/audit-package.json"
    sshx "sudo bash -s -- $ts" <<'REMOTE'
set -euo pipefail
TS="$1"
APP=/opt/skillhub-audit/app
BK=/opt/skillhub-audit/backups/app-$TS
mkdir -p "$BK/src"
cp -a "$APP/src/." "$BK/src/"
[ -f "$APP/package.json" ] && cp -a "$APP/package.json" "$BK/package.json"
restore() {
  echo "回滚：恢复 $BK" >&2
  rm -rf "$APP/src"
  mkdir -p "$APP/src"
  cp -a "$BK/src/." "$APP/src/"
  [ -f "$BK/package.json" ] && cp -a "$BK/package.json" "$APP/package.json"
  systemctl restart skillhub-audit-api
  sleep 2
  systemctl is-active skillhub-audit-api || true
}
trap 'rc=$?; if [ "$rc" -ne 0 ]; then restore; fi' EXIT
rsync -a --delete /tmp/audit-src/ "$APP/src/"
[ -f /tmp/audit-package.json ] && cp /tmp/audit-package.json "$APP/package.json"
rm -rf /tmp/audit-src /tmp/audit-package.json
systemctl restart skillhub-audit-api
sleep 2
systemctl is-active skillhub-audit-api
curl -fsS -m 5 http://127.0.0.1:8788/health >/dev/null
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST \
  http://127.0.0.1:8788/api/cogsteward -H 'content-type: application/json' \
  -d '{"metrics":{"broken_links":0}}')
[ "$code" = "402" ] || { echo "cogsteward 回归失败：http=$code" >&2; exit 1; }
echo "部署完成；备份 $BK"
REMOTE
    ;;

  *)
    cat <<EOF
用法: bash scripts/audit.sh <命令>
  url              当前公网隧道地址
  health           本地 + 公网健康检查
  probe [url]      402 冒烟（http/金额/payment-needed）
  env              查看服务端配置（私钥已打码）
  logs [n]         最近日志
  restart          重启 systemd 服务
  deploy [src]     备份 → 安装 src + package.json → 重启 → 健康/402 回归，失败自动回滚
EOF
    ;;
esac
