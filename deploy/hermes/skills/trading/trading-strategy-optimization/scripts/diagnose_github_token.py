#!/usr/bin/env python3
"""GitHub Token Diagnostic — determine token type, scopes, and repo permissions."""
import os, requests, sys

token = os.environ.get("GH_TOKEN", sys.argv[1] if len(sys.argv) > 1 else "")
if not token:
    print("Usage: GH_TOKEN=ghp_xxx python3 diagnose_github_token.py")
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
token_type = "fine-grained" if token.startswith("github_pat_") else "classic" if token.startswith("ghp_") else "unknown"

print(f"Token type: {token_type} (prefix: {token[:12]}...)")
print(f"Token length: {len(token)}")

# User info
resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
print(f"\nAuth: {resp.status_code}")
if resp.status_code == 200:
    print(f"  User: {resp.json()['login']}")
else:
    print(f"  FAILED: {resp.json().get('message')}")
    sys.exit(1)

# Scopes
scopes = resp.headers.get("X-OAuth-Scopes", "NONE (fine-grained PAT)")
print(f"  Scopes: {scopes}")

# Rate limit
resp2 = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=10)
if resp2.status_code == 200:
    print(f"  Rate limit: {resp2.headers.get('X-RateLimit-Limit')}")

# Repo access
repo = os.environ.get("GH_REPO", "yunya1991/Dreambuddy-V2")
resp3 = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=10)
print(f"\nRepo '{repo}': {resp3.status_code}")
if resp3.status_code == 200:
    perms = resp3.json().get("permissions", {})
    for k, v in perms.items():
        print(f"  {k}: {v}")
    
    # Test write access
    resp4 = requests.get(f"https://api.github.com/repos/{repo}/contents/README.md", headers=headers, timeout=10)
    print(f"\nWrite test (GET contents): {resp4.status_code}")
    if resp4.status_code == 200:
        print("  → Can read files. For write, check 'push' permission above.")
else:
    print(f"  Error: {resp3.json().get('message')}")

print(f"\nVerdict:")
if token_type == "classic":
    print("  → Should work with git push over HTTPS")
elif token_type == "fine-grained":
    print("  → git push likely FAILS even with push=true")
    print("  → Use GitHub Contents API for uploads")
    print("  → Ensure 'Contents: Read and write' is enabled in token settings")
