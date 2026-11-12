from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path
import os
import tempfile
from threading import Event, Lock
from time import sleep
from gitnest.providers import create_provider
from gitnest.providers.base import ProviderError
from gitnest.images import scan_images, safe_remote_path, safe_local_destination, sha256_bytes, validate_image
from gitnest.image_cache import save_remote_image


def with_provider(repository: dict, token: str):
    return create_provider(repository, token)


class UploadControl:
    """Thread-safe pause/resume/cancel checkpoints between individual file uploads."""
    def __init__(self):
        self._resume = Event()
        self._resume.set()
        self._cancel = Event()

    def pause(self):
        self._resume.clear()

    def resume(self):
        self._resume.set()

    def cancel(self):
        self._cancel.set()
        self._resume.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    @property
    def paused(self):
        return not self._resume.is_set()

    def checkpoint(self):
        while not self._cancel.is_set():
            if self._resume.wait(0.2):
                return not self._cancel.is_set()
        return False


def test_repository(repository: dict, token: str) -> None:
    provider = with_provider(repository, token)
    try:
        provider.test_connection()
    finally:
        provider.close()


def remote_images(repository: dict, token: str):
    provider = with_provider(repository, token)
    try:
        return provider.list_images(repository["base_path"])
    finally:
        provider.close()


def _download_destination(target_root: str, relative_path: str, conflict: str) -> Path | None:
    if conflict not in {"skip", "rename", "overwrite"}:
        raise ValueError("未知的下载冲突策略")
    destination = safe_local_destination(target_root, relative_path)
    if not destination.exists():
        return destination
    if conflict == "skip":
        return None
    if conflict == "overwrite":
        return destination
    stem, suffix = destination.stem, destination.suffix
    for index in range(1, 100000):
        candidate = destination.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法为同名文件生成新名称：{destination.name}")


