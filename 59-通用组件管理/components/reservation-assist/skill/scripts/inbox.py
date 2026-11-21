"""群消息入站（实验）：轮询 -> 解析参观人 -> Keychain 存储 -> 脱敏确认。

只存 Keychain，不落盘、不回显完整证件号；发送到群里的确认一律脱敏。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.request

APP_KEYCHAIN_SERVICE = "com.reservation-assist.feishu-app"
VISITOR_KEYCHAIN_SERVICE = "com.reservation-assist.visitors"

NAME_RE = re.compile(r"(?:姓名|参观人|预约人|就诊人)[：:\s]*([\u4e00-\u9fa5·]{2,8})")
ID_RE = re.compile(r"(?<![0-9A-Za-z])(\d{17}[0-9Xx])(?![0-9A-Za-z])")
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")


def _security(*args: str, timeout: int = 5) -> str:
    if not shutil.which("security"):
        return ""
    try:
        out = subprocess.run(["security", *args], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _decode_value(raw: str) -> str:
    """security -w 对非 ASCII 值会输出十六进制，这里还原成原文。"""
    if re.fullmatch(r"[0-9a-fA-F]+", raw) and len(raw) % 2 == 0:
        try:
            return bytes.fromhex(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return raw
    return raw


def load_app_config() -> dict:
    raw = _decode_value(_security("find-generic-password", "-w", "-s", APP_KEYCHAIN_SERVICE))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_visitors() -> list[dict]:
    raw = _decode_value(_security("find-generic-password", "-w", "-s", VISITOR_KEYCHAIN_SERVICE))
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_visitors(items: list[dict]) -> bool:
    if not shutil.which("security"):
        return False
    payload = json.dumps(items, ensure_ascii=False)
    out = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            VISITOR_KEYCHAIN_SERVICE,
            "-a",
            "visitors",
            "-w",
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return out.returncode == 0


def mask_name(name: str) -> str:
    return name[:1] + "*" * max(len(name) - 1, 1) if name else ""


def mask_id(value: str) -> str:
    return "**************" + value[-4:] if len(value) >= 4 else "****"


def mask_phone(value: str) -> str:
    return value[:3] + "****" + value[-4:] if len(value) == 11 else ""


def summarize(items: list[dict]) -> list[str]:
    return [
        "{} {} {}".format(
            mask_name(item.get("name", "")),
            mask_id(item.get("id", "")),
            mask_phone(item.get("phone", "")),
        ).strip()
        for item in items
    ]


def parse_visitors(text: str) -> list[dict]:
    """一条消息一个人：姓名 + 身份证，可选手机号。解析不出证件号则忽略。"""
    ids = ID_RE.findall(text)
    if not ids:
        return []
    match = NAME_RE.search(text)
    if match:
        name = match.group(1)
    else:
        prefix = text[: text.find(ids[0])]
        tokens = re.findall(r"[\u4e00-\u9fa5·]{2,8}", prefix)
        name = tokens[-1] if tokens else ""
    phones = PHONE_RE.findall(text)
    return [
        {
            "name": name,
            "id": ids[0].upper(),
            "phone": phones[0] if phones else "",
            "updated_at": int(time.time() * 1000),
        }
    ]


def _token(config: dict) -> str:
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps(
            {"app_id": config.get("app_id"), "app_secret": config.get("app_secret")}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("tenant_access_token") or ""


def fetch_messages(config: dict, start_time_ms: int) -> list[dict]:
    token = _token(config)
    if not token or not config.get("chat_id"):
        return []
    url = (
        "https://open.feishu.cn/open-apis/im/v1/messages"
        "?container_id_type=chat&container_id={}&start_time={}&page_size=20"
        "&sort_type=ByCreateTimeAsc"
    ).format(config["chat_id"], max(start_time_ms // 1000, 0))
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(request, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    items = []
    for row in (payload.get("data") or {}).get("items") or []:
        if row.get("msg_type") != "text":
            continue
        try:
            body = json.loads((row.get("body") or {}).get("content") or "{}")
        except json.JSONDecodeError:
            continue
        items.append(
            {
                "message_id": row.get("message_id"),
                "text": body.get("text", ""),
                "create_time": int(row.get("create_time") or 0),
            }
        )
    return items


def pull(store, config: dict, minutes: int = 60) -> dict:
    now_ms = int(time.time() * 1000)
    cursor = int(store.get_meta("inbox_cursor", "0") or 0)
    start = cursor or (now_ms - minutes * 60 * 1000)
    messages = fetch_messages(config, start)
    existing = {item.get("id"): item for item in load_visitors()}
    added: list[dict] = []
    newest = cursor
    for message in messages:
        newest = max(newest, message["create_time"])
        for person in parse_visitors(message["text"]):
            if person["id"] not in existing:
                added.append(person)
            existing[person["id"]] = person
    if added:
        save_visitors(list(existing.values()))
    if newest:
        store.set_meta("inbox_cursor", str(newest + 1))
    store.add_event("info", "inbox_pulled", "", {"scanned": len(messages), "added": len(added)})
    return {"scanned": len(messages), "added": added, "total": len(existing)}
