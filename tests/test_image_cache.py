from pathlib import Path

from PIL import Image

from gitnest.image_cache import create_local_thumbnail


def test_local_thumbnail_is_cached_for_unchanged_source(tmp_path):
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (1200, 800), "red").save(source)

    first = create_local_thumbnail(source, tmp_path / "cache")
    second = create_local_thumbnail(source, tmp_path / "cache")

    assert first == second
    assert first.is_file()
    with Image.open(first) as thumbnail:
        assert thumbnail.width <= 480
        assert thumbnail.height <= 360


def test_local_thumbnail_cache_changes_when_source_changes(tmp_path):
    source = tmp_path / "photo.png"
    cache = tmp_path / "cache"
    Image.new("RGBA", (80, 60), (255, 0, 0, 128)).save(source)

    first = create_local_thumbnail(source, cache)
    Image.new("RGBA", (80, 60), (0, 0, 255, 128)).save(source)
    # Ensure the cache identity changes even on filesystems with coarse mtime resolution.
    source.touch()
    second = create_local_thumbnail(source, cache)

    assert first != second
    assert second.is_file()
