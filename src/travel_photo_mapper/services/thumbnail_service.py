from __future__ import annotations

import base64
import hashlib
import threading
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QPixmap

register_heif_opener()


def _cache_dir() -> Path:
    base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    path = base / "thumbnail_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(path: Path, max_size: tuple[int, int]) -> Path:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{max_size}".encode("utf-8")
    key = hashlib.sha256(raw).hexdigest()
    return _cache_dir() / f"{key}.jpg"


def ensure_thumbnail(path: Path, max_size: tuple[int, int] = (1200, 800)) -> Path | None:
    temporary: Path | None = None
    try:
        cached = _cache_path(path, max_size)
        if cached.exists():
            return cached
        temporary = cached.with_name(f".{cached.name}.{threading.get_ident()}.tmp")
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail(max_size)
            image.save(temporary, format="JPEG", quality=86, optimize=True)
        temporary.replace(cached)
        return cached
    except Exception:
        return None
    finally:
        if temporary and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def load_pixmap(path: Path, max_size: tuple[int, int] = (1200, 800), use_cache: bool = True) -> QPixmap:
    try:
        cached = _cache_path(path, max_size)
        if use_cache and cached.exists():
            pix = QPixmap(str(cached))
            if not pix.isNull():
                return pix
        cached = ensure_thumbnail(path, max_size)
        return QPixmap(str(cached)) if cached else QPixmap()
    except Exception:
        return QPixmap()


def thumbnail_data_uri(path: Path, max_size: tuple[int, int] = (420, 420)) -> str:
    cached = ensure_thumbnail(path, max_size)
    if not cached:
        return ""
    try:
        encoded = base64.b64encode(cached.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        return ""
