from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QThread, QThreadPool, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QSplitter, QLineEdit, QFrame,
    QProgressBar, QMessageBox, QScrollArea, QGridLayout, QComboBox, QCheckBox,
    QListView, QAbstractItemView, QStyle
)

from app_info import APP_NAME, APP_VERSION
from i18n import LANGUAGES, detect_system_language, get_language, set_language, tr, trn
from models.photo import PhotoInfo
from services.photo_scanner import PhotoScannerWorker
from services.thumbnail_service import load_pixmap
from services.thumbnail_worker import ThumbnailWorker
from services.trip_service import build_stages, TripStage
from services.export_service import export_geojson, export_gpx
from ui.map_widget import MapWidget
from ui.photo_viewer import PhotoViewer
from ui.timeline_widget import TimelineWidget


STYLE = """
QMainWindow, QWidget {
    background:#f3f6f6; color:#20282a; font-family:"Segoe UI"; font-size:13px;
}
QFrame#topBar, QFrame#panel {
    background:#ffffff; border:1px solid #dce2e3; border-radius:6px;
}
QPushButton, QComboBox {
    min-height:30px; background:#ffffff; border:1px solid #cfd7d9;
    border-radius:5px; padding:3px 9px;
}
QPushButton:hover, QComboBox:hover { border-color:#0b8790; background:#f7fbfb; }
QPushButton:pressed { background:#e8f4f4; }
QPushButton:disabled, QComboBox:disabled { color:#9aa4a6; background:#f3f5f5; }
QPushButton#openButton {
    background:#ffc928; border-color:#e3ac00; color:#202124; font-weight:700;
}
QPushButton#openButton:hover { background:#ffd555; border-color:#c99400; }
QPushButton[compact="true"] { min-width:30px; max-width:34px; padding:2px; }
QLineEdit {
    min-height:30px; background:#ffffff; border:1px solid #cfd7d9;
    border-radius:5px; padding:3px 9px; selection-background-color:#0b8790;
}
QLineEdit:focus, QComboBox:focus { border:1px solid #0b8790; }
QLabel, QCheckBox { background:transparent; }
QLabel#brandTitle { font-size:16px; font-weight:700; color:#172326; }
QLabel#sectionTitle { font-size:14px; font-weight:700; color:#263235; }
QLabel#subtle, QLabel#metadataLabel { color:#6b7679; }
QLabel#metadataLabel { font-size:12px; font-weight:600; }
QLabel#metadataValue { color:#20282a; }
QLabel#photoPreview { background:#edf1f1; border:1px solid #e0e5e6; border-radius:5px; }
QListWidget#photoGallery { background:#ffffff; border:none; outline:none; }
QListWidget#photoGallery::item {
    background:#ffffff; border:2px solid transparent; border-radius:5px;
    padding:4px; color:#30383a; font-size:12px;
}
QListWidget#photoGallery::item:hover { background:#f5f8f8; border-color:#c7d7d9; }
QListWidget#photoGallery::item:selected {
    background:#fff8df; color:#202124; border:2px solid #f0ad00;
}
QScrollArea { background:#ffffff; border:none; }
QScrollBar:vertical { background:#f0f3f3; width:9px; margin:0; }
QScrollBar::handle:vertical { background:#b7c2c4; min-height:28px; border-radius:4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QSplitter::handle { background:#dfe5e6; }
QSplitter::handle:hover { background:#8abfc3; }
QCheckBox { spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; }
QCheckBox::indicator:unchecked { border:1px solid #aeb9bb; border-radius:3px; background:#fff; }
QCheckBox::indicator:checked { border:1px solid #b88a00; border-radius:3px; background:#ffc928; }
QProgressBar { border:1px solid #d3dcdd; border-radius:3px; background:#eef2f2; height:7px; text-align:center; }
QProgressBar::chunk { background:#0b8790; border-radius:2px; }
"""


