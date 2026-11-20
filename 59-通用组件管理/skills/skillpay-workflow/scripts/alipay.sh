#!/usr/bin/env bash
# 支付宝开放平台 CLI 封装：只做常用动作，输出单行摘要
set -euo pipefail

CLI="${ALIPAY_CLI:-$HOME/.local/bin/alipay-cli}"
APP_ID="${ALIPAY_APP_ID:-2016122204500401}"
SERVICE_ID="${ALIPAY_SERVICE_ID:-API_019D3B514ACE4D53}"

die() { echo "ERR: $*" >&2; exit 1; }
[[ -x "$CLI" ]] || die "alipay-cli 未安装：curl -fsSL https://opengw.alipay.com/alipaycli/install | bash"

py() { python3 -c "$1"; }

jget() {  # jget <python-expr-on-d> 读 stdin 的 json
  python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null || echo "?"
}

cmd="${1:-help}"; shift || true

case "$cmd" in
  whoami)
    "$CLI" whoami --json 2>/dev/null | jget "('login=%s scope=%s exp=%s' % (d['data'].get('logged_in'), d['data'].get('scope'), d['data'].get('expires_at')))"
    ;;

  login)
    r="$("$CLI" auth login --non-interactive --json 2>/dev/null)"
    st="$(printf '%s' "$r" | jget "d.get('data',{}).get('status')")"
    if [[ "$st" == "already_logged_in" ]]; then echo "already_logged_in"; exit 0; fi
    url="$(printf '%s' "$r" | jget "d['data']['verification_url']")"
    code="$(printf '%s' "$r" | jget "d['data']['verification_code']")"
    echo "请在浏览器打开并扫码授权（10 分钟内有效）："
    echo "  $url"
    echo "  验证码 $code"
    command -v open >/dev/null && open "$url" || true
    for _ in $(seq 1 60); do
      s="$("$CLI" auth login --complete --json 2>/dev/null | jget "d.get('data',{}).get('status')")"
      [[ "$s" == "logged_in" ]] && { echo "logged_in"; exit 0; }
      [[ "$s" == "auth_expired" ]] && die "授权过期，请重新执行 login"
      sleep 5
    done
    die "等待超时，请重新执行 login"
    ;;

  status)
    printf 'login: '; "$CLI" whoami --json 2>/dev/null | jget "d['data'].get('logged_in')"
    "$CLI" mcp call apprelease.queryApplicationInfo -d "{\"request\":{\"appId\":\"$APP_ID\"}}" --json 2>/dev/null \
      | python3 -c '
import sys,json
d=json.load(sys.stdin)
o=json.loads(d["content"][0]["text"]).get("resultObj") or {}
print("app=%s status=%s pid=%s logo=%s" % (o.get("appId"), o.get("status"), o.get("pid"), "yes" if o.get("logoUrl") else "no"))' 2>/dev/null || echo "app=query_failed"
    ;;

  app)   # 原始应用信息
    "$CLI" mcp call apprelease.queryApplicationInfo -d "{\"request\":{\"appId\":\"$APP_ID\"}}" --json
    ;;

  services)
    "$CLI" mcp call a2a-pay-service.discoverBazaarServicesForMcp -d '{}' --json
    ;;

  sign)
    "$CLI" mcp call ar-sign.previewFormView -d '{}' --json
    ;;

  call)  # call <server>.<tool> '<json>'
    [[ $# -ge 1 ]] || die "用法: alipay.sh call <server>.<tool> '<json>'"
    "$CLI" mcp call "$1" -d "${2:-{\}}" --json
    ;;

  tools) # tools <server>
    "$CLI" mcp list "${1:?用法: alipay.sh tools <server>}" --json
    ;;

  *)
    cat <<EOF
用法: bash scripts/alipay.sh <命令>
  status     登录态 + 应用审核状态（单行）
  whoami     仅登录态
  login      设备码登录（自动开浏览器并轮询）
  app        应用原始信息
  services   查询已注册的按量付费服务
  sign       签约表单预览
  tools <srv>           列出 MCP 工具
  call <srv>.<tool> '<json>'  任意调用

常量: APP_ID=$APP_ID SERVICE_ID=$SERVICE_ID
EOF
    ;;
esac
