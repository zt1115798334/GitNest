from pathlib import Path

import pytest

from gitnest.providers.base import ProviderError
from gitnest import services


class FakeProvider:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.writes = []
        self.closed = False

    def get_file(self, path):
        if path not in self.existing:
            raise ProviderError("not found", 404)
        return self.existing[path], "remote-sha"

    def put_file(self, path, content, message, sha=None):
        self.writes.append((path, content, message, sha))
        self.existing[path] = content
        return {}

    def close(self):
        self.closed = True


def test_upload_paths_uses_remote_subfolder_and_preserves_relative_paths(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    nested = root / "2026"
    nested.mkdir(parents=True)
    image = nested / "trip.png"
    image.write_bytes(b"png-bytes")
    provider = FakeProvider()
    progress = []
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    result = services.upload_paths(
        {"base_path": "images"}, "token", [image],
        remote_subpath="summer", relative_to=root,
        progress_callback=lambda *args: progress.append(args),
    )

    assert result[0][1] == "uploaded"
    assert progress[0][3] == "uploading"
    assert progress[-1] == (1, 1, "2026/trip.png", "uploaded", "已提交到 images/summer/2026/trip.png")
    assert provider.writes[0][0] == "images/summer/2026/trip.png"
    assert provider.writes[0][1] == b"png-bytes"
    assert provider.closed


def test_upload_paths_skips_existing_file_by_default(tmp_path, monkeypatch):
    image = tmp_path / "same.jpg"
    image.write_bytes(b"image")
    provider = FakeProvider({"assets/same.jpg": b"old"})
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    result = services.upload_paths(
        {"base_path": "assets"}, "token", [image], conflict="skip"
    )

    assert result[0][1] == "skipped"
    assert provider.writes == []


def test_upload_paths_overwrite_passes_remote_sha(tmp_path, monkeypatch):
    image = tmp_path / "same.jpg"
    image.write_bytes(b"new")
    provider = FakeProvider({"assets/same.jpg": b"old"})
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    result = services.upload_paths(
        {"base_path": "assets"}, "token", [image], conflict="overwrite"
    )

    assert result[0][1] == "uploaded"
    assert provider.writes[0][3] == "remote-sha"


def test_upload_paths_rejects_unsafe_remote_subfolder(tmp_path, monkeypatch):
    image = tmp_path / "safe.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        services, "with_provider",
        lambda *_: pytest.fail("provider must not be created for an unsafe path"),
    )

    with pytest.raises(ValueError, match="不安全"):
        services.upload_paths(
            {"base_path": "images"}, "token", [image], remote_subpath="../escape"
        )



def test_upload_paths_runs_multiple_workers_and_preserves_result_order(tmp_path, monkeypatch):
    import threading
    import time

    active = 0
    peak = 0
    state_lock = threading.Lock()
    writes = []

    class ConcurrentFakeProvider:
        def get_file(self, path):
            nonlocal active, peak
            with state_lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.08)
            with state_lock:
                active -= 1
            raise ProviderError("not found", 404)

        def put_file(self, path, content, message, sha=None):
            with state_lock:
                writes.append(path)
            return {}

        def close(self):
            pass

    monkeypatch.setattr(services, "with_provider", lambda *_: ConcurrentFakeProvider())
    files = []
    for name in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):
        path = tmp_path / name
        path.write_bytes(b"image")
        files.append(path)

    results = services.upload_paths(
        {"base_path": "images"}, "token", files, max_workers=3
    )

    assert [Path(row[0]).name for row in results] == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]
    assert all(row[1] == "uploaded" for row in results)
    assert peak >= 2
    assert len(writes) == 4
