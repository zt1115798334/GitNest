import pytest
from gitnest.images import is_image_path, safe_remote_path, safe_local_destination, sha256_bytes

def test_image_extensions():
    assert is_image_path("x.PNG")
    assert not is_image_path("x.txt")

def test_safe_remote_path_rejects_traversal():
    with pytest.raises(ValueError): safe_remote_path("../secret.png")

def test_safe_local_destination_stays_inside_root(tmp_path):
    assert safe_local_destination(tmp_path,"sub/a.png").parent == tmp_path / "sub"
    with pytest.raises(ValueError): safe_local_destination(tmp_path,"../escape.png")

def test_sha256_is_stable():
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
