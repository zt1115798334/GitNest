from pathlib import Path
from gitnest.providers import create_provider
from gitnest.providers.base import ProviderError
from gitnest.images import scan_images, safe_remote_path, safe_local_destination, sha256_bytes, validate_image
from gitnest.image_cache import save_remote_image

def with_provider(repository: dict, token: str):
    return create_provider(repository, token)

def test_repository(repository: dict, token: str) -> None:
    provider = with_provider(repository, token)
    try: provider.test_connection()
    finally: provider.close()

def remote_images(repository: dict, token: str):
    provider = with_provider(repository, token)
    try: return provider.list_images(repository["base_path"])
    finally: provider.close()

def download_one(repository: dict, token: str, remote_path: str, target_root: str):
    provider = with_provider(repository, token)
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
    provider=with_provider(repository, token)
    results=[]
    base=repository["base_path"].strip("/")
    try:
        for file_path in files:
            relative=file_path.relative_to(root).as_posix()
            remote_path=safe_remote_path(f"{base}/{relative}" if base else relative)
            try:
                content=file_path.read_bytes(); validate_image(content, relative)
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
                    p=Path(relative); candidate=f"{p.stem}_{sha256_bytes(content)[:8]}{p.suffix}"
                    remote_path=safe_remote_path(f"{base}/{p.parent.as_posix()}/{candidate}" if str(p.parent)!="." and base else (f"{base}/{candidate}" if base else candidate))
                    try:
                        _, existing_sha=provider.get_file(remote_path)
                        results.append((relative,"skipped",f"重命名目标已存在：{remote_path}")); continue
                    except ProviderError as exc:
                        if exc.status_code != 404: raise
                    remote_sha=None
                if exists and conflict == "overwrite": pass
                provider.put_file(remote_path, content, f"{commit_prefix}: {relative}", sha=remote_sha)
                results.append((relative, "uploaded", f"已提交到 {remote_path}"))
            except Exception as exc: results.append((relative, "failed", str(exc)))
        return results
    finally: provider.close()

def cache_remote_thumbnails(repository: dict, token: str, remote_items: list, cache_root: str):
    """Download remote images once and create local originals + thumbnails."""
    provider = with_provider(repository, token)
    results = {}
    try:
        for item in remote_items:
            try:
                content, _ = provider.get_file(item.path)
                original, thumbnail = save_remote_image(content, item.path, cache_root)
                results[item.path] = {"original": str(original), "thumbnail": str(thumbnail), "error": None}
            except Exception as exc:
                results[item.path] = {"original": None, "thumbnail": None, "error": str(exc)}
        return results
    finally:
        provider.close()

def compare_folders(repository: dict, token: str, local_root: str, remote_items: list):
    """Compare file content, not provider-specific Git blob hashes.

    A single provider client is reused for all remote reads. SHA-256 values and
    byte sizes are returned to make every comparison explainable in the UI.
    """
    root = Path(local_root).expanduser().resolve()
    local_files = scan_images(root)
    base = repository["base_path"].strip("/")
    local_map = {p.relative_to(root).as_posix(): p for p in local_files}
    remote_map = {}
    for item in remote_items:
        rel = item.path[len(base) + 1:] if base and item.path.startswith(base + "/") else item.path
        remote_map[rel] = item

    rows = []
    provider = with_provider(repository, token)
    try:
        for rel in sorted(set(local_map) | set(remote_map), key=str.casefold):
            local_path, remote_item = local_map.get(rel), remote_map.get(rel)
            if local_path and not remote_item:
                content = local_path.read_bytes()
                rows.append({"path": rel, "status": "local_only", "action": "upload",
                             "local_size": len(content), "remote_size": None,
                             "local_sha256": sha256_bytes(content), "remote_sha256": None})
                continue
            if remote_item and not local_path:
                rows.append({"path": rel, "status": "remote_only", "action": "download",
                             "local_size": None, "remote_size": remote_item.size,
                             "local_sha256": None, "remote_sha256": None})
                continue
            try:
                local_content = local_path.read_bytes()
                remote_content, _ = provider.get_file(remote_item.path)
                local_hash = sha256_bytes(local_content)
                remote_hash = sha256_bytes(remote_content)
                same = local_hash == remote_hash
                rows.append({"path": rel, "status": "same" if same else "different",
                             "action": "none" if same else "conflict",
                             "local_size": len(local_content), "remote_size": len(remote_content),
                             "local_sha256": local_hash, "remote_sha256": remote_hash})
            except Exception as exc:
                rows.append({"path": rel, "status": "error", "action": "retry",
                             "local_size": local_path.stat().st_size if local_path.exists() else None,
                             "remote_size": remote_item.size, "local_sha256": None,
                             "remote_sha256": None, "error": str(exc)})
    finally:
        provider.close()
    return rows
