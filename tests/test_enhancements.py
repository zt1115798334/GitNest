import base64
from io import BytesIO
from urllib.parse import parse_qs

import httpx
from PIL import Image

from gitnest.image_cache import save_remote_image
from gitnest.images import sha256_bytes
from gitnest.providers.base import RemoteFile
from gitnest.providers.github import GitHubProvider
from gitnest.providers.gitee import GiteeProvider
from gitnest.services import compare_folders


def test_github_contents_api_contract_and_token_header():
    seen = []
    image = b"fake-png-bytes"

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("/contents/images/photo.png") and request.method == "GET":
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(image).decode(), "sha": "blob-1"})
        if request.url.path.endswith("/contents/images/photo.png") and request.method == "PUT":
            import json
            payload = json.loads(request.content)
            assert base64.b64decode(payload["content"]) == image
            assert payload["sha"] == "blob-1"
            return httpx.Response(200, json={"commit": {"sha": "commit-1"}})
        if request.url.path.endswith("/contents/images"):
            return httpx.Response(200, json=[{"path": "images/photo.png", "name": "photo.png", "size": len(image), "type": "file", "sha": "blob-1"}])
        return httpx.Response(200, json={"name": "pics"})

    provider = GitHubProvider("acme", "pics", "main", "gh-token")
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        provider.test_connection()
        files = provider.list_path("images")
        content, sha = provider.get_file("images/photo.png")
        result = provider.put_file("images/photo.png", content, "update", sha=sha)
        assert files[0].path == "images/photo.png"
        assert content == image and sha == "blob-1"
        assert result["commit"]["sha"] == "commit-1"
        assert all(req.headers.get("Authorization") == "Bearer gh-token" for req in seen)
    finally:
        provider.close()


def test_gitee_contents_api_contract_and_token_query():
    seen = []
    image = b"gitee-image"

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("/contents/images/photo.png") and request.method == "GET":
            return httpx.Response(200, json={"content": base64.b64encode(image).decode(), "sha": "gitee-blob"})
        if request.url.path.endswith("/contents/images/photo.png") and request.method == "PUT":
            form = parse_qs(request.content.decode())
            assert form["access_token"] == ["gitee-token"]
            assert base64.b64decode(form["content"][0]) == image
            return httpx.Response(201, json={"commit": {"sha": "gitee-commit"}})
        if request.url.path.endswith("/contents/images"):
            return httpx.Response(200, json=[{"path": "images/photo.png", "name": "photo.png", "size": len(image), "type": "file"}])
        return httpx.Response(200, json={"name": "pics"})

    provider = GiteeProvider("acme", "pics", "main", "gitee-token")
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        provider.test_connection()
        files = provider.list_path("images")
        content, sha = provider.get_file("images/photo.png")
        result = provider.put_file("images/photo.png", content, "update", sha=sha)
        assert files[0].path == "images/photo.png"
        assert content == image and sha == "gitee-blob"
        assert result["commit"]["sha"] == "gitee-commit"
        assert all(
            req.url.params.get("access_token") == "gitee-token"
            or parse_qs(req.content.decode()).get("access_token") == ["gitee-token"]
            for req in seen
        )
    finally:
        provider.close()


def test_remote_image_cache_creates_original_and_thumbnail(tmp_path):
    stream = BytesIO()
    Image.new("RGBA", (1200, 800), (255, 0, 0, 120)).save(stream, format="PNG")
    content = stream.getvalue()
    original, thumbnail = save_remote_image(content, "images/a/photo.png", tmp_path)
    assert original.read_bytes() == content
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG"
        assert image.width <= 480 and image.height <= 360


def test_cache_key_uses_full_remote_path(tmp_path):
    stream = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(stream, format="PNG")
    content = stream.getvalue()
    first = save_remote_image(content, "images/a/photo.png", tmp_path)
    second = save_remote_image(content, "images/b/photo.png", tmp_path)
    assert first[0] != second[0]
    assert first[1] != second[1]


class FakeProvider:
    def __init__(self, remote):
        self.remote = remote
        self.calls = []

    def get_file(self, path):
        self.calls.append(path)
        return self.remote[path], "provider-blob-sha"

    def close(self):
        pass


def test_compare_folders_uses_content_sha256_and_reuses_provider(tmp_path, monkeypatch):
    (tmp_path / "same.png").write_bytes(b"same-content")
    (tmp_path / "changed.png").write_bytes(b"local-content")
    (tmp_path / "local.png").write_bytes(b"local-only")
    remote = {
        "images/same.png": b"same-content",
        "images/changed.png": b"remote-content",
    }
    provider = FakeProvider(remote)
    created = []

    def factory(repository, token):
        created.append((repository, token))
        return provider

    monkeypatch.setattr("gitnest.services.with_provider", factory)
    rows = compare_folders({"base_path": "images"}, "token", str(tmp_path), [
        RemoteFile("images/same.png", "same.png", 12),
        RemoteFile("images/changed.png", "changed.png", 14),
        RemoteFile("images/remote.png", "remote.png", 8),
    ])
    by_path = {row["path"]: row for row in rows}
    assert by_path["same.png"]["status"] == "same"
    assert by_path["same.png"]["local_sha256"] == sha256_bytes(b"same-content")
    assert by_path["changed.png"]["status"] == "different"
    assert by_path["changed.png"]["local_sha256"] != by_path["changed.png"]["remote_sha256"]
    assert by_path["local.png"]["status"] == "local_only"
    assert by_path["remote.png"]["status"] == "remote_only"
    assert len(created) == 1
    assert len(provider.calls) == 2
