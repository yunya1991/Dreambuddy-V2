"""自动加载模块（sitecustomize 机制），启动时自动注入 FastAPI 兼容补丁。

通过 PYTHONPATH=. 或在 site-packages 中放置本文件即可自动加载。
为了让 Freqtrade 的 webserver.py 能正常启动（FastAPI 0.103+ 移除 add_event_handler）。
"""
try:
    import fastapi_compat_shim
    fastapi_compat_shim.apply()
except Exception as e:  # noqa: BLE001
    # 静默失败 - 不要阻断 Python 启动
    import sys
    print(f"[usercustomize] WARN: fastapi_compat_shim apply failed: {e}", file=sys.stderr)
