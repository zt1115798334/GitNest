from pathlib import Path
from platformdirs import user_data_path, user_cache_path

APP_NAME = "GitNest"
DATA_DIR = Path(user_data_path(APP_NAME, appauthor=False))
CACHE_DIR = Path(user_cache_path(APP_NAME, appauthor=False))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "gitnest.sqlite3"
KEYRING_SERVICE = "GitNest"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