class ClickableLabel(QLabel):
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1580, 940)
        self.settings = QSettings()
        saved_language = self.settings.value("language", "", type=str)
        set_language(saved_language if saved_language in LANGUAGES else detect_system_language())

        self.photos: list[PhotoInfo] = []
        self.visible_indices: list[int] = []
        self.stages: list[TripStage] = []
        self._thread: QThread | None = None
        self._worker: PhotoScannerWorker | None = None
        self._play_pos = 0
        self._thumbnail_generation = 0
        self._items_by_index: dict[int, QListWidgetItem] = {}
        self._thumbnail_pool = QThreadPool.globalInstance()
        self._photo_viewer: PhotoViewer | None = None
        self._preview_source = QPixmap()
        self._suppress_map_focus = False
        self._counter_state: tuple[str, dict] = ("status", {"key": "counter.empty"})

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(2000)
        self.play_timer.timeout.connect(self._play_next)

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(250)
        self.filter_timer.timeout.connect(self.apply_filter)

        self._build_ui()
        self.setStyleSheet(STYLE)
        self._restore_settings()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("appRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        toolbar = QFrame(); toolbar.setObjectName("topBar")
        tb = QHBoxLayout(toolbar); tb.setContentsMargins(10, 8, 10, 8); tb.setSpacing(7)
        brand_icon = QLabel(); brand_icon.setFixedSize(30, 30)
        brand_icon.setPixmap(self.windowIcon().pixmap(28, 28)); brand_icon.setScaledContents(True)
        self.brand_title = QLabel(APP_NAME); self.brand_title.setObjectName("brandTitle")
        self.open_btn = QPushButton(tr("toolbar.open_folder")); self.open_btn.setObjectName("openButton")
        self.open_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.open_btn.clicked.connect(self.choose_folder)
        self.cancel_btn = QPushButton(tr("toolbar.cancel"))
        self.cancel_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_scan)
        self.path_edit = QLineEdit(); self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText(tr("toolbar.folder_placeholder"))
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText(tr("toolbar.search_placeholder"))
        self.search_edit.textChanged.connect(lambda _text: self.filter_timer.start())
        self.counter = QLabel(tr("counter.empty")); self.counter.setObjectName("subtle")
        self.language_combo = QComboBox()
        self._compact_combo(self.language_combo, 8)
        self.language_combo.setToolTip(tr("toolbar.language"))
        for code, name in LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(get_language()))
        self.language_combo.currentIndexChanged.connect(self._change_language)

        self.export_geojson_btn = QPushButton("GeoJSON")
        self.export_geojson_btn.clicked.connect(self.export_geojson_clicked)
        self.export_gpx_btn = QPushButton("GPX")
        self.export_gpx_btn.clicked.connect(self.export_gpx_clicked)

        tb.addWidget(brand_icon)
        tb.addWidget(self.brand_title)
        tb.addSpacing(5)
        tb.addWidget(self.open_btn)
        tb.addWidget(self.cancel_btn)
        tb.addWidget(self.path_edit, 1)
        tb.addWidget(self.counter)
        tb.addWidget(self.export_geojson_btn)
        tb.addWidget(self.export_gpx_btn)
        tb.addWidget(self.language_combo)
        outer.addWidget(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        splitter = self.splitter

        left = QFrame(); left.setObjectName("panel"); left.setMinimumWidth(288)
        left_l = QVBoxLayout(left); left_l.setContentsMargins(10, 10, 10, 10); left_l.setSpacing(7)
        self.gallery_title = QLabel(tr("gallery.title")); self.gallery_title.setObjectName("sectionTitle")
        left_l.addWidget(self.gallery_title)
        left_l.addWidget(self.search_edit)

        self.filters_caption = QLabel(tr("filters.label")); self.filters_caption.setObjectName("subtle")
        left_l.addWidget(self.filters_caption)
        filter_grid = QGridLayout()
        filter_grid.setContentsMargins(0, 0, 0, 0)
        filter_grid.setHorizontalSpacing(6); filter_grid.setVerticalSpacing(6)
        self.day_filter = QComboBox(); self.day_filter.addItem(tr("filters.all_days"), None)
        self._compact_combo(self.day_filter, 12)
        self.day_filter.currentIndexChanged.connect(self.apply_filter)
        self.stage_filter = QComboBox(); self.stage_filter.addItem(tr("filters.all_stages"), None)
        self._compact_combo(self.stage_filter, 18)
        self.stage_filter.currentIndexChanged.connect(self.apply_filter)
        self.gps_filter = QComboBox()
        self._compact_combo(self.gps_filter, 12)
        self.gps_filter.addItem(tr("filters.all_photos"), None)
        self.gps_filter.addItem(tr("filters.with_gps"), True)
        self.gps_filter.addItem(tr("filters.without_gps"), False)
        self.gps_filter.currentIndexChanged.connect(self.apply_filter)
        self.route_check = QCheckBox(tr("filters.route")); self.route_check.setChecked(True)
        self.route_check.toggled.connect(self._toggle_route)
        self.heat_check = QCheckBox(tr("filters.heatmap"))
        self.heat_check.toggled.connect(self._toggle_heatmap)
        self.trip_summary = QLabel(tr("trip.none")); self.trip_summary.setObjectName("subtle")
        filter_grid.addWidget(self.day_filter, 0, 0)
        filter_grid.addWidget(self.gps_filter, 0, 1)
        filter_grid.addWidget(self.stage_filter, 1, 0, 1, 2)
        left_l.addLayout(filter_grid)
        left_l.addWidget(self.trip_summary)

        self.photo_list = QListWidget(); self.photo_list.setObjectName("photoGallery")
        self.photo_list.setViewMode(QListView.ViewMode.ListMode)
        self.photo_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.photo_list.setMovement(QListView.Movement.Static)
        self.photo_list.setFlow(QListView.Flow.TopToBottom)
        self.photo_list.setWrapping(False)
        self.photo_list.setWordWrap(True)
        self.photo_list.setUniformItemSizes(True)
        self.photo_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.photo_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.photo_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.photo_list.setSpacing(3)
        self.photo_list.setIconSize(QSize(120, 72))
        self.photo_list.currentRowChanged.connect(self.on_photo_selected)
        self.photo_list.itemDoubleClicked.connect(lambda _item: self.open_photo_viewer())
        left_l.addWidget(self.photo_list, 1)
        splitter.addWidget(left)

        center = QFrame(); center.setObjectName("panel")
        center_l = QVBoxLayout(center); center_l.setContentsMargins(8, 8, 8, 8); center_l.setSpacing(7)
        map_header = QHBoxLayout()
        self.map_title = QLabel(tr("map.title")); self.map_title.setObjectName("sectionTitle")
        self.map_home_btn = QPushButton("🏠"); self.map_home_btn.setProperty("compact", True)
        self.map_home_btn.setStyleSheet("font-size:18px; color:#48575a;")
        self.map_home_btn.setToolTip(tr("map.full_extent"))
        map_header.addWidget(self.map_title)
        map_header.addStretch(1)
        map_header.addWidget(self.route_check)
        map_header.addWidget(self.heat_check)
        map_header.addWidget(self.map_home_btn)
        center_l.addLayout(map_header)
        self.map_widget = MapWidget(); self.map_widget.photo_selected.connect(self.select_original_index)
        self.map_home_btn.clicked.connect(self.map_widget.fit_all_photos)
        center_l.addWidget(self.map_widget, 1)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        center_l.addWidget(self.progress)
        splitter.addWidget(center)

        right = QFrame(); right.setObjectName("panel"); right.setMinimumWidth(310)
        right_l = QVBoxLayout(right); right_l.setContentsMargins(10, 10, 10, 10); right_l.setSpacing(8)
        details_header = QHBoxLayout()
        self.details_title = QLabel(tr("details.title")); self.details_title.setObjectName("sectionTitle")
        self.viewer_btn = QPushButton(); self.viewer_btn.setProperty("compact", True)
        self.viewer_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
        self.viewer_btn.setToolTip(tr("details.open_viewer"))
        self.viewer_btn.clicked.connect(self.open_photo_viewer)
        details_header.addWidget(self.details_title)
        details_header.addStretch(1)
        details_header.addWidget(self.viewer_btn)
        right_l.addLayout(details_header)
        self.preview = ClickableLabel(tr("details.preview_empty")); self.preview.setObjectName("photoPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(235)
        self.preview.setToolTip(tr("details.preview_tooltip"))
        self.preview.double_clicked.connect(self.open_photo_viewer)
        right_l.addWidget(self.preview)

        details_scroll = QScrollArea(); details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details_holder = QWidget(); grid = QGridLayout(details_holder); grid.setColumnStretch(1, 1)
        grid.setContentsMargins(0, 3, 0, 0); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(8)
        labels = [
            ("details.filename", "filename"), ("details.datetime", "datetime"), ("details.gps", "gps"),
            ("details.latitude", "lat"), ("details.longitude", "lon"), ("details.altitude", "alt"),
            ("details.camera", "camera"), ("details.lens", "lens"), ("details.resolution", "resolution"),
            ("details.filesize", "filesize"), ("details.date_source", "date_source"),
            ("details.metadata_status", "metadata_status"), ("details.stage", "stage"),
        ]
        self.detail_values = {}
        self.detail_captions = {}
        for row, (caption_key, key) in enumerate(labels):
            k = QLabel(tr(caption_key)); k.setObjectName("metadataLabel"); k.setWordWrap(True)
            v = QLabel("—"); v.setObjectName("metadataValue"); v.setWordWrap(True)
            grid.addWidget(k, row, 0, alignment=Qt.AlignmentFlag.AlignTop)
            grid.addWidget(v, row, 1, alignment=Qt.AlignmentFlag.AlignTop)
            self.detail_values[key] = v
            self.detail_captions[key] = (k, caption_key)
        grid.setRowStretch(len(labels), 1)
        details_scroll.setWidget(details_holder)
        right_l.addWidget(details_scroll, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setStretchFactor(2, 0)
        splitter.setSizes([330, 890, 350])
        outer.addWidget(splitter, 1)

        timeline_panel = QFrame(); timeline_panel.setObjectName("panel")
        tl = QVBoxLayout(timeline_panel); tl.setContentsMargins(10, 7, 10, 7); tl.setSpacing(3)
        top = QHBoxLayout()
        self.timeline_title = QLabel(tr("timeline.title")); self.timeline_title.setObjectName("sectionTitle")
        self.timeline_zoom_out_btn = QPushButton("−"); self.timeline_zoom_out_btn.setProperty("compact", True)
        self.timeline_zoom_out_btn.setToolTip(tr("timeline.zoom_out"))
        self.timeline_reset_btn = QPushButton("Fit")
        self.timeline_reset_btn.setToolTip(tr("timeline.fit"))
        self.timeline_zoom_in_btn = QPushButton("+"); self.timeline_zoom_in_btn.setProperty("compact", True)
        self.timeline_zoom_in_btn.setToolTip(tr("timeline.zoom_in"))
        self.prev_btn = QPushButton(); self.prev_btn.setProperty("compact", True)
        self.prev_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.prev_btn.clicked.connect(self._select_previous)
        self.play_btn = QPushButton(); self.play_btn.setProperty("compact", True)
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_btn.clicked.connect(self._toggle_playback)
        self.next_btn = QPushButton(); self.next_btn.setProperty("compact", True)
        self.next_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.next_btn.clicked.connect(self._select_next)
        self.play_speed = QComboBox()
        self._compact_combo(self.play_speed, 4)
        self._populate_play_speeds()
        self.play_speed.currentIndexChanged.connect(self._update_playback_speed)
        self.timeline_label = QLabel(tr("timeline.select_folder")); self.timeline_label.setObjectName("subtle")
        top.addWidget(self.timeline_title); top.addStretch(1); top.addWidget(self.timeline_label)
        top.addWidget(self.timeline_zoom_out_btn); top.addWidget(self.timeline_reset_btn); top.addWidget(self.timeline_zoom_in_btn)
        top.addWidget(self.prev_btn); top.addWidget(self.play_btn); top.addWidget(self.next_btn); top.addWidget(self.play_speed)
        tl.addLayout(top)
        self.timeline = TimelineWidget(); self.timeline.photo_selected.connect(self.select_original_index)
        self.timeline_zoom_out_btn.clicked.connect(self.timeline.zoom_out)
        self.timeline_reset_btn.clicked.connect(self.timeline.reset_view)
        self.timeline_zoom_in_btn.clicked.connect(self.timeline.zoom_in)
        tl.addWidget(self.timeline)
        outer.addWidget(timeline_panel)

        self.setCentralWidget(root)
        self._set_photo_controls_enabled(False)

    @staticmethod
    def _compact_combo(combo: QComboBox, minimum_characters: int):
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMinimumContentsLength(minimum_characters)

    def choose_folder(self):
        initial = self.settings.value("last_folder", "", type=str)
        folder = QFileDialog.getExistingDirectory(self, tr("dialog.select_folder"), initial)
        if folder:
            self.load_folder(Path(folder))

    def load_folder(self, folder: Path):
        if self._photo_viewer is not None:
            self._photo_viewer.close()
        self.play_timer.stop(); self._set_playback_icon(False)
        self.filter_timer.stop()
        self.settings.setValue("last_folder", str(folder))
        self.path_edit.setText(str(folder))
        self.photos.clear(); self.visible_indices.clear(); self.stages.clear(); self.photo_list.clear()
        self._thumbnail_generation += 1
        self._items_by_index.clear()
        self._reset_filters()
        self.map_widget.set_photos([], [])
        self.timeline.set_photos([], [])
        self._clear_details()
        self._set_counter_status("counter.scanning")
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        self.open_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True); self.cancel_btn.setVisible(True)
        self._set_photo_controls_enabled(False)

        thread = QThread(self)
        worker = PhotoScannerWorker(folder)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.on_scan_progress)
        worker.finished.connect(self.on_scan_finished)
        worker.failed.connect(self.on_scan_failed)
        worker.cancelled.connect(self.on_scan_cancelled)
        worker.finished.connect(thread.quit); worker.failed.connect(thread.quit); worker.cancelled.connect(thread.quit)
        worker.finished.connect(worker.deleteLater); worker.failed.connect(worker.deleteLater); worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread; self._worker = worker
        thread.start()

    def _reset_filters(self):
        for combo, text in ((self.day_filter, tr("filters.all_days")), (self.stage_filter, tr("filters.all_stages"))):
            combo.blockSignals(True); combo.clear(); combo.addItem(text, None); combo.blockSignals(False)
        self.gps_filter.blockSignals(True)
        self.gps_filter.setCurrentIndex(0)
        self.gps_filter.blockSignals(False)

    def cancel_scan(self):
        if self._worker is not None:
            self.cancel_btn.setEnabled(False)
            self._set_counter_status("counter.cancelling")
            self._worker.request_cancel()

    def on_scan_progress(self, current: int, total: int, from_cache: bool):
        if self.progress.maximum() != total:
            self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self._set_counter_status(
            "counter.progress",
            current=current,
            total=total,
            source_key="counter.cache" if from_cache else "counter.exif",
        )

    def on_scan_finished(self, photos: list[PhotoInfo], cached_count: int, analyzed_count: int):
        self.photos = photos
        self.stages = build_stages(photos)
        self._finish_scan_ui()
        self._set_photo_controls_enabled(bool(photos))
        self._populate_day_filter(); self._populate_stage_filter(); self.apply_filter()
        gps_count = sum(p.has_gps for p in photos)
        warning_count = sum(p.metadata_error is not None for p in photos)
        days = len({p.taken_at.date() for p in photos if p.taken_at})
        self._set_counter_summary(
            len(photos), gps_count, cached_count, analyzed_count, warning_count
        )
        self._set_trip_summary(days, len(self.stages))
        if self.photo_list.count():
            self.photo_list.setCurrentRow(0)

    def on_scan_failed(self, message: str):
        self._finish_scan_ui()
        self._set_photo_controls_enabled(False)
        self._set_counter_status("counter.error")
        QMessageBox.critical(self, tr("dialog.error"), message)

    def on_scan_cancelled(self):
        self._finish_scan_ui()
        self._set_photo_controls_enabled(False)
        self._set_counter_status("counter.cancelled")
        self.trip_summary.setText(tr("trip.none"))

    def _finish_scan_ui(self):
        self.open_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(False)
        self._worker = None

    def _on_thread_finished(self):
        self._thread = None

    def _set_photo_controls_enabled(self, enabled: bool):
        controls = (
            self.search_edit, self.day_filter, self.stage_filter, self.gps_filter,
            self.route_check, self.heat_check, self.export_geojson_btn,
            self.export_gpx_btn, self.viewer_btn, self.map_home_btn,
            self.timeline_zoom_out_btn,
            self.timeline_reset_btn, self.timeline_zoom_in_btn, self.prev_btn,
            self.play_btn, self.next_btn, self.play_speed,
        )
        for control in controls:
            control.setEnabled(enabled)

    def _set_counter_status(self, key: str, **values):
        self._counter_state = ("status", {"key": key, **values})
        self._refresh_counter()

    def _set_counter_summary(
        self,
        photo_count: int,
        gps_count: int,
        cached_count: int,
        analyzed_count: int,
        warning_count: int,
    ):
        self._counter_state = (
            "summary",
            {
                "photo_count": photo_count,
                "gps_count": gps_count,
                "cached_count": cached_count,
                "analyzed_count": analyzed_count,
                "warning_count": warning_count,
            },
        )
        self._refresh_counter()

    def _refresh_counter(self):
        mode, values = self._counter_state
        if mode == "status":
            rendered_values = dict(values)
            key = rendered_values.pop("key")
            source_key = rendered_values.pop("source_key", None)
            if source_key:
                rendered_values["source"] = tr(source_key)
            self.counter.setText(tr(key, **rendered_values))
            return

        parts = [
            trn("count.photos", values["photo_count"]),
            trn("count.gps", values["gps_count"]),
            tr(
                "counter.analyzed",
                cached=values["cached_count"],
                analyzed=values["analyzed_count"],
            ),
        ]
        if values["warning_count"]:
            parts.append(trn("count.warnings", values["warning_count"]))
        self.counter.setText(" · ".join(parts))

    def _set_trip_summary(self, day_count: int, stage_count: int):
        self.trip_summary.setText(
            f"{trn('count.days', day_count)} · {trn('count.stages', stage_count)}"
        )

    def _populate_play_speeds(self):
        current_interval = self.play_speed.currentData() if self.play_speed.count() else 2000
        decimal = "," if get_language() == "it" else "."
        self.play_speed.blockSignals(True)
        self.play_speed.clear()
        for label, interval in (
            (f"0{decimal}5×", 4000), ("1×", 2000), ("2×", 1000), ("4×", 500)
        ):
            self.play_speed.addItem(label, interval)
        index = self.play_speed.findData(current_interval)
        self.play_speed.setCurrentIndex(index if index >= 0 else 1)
        self.play_speed.blockSignals(False)

    def _populate_gps_filter(self, selected=None):
        self.gps_filter.blockSignals(True)
        self.gps_filter.clear()
        self.gps_filter.addItem(tr("filters.all_photos"), None)
        self.gps_filter.addItem(tr("filters.with_gps"), True)
        self.gps_filter.addItem(tr("filters.without_gps"), False)
        index = self.gps_filter.findData(selected)
        self.gps_filter.setCurrentIndex(max(0, index))
        self.gps_filter.blockSignals(False)

    def _change_language(self, _index: int):
        language = self.language_combo.currentData()
        if language not in LANGUAGES or language == get_language():
            return
        set_language(language)
        self.settings.setValue("language", language)
        if self._photo_viewer is not None:
            self._photo_viewer.close()
        self._retranslate_ui()

    def _retranslate_ui(self):
        selected_day = self.day_filter.currentData()
        selected_stage = self.stage_filter.currentData()
        selected_gps = self.gps_filter.currentData()

        self.open_btn.setText(tr("toolbar.open_folder"))
        self.cancel_btn.setText(tr("toolbar.cancel"))
        self.path_edit.setPlaceholderText(tr("toolbar.folder_placeholder"))
        self.search_edit.setPlaceholderText(tr("toolbar.search_placeholder"))
        self.language_combo.setToolTip(tr("toolbar.language"))
        self.filters_caption.setText(tr("filters.label"))
        self.route_check.setText(tr("filters.route"))
        self.heat_check.setText(tr("filters.heatmap"))
        self.gallery_title.setText(tr("gallery.title"))
        self.map_title.setText(tr("map.title"))
        self.map_home_btn.setToolTip(tr("map.full_extent"))
        self.details_title.setText(tr("details.title"))
        self.viewer_btn.setToolTip(tr("details.open_viewer"))
        self.preview.setToolTip(tr("details.preview_tooltip"))
        self.timeline_title.setText(tr("timeline.title"))
        self.timeline_zoom_out_btn.setToolTip(tr("timeline.zoom_out"))
        self.timeline_reset_btn.setToolTip(tr("timeline.fit"))
        self.timeline_zoom_in_btn.setToolTip(tr("timeline.zoom_in"))
        for label, caption_key in self.detail_captions.values():
            label.setText(tr(caption_key))

        self._populate_day_filter()
        self._populate_stage_filter()
        self._populate_gps_filter(selected_gps)
        for combo, value in (
            (self.day_filter, selected_day),
            (self.stage_filter, selected_stage),
        ):
            index = combo.findData(value)
            combo.setCurrentIndex(max(0, index))
        self._populate_play_speeds()
        self._refresh_counter()

        if self.photos:
            days = len({p.taken_at.date() for p in self.photos if p.taken_at})
            self._set_trip_summary(days, len(self.stages))
            self.apply_filter()
        else:
            self.trip_summary.setText(tr("trip.none"))
            self.timeline_label.setText(tr("timeline.select_folder"))
            self._clear_details()

    def _populate_day_filter(self):
        days = sorted({p.taken_at.date() for p in self.photos if p.taken_at})
        self.day_filter.blockSignals(True)
        self.day_filter.clear(); self.day_filter.addItem(tr("filters.all_days"), None)
        for day in days:
            self.day_filter.addItem(day.strftime("%d/%m/%Y"), day.isoformat())
        self.day_filter.blockSignals(False)

    def _populate_stage_filter(self):
        self.stage_filter.blockSignals(True)
        self.stage_filter.clear(); self.stage_filter.addItem(tr("filters.all_stages"), None)
        for stage in self.stages:
            self.stage_filter.addItem(stage.label, stage.number)
        self.stage_filter.blockSignals(False)

    def apply_filter(self):
        if not self.photos:
            self.visible_indices = []
            self.photo_list.clear()
            self._items_by_index.clear()
            self.map_widget.set_photos([], [])
            self.timeline.set_photos([], [])
            self._clear_details()
            return

        current_item = self.photo_list.currentItem()
        selected_index = (
            current_item.data(Qt.ItemDataRole.UserRole) if current_item else None
        )

        query = self.search_edit.text().strip().lower()
        day_raw = self.day_filter.currentData()
        selected_day = date.fromisoformat(day_raw) if day_raw else None
        stage_number = self.stage_filter.currentData()
        gps_required = self.gps_filter.currentData()
        stage_indices = None
        if stage_number is not None:
            stage = next((s for s in self.stages if s.number == stage_number), None)
            stage_indices = set(stage.indices) if stage else set()

        self.visible_indices = []
        for i, photo in enumerate(self.photos):
            if query and query not in photo.filename.lower():
                continue
            if selected_day and (not photo.taken_at or photo.taken_at.date() != selected_day):
                continue
            if stage_indices is not None and i not in stage_indices:
                continue
            if gps_required is not None and photo.has_gps != gps_required:
                continue
            self.visible_indices.append(i)

        self.populate_list()
        self.map_widget.set_photos(self.photos, self.visible_indices)
        self.map_home_btn.setEnabled(
            any(self.photos[index].has_gps for index in self.visible_indices)
        )
        self.timeline.set_photos(self.photos, self.visible_indices)
        self._toggle_heatmap(self.heat_check.isChecked())
        self._toggle_route(self.route_check.isChecked())
        self.timeline_label.setText(
            trn("timeline.filtered_count", len(self.visible_indices))
        )
        if self.visible_indices:
            target = selected_index if selected_index in self.visible_indices else self.visible_indices[0]
            self._suppress_map_focus = True
            try:
                self.photo_list.setCurrentRow(self.visible_indices.index(target))
            finally:
                self._suppress_map_focus = False
        else:
            self._clear_details()

    def populate_list(self):
        self._thumbnail_generation += 1
        generation = self._thumbnail_generation
        self.photo_list.clear()
        self._items_by_index.clear()
        for original_index in self.visible_indices:
            photo = self.photos[original_index]
            date_text = photo.taken_at.strftime("%d/%m/%Y") if photo.taken_at else tr("date.unknown")
            time_text = photo.taken_at.strftime("%H:%M") if photo.taken_at else ""
            full_date_text = photo.taken_at.strftime("%d/%m/%Y  %H:%M") if photo.taken_at else tr("date.unknown")
            gps_text = "  📍" if photo.has_gps else ""
            item_text = f"{photo.filename}{gps_text}\n{date_text}"
            if time_text:
                item_text += f"\n{time_text}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, original_index)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setToolTip(f"{photo.filename}\n{full_date_text}")
            self.photo_list.addItem(item)
            self._items_by_index[original_index] = item
            worker = ThumbnailWorker(generation, original_index, photo.path)
            worker.signals.finished.connect(self._thumbnail_ready)
            self._thumbnail_pool.start(worker)

    def _thumbnail_ready(self, generation: int, original_index: int, thumbnail_path: str):
        if generation != self._thumbnail_generation or not thumbnail_path:
            return
        item = self._items_by_index.get(original_index)
        if item is None:
            return
        pixmap = QPixmap(thumbnail_path)
        if not pixmap.isNull():
            thumbnail_size = self.photo_list.iconSize()
            scaled = pixmap.scaled(
                thumbnail_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = max(0, (scaled.width() - thumbnail_size.width()) // 2)
            y = max(0, (scaled.height() - thumbnail_size.height()) // 2)
            item.setIcon(QIcon(scaled.copy(x, y, thumbnail_size.width(), thumbnail_size.height())))

    def on_photo_selected(self, row: int):
        if row < 0:
            return
        item = self.photo_list.item(row)
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None or index >= len(self.photos):
            return
        self._show_index(index)

    def select_original_index(self, original_index: int):
        for row in range(self.photo_list.count()):
            item = self.photo_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == original_index:
                self.photo_list.setCurrentRow(row)
                self.photo_list.scrollToItem(item)
                return

    def _show_index(self, index: int):
        photo = self.photos[index]
        self.show_photo(photo, index)
        self.timeline.set_selected(index)
        if photo.has_gps and not self._suppress_map_focus:
            self.map_widget.focus_photo(index)
        try:
            self._play_pos = self.visible_indices.index(index)
        except ValueError:
            pass

    def _stage_for_index(self, index: int) -> TripStage | None:
        return next((s for s in self.stages if index in s.indices), None)

    def show_photo(self, photo: PhotoInfo, index: int):
        pixmap = load_pixmap(photo.path, (900, 600))
        if pixmap.isNull():
            self._preview_source = QPixmap()
            self.preview.setPixmap(QPixmap()); self.preview.setText(tr("details.preview_unavailable"))
        else:
            self._preview_source = pixmap
            self._update_preview()

        dt = photo.taken_at.strftime("%d/%m/%Y %H:%M:%S") if photo.taken_at else "—"
        self.detail_values["filename"].setText(photo.filename)
        self.detail_values["datetime"].setText(dt)
        self.detail_values["gps"].setText(tr("details.yes") if photo.has_gps else tr("details.no"))
        self.detail_values["lat"].setText(f"{photo.latitude:.6f}" if photo.latitude is not None else "—")
        self.detail_values["lon"].setText(f"{photo.longitude:.6f}" if photo.longitude is not None else "—")
        self.detail_values["alt"].setText(f"{photo.altitude:.1f} m" if photo.altitude is not None else "—")
        self.detail_values["camera"].setText(photo.camera_model or "—")
        self.detail_values["lens"].setText(photo.lens_model or "—")
        self.detail_values["resolution"].setText(f"{photo.width} × {photo.height}" if photo.width and photo.height else "—")
        self.detail_values["filesize"].setText(self._format_size(photo.file_size) if photo.file_size else "—")
        source_labels = {
            "exif": tr("date.source.exif"),
            "file_mtime": tr("date.source.file_mtime"),
            "unknown": tr("date.source.unknown"),
        }
        self.detail_values["date_source"].setText(
            source_labels.get(photo.taken_at_source, photo.taken_at_source)
        )
        self.detail_values["metadata_status"].setText(photo.metadata_error or tr("details.ok"))
        stage = self._stage_for_index(index)
        self.detail_values["stage"].setText(stage.label if stage else "—")

    def _clear_details(self):
        self._preview_source = QPixmap()
        self.preview.setPixmap(QPixmap())
        self.preview.setText(tr("details.preview_empty"))
        if hasattr(self, "detail_values"):
            for value in self.detail_values.values():
                value.setText("—")

    def _update_preview(self):
        if self._preview_source.isNull():
            return
        scaled = self._preview_source.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setText("")
        self.preview.setPixmap(scaled)

    def open_photo_viewer(self, fullscreen: bool = False):
        item = self.photo_list.currentItem()
        if item is None or not self.visible_indices:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index not in self.visible_indices:
            return
        if self._photo_viewer is not None:
            self._photo_viewer.close()
        viewer = PhotoViewer(self.photos, self.visible_indices, index, self)
        viewer.photo_changed.connect(self.select_original_index)
        viewer.destroyed.connect(
            lambda _object=None, instance=viewer: self._photo_viewer_destroyed(instance)
        )
        self._photo_viewer = viewer
        if fullscreen:
            viewer.showFullScreen()
        else:
            viewer.show()

    def _photo_viewer_destroyed(self, viewer: PhotoViewer):
        if self._photo_viewer is viewer:
            self._photo_viewer = None

    def _toggle_heatmap(self, checked: bool):
        self.map_widget.set_heatmap_visible(checked)

    def _toggle_route(self, checked: bool):
        self.map_widget.set_route_visible(checked)

    def _select_previous(self):
        if not self.visible_indices:
            return
        self._play_pos = max(0, self._play_pos - 1)
        self.select_original_index(self.visible_indices[self._play_pos])

    def _select_next(self):
        if not self.visible_indices:
            return
        self._play_pos = min(len(self.visible_indices) - 1, self._play_pos + 1)
        self.select_original_index(self.visible_indices[self._play_pos])

    def _toggle_playback(self):
        if self.play_timer.isActive():
            self.play_timer.stop(); self._set_playback_icon(False)
        else:
            if not self.visible_indices:
                return
            self.play_timer.start(); self._set_playback_icon(True)

    def _set_playback_icon(self, playing: bool):
        standard_icon = (
            QStyle.StandardPixmap.SP_MediaPause
            if playing
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_btn.setText("")
        self.play_btn.setIcon(self.style().standardIcon(standard_icon))

    def _update_playback_speed(self):
        interval = self.play_speed.currentData()
        if interval:
            self.play_timer.setInterval(interval)

    def _play_next(self):
        if not self.visible_indices:
            self.play_timer.stop(); self._set_playback_icon(False); return
        if self._play_pos >= len(self.visible_indices) - 1:
            self.play_timer.stop(); self._set_playback_icon(False); return
        self._play_pos += 1
        self.select_original_index(self.visible_indices[self._play_pos])

    def _restore_settings(self):
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("main_splitter_v2")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def keyPressEvent(self, event: QKeyEvent):
        if isinstance(self.focusWidget(), QLineEdit):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Left:
            self._select_previous()
        elif event.key() == Qt.Key.Key_Right:
            self._select_next()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_photo_viewer()
        elif event.key() == Qt.Key.Key_F:
            self.open_photo_viewer(fullscreen=True)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("main_splitter_v2", self.splitter.saveState())
        if self._worker is not None:
            self._worker.request_cancel()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(3000):
                event.ignore()
                return
        super().closeEvent(event)

    def _photos_for_export(self) -> list[PhotoInfo]:
        return [self.photos[i] for i in self.visible_indices]

    def _validate_export_selection(self) -> list[PhotoInfo] | None:
        photos = self._photos_for_export()
        if not photos:
            QMessageBox.information(
                self, tr("dialog.export"), tr("export.no_filtered_photos")
            )
            return None
        if not any(photo.has_gps for photo in photos):
            QMessageBox.information(self, tr("dialog.export"), tr("export.no_gps"))
            return None
        return photos

    def export_geojson_clicked(self):
        if not self.photos:
            QMessageBox.information(self, tr("dialog.export"), tr("export.load_first"))
            return
        photos = self._validate_export_selection()
        if photos is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("export.geojson_title"), "travel_photos.geojson", "GeoJSON (*.geojson)"
        )
        if filename:
            export_geojson(Path(filename), photos)
            QMessageBox.information(
                self, tr("dialog.export"), tr("export.geojson_success")
            )

    def export_gpx_clicked(self):
        if not self.photos:
            QMessageBox.information(self, tr("dialog.export"), tr("export.load_first"))
            return
        photos = self._validate_export_selection()
        if photos is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, tr("export.gpx_title"), "travel_photos.gpx", "GPX (*.gpx)"
        )
        if filename:
            export_gpx(Path(filename), photos)
            QMessageBox.information(
                self, tr("dialog.export"), tr("export.gpx_success")
            )

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"
