#!/usr/bin/env python3
"""
6-TRADING 邮箱扫描器
==================
每小时扫描 6-TRADING 交易邮箱，解析产物 frontmatter，
提取交易指令，投递到产物中台 (artifact-alignment-manager)

功能:
  1. 扫描 6-TRADING 邮箱各子目录新文件
  2. 解析 YAML frontmatter + Markdown 内容
  3. 分类提取: 方向决策 / 订单设置 / 信号触发 / 执行日志
  4. 生成交易指令摘要 JSON
  5. 投递到产物中台 (artifacts/trading/)

用法:
    python3 mailbox_scanner.py
    python3 mailbox_scanner.py --verbose
    python3 mailbox_scanner.py --since 2026-05-16T00:00:00
"""

import os
import re
import json
import sys
import yaml
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# ==================== 配置 ====================

BASE_DIR = Path.home() / ".workbuddy" / "skills" / "boss-secretary" / "reports" / "trading"
MAILBOX_DIR = BASE_DIR / "6-trading"
ARTIFACTS_DIR = Path.home() / ".workbuddy" / "artifacts" / "trading"

# 子目录定义
SUBDIRS = {
    "screen1": "第一屏周度方向输出",
    "screen2": "第二屏日线订单设置",
    "signals": "第三屏信号 (A4/A5/A6/A9)",
    "orders": "当前活跃订单状态",
    "execution_log": "执行日志",
}

# 上次扫描状态文件
STATE_FILE = MAILBOX_DIR / ".scanner_state.json"

# Artifact Hub 连通配置
HUB_URL = os.getenv("DREAM_HUB_URL", "http://127.0.0.1:3456")
HUB_TRADING_ENDPOINT = f"{HUB_URL}/api/trading/mailbox-scan"

# ==================== YAML Frontmatter 解析 ====================

def parse_frontmatter(content: str) -> tuple:
    """
    解析 Markdown 文件的 YAML frontmatter

    返回: (metadata_dict, body_content)
    """
    pattern = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
    match = pattern.match(content)

    if not match:
        return {}, content

    try:
        metadata = yaml.safe_load(match.group(1))
        if not isinstance(metadata, dict):
            metadata = {}
    except yaml.YAMLError:
        metadata = {}

    body = content[match.end():]
    return metadata, body


# ==================== 文件扫描 ====================

def get_new_files(subdir: str, since: Optional[datetime] = None) -> List[Path]:
    """获取指定子目录中的新文件"""
    dir_path = MAILBOX_DIR / subdir
    if not dir_path.exists():
        return []

    files = []
    for f in dir_path.iterdir():
        if f.is_file() and f.suffix in ('.md', '.json') and not f.name.startswith('.'):
            if since is None:
                files.append(f)
            else:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime >= since:
                    files.append(f)

    return sorted(files, key=lambda x: x.stat().st_mtime)


def scan_all(since: Optional[datetime] = None) -> Dict[str, List[Dict]]:
    """扫描所有子目录，返回新文件列表"""
    results = {}

    for subdir, desc in SUBDIRS.items():
        if subdir == "orders":
            # orders 目录只有一个 active_orders.json 状态文件，特殊处理
            continue

        files = get_new_files(subdir, since)
        if files:
            results[subdir] = []
            for f in files:
                parsed = parse_file(f, subdir)
                if parsed:
                    results[subdir].append(parsed)

    return results


# ==================== 文件解析 ====================

