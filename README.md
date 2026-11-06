# GitNest

**GitNest** is a Python desktop application for managing image assets in GitHub and Gitee repositories. It supports remote browsing, image preview, batch upload/download, content-hash comparison, conflict handling, and operation history.

## Runtime

- Python **3.14.8** (project target; `requires-python >=3.14`)
- Flet 0.86.5
- Windows 10/11, macOS and Linux (keyring backend availability depends on desktop environment)

## Quick start (Windows)

```powershell
py -3.14 -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

## Features

- Multiple GitHub and Gitee repositories and branches.
- PAT / Gitee private-token authentication. Tokens are stored in the OS credential vault through `keyring`; they are never written to SQLite or logs.
- Recursive remote image listing, local image folder scanning, image previews and direct download.
- Batch uploads with create/update detection, per-file results and commit messages.
- Batch downloads that preserve paths relative to the configured remote image directory.
- Two-way comparison by SHA-256 content, with explicit upload/download/replace/skip choices. No automatic remote deletion.
- SQLite operation history and safe error reporting.

## Configure a repository

1. Open **Repositories** and choose GitHub or Gitee.
2. Enter owner, repository, branch and image root (e.g. `images`).
3. Create a token with only the required repository content read/write permissions.
4. Save the repository and test the connection.

GitHub fine-grained PAT: grant access to this repository and `Contents: Read and write`. Gitee: create a private token with repository read/write access according to the permissions offered by your Gitee account.

## Safety

- Existing remote files are never overwritten silently. Choose an explicit conflict policy before uploading.
- Sync preview is non-destructive. GitNest does not delete remote files.
- Path traversal is rejected; downloaded files must remain inside the selected local directory.
- API tokens are held in memory only while a request is being made and persisted via the OS credential manager.
- Do not use an account password. Use access tokens.

## API notes

GitHub uses the REST Contents API. Gitee uses its v5 repository Contents API. Provider API limits and maximum content sizes apply. GitHub's Contents API is not intended for very large files; use Git LFS or a future Git transport adapter for large assets.

## Tests

```powershell
python -m pytest
python -m compileall -q .
```

Unit tests use mocked provider responses and do not require real tokens.
