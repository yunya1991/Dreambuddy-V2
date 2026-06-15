#!/usr/bin/env python3
"""
V15 Hourly Baseline Signal Runner
=================================
每小时自动运行，纯 Python 代码驱动，零 Token 消耗。
- 调用 v15_signal.py 获取实时信号
- 记录到日志文件
- 仅在信号变化时写入状态文件（供飞书通知等下游消费）

Crontab: 0 * * * * python3 /home/ubuntu/Dreambuddy-V2-main/6-TRADING/scripts/v15_hourly_runner.py >> /home/ubuntu/Dreambuddy-V2-main/6-TRADING/logs/v15_cron.log 2>&1
"""
import subprocess, json, os, sys
from datetime import datetime, timezone
import sys
sys.path.insert(0, '/home/ubuntu/archives/Dreambuddy-V2-main/6-TRADING/scripts')
from a_product_delivery import deliver_product

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
V15_SIGNAL = os.path.join(SCRIPT_DIR, 'v15_signal.py')
TRADING_DIR = os.path.dirname(SCRIPT_DIR)
LOG_DIR = os.path.join(TRADING_DIR, 'logs')
STATE_FILE = os.path.join(TRADING_DIR, 'v15_hourly_state.json')
MEMORY_FILE = os.path.join(TRADING_DIR, 'V15_SOUL_MEMORY.md')

os.makedirs(LOG_DIR, exist_ok=True)

def run_v15_signal():
    """调用 v15_signal.py 获取当前信号"""
    try:
        result = subprocess.run(
            [sys.executable, V15_SIGNAL],
            capture_output=True, text=True, timeout=90,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            # 网络不可达等非致命错误
            if 'Binance unreachable' in stderr or 'Binance unreachable' in stdout:
                return None, 'NETWORK_UNAVAILABLE'
            return None, f"ERROR(exit={result.returncode}): {stderr[:300] or stdout[:300]}"
        return stdout, None
    except subprocess.TimeoutExpired:
        return None, 'TIMEOUT'
    except Exception as e:
        return None, f'EXCEPTION: {e}'

def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def main():
    now = datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%d %H:%M:%S UTC')
    date_str = now.strftime('%Y%m%d')
    hour = now.strftime('%H')
    
    output, error = run_v15_signal()
    
    # 记录日志（每天一个文件）
    log_file = os.path.join(LOG_DIR, f"v15_hourly_{date_str}.log")
    
    prev = load_previous_state()
    
    if error:
        # 区分网络错误和真正的代码错误
        if error in ('NETWORK_UNAVAILABLE', 'TIMEOUT'):
            # 网络不可达，静默跳过（不写详细日志避免刷屏）
            is_first_fail = not prev.get('last_error_time')
            prev['last_error_time'] = ts
            prev['error_count'] = prev.get('error_count', 0) + 1
            prev['status'] = 'network_unavailable'
            save_state(prev)
            if is_first_fail or prev['error_count'] % 6 == 0:
                with open(log_file, 'a') as f:
                    f.write(f"[{ts}] NETWORK_UNAVAILABLE (count={prev['error_count']})\n")
                print(f"[{ts}] NETWORK_UNAVAILABLE (count={prev['error_count']})")
            return
        
        # 真正的错误
        with open(log_file, 'a') as f:
            f.write(f"[{ts}] ERROR: {error}\n")
        prev['last_error_time'] = ts
        prev['last_error'] = error[:200]
        prev['status'] = 'error'
        save_state(prev)
        print(f"[{ts}] ERROR: {error[:120]}")
        return
    
    # 成功获取信号
    import hashlib
    new_hash = hashlib.md5(output.encode()).hexdigest()
    prev_hash = prev.get('signal_hash', '')
    prev['error_count'] = 0
    prev['last_error_time'] = None
    prev['last_error'] = None
    
    if new_hash != prev_hash:
        # 信号变化 → 完整记录
        with open(log_file, 'a') as f:
            f.write(f"\n=== {ts} [SIGNAL CHANGED] ===\n{output}\n")
        prev['last_run'] = ts
        prev['signal_hash'] = new_hash
        prev['signal_summary'] = output[:500]
        prev['status'] = 'updated'
        save_state(prev)
        print(f"[{ts}] SIGNAL_CHANGED")

        # 双通道投递 - 信号变化时推送
        try:
            deliver_product(
                phase="v15",
                title="v15 信号变更提醒",
                summary=prev.get("signal_summary", "信号已更新")[:200],
                detail={
                    "signal_hash": new_hash,
                    "prev_hash": prev_hash,
                    "status": "changed",
                },
                status="alert",
            )
        except Exception as e:
            print("[v15] 双通道投递失败: " + str(e))
    else:
        # 信号不变 → 仅记录时间戳
        prev['last_run'] = ts
        prev['status'] = 'unchanged'
        prev['consecutive_unchanged'] = prev.get('consecutive_unchanged', 0) + 1
        save_state(prev)
        # 每6小时打印一次确认
        if prev['consecutive_unchanged'] % 6 == 0:
            print(f"[{ts}] SIGNAL_UNCHANGED (x{prev['consecutive_unchanged']})")

if __name__ == '__main__':
    main()
