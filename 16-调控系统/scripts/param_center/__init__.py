"""兼容 shim：param_center 已迁至 4-MEMORY/9-工具与接口/param_center。

旧路径（16-调控系统/scripts/param_center）继续可用：
  - 把本包 ``__path__`` 指向新目录，子模块仍以 ``param_center.*`` 名称加载，
    全进程只有一份模块对象（避免 isinstance / 异常类型失效）；
  - 补齐包导入期需要的 sys.path（11 的 scripts 与新目录父级）。
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_THIS = _Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parents[3]  # dreambuddy-v2
_NEW_DIR = _PROJECT_ROOT / "4-MEMORY" / "9-工具与接口" / "param_center"
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"

if _NEW_DIR.is_dir():
    __path__ = [str(_NEW_DIR)]

for _p in (_YIJING_SCRIPTS, _NEW_DIR.parent):
    _sp = str(_p)
    if _sp not in _sys.path:
        _sys.path.insert(0, _sp)
