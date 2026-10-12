"""
safe_call — Phase 3 P0-4 FAIL-OPEN 登记制核心模块

三层分层:
- L1: 现有 try/except 保留 (热路径 FAIL-OPEN 不破坏)
- L2: safe_call(fn, fallback, *args, **kwargs) 装饰器, 登记异常到 ring buffer
- L3: cognitive_enabled 关闭时, safe_call 降级为纯 try/except (不登记)

蓝图: SPEC-自进化系统逆向解析改进 v0.3 §P0-4
硬约束: 不破坏现有热路径 FAIL-OPEN 语义; ring buffer 64KB mmap 持久化.
"""
from __future__ import annotations

import hashlib
import json
import logging
import mmap
import os
import struct
import time
import traceback
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ring buffer 固定大小: 64KB
_RING_BUFFER_SIZE = 64 * 1024  # 65536 bytes
# 文件头: write_pos (uint32) + entry_count (uint32) = 8 bytes
_HEADER_SIZE = 8
# body: 变长 JSON 行, 以 \n 分隔, 环形覆盖
_BODY_SIZE = _RING_BUFFER_SIZE - _HEADER_SIZE
# 单条登记最大长度 (防止一条巨长记录挤爆 buffer)
_MAX_ENTRY_LEN = 4096

# 默认 ring buffer 文件路径: dreambuddy_evolution/data/error_ring.bin
_DEFAULT_RING_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "error_ring.bin"
)


class ErrorRingBuffer:
    """固定 64KB mmap 文件, 环形写入异常登记条目.

    文件格式:
        [0:4]   write_pos  (uint32, body 内下一个写入偏移)
        [4:8]   entry_count (uint32, 累计写入条数, 用于覆盖检测)
        [8:]    body (65528 bytes, JSON 行以 \\n 分隔)

    环形覆盖: write_pos 达 body 末尾后回绕到 0, 覆盖最旧条目.
    持久化: mmap MAP_SHARED, 进程重启后内容可见.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _DEFAULT_RING_PATH
        self._mmap: mmap.mmap | None = None
        self._file = None
        self._ensure_lock = False

    def ensure_created(self) -> None:
        """确保文件存在且大小为 64KB (FAIL-OPEN: 失败不阻断)"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                # 创建并预分配 64KB
                with open(self.path, "wb") as f:
                    f.truncate(_RING_BUFFER_SIZE)
                # 写入 header 初始值
                with open(self.path, "r+b") as f:
                    f.write(struct.pack("<II", 0, 0))
            else:
                # 文件存在, 检查大小
                cur_size = self.path.stat().st_size
                if cur_size != _RING_BUFFER_SIZE:
                    # 大小不一致, 重建
                    with open(self.path, "r+b") as f:
                        f.truncate(_RING_BUFFER_SIZE)
                        f.seek(0)
                        f.write(struct.pack("<II", 0, 0))
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO] ErrorRingBuffer.ensure_created crash: %s", e)

    def _open_mmap(self) -> mmap.mmap | None:
        """打开 mmap (FAIL-OPEN: 失败返回 None)"""
        try:
            self.ensure_created()
            self._file = open(self.path, "r+b")
            self._mmap = mmap.mmap(
                self._file.fileno(),
                length=_RING_BUFFER_SIZE,
                access=mmap.ACCESS_WRITE,
            )
            return self._mmap
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO] ErrorRingBuffer._open_mmap crash: %s", e)
            return None

    def _close_mmap(self) -> None:
        """关闭 mmap (FAIL-OPEN)"""
        try:
            if self._mmap is not None:
                self._mmap.flush()
                self._mmap.close()
                self._mmap = None
            if self._file is not None:
                self._file.close()
                self._file = None
        except Exception as e:  # noqa: BLE001
            logger.debug("[FO] ring buffer close fail: %s", e)

    def _read_header(self, mm: mmap.mmap) -> tuple[int, int]:
        """读取 header: (write_pos, entry_count)"""
        try:
            write_pos, entry_count = struct.unpack("<II", mm[0:_HEADER_SIZE])
            return write_pos, entry_count
        except Exception:  # noqa: BLE001
            return 0, 0

    def _write_header(self, mm: mmap.mmap, write_pos: int, entry_count: int) -> None:
        """写入 header"""
        mm[0:_HEADER_SIZE] = struct.pack("<II", write_pos, entry_count)

    def append(self, entry: dict[str, Any]) -> None:
        """追加一条登记. 环形覆盖最旧.

        entry 字段: timestamp, module, error_hash, error_type, error, ...
        """
        try:
            line = json.dumps(entry, ensure_ascii=False, default=str)
            # 截断保护
            if len(line) > _MAX_ENTRY_LEN:
                line = line[:_MAX_ENTRY_LEN - 50] + '"...truncated"}'
            line_bytes = (line + "\n").encode("utf-8")
            line_len = len(line_bytes)

            mm = self._open_mmap()
            if mm is None:
                return

            try:
                write_pos, entry_count = self._read_header(mm)
                # body 边界保护
                if write_pos >= _BODY_SIZE:
                    write_pos = 0

                # 写入位置: body 起始偏移 + write_pos
                body_start = _HEADER_SIZE
                # 若剩余空间不足, 覆盖最旧: 回绕到 0
                if write_pos + line_len > _BODY_SIZE:
                    # 写到末尾 + 回绕
                    first_part = _BODY_SIZE - write_pos
                    mm[body_start + write_pos : _RING_BUFFER_SIZE] = line_bytes[:first_part]
                    remaining = line_len - first_part
                    mm[body_start : body_start + remaining] = line_bytes[first_part:]
                    new_write_pos = remaining
                else:
                    end = body_start + write_pos + line_len
                    mm[body_start + write_pos : end] = line_bytes
                    new_write_pos = write_pos + line_len
                    if new_write_pos >= _BODY_SIZE:
                        new_write_pos = 0

                self._write_header(mm, new_write_pos, entry_count + 1)
                mm.flush()
            finally:
                self._close_mmap()
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO] ErrorRingBuffer.append crash: %s", e)

    def read_all(self) -> list[dict[str, Any]]:
        """读取所有可解析的登记条目 (按写入顺序, 已覆盖的丢失)."""
        entries: list[dict[str, Any]] = []
        try:
            mm = self._open_mmap()
            if mm is None:
                return entries
            try:
                write_pos, _entry_count = self._read_header(mm)
                body_start = _HEADER_SIZE
                # 读出整个 body (mm 切片返回 bytes, 直接 decode)
                body_bytes = bytes(mm[body_start:_RING_BUFFER_SIZE])
                # 按 \n 分割, 解析 JSON
                text = body_bytes.decode("utf-8", errors="ignore")
                # 找出所有完整的 JSON 行
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, dict):
                            entries.append(entry)
                    except Exception:  # noqa: BLE001
                        continue
                # 按时间戳排序 (若有)
                entries.sort(key=lambda e: e.get("timestamp", 0))
                return entries
            finally:
                self._close_mmap()
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO] ErrorRingBuffer.read_all crash: %s", e)
            return entries

    def clear(self) -> None:
        """清空 ring buffer (重置 header + body)"""
        try:
            mm = self._open_mmap()
            if mm is None:
                return
            try:
                self._write_header(mm, 0, 0)
                # body 填 0
                mm[_HEADER_SIZE:_RING_BUFFER_SIZE] = b"\x00" * _BODY_SIZE
                mm.flush()
            finally:
                self._close_mmap()
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO] ErrorRingBuffer.clear crash: %s", e)


