from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from i18n import tr
from models.photo import PhotoInfo


class TimelineWidget(QWidget):
    photo_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(138)
        self.setMouseTracking(True)
        self.photos: list[PhotoInfo] = []
        self.indices: list[int] = []
        self._points: list[tuple[float, int]] = []
        self.selected_index: int | None = None
        self._full_start = 0.0
        self._full_end = 1.0
        self._view_start = 0.0
        self._view_end = 1.0
        self._overview_rect = QRectF()
        self._detail_rect = QRectF()
        self._press_pos: QPoint | None = None
        self._last_x = 0.0
        self._dragging = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_photos(self, photos: list[PhotoInfo], indices: list[int]):
        self.photos = photos
        self.indices = [i for i in indices if photos[i].taken_at is not None]
        self.selected_index = None
        if self.indices:
            times = [photos[i].taken_at.timestamp() for i in self.indices]
            self._full_start = min(times)
            self._full_end = max(max(times), self._full_start + 1.0)
            self.reset_view()
        else:
            self._points = []
            self.update()

    def set_selected(self, index: int | None):
        self.selected_index = index
        if index is not None and index in self.indices:
            timestamp = self.photos[index].taken_at.timestamp()
            if timestamp < self._view_start or timestamp > self._view_end:
                span = self._view_end - self._view_start
                self._set_view(timestamp - span / 2, timestamp + span / 2)
        self.update()

    def reset_view(self):
        self._view_start = self._full_start
        self._view_end = self._full_end
        self.update()

    def zoom_in(self):
        self._zoom_at(0.5, 0.65)

    def zoom_out(self):
        self._zoom_at(0.5, 1 / 0.65)

    def _zoom_at(self, anchor_ratio: float, factor: float):
        if not self.indices:
            return
        full_span = self._full_end - self._full_start
        span = self._view_end - self._view_start
        new_span = max(min(60.0, full_span), min(full_span, span * factor))
        anchor = self._view_start + span * anchor_ratio
        start = anchor - new_span * anchor_ratio
        self._set_view(start, start + new_span)

    def _set_view(self, start: float, end: float):
        full_span = self._full_end - self._full_start
        span = min(end - start, full_span)
        if start < self._full_start:
            start = self._full_start
        if start + span > self._full_end:
            start = self._full_end - span
        self._view_start = start
        self._view_end = start + span
        self.update()

    @staticmethod
    def _x_for(timestamp: float, start: float, end: float, rect: QRectF) -> float:
        ratio = (timestamp - start) / max(end - start, 1.0)
        return rect.left() + ratio * rect.width()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = self.rect().adjusted(18, 7, -18, -8)
        self._overview_rect = QRectF(outer.left(), outer.top(), outer.width(), 24)
        self._detail_rect = QRectF(outer.left(), outer.top() + 39, outer.width(), outer.height() - 39)
        self._points = []

        if not self.indices:
            painter.setPen(QColor("#687078"))
            painter.drawText(
                outer, Qt.AlignmentFlag.AlignCenter, tr("timeline.empty")
            )
            return

        self._draw_overview(painter)
        self._draw_detail(painter)

    def _draw_overview(self, painter: QPainter):
        rect = self._overview_rect
        painter.setPen(QPen(QColor("#cfd5dc"), 1))
        painter.setBrush(QColor("#edf2f2"))
        painter.drawRoundedRect(rect, 3, 3)

        bins = max(20, int(rect.width() / 5))
        counts = [0] * bins
        for index in self.indices:
            timestamp = self.photos[index].taken_at.timestamp()
            position = int((timestamp - self._full_start) / (self._full_end - self._full_start) * (bins - 1))
            counts[max(0, min(bins - 1, position))] += 1
        maximum = max(counts, default=1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0b8790"))
        bin_width = rect.width() / bins
        for position, count in enumerate(counts):
            if count:
                height = max(2.0, (rect.height() - 4) * count / maximum)
                painter.drawRect(QRectF(rect.left() + position * bin_width, rect.bottom() - height - 1, max(1.0, bin_width), height))

        left = self._x_for(self._view_start, self._full_start, self._full_end, rect)
        right = self._x_for(self._view_end, self._full_start, self._full_end, rect)
        viewport = QRectF(left, rect.top(), max(3.0, right - left), rect.height())
        painter.setPen(QPen(QColor("#0b8790"), 2))
        painter.setBrush(QColor(11, 135, 144, 28))
        painter.drawRoundedRect(viewport, 3, 3)

    def _draw_detail(self, painter: QPainter):
        rect = self._detail_rect
        painter.setPen(QPen(QColor("#d6dbe1"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(rect)

        view_start_dt = datetime.fromtimestamp(self._view_start)
        view_end_dt = datetime.fromtimestamp(self._view_end)
        day = view_start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_number = 0
        while day.timestamp() < self._view_end:
            next_day = day + timedelta(days=1)
            left = self._x_for(max(day.timestamp(), self._view_start), self._view_start, self._view_end, rect)
            right = self._x_for(min(next_day.timestamp(), self._view_end), self._view_start, self._view_end, rect)
            if day_number % 2:
                painter.fillRect(QRectF(left, rect.top(), right - left, rect.height()), QColor("#f5f7f9"))
            if day.timestamp() >= self._view_start:
                painter.setPen(QPen(QColor("#b8c0c8"), 1))
                painter.drawLine(int(left), int(rect.top()), int(left), int(rect.bottom()))
                painter.setPen(QColor("#59636e"))
                painter.drawText(
                    QRectF(left + 4, rect.top() + 2, 90, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    day.strftime("%d/%m"),
                )
            day = next_day
            day_number += 1

        visible: list[tuple[float, int]] = []
        columns: dict[int, list[tuple[float, int]]] = {}
        for index in self.indices:
            timestamp = self.photos[index].taken_at.timestamp()
            if self._view_start <= timestamp <= self._view_end:
                x = self._x_for(timestamp, self._view_start, self._view_end, rect)
                visible.append((x, index))
                columns.setdefault(round(x), []).append((x, index))
        self._points = visible

        baseline = rect.bottom() - 13
        maximum = max((len(group) for group in columns.values()), default=1)
        for group in columns.values():
            x = group[0][0]
            count = len(group)
            height = 8 + min(28, 28 * count / maximum)
            painter.setPen(QPen(QColor("#9aa4ae"), 1))
            painter.drawLine(int(x), int(baseline), int(x), int(baseline - height))
            representative = self.photos[group[0][1]]
            colors = {
                "exif": QColor("#0b8790"),
                "file_mtime": QColor("#d99b00"),
                "unknown": QColor("#7b8793"),
            }
            color = colors.get(representative.taken_at_source, colors["unknown"])
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(x - 4, baseline - height - 4, 8, 8))
            if count > 1:
                painter.setPen(QColor("#3f4851"))
                painter.drawText(
                    QRectF(x + 5, baseline - height - 9, 34, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"×{count}",
                )

        if self.selected_index is not None and self.selected_index in self.indices:
            timestamp = self.photos[self.selected_index].taken_at.timestamp()
            if self._view_start <= timestamp <= self._view_end:
                x = self._x_for(timestamp, self._view_start, self._view_end, rect)
                painter.setPen(QPen(QColor("#f0ad00"), 2))
                painter.drawLine(int(x), int(rect.top() + 18), int(x), int(rect.bottom()))
                painter.setBrush(QColor("#f0ad00"))
                painter.drawEllipse(QRectF(x - 6, rect.top() + 13, 12, 12))

        painter.setPen(QColor("#4f5963"))
        fm = QFontMetrics(painter.font())
        left_text = view_start_dt.strftime("%d/%m/%Y %H:%M")
        right_text = view_end_dt.strftime("%d/%m/%Y %H:%M")
        painter.drawText(int(rect.left() + 4), int(rect.bottom() - 2), left_text)
        painter.drawText(
            int(rect.right() - fm.horizontalAdvance(right_text) - 4),
            int(rect.bottom() - 2),
            right_text,
        )

    def wheelEvent(self, event):
        if not self.indices or not self._detail_rect.contains(event.position()):
            return
        ratio = (event.position().x() - self._detail_rect.left()) / max(self._detail_rect.width(), 1.0)
        self._zoom_at(max(0.0, min(1.0, ratio)), 0.72 if event.angleDelta().y() > 0 else 1 / 0.72)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.indices:
            return
        if self._overview_rect.contains(event.position()):
            ratio = (event.position().x() - self._overview_rect.left()) / max(self._overview_rect.width(), 1.0)
            center = self._full_start + ratio * (self._full_end - self._full_start)
            span = self._view_end - self._view_start
            self._set_view(center - span / 2, center + span / 2)
            return
        self._press_pos = event.position().toPoint()
        self._last_x = event.position().x()
        self._dragging = False

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position().x() - self._last_x
            if abs(event.position().x() - self._press_pos.x()) > 3:
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._dragging:
                seconds = -(delta / max(self._detail_rect.width(), 1.0)) * (self._view_end - self._view_start)
                self._set_view(self._view_start + seconds, self._view_end + seconds)
            self._last_x = event.position().x()
            return

        if self._points and self._detail_rect.contains(event.position()):
            distance, index = min((abs(x - event.position().x()), index) for x, index in self._points)
            if distance <= 8:
                photo = self.photos[index]
                sources = {
                    "exif": tr("date.source.exif"),
                    "file_mtime": tr("timeline.source.file_mtime"),
                    "unknown": tr("timeline.source.unknown"),
                }
                source = sources.get(
                    photo.taken_at_source, tr("timeline.source.unknown")
                )
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{photo.filename}\n{photo.taken_at:%d/%m/%Y %H:%M:%S} · {source}",
                    self,
                )
                return
        QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return
        if not self._dragging and self._points:
            _, index = min((abs(x - event.position().x()), index) for x, index in self._points)
            self.photo_selected.emit(index)
        self._press_pos = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event):
        if self._overview_rect.contains(event.position()) or self._detail_rect.contains(event.position()):
            self.reset_view()
            event.accept()
