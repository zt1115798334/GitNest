"""Opt-in live-account smoke tests for GitHub and Gitee.

These tests are skipped unless the corresponding environment variables are set.
They create a uniquely named image under .gitnest-live-tests/<run-id>/ and
intentionally leave it in the remote repository (GitNest has no remote-delete
feature). Use a dedicated test repository or remove the artifact manually.
"""
from __future__ import annotations

import os
import uuid
from io import BytesIO

import pytest
from PIL import Image

from gitnest.images import sha256_bytes
from gitnest.services import cache_remote_thumbnails, download_one, remote_images, upload_folder


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (96, 64), (37, 116, 180)).save(buffer, format="PNG")
    return buffer.getvalue()


def _live_round_trip(platform: str, tmp_path) -> None:
    prefix = platform.upper()
    token = os.getenv(f"{prefix}_TOKEN")
    owner = os.getenv(f"{prefix}_OWNER")
    repo_name = os.getenv(f"{prefix}_REPO")
    branch = os.getenv(f"{prefix}_BRANCH", "").strip()

    if not all((token, owner, repo_name)):
        pytest.skip(f"set {prefix}_TOKEN, {prefix}_OWNER and {prefix}_REPO to enable live test")
    if platform == "gitee" and not branch:
        pytest.skip("set GITEE_BRANCH to the target Gitee branch")

    run_id = uuid.uuid4().hex
    remote_root = f".gitnest-live-tests/{run_id}"
    repository = {
        "platform": platform,
        "owner": owner,
        "repo": repo_name,
        "branch": branch,
        "base_path": remote_root,
    }

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "live_probe.png"
    expected = _png_bytes()
    source_file.write_bytes(expected)

    # Upload through the same service path used by the desktop application.
    upload_results = upload_folder(repository, token, str(source_dir), conflict="skip")
    assert len(upload_results) == 1, upload_results
    assert upload_results[0][1] == "uploaded", upload_results

    remote_path = f"{remote_root}/live_probe.png"
    listed = remote_images(repository, token)
    matching = [item for item in listed if item.path == remote_path]
    assert len(matching) == 1, f"uploaded image not found in remote listing: {remote_path}"

    # Read back from the live API and compare the actual bytes.
    from gitnest.providers import create_provider

    provider = create_provider(repository, token)
    try:
        downloaded, _ = provider.get_file(remote_path)
    finally:
        provider.close()
    assert sha256_bytes(downloaded) == sha256_bytes(expected), "remote content differs after upload"

    # Exercise the real download service and verify the local file.
    download_root = tmp_path / "download"
    downloaded_path = download_one(repository, token, remote_path, str(download_root))
    assert downloaded_path.read_bytes() == expected

    # Exercise the real remote-image cache and validate the generated thumbnail.
    cache_results = cache_remote_thumbnails(
        repository, token, matching, str(tmp_path / "cache")
    )
    cached = cache_results[remote_path]
    assert cached["error"] is None, cached
    assert cached["original"] and cached["thumbnail"]
    assert open(cached["original"], "rb").read() == expected
    with Image.open(cached["thumbnail"]) as thumbnail:
        thumbnail.load()
        assert thumbnail.format == "JPEG"
        assert thumbnail.width > 0 and thumbnail.height > 0


def test_live_github_upload_download_and_thumbnail(tmp_path):
    _live_round_trip("github", tmp_path)


def test_live_gitee_upload_download_and_thumbnail(tmp_path):
    _live_round_trip("gitee", tmp_path)
