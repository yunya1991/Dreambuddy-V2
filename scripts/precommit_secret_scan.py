#!/usr/bin/env python3
"""G2 pre-commit 门禁：只扫描 staged 文件中的密钥/敏感文件泄露。

用法（由 .pre-commit-config.yaml 调用，pre-commit 只传入 staged 文件名）：
    python3 scripts/precommit_secret_scan.py [files...]

规则：
  1. 文件名命中敏感名单（.env / *.pem / *.key / id_rsa / credentials.json ...）→ 拦截
  2. 内容命中密钥特征（私钥块 / 云厂商 / 大模型 / GitHub / Slack token / 长字面量赋值）→ 拦截
  3. 允许行内豁免：命中行尾带 `# secret-scan: allow` 或 `// secret-scan: allow`
  4. 占位符自动放行：含 your/example/placeholder/xxx/${/{{/getenv/os.environ 等

退出码：0 = 通过；1 = 发现疑似密钥（阻断 commit）。
只打印 文件:行号:规则名，绝不打印命中值本身。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "secret.json",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}

# (规则名, 正则)
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key-block",
        re.compile(r"-----BEGIN\s+(?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
    ),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai-like-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "hex-private-key-assignment",
        re.compile(
            r"(?i)\b(?:private_key|priv_key|signer_key|secret_key)\b\s*[:=]\s*"
            r"['\"](?:0x)?[0-9a-f]{64}['\"]"
        ),
    ),
    (
        "literal-assignment",
        re.compile(
            r"(?i)\b(?:api_key|apikey|api_secret|secret|passwd|password|token|access_key)\b"
            r"\s*[:=]\s*['\"][A-Za-z0-9_\-/+]{16,}['\"]"
        ),
    ),
]

PLACEHOLDER_MARKERS = (
    "your",
    "example",
    "placeholder",
    "dummy",
    "sample",
    "xxxx",
    "${",
    "{{",
    "%s",
    "getenv",
    "os.environ",
    "process.env",
    "redacted",
    "<",
    "***",
)
ALLOW_MARKERS = ("secret-scan: allow", "pragma: allowlist secret")
MAX_BYTES = 2 * 1024 * 1024


def is_sensitive_name(path: Path) -> bool:
    name = path.name.lower()
    return name in SENSITIVE_FILENAMES or path.suffix.lower() in SENSITIVE_SUFFIXES


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    if is_sensitive_name(path):
        findings.append(f"{path}:0:sensitive-filename")
        return findings
    try:
        if path.stat().st_size > MAX_BYTES:
            return findings
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return findings

    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(marker in line for marker in ALLOW_MARKERS):
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            continue
        for rule, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(f"{path}:{lineno}:{rule}")
                break
    return findings


def main(argv: list[str]) -> int:
    files = [Path(p) for p in argv if p]
    findings: list[str] = []
    for path in files:
        if not path.is_file():
            continue
        findings.extend(scan_file(path))

    if not findings:
        print(f"secret-scan: OK ({len(files)} staged files)")
        return 0

    print("secret-scan: 发现疑似密钥/敏感文件，已阻断 commit：", file=sys.stderr)
    for item in findings:
        print(f"  {item}", file=sys.stderr)
    print(
        "确认非真实密钥可在该行加 `# secret-scan: allow`，"
        "真实密钥请改用环境变量并从历史中移除。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