# ---- 全局单例 (进程内) ----
_global_ring_buffer: ErrorRingBuffer | None = None


def get_ring_buffer() -> ErrorRingBuffer:
    """获取全局 ErrorRingBuffer 单例"""
    global _global_ring_buffer
    if _global_ring_buffer is None:
        _global_ring_buffer = ErrorRingBuffer()
    return _global_ring_buffer


def _cognitive_enabled() -> bool:
    """检查 cognitive_record 开关 (L3 fallback 闸门)

    FAIL-OPEN: 检查异常视为 False (不登记, 走 L3 降级).
    """
    try:
        from dreambuddy_evolution.agi_config import is_enabled
        return is_enabled("enable_cognitive_record")
    except Exception:  # noqa: BLE001
        return False


def _caller_module_name(fn: Callable) -> str:
    """提取调用方模块名 (用于登记)"""
    try:
        mod = getattr(fn, "__module__", None)
        if mod:
            return mod
        # 退化: 文件名
        fname = getattr(fn, "__code__", None)
        if fname and fname.co_filename:
            return Path(fname.co_filename).stem
    except Exception as e:  # noqa: BLE001
        logger.debug("[FO] caller module resolve fail: %s", e)
    return "unknown"


def _hash_error(error_type: str, error_msg: str) -> str:
    """计算异常签名 hash (error_type + msg 前 200 字符)"""
    try:
        sig = f"{error_type}:{error_msg[:200]}"
        return hashlib.md5(sig.encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return "hash_fail"


def safe_call(fn: Callable, fallback: Any = None, *args: Any, **kwargs: Any) -> Any:
    """FAIL-OPEN 安全调用, 含 L2/L3 分层登记.

    三层分层 (SPEC P0-4):
        L1: try/except 保留 (热路径不破坏)
        L2: cognitive_enabled=True 时, 异常登记到 ring buffer
        L3: cognitive_enabled=False 时, 仅 try/except 不登记

    Args:
        fn: 要调用的函数
        fallback: 异常时返回的降级值 (默认 None)
        *args, **kwargs: 传给 fn 的参数

    Returns:
        fn() 的返回值; 或 fallback (异常时)
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        # L3 闸门: cognitive 关闭时不登记
        if not _cognitive_enabled():
            return fallback
        # L2: 登记
        try:
            error_type = type(exc).__name__
            error_msg = str(exc)[:500]
            entry = {
                "timestamp": int(time.time()),
                "module": _caller_module_name(fn),
                "error_type": error_type,
                "error": error_msg,
                "error_hash": _hash_error(error_type, error_msg),
                "fn_name": getattr(fn, "__name__", "<lambda>"),
            }
            get_ring_buffer().append(entry)
        except Exception as e:  # noqa: BLE001
            # 登记 failure 不破坏 FAIL-OPEN（可观测降级）
            logger.debug("[FO] ring buffer 登记 fail: %s", e)
        return fallback


__all__ = [
    "safe_call",
    "ErrorRingBuffer",
    "get_ring_buffer",
]
