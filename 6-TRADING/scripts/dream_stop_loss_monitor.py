#!/usr/bin/env python3
"""
Dream-MultiSkill 动态止损监控器 v1.1
====================================
v1.1 变更:
- 移除硬编码 API 凭证，改用 ~/.okx/config.toml 或环境变量
- REPORTS_DIR / TRADING_DIR 改用 ~/.workbuddy/ 标准路径
- 支持 --profile 指定 OKX 账户 profile

使用方法:
    python scripts/dream_stop_loss_monitor.py           # 检查+执行
    python scripts/dream_stop_loss_monitor.py --dry     # 仅检查不下单
    python scripts/dream_stop_loss_monitor.py --report  # 生成状态报告
    python scripts/dream_stop_loss_monitor.py --profile sim  # 指定 profile

凭证加载顺序:
    1. 环境变量: OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE
    2. ~/.okx/config.toml (profile 由 --profile 或 OKX_PROFILE 指定, 默认 live)
"""

import requests
import json
import time
import hmac
import base64
import hashlib
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# ==================== 凭证加载 ====================

def load_credentials(profile: str = "live") -> Dict[str, str]:
    """加载 OKX API 凭证。优先级：环境变量 > ~/.okx/config.toml"""
    api_key = os.environ.get("OKX_API_KEY", "")
    secret_key = os.environ.get("OKX_SECRET_KEY", "")
    passphrase = os.environ.get("OKX_PASSPHRASE", "")

    if api_key and secret_key and passphrase:
        return {"api_key": api_key, "secret_key": secret_key, "passphrase": passphrase}

    config_file = os.path.expanduser("~/.okx/config.toml")
    if not os.path.exists(config_file):
        raise RuntimeError(
            "未找到 OKX 凭证。请设置环境变量 OKX_API_KEY/OKX_SECRET_KEY/OKX_PASSPHRASE，"
            "或创建 ~/.okx/config.toml 文件。"
        )

    try:
        import tomllib  # Python 3.11+
        with open(config_file, "rb") as f:
            config = tomllib.load(f)
    except ImportError:
        config = _parse_toml_simple(config_file)

    creds = config.get(profile, config)
    return {
        "api_key": creds.get("api_key", creds.get("apiKey", "")),
        "secret_key": creds.get("secret_key", creds.get("secretKey", "")),
        "passphrase": creds.get("passphrase", ""),
    }


def _parse_toml_simple(config_file: str) -> Dict:
    """简单 TOML 解析器（降级使用，支持 [section] + key = "value"）"""
    result: Dict = {}
    current_section = None
    with open(config_file) as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                result.setdefault(current_section, {})
            elif "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                v = v.strip().strip('"').strip("'")
                if current_section:
                    result[current_section][k.strip()] = v
                else:
                    result[k.strip()] = v
    return result


# ==================== 配置 ====================

BASE_URL = "https://www.okx.com"
INST_ID = "BTC-USDT-SWAP"
CONFIG_PATH = os.path.expanduser("~/.workbuddy/config/dynamic_stop_loss.json")
REPORTS_DIR = os.path.expanduser("~/.workbuddy/reports/stop_loss")
TRADING_DIR = os.path.expanduser("~/.workbuddy/reports/trading")

_CREDS: Dict[str, str] = {}


# ==================== OKX API ====================

