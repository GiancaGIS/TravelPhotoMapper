from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QStyle,
    QToolButton,
    QVBoxLayout,
)

from i18n import tr
from models.photo import PhotoInfo
from services.thumbnail_service import load_pixmap

register_heif_opener()


def load_original_image(path: Path) -> QImage:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGBA")
        raw = image.tobytes("raw", "RGBA")
        return QImage(
            raw,
            image.width,
            image.height,
            image.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()


class PhotoLoadSignals(QObject):
    finished = pyqtSignal(int, object, str)


class PhotoLoadWorker(QRunnable):
    def __init__(self, generation: int, path: Path):
        super().__init__()
        self.generation = generation
        self.path = path
        self.signals = PhotoLoadSignals()

    @pyqtSlot()
    def run(self):
        try:
            image = load_original_image(self.path)
            self.signals.finished.emit(self.generation, image, "")
        except Exception as exc:
            self.signals.finished.emit(self.generation, QImage(), str(exc))


class PhotoCanvas(QGraphicsView):
    zoom_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._item = QGraphicsPixmapItem()
        self.scene().addItem(self._item)
        self._fit_mode = True
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def set_pixmap(self, pixmap: QPixmap):
        self._item.setPixmap(pixmap)
        self.scene().setSceneRect(self._item.boundingRect())
        self.fit_image()

    def fit_image(self):
        if self._item.pixmap().isNull():
            return
        self._fit_mode = True
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self._emit_zoom()

    def actual_size(self):
        if self._item.pixmap().isNull():
            return
        self._fit_mode = False
        self.resetTransform()
        self.centerOn(self._item)
        self._emit_zoom()

    def zoom_by(self, factor: float):
        if self._item.pixmap().isNull():
            return
        current = self.transform().m11()
        target = max(0.05, min(16.0, current * factor))
        self._fit_mode = False
        self.scale(target / current, target / current)
        self._emit_zoom()

    def _emit_zoom(self):
        self.zoom_changed.emit(round(self.transform().m11() * 100))

    def wheelEvent(self, event):
        self.zoom_by(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_image()

    def mouseDoubleClickEvent(self, event):
        dialog = self.window()
        if isinstance(dialog, PhotoViewer):
            dialog.toggle_fullscreen()
        event.accept()


class PhotoViewer(QDialog):
    photo_changed = pyqtSignal(int)

    def __init__(
        self,
        photos: list[PhotoInfo],
        visible_indices: list[int],
        initial_index: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("viewer.title"))
        self.resize(1280, 820)
        self.photos = photos
        self.indices = list(visible_indices)
        self.position = self.indices.index(initial_index)
        self._generation = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 6)
        self.prev_btn = self._tool_button(QStyle.StandardPixmap.SP_ArrowBack, tr("viewer.previous"), self.previous)
        self.next_btn = self._tool_button(QStyle.StandardPixmap.SP_ArrowForward, tr("viewer.next"), self.next)
        self.zoom_out_btn = self._text_button("−", tr("viewer.zoom_out"), lambda: self.canvas.zoom_by(1 / 1.25))
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(54)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_in_btn = self._text_button("+", tr("viewer.zoom_in"), lambda: self.canvas.zoom_by(1.25))
        self.fit_btn = self._text_button("Fit", tr("viewer.fit"), self.canvas_fit)
        self.actual_btn = self._text_button("1:1", tr("viewer.actual"), self.canvas_actual)
        self.fullscreen_btn = self._tool_button(
            QStyle.StandardPixmap.SP_TitleBarMaxButton, tr("viewer.fullscreen"), self.toggle_fullscreen
        )
        self.open_btn = self._tool_button(
            QStyle.StandardPixmap.SP_FileIcon, tr("viewer.open_external"), self.open_external
        )
        self.folder_btn = self._tool_button(
            QStyle.StandardPixmap.SP_DirOpenIcon, tr("viewer.open_folder"), self.open_folder
        )

        for widget in (
            self.prev_btn, self.next_btn, self.zoom_out_btn, self.zoom_label,
            self.zoom_in_btn, self.fit_btn, self.actual_btn,
        ):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        toolbar.addWidget(self.open_btn)
        toolbar.addWidget(self.folder_btn)
        toolbar.addWidget(self.fullscreen_btn)
        layout.addLayout(toolbar)

        self.canvas = PhotoCanvas()
        self.canvas.zoom_changed.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        layout.addWidget(self.canvas, 1)

        self.info_label = QLabel()
        self.info_label.setContentsMargins(10, 6, 10, 6)
        self.info_label.setStyleSheet("background:#17191c; color:#f3f4f5;")
        layout.addWidget(self.info_label)

        self._show_current()

    def _tool_button(self, icon, tooltip: str, callback) -> QToolButton:
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _text_button(text: str, tooltip: str, callback) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def canvas_fit(self):
        self.canvas.fit_image()

    def canvas_actual(self):
        self.canvas.actual_size()

    def _show_current(self):
        index = self.indices[self.position]
        photo = self.photos[index]
        self._generation += 1
        generation = self._generation

        preview = load_pixmap(photo.path, (900, 600))
        if not preview.isNull():
            self.canvas.set_pixmap(preview)

        dimensions = f"{photo.width} × {photo.height}" if photo.width and photo.height else tr("viewer.unknown_dimensions")
        taken_at = photo.taken_at.strftime("%d/%m/%Y %H:%M:%S") if photo.taken_at else tr("viewer.unknown_date")
        self.info_label.setText(
            f"{self.position + 1} / {len(self.indices)}   ·   {photo.filename}   ·   {dimensions}   ·   {taken_at}"
        )
        self.setWindowTitle(tr("viewer.window_title", filename=photo.filename))
        self.prev_btn.setEnabled(self.position > 0)
        self.next_btn.setEnabled(self.position < len(self.indices) - 1)
        self.photo_changed.emit(index)

        worker = PhotoLoadWorker(generation, photo.path)
        worker.signals.finished.connect(self._original_loaded)
        self._pool.clear()
        self._pool.start(worker)

    def _original_loaded(self, generation: int, image: QImage, error: str):
        if generation != self._generation:
            return
        if error or image.isNull():
            QMessageBox.warning(
                self,
                tr("viewer.image_error_title"),
                tr("viewer.image_error", error=error),
            )
            return
        self.canvas.set_pixmap(QPixmap.fromImage(image))

    def previous(self):
        if self.position > 0:
            self.position -= 1
            self._show_current()

    def next(self):
        if self.position < len(self.indices) - 1:
            self.position += 1
            self._show_current()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def open_external(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.photos[self.indices[self.position]].path)))

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.photos[self.indices[self.position]].path.parent)))

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Left:
            self.previous()
        elif key == Qt.Key.Key_Right:
            self.next()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.canvas.zoom_by(1.25)
        elif key == Qt.Key.Key_Minus:
            self.canvas.zoom_by(1 / 1.25)
        elif key == Qt.Key.Key_0:
            self.canvas.fit_image()
        elif key == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        self._generation += 1
        self._pool.clear()
        super().closeEvent(event)
