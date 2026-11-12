from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from gitnest import services
from gitnest.providers.base import ProviderError


def make_png(color):
    stream = BytesIO()
    Image.new("RGB", (8, 8), color).save(stream, format="PNG")
    return stream.getvalue()


@dataclass
class RemoteItem:
    path: str
    name: str
    size: int


class CompareProvider:
    def __init__(self, files):
        self.files = files
        self.closed = False

    def get_file(self, path):
        if path not in self.files:
            raise ProviderError("not found", 404)
        return self.files[path], "sha"

    def close(self):
        self.closed = True


def test_compare_folders_classifies_local_remote_same_and_different(tmp_path, monkeypatch):
    root = tmp_path / "local"
    root.mkdir()
    same = make_png("red")
    different_local = make_png("blue")
    different_remote = make_png("green")
    (root / "same.png").write_bytes(same)
    (root / "different.png").write_bytes(different_local)
    (root / "local-only.png").write_bytes(make_png("yellow"))

    remote_files = {
        "images/same.png": same,
        "images/different.png": different_remote,
        "images/remote-only.png": make_png("purple"),
    }
    provider = CompareProvider(remote_files)
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)
    remote_items = [
        RemoteItem(path, Path(path).name, len(content))
        for path, content in remote_files.items()
    ]

    rows = services.compare_folders(
        {"base_path": "images"}, "token", str(root), remote_items
    )
    states = {row["path"]: row["status"] for row in rows}
    actions = {row["path"]: row["action"] for row in rows}

    assert states == {
        "different.png": "different",
        "local-only.png": "local_only",
        "remote-only.png": "remote_only",
        "same.png": "same",
    }
    assert actions["different.png"] == "conflict"
    assert actions["local-only.png"] == "upload"
    assert actions["remote-only.png"] == "download"
    assert actions["same.png"] == "none"
    assert provider.closed


def test_compare_folders_does_not_treat_same_size_different_content_as_same(tmp_path, monkeypatch):
    root = tmp_path / "local"
    root.mkdir()
    local = make_png("red")
    remote = make_png("blue")
    assert len(local) == len(remote)
    (root / "photo.png").write_bytes(local)
    provider = CompareProvider({"images/photo.png": remote})
    monkeypatch.setattr(services, "with_provider", lambda *_: provider)

    rows = services.compare_folders(
        {"base_path": "images"}, "token", str(root),
        [RemoteItem("images/photo.png", "photo.png", len(remote))]
    )

    assert rows[0]["status"] == "different"
    assert rows[0]["local_sha256"] != rows[0]["remote_sha256"]