def get_headers(method: str, path: str, body: str = "") -> Dict[str, str]:
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    mac = hmac.new(_CREDS["secret_key"].encode(), msg.encode(), hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode()
    return {
        'OK-ACCESS-KEY': _CREDS["api_key"],
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': _CREDS["passphrase"],
        'Content-Type': 'application/json',
    }


def okx_get(path: str, params: Optional[Dict] = None) -> Dict:
    sign_path = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        sign_path = path + "?" + qs
    headers = get_headers("GET", sign_path)
    resp = requests.get(BASE_URL + path, params=params, headers=headers, timeout=15)
    return resp.json()


def okx_post(path: str, body_dict: Dict) -> Dict:
    body = json.dumps(body_dict)
    headers = get_headers("POST", path, body)
    resp = requests.post(BASE_URL + path, data=body, headers=headers, timeout=15)
    return resp.json()


# ==================== 配置读取 ====================

def load_stop_loss_config() -> Optional[Dict]:
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️  配置文件不存在: {CONFIG_PATH}")
        return None
    with open(CONFIG_PATH) as f:
        return json.load(f)


def is_legacy_position_grace_period(config: Dict, _now: datetime) -> Tuple[bool, int]:
    grace_period_hours = config.get('legacy_position_grace_period_hours', 24)
    config_update_time_str = config.get('last_updated', '2000-01-01T00:00:00')
    config_update_time = datetime.fromisoformat(config_update_time_str.replace('Z', '+00:00'))
    grace_end_time = config_update_time + timedelta(hours=grace_period_hours)
    now = datetime.now(timezone.utc)
    if now < grace_end_time:
        remaining = (grace_end_time - now).total_seconds() / 3600
        return True, int(remaining)
    return False, 0


# ==================== 持仓检查 ====================

def get_positions() -> List[Dict]:
    resp = okx_get("/api/v5/account/positions", {"instType": "SWAP"})
    if resp.get('code') != '0':
        print(f"❌ 获取持仓失败: {resp}")
        return []
    return [p for p in resp.get('data', [])
            if float(p.get('pos', 0)) > 0 and p.get('instId') == INST_ID]


def get_leverage(inst_id: str, pos_side: str) -> int:
    resp = okx_get("/api/v5/account/leverage-info", {"instId": inst_id, "mgnMode": "cross"})
    if resp.get('code') != '0':
        return 1
    for item in resp.get('data', []):
        if item.get('posSide') == pos_side:
            return int(item.get('lever', 1))
    return 1


# ==================== 触发检查 ====================

def check_leverage_breach(position: Dict, config: Dict, is_grace: bool) -> Optional[Dict]:
    max_leverage = config.get('trigger_conditions', {}).get('max_leverage', 2.0)
    pos_side = position.get('posSide', 'long')
    leverage = get_leverage(position.get('instId'), pos_side)
    if leverage > max_leverage:
        if is_grace:
            for rule in config.get('stop_loss_rules', []):
                if rule.get('condition') == 'leverage > 2.0' and rule.get('legacy_exempt'):
                    return None
        return {
            'trigger': 'leverage_breach', 'leverage': leverage, 'max_allowed': max_leverage,
            'action': config.get('auto_actions', {}).get('leverage_breach', {}),
            'is_grace': is_grace,
        }
    return None


def check_upl_breach(position: Dict, config: Dict) -> Optional[Dict]:
    max_upl_loss = config.get('trigger_conditions', {}).get('max_upl_loss_usdt', -5.0)
    upl = float(position.get('upl', 0))
    if upl < max_upl_loss:
        return {
            'trigger': 'upl_breach', 'upl': upl, 'threshold': max_upl_loss,
            'action': config.get('auto_actions', {}).get('upl_breach', {}),
            'is_grace': False,
        }
    return None


# ==================== 执行动作 ====================

def execute_reduction(position: Dict, action: Dict, dry_run: bool = True) -> Dict:
    inst_id = position.get('instId')
    pos_side = position.get('posSide')
    current_pos = int(position.get('pos', 0))
    close_pct = action.get('size_percent', 50) / 100
    close_qty = max(1, int(current_pos * close_pct))
    result = {
        'action': 'CLOSE_PARTIAL',
        'direction': 'sell' if pos_side == 'long' else 'buy',
        'qty': close_qty, 'inst_id': inst_id, 'pos_side': pos_side, 'dry_run': dry_run,
    }
    if dry_run:
        result['status'] = 'DRY_RUN'
        print(f"  [DRY] 平仓 {close_qty} 张 ({int(close_pct*100)}%)")
        return result
    resp = okx_post("/api/v5/trade/order", {
        "instId": inst_id, "tdMode": "cross",
        "side": result['direction'], "ordType": "market",
        "sz": str(close_qty), "posSide": pos_side,
    })
    result['response'] = resp
    result['status'] = 'SUCCESS' if resp.get('code') == '0' else 'FAILED'
    print(f"  平仓结果: {resp.get('code')} {resp.get('msg')}")
    return result


def execute_stop_loss(position: Dict, action: Dict, dry_run: bool = True) -> Dict:
    inst_id = position.get('instId')
    pos_side = position.get('posSide')
    avgPx = float(position.get('avgPx', 0))
    current_pos = int(position.get('pos', 0))
    offset_pct = action.get('trigger_offset_percent', 1.5) / 100
    stop_price = avgPx * (1 - offset_pct) if pos_side == 'long' else avgPx * (1 + offset_pct)
    sl_side = 'sell' if pos_side == 'long' else 'buy'
    result = {
        'action': 'SET_STOP_LOSS', 'trigger_price': round(stop_price, 2),
        'qty': current_pos, 'inst_id': inst_id, 'pos_side': pos_side, 'dry_run': dry_run,
    }
    if dry_run:
        result['status'] = 'DRY_RUN'
        print(f"  [DRY] 设置止损触发价 ${result['trigger_price']}")
        return result
    resp = okx_post("/api/v5/trade/order-algo", {
        "instId": inst_id, "tdMode": "cross", "side": sl_side,
        "ordType": "conditional", "sz": str(current_pos), "posSide": pos_side,
        "slTriggerPx": str(round(stop_price, 2)), "slOrdPx": "-1", "slTriggerPxType": "mark",
    })
    result['response'] = resp
    result['status'] = 'SUCCESS' if resp.get('code') == '0' else 'FAILED'
    print(f"  止损设置结果: {resp.get('code')} {resp.get('msg')}")
    return result


def trigger_manual_review(position: Dict, reason: str, dry_run: bool = True) -> Dict:
    result = {
        'action': 'FORCE_REVIEW', 'reason': reason,
        'position': {k: position.get(k) for k in ('instId', 'posSide', 'pos', 'avgPx', 'upl')},
        'dry_run': dry_run, 'status': 'PENDING_MANUAL_REVIEW',
    }
    print(f"  ⚠️  需要人工确认: {reason}")
    return result


# ==================== 主监控逻辑 ====================

def monitor_positions(dry_run: bool = True) -> Dict:
    config = load_stop_loss_config()
    if not config:
        return {'status': 'NO_CONFIG', 'alerts': []}

    print(f"\n{'='*60}")
    print(f"🔍 动态止损监控 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"模式: {'🔎 DRY_RUN (仅检查)' if dry_run else '⚡ LIVE (执行动作)'}")

    positions = get_positions()
    if not positions:
        print("\n✅ 无持仓，跳过检查")
        return {'status': 'NO_POSITIONS', 'alerts': []}

    results: List[Dict] = []
    alerts: List[Dict] = []

    for pos in positions:
        print(f"\n📊 持仓: {pos.get('instId')} | {pos.get('posSide')} | "
              f"数量:{pos.get('pos')} | 入场价:${float(pos.get('avgPx', 0)):.2f} | "
              f"浮亏:${float(pos.get('upl', 0)):.2f}")

        is_grace, remaining = is_legacy_position_grace_period(config, datetime.now())
        if is_grace:
            print(f"  ⏳ 存量持仓豁免中，剩余 {remaining}h")

        triggers: List[Dict] = []
        checks = [
            (check_leverage_breach(pos, config, is_grace), '杠杆超限'),
            (check_upl_breach(pos, config), '浮亏超限'),
        ]
        for breach, alert_type in checks:
            if breach:
                triggers.append(breach)
                alerts.append({'level': '🔴', 'type': alert_type, 'data': breach})

        if not triggers:
            print("  ✅ 无触发条件")
            results.append({'position': pos, 'triggers': [], 'actions': []})
            continue

        actions: List[Dict] = []
        for trigger in triggers:
            action_config = trigger.get('action', {})
            action_type = action_config.get('action')
            print(f"\n  📋 触发: {trigger['trigger']} | 动作: {action_type}")
            if action_type == 'CLOSE_PARTIAL':
                actions.append(execute_reduction(pos, action_config, dry_run))
            elif action_type == 'SET_STOP_LOSS':
                actions.append(execute_stop_loss(pos, action_config, dry_run))
            elif action_type == 'FORCE_REVIEW':
                actions.append(trigger_manual_review(pos, trigger.get('description', ''), dry_run))

        results.append({'position': pos, 'triggers': triggers, 'actions': actions})

    print(f"\n{'='*60}")
    print(f"持仓数量: {len(positions)} | 触发数量: {len(alerts)}")
    for alert in alerts:
        print(f"  {alert['level']} {alert['type']}")

    return {
        'status': 'COMPLETE', 'positions_checked': len(positions),
        'alerts': alerts, 'results': results,
        'dry_run': dry_run, 'timestamp': datetime.now().isoformat(),
    }


# ==================== 报告生成 ====================

def generate_report(monitor_result: Dict) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_path = os.path.join(
        REPORTS_DIR,
        f"stop_loss_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )
    alerts = monitor_result.get('alerts', [])
    lines = [
        "# 🔍 动态止损监控报告\n\n",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"**模式**: {'🔎 DRY_RUN' if monitor_result.get('dry_run') else '⚡ LIVE'}\n\n---\n\n",
        f"- 检查状态: {monitor_result.get('status')}\n",
        f"- 持仓数量: {monitor_result.get('positions_checked', 0)}\n",
        f"- 触发告警: {len(alerts)}\n\n---\n\n",
    ]
    for alert in alerts:
        lines.append(f"### {alert['level']} {alert['type']}\n\n")
        lines.append(f"```json\n{json.dumps(alert.get('data', {}), indent=2, ensure_ascii=False)}\n```\n\n")
    if not alerts:
        lines.append("✅ 无触发告警\n")
    lines.append(f"\n配置文件: `{CONFIG_PATH}`\n")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"\n📄 报告已生成: {report_path}")
    return report_path


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description='动态止损监控器 v1.1')
    parser.add_argument('--dry', action='store_true', help='仅检查不下单')
    parser.add_argument('--report', action='store_true', help='生成报告')
    parser.add_argument('--config', type=str, help='指定止损配置文件路径')
    parser.add_argument('--profile', type=str,
                        default=os.environ.get("OKX_PROFILE", "live"),
                        help='OKX 账户 profile (默认: live, 可选: sim)')
    args = parser.parse_args()

    if args.config:
        global CONFIG_PATH
        CONFIG_PATH = args.config

    global _CREDS
    try:
        _CREDS = load_credentials(args.profile)
    except RuntimeError as e:
        print(f"❌ 凭证加载失败: {e}")
        sys.exit(2)

    result = monitor_positions(dry_run=args.dry)

    if args.report:
        generate_report(result)

    sys.exit(1 if result.get('alerts') else 0)


if __name__ == "__main__":
    main()
