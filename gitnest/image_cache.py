"""Local cache helpers for remote image previews and thumbnails."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


def cache_key(remote_path: str) -> str:
    return hashlib.sha256(remote_path.encode("utf-8")).hexdigest()


def save_remote_image(content: bytes, remote_path: str, cache_root: str | Path) -> tuple[Path, Path]:
    """Persist the original and a display-sized JPEG thumbnail.

    The cache key is based on the full repository path, so same-named files in
    different folders never overwrite each other.
    """
    root = Path(cache_root).expanduser().resolve()
    key = cache_key(remote_path)
    suffix = Path(remote_path).suffix.lower() or ".img"
    original = root / "original" / f"{key}{suffix}"
    thumbnail = root / "thumbs" / f"{key}.jpg"
    original.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.parent.mkdir(parents=True, exist_ok=True)

    if not original.exists() or original.read_bytes() != content:
        original.write_bytes(content)
    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((480, 360), Image.Resampling.LANCZOS)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.save(thumbnail, format="JPEG", quality=84, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"无法生成图片缩略图：{remote_path}（{exc}）") from exc
    return original, thumbnail