def parse_file(filepath: Path, subdir: str) -> Optional[Dict]:
    """解析单个文件，提取交易指令"""
    try:
        content = filepath.read_text(encoding='utf-8')
    except (UnicodeDecodeError, IOError) as e:
        return {"file": str(filepath), "error": f"读取失败: {e}"}

    if filepath.suffix == '.json':
        try:
            data = json.loads(content)
            return {
                "file": str(filepath),
                "filename": filepath.name,
                "subdir": subdir,
                "type": "json_state",
                "data": data,
                "parsed_at": datetime.now().isoformat(),
            }
        except json.JSONDecodeError as e:
            return {"file": str(filepath), "error": f"JSON解析失败: {e}"}

    # Markdown 文件: 解析 frontmatter
    metadata, body = parse_frontmatter(content)

    if not metadata:
        return {"file": str(filepath), "warning": "无 frontmatter", "filename": filepath.name}

    return {
        "file": str(filepath),
        "filename": filepath.name,
        "subdir": subdir,
        "type": metadata.get("type", "unknown"),
        "chain_phase": metadata.get("chain_phase", subdir),
        "title": metadata.get("title", filepath.name),
        "date": metadata.get("date", ""),
        "status": metadata.get("status", "unknown"),
        "confidence": metadata.get("confidence", None),
        "inst_id": metadata.get("inst_id", "BTC-USDT-SWAP"),
        "department": metadata.get("department", ""),
        "body_preview": body[:500].strip() if body else "",
        "metadata": metadata,
        "parsed_at": datetime.now().isoformat(),
    }


# ==================== 指令提取 ====================

