from pathlib import Path, PurePosixPath
from io import BytesIO
import hashlib
import warnings

from PIL import Image, UnidentifiedImageError
from gitnest.config import IMAGE_EXTENSIONS, MAX_IMAGE_BYTES

class ImageFileError(ValueError):
    pass

def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS

def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def scan_images(folder: str | Path) -> list[Path]:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ImageFileError("请选择有效的本地图片目录")
    return sorted((p for p in root.rglob("*") if p.is_file() and is_image_path(p)), key=lambda p: str(p).lower())

def safe_remote_path(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute() or any(part in ("", ".", "..") for part in normalized.parts):
        raise ImageFileError(f"不安全的仓库路径：{path}")
    return normalized.as_posix()

def safe_local_destination(root: str | Path, relative_path: str) -> Path:
    base = Path(root).expanduser().resolve()
    rel = PurePosixPath(relative_path)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ImageFileError(f"不安全的相对路径：{relative_path}")
    destination = (base / Path(*rel.parts)).resolve()
    if destination != base and base not in destination.parents:
        raise ImageFileError("目标路径超出所选目录")
    return destination

def validate_image(content: bytes, path: str) -> None:
    """Validate both the filename extension and the actual encoded image."""
    if not is_image_path(path):
        raise ImageFileError("文件扩展名不是支持的图片格式")
    if not content:
        raise ImageFileError("图片文件为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise ImageFileError(f"图片超过当前版本限制（{MAX_IMAGE_BYTES // 1024 // 1024} MB）")

    expected_formats = {
        ".jpg": {"JPEG"}, ".jpeg": {"JPEG"}, ".png": {"PNG"},
        ".gif": {"GIF"}, ".webp": {"WEBP"}, ".bmp": {"BMP"},
        ".tif": {"TIFF"}, ".tiff": {"TIFF"}, ".avif": {"AVIF"},
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                actual_format = (image.format or "").upper()
                if actual_format not in expected_formats[Path(path).suffix.lower()]:
                    raise ImageFileError(
                        f"图片内容格式为 {actual_format or '未知'}，与文件扩展名 {Path(path).suffix} 不匹配"
                    )
                image.verify()
    except ImageFileError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ImageFileError(f"图片文件损坏或格式无法识别：{Path(path).name}（{exc}）") from exc
