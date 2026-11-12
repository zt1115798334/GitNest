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


def test_validate_image_checks_real_format_and_corruption():
    from io import BytesIO
    from PIL import Image
    from gitnest.images import validate_image, ImageFileError

    stream = BytesIO()
    Image.new("RGB", (12, 8), "red").save(stream, format="PNG")
    png = stream.getvalue()
    validate_image(png, "photo.png")

    with pytest.raises(ImageFileError, match="与文件扩展名"):
        validate_image(png, "photo.jpg")
    with pytest.raises(ImageFileError, match="损坏或格式无法识别"):
        validate_image(b"not-an-image", "photo.png")