def extract_trading_instructions(scan_results: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """
    从扫描结果中提取交易指令摘要

    返回结构:
    {
        "screen1": { "direction": "LONG", "strategy": "...", ... },
        "screen2": { "orders": [...], ... },
        "signals": [ { "skill": "A4", "confidence": 80, "action": "EXECUTE", ... }, ... ],
        "orders": { "active_orders": { ... } },
    }
    """
    summary = {
        "scanned_at": datetime.now().isoformat(),
        "screen1": None,
        "screen2": None,
        "signals": [],
        "execution_log": [],
    }

    # Screen1: 取最新方向决策
    if "screen1" in scan_results:
        for item in scan_results["screen1"]:
            if item.get("type") == "direction_decision":
                body = item.get("body_preview", "")
                # 尝试从正文提取方向
                direction = "UNKNOWN"
                for keyword in ["LONG", "SHORT", "强多头", "弱多头", "观望", "空头"]:
                    if keyword in body.upper() or keyword in body:
                        if keyword in ("LONG", "强多头", "弱多头"):
                            direction = "LONG"
                        elif keyword in ("SHORT", "空头"):
                            direction = "SHORT"
                        else:
                            direction = "LONG"  # 观望默认多头
                        break

                summary["screen1"] = {
                    "filename": item.get("filename"),
                    "date": item.get("date"),
                    "direction": direction,
                    "confidence": item.get("confidence"),
                    "inst_id": item.get("inst_id"),
                    "title": item.get("title"),
                }
                break  # 只取最新的

    # Screen2: 取最新订单设置
    if "screen2" in scan_results:
        for item in scan_results["screen2"]:
            if item.get("type") == "order_setup":
                summary["screen2"] = {
                    "filename": item.get("filename"),
                    "date": item.get("date"),
                    "confidence": item.get("confidence"),
                    "inst_id": item.get("inst_id"),
                    "title": item.get("title"),
                    "body_preview": item.get("body_preview", "")[:300],
                }
                break

    # Signals: 提取所有信号
    if "signals" in scan_results:
        for item in scan_results["signals"]:
            signal = {
                "skill": _extract_skill(item.get("filename", "")),
                "filename": item.get("filename"),
                "date": item.get("date"),
                "confidence": item.get("confidence"),
                "type": item.get("type"),
                "inst_id": item.get("inst_id"),
            }
            summary["signals"].append(signal)

    # Execution log
    if "execution_log" in scan_results:
        for item in scan_results["execution_log"]:
            summary["execution_log"].append({
                "filename": item.get("filename"),
                "date": item.get("date"),
                "title": item.get("title"),
            })

    return summary


def _extract_skill(filename: str) -> str:
    """从文件名提取 SKILL 标识"""
    if "a4" in filename.lower():
        return "A4"
    elif "a5" in filename.lower():
        return "A5"
    elif "a6" in filename.lower():
        return "A6"
    elif "a9" in filename.lower():
        return "A9"
    return "UNKNOWN"


# ==================== 状态管理 ====================

def load_state() -> Dict:
    """加载上次扫描状态"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_scan": None, "scan_count": 0, "total_files_processed": 0}


def save_state(state: Dict):
    """保存扫描状态"""
    state["last_scan"] = datetime.now().isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


# ==================== 投递到产物中台 ====================

def deliver_to_artifact_hub(summary: Dict[str, Any], verbose: bool = False) -> bool:
    """
    将交易指令摘要投递到产物中台

    1. 写入 artifacts/trading/6_trading_summary.json
    2. 如果有 Screen1/Screen2，更新 active_orders.json
    3. 返回投递结果
    """
    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

        # 1. 写入摘要文件
        summary_file = ARTIFACTS_DIR / "6_trading_summary.json"
        summary_file.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

        if verbose:
            print(f"  已写入产物中台: {summary_file}")

        # 2. 更新 active_orders.json (如果有新方向/订单)
        orders_file = MAILBOX_DIR / "orders" / "active_orders.json"
        if summary.get("screen1"):
            try:
                orders = json.loads(orders_file.read_text(encoding='utf-8'))
                orders["screen1_direction"] = summary["screen1"]["direction"]
                orders["screen1_week"] = summary["screen1"]["date"]
                orders["last_updated"] = datetime.now().isoformat()
                orders_file.write_text(
                    json.dumps(orders, indent=2, ensure_ascii=False),
                    encoding='utf-8'
                )
                if verbose:
                    print(f"  已更新活跃订单: direction={summary['screen1']['direction']}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"  更新活跃订单失败: {e}")

        # 3. 更新 artifacts/trading/index.json
        index_file = ARTIFACTS_DIR / "index.json"
        index_data = []
        if index_file.exists():
            try:
                index_data = json.loads(index_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, IOError):
                pass

        # 添加新条目
        entry = {
            "filename": "6_trading_summary.json",
            "title": "6-TRADING 交易指令摘要",
            "chain_phase": "trading_workflow",
            "date": summary["scanned_at"],
            "tags": "6-trading mailbox scanner",
            "type": "trading_summary",
        }
        # 更新或追加
        found = False
        for i, item in enumerate(index_data):
            if item.get("filename") == "6_trading_summary.json":
                index_data[i] = entry
                found = True
                break
        if not found:
            index_data.append(entry)

        index_file.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

        return True

    except Exception as e:
        print(f"  投递到产物中台失败: {e}")
        return False


# ==================== 推送到 Artifact Hub ====================

def push_to_hub(summary: Dict[str, Any], verbose: bool = False) -> bool:
    """
    将交易指令摘要通过 HTTP POST 推送到 Artifact Hub

    这是 mailbox_scanner → Hub 的实时 API 通道，
    替代纯文件投递的单向管道模式。

    返回: 推送是否成功
    """
    try:
        payload = json.dumps({
            "source": "mailbox_scanner",
            "scanned_at": summary.get("scanned_at"),
            "screen1": summary.get("screen1"),
            "screen2": summary.get("screen2"),
            "signals": summary.get("signals", []),
            "execution_log": summary.get("execution_log", []),
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            HUB_TRADING_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")

        if status in (200, 201):
            if verbose:
                print(f"  Hub 推送成功: {HUB_TRADING_ENDPOINT} (HTTP {status})")
            return True
        else:
            if verbose:
                print(f"  Hub 推送异常: HTTP {status} — {body[:200]}")
            return False

    except urllib.error.URLError as e:
        reason = str(e.reason)
        if verbose:
            print(f"  Hub 推送失败: {HUB_TRADING_ENDPOINT} — {reason}")
        return False
    except Exception as e:
        if verbose:
            print(f"  Hub 推送异常: {e}")
        return False


# ==================== 报告生成 ====================

def generate_scan_report(
    scan_results: Dict[str, List[Dict]],
    summary: Dict[str, Any],
    deliver_ok: bool,
    hub_ok: bool = False,
    verbose: bool = False
) -> str:
    """生成扫描报告"""
    total_files = sum(len(v) for v in scan_results.values())

    lines = [
        "=" * 50,
        "6-TRADING 邮箱扫描报告",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 50,
        "",
        f"扫描文件数: {total_files}",
    ]

    # 各目录状态
    for subdir, desc in SUBDIRS.items():
        if subdir == "orders":
            continue
        count = len(scan_results.get(subdir, []))
        status = f"{count} 个新文件" if count > 0 else "无新文件"
        lines.append(f"  {subdir:15s} ({desc}): {status}")

    lines.append("")

    # Screen1 摘要
    if summary["screen1"]:
        s1 = summary["screen1"]
        lines.append(f"  最新方向: {s1['direction']} (置信度: {s1['confidence']})")
        lines.append(f"  方向日期: {s1['date']}")
    else:
        lines.append("  最新方向: 无 (等待 Screen1 输出)")

    lines.append("")

    # 信号摘要
    if summary["signals"]:
        lines.append(f"  待处理信号: {len(summary['signals'])} 个")
        for sig in summary["signals"]:
            conf = sig.get("confidence", "?")
            lines.append(f"    - {sig['skill']} | 置信度: {conf} | 日期: {sig.get('date', '?')}")
    else:
        lines.append("  待处理信号: 无")

    lines.append("")

    # 投递状态
    deliver_status = "成功" if deliver_ok else "失败"
    lines.append(f"  产物中台投递: {deliver_status}")
    hub_status = "成功" if hub_ok else "未推送/失败"
    lines.append(f"  Hub 实时推送:  {hub_status}")

    lines.append("")
    lines.append("=" * 50)

    report = "\n".join(lines)
    if verbose:
        print(report)

    return report


def json_serializer(obj):
    """处理无法直接JSON序列化的对象"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="6-TRADING 邮箱扫描器")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--since", type=str, default=None,
                        help="只扫描此时间之后的文件 (ISO格式)")
    parser.add_argument("--dry-run", action="store_true", help="只扫描不投递")
    parser.add_argument("--force", action="store_true", help="忽略状态文件，扫描所有文件")
    args = parser.parse_args()

    print("6-TRADING 邮箱扫描器 v1.0")

    # 检查邮箱目录
    if not MAILBOX_DIR.exists():
        print(f"错误: 邮箱目录不存在 {MAILBOX_DIR}")
        sys.exit(1)

    # 确定扫描起始时间
    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"错误: 无效的时间格式 {args.since}")
            sys.exit(1)
    elif not args.force:
        state = load_state()
        if state.get("last_scan"):
            since = datetime.fromisoformat(state["last_scan"])
            if args.verbose:
                print(f"上次扫描: {since}")

    # 扫描
    if args.verbose:
        print(f"扫描目录: {MAILBOX_DIR}")
        print(f"起始时间: {since or '全部文件'}")
        print()

    scan_results = scan_all(since)

    if not scan_results:
        print("无新文件需要处理")
        save_state(load_state())
        return

    # 提取交易指令
    summary = extract_trading_instructions(scan_results)

    # 投递到产物中台
    deliver_ok = False
    if not args.dry_run:
        deliver_ok = deliver_to_artifact_hub(summary, verbose=args.verbose)

    # 实时推送到 Artifact Hub (Hub → Trading 双向连通)
    hub_ok = False
    if not args.dry_run:
        hub_ok = push_to_hub(summary, verbose=args.verbose)

    # 生成报告
    report = generate_scan_report(scan_results, summary, deliver_ok, hub_ok, verbose=args.verbose)

    # 保存报告到 execution_log
    report_file = MAILBOX_DIR / "execution_log" / f"scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    report_data = {
        "report": report,
        "summary": summary,
        "scan_results_count": {k: len(v) for k, v in scan_results.items()},
        "deliver_success": deliver_ok,
        "hub_push_success": hub_ok,
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding='utf-8')

    # 更新状态
    state = load_state()
    state["scan_count"] = state.get("scan_count", 0) + 1
    state["total_files_processed"] = state.get("total_files_processed", 0) + sum(
        len(v) for v in scan_results.values()
    )
    save_state(state)

    print(f"\n扫描完成 (第 {state['scan_count']} 次, 累计 {state['total_files_processed']} 个文件)")


if __name__ == "__main__":
    main()
