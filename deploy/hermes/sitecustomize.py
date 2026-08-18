"""Force TLS 1.2 + bypass macOS system proxy for Hermes on macOS.

OpenSSL 3.5.7 TLS 1.3 handshake fails with Aliyun NLB + Feishu API.
Patches both ssl.create_default_context (httpx) and urllib3 (requests/lark_oapi).
"""
import os as _os
import ssl as _ssl

# 1. Bypass macOS system proxy
_os.environ.setdefault('no_proxy', '*')
_os.environ.setdefault('NO_PROXY', '*')
_os.environ.setdefault('http_proxy', '')
_os.environ.setdefault('https_proxy', '')
_os.environ.setdefault('HTTP_PROXY', '')
_os.environ.setdefault('HTTPS_PROXY', '')

# 2. Patch ssl.create_default_context (used by httpx)
_orig_create_default_context = _ssl.create_default_context

def _patched_create_default_context(*args, **kwargs):
    ctx = _orig_create_default_context(*args, **kwargs)
    ctx.maximum_version = _ssl.TLSVersion.TLSv1_2
    return ctx

_ssl.create_default_context = _patched_create_default_context

# 3. Patch urllib3 create_urllib3_context (used by requests/lark_oapi/feishu SDK)
try:
    import urllib3.util.ssl_ as _urllib3_ssl
    _orig_urllib3_create = _urllib3_ssl.create_urllib3_context

    def _patched_urllib3_create(*args, **kwargs):
        ctx = _orig_urllib3_create(*args, **kwargs)
        ctx.maximum_version = _ssl.TLSVersion.TLSv1_2
        return ctx

    _urllib3_ssl.create_urllib3_context = _patched_urllib3_create
except ImportError:
    pass
