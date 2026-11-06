# GitNest

**GitNest** is a Python desktop application for managing image assets in GitHub and Gitee repositories. It supports remote browsing, thumbnail gallery, image preview, batch upload/download, SHA-256 content comparison, conflict handling, and operation history.

## Runtime

- Python **3.14.8** (project target; \`requires-python >=3.14\`)
- Flet 0.86.5
- Windows 10/11, macOS and Linux (keyring backend availability depends on desktop environment)

## Quick start (Windows)

\`\`\`powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
\`\`\`

If PowerShell blocks activation, run \`.venv\Scripts\activate.bat\` from CMD instead.

## Features

- Multiple GitHub and Gitee repositories and branches.
- PAT / Gitee private-token authentication. Tokens are stored in the OS credential vault through \`keyring\`; they are never written to SQLite or logs.
- Recursive remote image listing, local image folder scanning, image previews and direct download.
- Remote thumbnail gallery: originals and JPEG thumbnails are cached locally; cache keys use the full repository path to avoid collisions between same-named files.
- Batch uploads with create/update detection, per-file results and commit messages.
- Batch downloads that preserve paths relative to the configured remote image directory.
- Two-way comparison by actual file-content SHA-256. Same-path files report both hashes and byte sizes; local-only, remote-only, identical, different and read-error states are distinguished.
- SQLite operation history and safe error reporting.
- Overwrite mode requires an explicit confirmation checkbox before upload starts.

## Configure a repository

1. Open **Repositories** and choose GitHub or Gitee.
2. Enter owner, repository, branch and image root (e.g. \`images\`).
3. Create a token with only the required repository content read/write permissions.
4. Save the repository and test the connection.

GitHub fine-grained PAT: grant access to this repository and \`Contents: Read and write\`. Gitee: create a private token with repository read/write access according to the permissions offered by your Gitee account.

## Safety

- Existing remote files are never overwritten silently. Choose an explicit conflict policy before uploading.
- Sync preview is non-destructive. GitNest does not delete remote files.
- Path traversal is rejected; downloaded files must remain inside the selected local directory.
- API tokens are held in memory only while a request is being made and persisted via the OS credential manager.
- Do not use an account password. Use access tokens.

## API notes and live verification

GitHub uses the REST Contents API. Gitee uses its v5 repository Contents API. Provider API limits and maximum content sizes apply. GitHub's Contents API is not intended for very large files; use Git LFS or a future Git transport adapter for large assets.

The test suite uses \`httpx.MockTransport\` to exercise GitHub and Gitee request contracts (authentication, repository/branch checks, Contents listing, file read and file write) without real credentials. These are deterministic API-contract tests, not a live account integration test. For a real account, configure its token in the desktop app, use **测试连接**, then load the remote image directory and perform a controlled upload/download against a test repository.

## Tests

\`\`\`powershell
python -m pytest
python -m compileall -q .
\`\`\`
