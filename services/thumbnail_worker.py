from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from services.thumbnail_service import ensure_thumbnail


class ThumbnailWorkerSignals(QObject):
    finished = pyqtSignal(int, int, str)


class ThumbnailWorker(QRunnable):
    def __init__(self, generation: int, photo_index: int, path: Path):
        super().__init__()
        self.generation = generation
        self.photo_index = photo_index
        self.path = path
        self.signals = ThumbnailWorkerSignals()

    @pyqtSlot()
    def run(self):
        gallery_path = ensure_thumbnail(self.path, (160, 110))
        # Prepara anche il formato usato dai popup della mappa.
        ensure_thumbnail(self.path, (420, 420))
        self.signals.finished.emit(
            self.generation,
            self.photo_index,
            str(gallery_path) if gallery_path else "",
        )
