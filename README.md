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

The normal test suite uses \`httpx.MockTransport\` for deterministic API-contract tests; these do not prove that a real account can upload, download, or render thumbnails. Optional live-account smoke tests are provided in \`tests/test_live_accounts.py\`. They use the same provider and service functions as the desktop app and verify a real upload, remote listing, read-back SHA-256, local download, and generated JPEG thumbnail for each platform.

Run the live tests only against dedicated test repositories (or a repository where you are comfortable leaving test artifacts). Each run creates a unique image under \`.gitnest-live-tests/<random-id>/live_probe.png\`. It intentionally does not delete remote files because GitNest currently has no remote-delete feature. Remove the test artifact manually from the repository after verification if desired.

PowerShell example (use your own test repository values; never commit tokens):

\`\`\`powershell
$env:GITHUB_TOKEN = "your-github-token"
$env:GITHUB_OWNER = "your-owner"
$env:GITHUB_REPO = "your-test-repository"
$env:GITHUB_BRANCH = "main"  # optional for GitHub; blank uses the repository default

$env:GITEE_TOKEN = "your-gitee-private-token"
$env:GITEE_OWNER = "your-gitee-username"
$env:GITEE_REPO = "your-test-repository"
$env:GITEE_BRANCH = "master"

python -m pytest -v tests/test_live_accounts.py
\`\`\`

Each platform test is skipped when its required environment variables are absent. GitHub requires \`GITHUB_TOKEN\`, \`GITHUB_OWNER\`, and \`GITHUB_REPO\`; \`GITHUB_BRANCH\` is optional. Gitee requires \`GITEE_TOKEN\`, \`GITEE_OWNER\`, \`GITEE_REPO\`, and \`GITEE_BRANCH\`. The test output never prints token values. Keep tokens in environment variables or the desktop credential vault, not source files, command-line arguments, screenshots, or logs.

## Tests

\`\`\`powershell
python -m pytest
python -m compileall -q .
\`\`\`