def download_one(repository: dict, token: str, remote_path: str, target_root: str, conflict: str = "skip"):
    root = repository["base_path"].strip("/")
    rel = remote_path[len(root) + 1:] if root and remote_path.startswith(root + "/") else remote_path
    destination = _download_destination(target_root, rel, conflict)
    if destination is None:
        return None
    provider = with_provider(repository, token)
    temporary_path = None
    try:
        content, _ = provider.get_file(remote_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the destination and atomically replace it, so a failed
        # transfer never leaves a truncated file under the final filename.
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{destination.name}.", suffix=".part",
            dir=destination.parent, delete=False
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
        temporary_path = None
        return destination
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        provider.close()


def download_all(repository: dict, token: str, target_root: str, remote_items: list, conflict: str = "skip", max_workers: int = 4):
    """Download with bounded parallelism and preserve input result order."""
    if not remote_items:
        return []
    worker_count = max(1, min(int(max_workers), 8))
    results = [None] * len(remote_items)

    def download_one_item(index, item):
        try:
            path = download_one(repository, token, item.path, target_root, conflict)
            if path is None:
                return (item.path, "skipped", "本地同名文件已存在，按策略跳过")
            return (item.path, "downloaded", str(path))
        except Exception as exc:
            return (item.path, "failed", str(exc))

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="gitnest-download") as executor:
        futures = {executor.submit(download_one_item, index, item): index
                   for index, item in enumerate(remote_items)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
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
    control: UploadControl | None = None,
    max_workers: int = 3,
    expected_files: dict | None = None,
):
    """Upload files concurrently with one isolated provider/client per worker.

    GitHub/Gitee branch updates can race when several files are committed at once.
    A bounded retry handles non-fast-forward/conflict responses without sharing
    an HTTP client between threads. Results are returned in the original input order.
    """
    if conflict not in {"skip", "overwrite", "rename"}:
        raise ValueError("未知的上传冲突策略")
    max_workers = max(1, min(int(max_workers), 5))
    base = repository["base_path"].strip("/")
    subpath = remote_subpath.strip().replace("\\", "/").strip("/")
    if subpath:
        subpath = safe_remote_path(subpath)
    remote_root = "/".join(part for part in (base, subpath) if part)
    root = Path(relative_to).expanduser().resolve() if relative_to else None
    progress_lock = Lock()
    completed_count = 0
    results_by_index = {}

    def notify(index, total, path, state, message):
        if progress_callback:
            try:
                progress_callback(index, total, path, state, message)
            except Exception:
                # UI observers must never interrupt repository writes.
                pass

    def upload_one(index, selected):
        nonlocal completed_count
        file_path = Path(selected).expanduser().resolve()
        display_path = str(selected)
        relative = display_path
        provider = None

        def finish(state, message):
            nonlocal completed_count
            with progress_lock:
                completed_count += 1
                current = completed_count
            result = (relative, state, message)
            results_by_index[index] = result
            notify(current, len(paths), relative, state, message)
            return result

        if control is not None and not control.checkpoint():
            results_by_index[index] = (display_path, "queued", "任务取消，等待下次继续")
            return results_by_index[index]

        notify(completed_count + 1, len(paths), display_path, "uploading", "正在上传")
        try:
            if not file_path.is_file():
                raise ValueError("文件不存在或不是普通文件")
            relative = file_path.relative_to(root).as_posix() if root else file_path.name
            expected = (expected_files or {}).get(str(file_path))
            before = file_path.stat()
            if expected and (before.st_size != expected.get("size") or before.st_mtime_ns != expected.get("mtime_ns")):
                raise ValueError("文件自加入上传队列后已发生变化，请重新选择文件再上传")
            content = file_path.read_bytes()
            after = file_path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("上传期间本地文件发生变化，请重新选择文件再上传")
            validate_image(content, relative)
            remote_path = safe_remote_path(f"{remote_root}/{relative}" if remote_root else relative)
            provider = with_provider(repository, token)

            # Contents APIs create a commit per file. Retry branch update conflicts
            # after refreshing the remote SHA; never reuse a client across threads.
            for attempt in range(4):
                if control is not None and not control.checkpoint():
                    return finish("queued", "任务取消，等待下次继续")
                remote_sha = None
                try:
                    _, remote_sha = provider.get_file(remote_path)
                    exists = True
                except ProviderError as exc:
                    if exc.status_code == 404:
                        exists = False
                    else:
                        raise

                target_path = remote_path
                target_sha = remote_sha if exists and conflict == "overwrite" else None
                if exists and conflict == "skip":
                    return finish("skipped", "远程已存在，按策略跳过")
                if exists and conflict == "rename":
                    p = Path(relative)
                    candidate = f"{p.stem}_{sha256_bytes(content)[:8]}{p.suffix}"
                    renamed = (p.parent / candidate).as_posix()
                    target_path = safe_remote_path(f"{remote_root}/{renamed}" if remote_root else renamed)
                    try:
                        provider.get_file(target_path)
                        return finish("skipped", f"重命名目标已存在：{target_path}")
                    except ProviderError as exc:
                        if exc.status_code != 404:
                            raise
                    target_sha = None

                try:
                    provider.put_file(
                        target_path, content, f"{commit_prefix}: {relative}", sha=target_sha
                    )
                    return finish("uploaded", f"已提交到 {target_path}")
                except ProviderError as exc:
                    if exc.status_code == 409 and attempt < 3:
                        sleep(0.25 * (attempt + 1))
                        continue
                    raise
            raise RuntimeError("远程分支持续发生提交冲突，请稍后重试")
        except Exception as exc:
            return finish("failed", str(exc))
        finally:
            if provider is not None:
                provider.close()

    if not paths:
        return []
    # Bound queued futures so huge folders do not consume unbounded memory.
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gitnest-upload") as executor:
        pending = {}
        next_index = 0
        while next_index < len(paths) and len(pending) < max_workers:
            pending[executor.submit(upload_one, next_index, paths[next_index])] = next_index
            next_index += 1
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                try:
                    future.result()
                except Exception as exc:
                    results_by_index[index] = (str(paths[index]), "failed", str(exc))
                if next_index < len(paths):
                    pending[executor.submit(upload_one, next_index, paths[next_index])] = next_index
                    next_index += 1
    return [results_by_index[index] for index in range(len(paths))]


def upload_folder(
    repository: dict,
    token: str,
    local_root: str,
    conflict: str = "skip",
    commit_prefix: str = "GitNest upload",
    remote_subpath: str = "",
    progress_callback=None,
    max_workers: int = 3,
):
    root = Path(local_root).expanduser().resolve()
    files = scan_images(root)
    if not files:
        raise ValueError("所选目录中没有找到支持的图片")
    return upload_paths(
        repository, token, files, conflict, commit_prefix, remote_subpath, root,
        progress_callback=progress_callback, max_workers=max_workers,
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
    """Compare file content, not provider-specific Git blob hashes."""
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
