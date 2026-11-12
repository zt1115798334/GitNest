from pathlib import Path

import pytest

from gitnest import services
from gitnest.providers.base import RemoteFile


class FakeProvider:
    def __init__(self, content=b"remote-image"):
        self.content = content
        self.closed = False

    def get_file(self, path):
        return self.content, "remote-sha"

    def close(self):
        self.closed = True


def test_download_skips_existing_file_by_default(tmp_path, monkeypatch):
    target = tmp_path / "photo.png"
    target.write_bytes(b"keep-me")
    monkeypatch.setattr(
        services, "with_provider",
        lambda *_: pytest.fail("provider should not be created when download is skipped"),
    )

    result = services.download_one(
        {"base_path": "images"}, "token", "images/photo.png", str(tmp_path)
    )

    assert result is None
    assert target.read_bytes() == b"keep-me"


def test_download_rename_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "photo.png"
    target.write_bytes(b"original")
    provider = FakeProvider(b"downloaded")
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    result = services.download_one(
        {"base_path": "images"}, "token", "images/photo.png", str(tmp_path), "rename"
    )

    assert result == tmp_path / "photo_1.png"
    assert target.read_bytes() == b"original"
    assert result.read_bytes() == b"downloaded"
    assert provider.closed


def test_download_overwrite_is_atomic_and_explicit(tmp_path, monkeypatch):
    target = tmp_path / "photo.png"
    target.write_bytes(b"old")
    provider = FakeProvider(b"new-content")
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    result = services.download_one(
        {"base_path": "images"}, "token", "images/photo.png", str(tmp_path), "overwrite"
    )

    assert result == target
    assert target.read_bytes() == b"new-content"
    assert list(tmp_path.glob("*.part")) == []
    assert provider.closed


def test_download_failure_does_not_leave_partial_destination(tmp_path, monkeypatch):
    class BrokenProvider(FakeProvider):
        def get_file(self, path):
            raise RuntimeError("network interrupted")

    provider = BrokenProvider()
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    with pytest.raises(RuntimeError, match="network interrupted"):
        services.download_one(
            {"base_path": "images"}, "token", "images/photo.png", str(tmp_path)
        )

    assert not (tmp_path / "photo.png").exists()
    assert provider.closed


def test_download_all_reports_downloaded_skipped_and_failed(tmp_path, monkeypatch):
    (tmp_path / "exists.png").write_bytes(b"keep")
    provider = FakeProvider()
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    items = [
        RemoteFile("images/new.png", "new.png", 10),
        RemoteFile("images/exists.png", "exists.png", 4),
    ]
    results = services.download_all(
        {"base_path": "images"}, "token", str(tmp_path), items, "skip"
    )

    assert [row[1] for row in results] == ["downloaded", "skipped"]
    assert (tmp_path / "new.png").read_bytes() == b"remote-image"
    assert (tmp_path / "exists.png").read_bytes() == b"keep"
