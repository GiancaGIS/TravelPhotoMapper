from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from models.photo import PhotoInfo
from services.cache_service import CacheService
from services.exif_reader import read_photo_metadata


SUPPORTED_EXTENSIONS = {
    ".heic", ".heif",
    ".jpg", ".jpeg",
    ".png",
    ".tif", ".tiff",
}


class PhotoScannerWorker(QObject):
    progress = pyqtSignal(int, int, object, bool)
    finished = pyqtSignal(list, int, int)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, folder: Path):
        super().__init__()
        self.folder = folder
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    @pyqtSlot()
    def run(self):
        cache = None
        try:
            if self._cancel_requested:
                self.cancelled.emit()
                return
            cache = CacheService(self.folder)
            paths = sorted(
                p for p in self.folder.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )

            result: list[PhotoInfo] = []
            total = len(paths)
            cached_count = 0
            analyzed_count = 0

            for index, path in enumerate(paths, start=1):
                if self._cancel_requested:
                    self.cancelled.emit()
                    return
                photo = cache.get(path)
                from_cache = photo is not None
                if photo is None:
                    photo = read_photo_metadata(path)
                    analyzed_count += 1
                    cache.put(photo, commit=False)
                    if analyzed_count % 100 == 0:
                        cache.commit()
                else:
                    cached_count += 1

                result.append(photo)
                self.progress.emit(index, total, photo, from_cache)

            cache.commit()
            result.sort(key=lambda p: (p.taken_at is None, p.taken_at, p.filename))
            self.finished.emit(result, cached_count, analyzed_count)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if cache:
                cache.close()
