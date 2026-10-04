"""截图对比共享工具 — 像素级 numpy diff

抽离自 core/result_verifier.py:_compare_screenshots，供：
- ResultVerifier（Playwright 截图 bytes vs 基准文件）
- DesktopAssertions.ui_visual_match（文件路径 vs 文件路径）

两种入参形态：
- compare_screenshot_bytes(baseline_path, current_bytes) -> float  # Playwright Page.screenshot() 返回 bytes
- compare_screenshot_paths(baseline_path, current_path) -> float    # 双方都是文件路径（线5 模式 B 截图）
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Union

from PIL import Image
import numpy as np


def _load_image_bytes(path: str) -> Image.Image:
    return Image.open(path).convert("RGB")


def _load_bytes(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b)).convert("RGB")


def _resize_to_baseline(baseline: Image.Image, current: Image.Image) -> Image.Image:
    if baseline.size != current.size:
        current = current.resize(baseline.size)
    return current


def _diff_percentage(baseline_arr: np.ndarray, current_arr: np.ndarray) -> float:
    diff = np.abs(baseline_arr.astype(np.float32) - current_arr.astype(np.float32))
    return float(np.mean(diff) / 255.0)


def compare_screenshot_bytes(baseline_path: str, current_bytes: bytes) -> float:
    """对比基准文件 vs bytes 截图，返回差异比例（0-1）。

    与原 ResultVerifier._compare_screenshots 行为一致。
    """
    baseline = _load_image_bytes(baseline_path)
    current = _load_bytes(current_bytes)
    current = _resize_to_baseline(baseline, current)
    return _diff_percentage(np.array(baseline), np.array(current))


def compare_screenshot_paths(baseline_path: str, current_path: str) -> float:
    """对比两个截图文件，返回差异比例（0-1）。

    供 DesktopAssertions.ui_visual_match 使用。
    """
    baseline = _load_image_bytes(baseline_path)
    current = _load_image_bytes(current_path)
    current = _resize_to_baseline(baseline, current)
    return _diff_percentage(np.array(baseline), np.array(current))


def save_diff_screenshot(baseline_path: str, current_bytes: bytes, diff_path: str) -> None:
    """生成差异图（红色高亮差异区域）。保留与原 _save_diff_screenshot 一致行为。"""
    baseline = _load_image_bytes(baseline_path)
    current = _load_bytes(current_bytes)
    current = _resize_to_baseline(baseline, current)

    baseline_arr = np.array(baseline)
    current_arr = np.array(current)

    diff_mask = np.any(
        np.abs(baseline_arr.astype(int) - current_arr.astype(int)) > 30, axis=2
    )
    diff_arr = current_arr.copy()
    diff_arr[diff_mask] = [255, 0, 0]
    Image.fromarray(diff_arr).save(diff_path)


def save_diff_screenshot_paths(baseline_path: str, current_path: str, diff_path: str) -> None:
    """双方都是文件路径版本的差异图保存。"""
    baseline = _load_image_bytes(baseline_path)
    current = _load_image_bytes(current_path)
    current = _resize_to_baseline(baseline, current)

    baseline_arr = np.array(baseline)
    current_arr = np.array(current)

    diff_mask = np.any(
        np.abs(baseline_arr.astype(int) - current_arr.astype(int)) > 30, axis=2
    )
    diff_arr = current_arr.copy()
    diff_arr[diff_mask] = [255, 0, 0]
    Image.fromarray(diff_arr).save(diff_path)
