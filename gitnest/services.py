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

def upload_paths(
    repository: dict,
    token: str,
    paths: list[str | Path],
    conflict: str = "skip",
    commit_prefix: str = "GitNest upload",
    remote_subpath: str = "",
    relative_to: str | Path | None = None,
    progress_callback=None,
):
    """Upload selected image paths and optionally report each completed file."""
    if conflict not in {"skip", "overwrite", "rename"}:
        raise ValueError("未知的上传冲突策略")
    base = repository["base_path"].strip("/")
    subpath = remote_subpath.strip().replace("\\", "/").strip("/")
    if subpath:
        subpath = safe_remote_path(subpath)
    remote_root = "/".join(part for part in (base, subpath) if part)
    root = Path(relative_to).expanduser().resolve() if relative_to else None
    provider = with_provider(repository, token)
    results = []

    def record(path, state, message):
        results.append((path, state, message))
        if progress_callback:
            try:
                progress_callback(len(results), len(paths), path, state, message)
            except Exception:
                # A UI progress observer must never interrupt a repository write.
                pass

    try:
        for selected in paths:
            file_path = Path(selected).expanduser().resolve()
            try:
                if not file_path.is_file():
                    raise ValueError("文件不存在或不是普通文件")
                relative = file_path.relative_to(root).as_posix() if root else file_path.name
                content = file_path.read_bytes()
                validate_image(content, relative)
                remote_path = safe_remote_path(f"{remote_root}/{relative}" if remote_root else relative)
                remote_sha = None
                try:
                    _, remote_sha = provider.get_file(remote_path)
                    exists = True
                except ProviderError as exc:
                    if exc.status_code == 404:
                        exists = False
                    else:
                        raise
                if exists and conflict == "skip":
                    record(relative, "skipped", "远程已存在，按策略跳过")
                    continue
                if exists and conflict == "rename":
                    p = Path(relative)
                    candidate = f"{p.stem}_{sha256_bytes(content)[:8]}{p.suffix}"
                    renamed = (p.parent / candidate).as_posix()
                    remote_path = safe_remote_path(f"{remote_root}/{renamed}" if remote_root else renamed)
                    try:
                        provider.get_file(remote_path)
                        record(relative, "skipped", f"重命名目标已存在：{remote_path}")
                        continue
                    except ProviderError as exc:
                        if exc.status_code != 404:
                            raise
                    remote_sha = None
                provider.put_file(
                    remote_path, content, f"{commit_prefix}: {relative}",
                    sha=remote_sha if exists and conflict == "overwrite" else None,
                )
                record(relative, "uploaded", f"已提交到 {remote_path}")
            except Exception as exc:
                record(str(selected), "failed", str(exc))
        return results
    finally:
        provider.close()


def upload_folder(
    repository: dict,
    token: str,
    local_root: str,
    conflict: str = "skip",
    commit_prefix: str = "GitNest upload",
    remote_subpath: str = "",
    progress_callback=None,
):
    root = Path(local_root).expanduser().resolve()
    files = scan_images(root)
    if not files:
        raise ValueError("所选目录中没有找到支持的图片")
    return upload_paths(
        repository, token, files, conflict, commit_prefix, remote_subpath, root,
        progress_callback=progress_callback,
    )

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
