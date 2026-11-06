from pathlib import Path
from gitnest.providers import create_provider
from gitnest.providers.base import ProviderError
from gitnest.images import scan_images, safe_remote_path, safe_local_destination, sha256_bytes, validate_image

def test_repository(repository: dict, token: str) -> None:
    provider = create_provider(repository, token)
    try: provider.test_connection()
    finally: provider.close()

def remote_images(repository: dict, token: str):
    provider = create_provider(repository, token)
    try: return provider.list_images(repository["base_path"])
    finally: provider.close()

def download_one(repository: dict, token: str, remote_path: str, target_root: str):
    provider = create_provider(repository, token)
    try:
        root = repository["base_path"].strip("/")
        rel = remote_path[len(root)+1:] if root and remote_path.startswith(root + "/") else remote_path
        destination = safe_local_destination(target_root, rel)
        content, _ = provider.get_file(remote_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination
    finally: provider.close()

def download_all(repository: dict, token: str, target_root: str, remote_items: list):
    results=[]
    for item in remote_items:
        try:
            path=download_one(repository, token, item.path, target_root)
            results.append((item.path, True, str(path)))
        except Exception as exc: results.append((item.path, False, str(exc)))
    return results

def upload_folder(repository: dict, token: str, local_root: str, conflict: str = "skip", commit_prefix: str = "GitNest upload"):
    root=Path(local_root).expanduser().resolve()
    files=scan_images(root)
    provider=create_provider(repository, token)
    results=[]
    base=repository["base_path"].strip("/")
    try:
        for file_path in files:
            relative=file_path.relative_to(root).as_posix()
            remote_path=safe_remote_path(f"{base}/{relative}" if base else relative)
            try:
                content=file_path.read_bytes()
                validate_image(content, relative)
                remote_sha=None
                try:
                    _, remote_sha=provider.get_file(remote_path)
                    exists=True
                except ProviderError as exc:
                    if exc.status_code == 404: exists=False
                    else: raise
                if exists and conflict == "skip":
                    results.append((relative, "skipped", "远程已存在，按策略跳过")); continue
                if exists and conflict == "rename":
                    p=Path(relative)
                    candidate=f"{p.stem}_{sha256_bytes(content)[:8]}{p.suffix}"
                    parent=p.parent.as_posix()
                    renamed=f"{base}/{parent}/{candidate}" if base and parent != "." else (f"{base}/{candidate}" if base else candidate)
                    remote_path=safe_remote_path(renamed)
                    try:
                        provider.get_file(remote_path)
                        results.append((relative,"skipped",f"重命名目标已存在：{remote_path}")); continue
                    except ProviderError as exc:
                        if exc.status_code != 404: raise
                    remote_sha=None
                provider.put_file(remote_path, content, f"{commit_prefix}: {relative}", sha=remote_sha)
                results.append((relative, "uploaded", f"已提交到 {remote_path}"))
            except Exception as exc: results.append((relative, "failed", str(exc)))
        return results
    finally: provider.close()

def compare_folders(repository: dict, token: str, local_root: str, remote_items: list):
    root=Path(local_root).expanduser().resolve()
    local_files=scan_images(root)
    base=repository["base_path"].strip("/")
    local_map={p.relative_to(root).as_posix():p for p in local_files}
    remote_map={}
    for item in remote_items:
        rel=item.path[len(base)+1:] if base and item.path.startswith(base+"/") else item.path
        remote_map[rel]=item
    rows=[]
    provider=create_provider(repository, token)
    try:
        for rel in sorted(set(local_map)|set(remote_map), key=str.casefold):
            lp, ri=local_map.get(rel), remote_map.get(rel)
            if lp and not ri: rows.append({"path":rel,"status":"local_only","action":"upload"})
            elif ri and not lp: rows.append({"path":rel,"status":"remote_only","action":"download"})
            else:
                local_hash=sha256_bytes(lp.read_bytes())
                remote_content,_=provider.get_file(ri.path)
                remote_hash=sha256_bytes(remote_content)
                rows.append({"path":rel,"status":"same" if local_hash==remote_hash else "different",
                             "action":"none" if local_hash==remote_hash else "conflict"})
    finally: provider.close()
    return rows
