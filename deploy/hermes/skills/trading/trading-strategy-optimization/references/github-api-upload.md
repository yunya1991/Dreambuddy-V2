# GitHub API Upload Fallback

Use when `git push` fails (auth issues, network timeout, or repo too large).

## Token Type Diagnosis

```python
import requests
token = "ghp_xxx"  # or github_pat_xxx
headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
resp = requests.get("https://api.github.com/user", headers=headers, timeout=10)
# Check: resp.headers.get("X-OAuth-Scopes")
#   "NONE" = fine-grained token
#   "repo,user" = classic token

# Check repo permissions:
resp2 = requests.get("https://api.github.com/repos/{owner}/{repo}", headers=headers)
print(resp2.json()["permissions"])
```

## Fallback Chain

1. **Classic `ghp_` token → `git push`** (fastest, full repo sync)
2. **Fine-grained `github_pat_` + Contents:Write → GitHub Contents API** (best for ≤5 files)
3. **No valid token → commit locally, tell user to push manually**

## Contents API Upload (Option 2)

```python
api = "https://api.github.com/repos/{owner}/{repo}/contents"

for path, local_file in files.items():
    with open(local_file, "r") as f:
        content = f.read()
    
    # Get current SHA for updates
    sha = None
    r = requests.get(f"{api}/{path}", headers=headers, timeout=15)
    if r.status_code == 200:
        sha = r.json()["sha"]
    
    payload = {
        "message": "commit message",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    
    r = requests.put(f"{api}/{path}", headers=headers, json=payload, timeout=15)
    # 200 = updated, 201 = created
```

## Clean git commit (Option 3 prep)

```bash
# In dirty repo (many unstaged deletions from worktree operations):
git reset HEAD .           # unstage everything
git add file1 file2 ...    # stage ONLY target files
git status --short | head  # verify before commit
git commit -m "message"
```

## Auth Issues by Token Type

| Symptom | Token Type | Fix |
|---------|-----------|-----|
| `git push` → 403 "Permission denied" | fine-grained | Use Contents API |
| `git push` → hangs, no error | classic (auth OK) | Network slow; use Contents API |
| API PUT → 403 "Resource not accessible" | fine-grained | Token needs Contents:Write scope |
| API PUT → 200/201 OK | either | Success |
