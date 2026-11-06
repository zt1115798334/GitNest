import pytest
from gitnest.providers.base import GitProvider, ProviderError, RemoteFile

class FakeProvider(GitProvider):
    def __init__(self, entries):
        self.entries = entries
    def list_path(self, path=""):
        value = self.entries.get(path)
        if isinstance(value, Exception):
            raise value
        return value or []
    def get_file(self, path):
        raise NotImplementedError
    def put_file(self, path, content, message, sha=None):
        raise NotImplementedError
    def test_connection(self):
        return None
    def close(self):
        return None

def test_missing_configured_image_root_is_empty():
    provider = FakeProvider({"assets": ProviderError("not found", 404)})
    assert provider.list_images("assets") == []

def test_nested_directory_errors_are_not_silently_ignored():
    provider = FakeProvider({"assets": [RemoteFile("assets/sub", "sub", type="dir")],
                             "assets/sub": ProviderError("forbidden", 403)})
    with pytest.raises(ProviderError):
        provider.list_images("assets")
