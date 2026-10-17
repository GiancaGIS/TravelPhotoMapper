from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout

from travel_photo_mapper.app_info import APP_VERSION
from travel_photo_mapper.i18n import tr
from travel_photo_mapper.services.update_service import UpdateResult


class UpdateToast(QFrame):
    release_requested = pyqtSignal(str)
    DISPLAY_TIME_MS = 15_000

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("updateToast")
        self.setStyleSheet("""
            QFrame#updateToast { background:#fff; border:1px solid #a9cccb;
                border-left:4px solid #0b8790; border-radius:8px; }
            QFrame#updateToast QLabel { border:0; background:transparent; }
            QLabel#toastTitle { font-weight:700; color:#176568; }
        """)
        self._result: UpdateResult | None = None
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._auto_dismiss)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 12, 12)
        layout.setSpacing(9)
        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("toastTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setProperty("compact", True)
        self.close_button.clicked.connect(self.dismiss)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        self.message_label = QLabel()
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        self.open_button = QPushButton()
        self.open_button.clicked.connect(self._open_release)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignLeft)
        parent.installEventFilter(self)
        self.hide()

    def present(self, result: UpdateResult):
        self._result = result
        self.retranslate()
        self._position()
        self.show()
        self.raise_()
        self._dismiss_timer.start(self.DISPLAY_TIME_MS)

    def retranslate(self):
        self.title_label.setText(tr("updates.title"))
        self.close_button.setToolTip(tr("common.close"))
        self.close_button.setAccessibleName(tr("common.close"))
        self.open_button.setText(tr("updates.open_release"))
        if self._result is not None:
            self.message_label.setText(tr("updates.available", latest=self._result.tag, current=APP_VERSION))
            self._position()

    def dismiss(self):
        self._dismiss_timer.stop()
        self.hide()

    def _auto_dismiss(self):
        focus = QApplication.focusWidget()
        if self.underMouse() or (focus is not None and self.isAncestorOf(focus)):
            self._dismiss_timer.start(self.DISPLAY_TIME_MS)
        else:
            self.dismiss()

    def _open_release(self):
        if self._result is not None:
            self.release_requested.emit(self._result.release_url)
        self.dismiss()

    def _position(self):
        parent = self.parentWidget()
        margin = 16
        self.setFixedWidth(max(1, min(420, parent.width() - margin * 2)))
        self.adjustSize()
        self.move(max(0, parent.width() - self.width() - margin),
                  max(0, parent.height() - self.height() - margin))

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._position()
        return super().eventFilter(watched, event)
