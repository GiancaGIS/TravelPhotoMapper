from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout,
)

from travel_photo_mapper.i18n import tr
from travel_photo_mapper.services.saved_trip_service import SavedTrip, SavedTripService


class SavedTripsDialog(QDialog):
    def __init__(self, service: SavedTripService, parent=None):
        super().__init__(parent)
        self.service = service
        self.selected_trip: SavedTrip | None = None
        self.setWindowTitle(tr("trips.title"))
        self.resize(620, 390)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("trips.description")))
        self.trip_list = QListWidget()
        self.trip_list.itemDoubleClicked.connect(lambda _item: self._open())
        layout.addWidget(self.trip_list)
        self.empty_label = QLabel(tr("trips.empty"))
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        buttons = QHBoxLayout()
        self.open_button = QPushButton(tr("trips.open"))
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self._open)
        self.rename_button = QPushButton(tr("trips.rename"))
        self.rename_button.clicked.connect(self._rename)
        self.delete_button = QPushButton(tr("trips.remove"))
        self.delete_button.clicked.connect(self._remove)
        close_button = QPushButton(tr("common.close"))
        close_button.clicked.connect(self.reject)
        for button in (self.open_button, self.rename_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self.trip_list.clear()
        trips = self.service.list_trips()
        for trip in trips:
            item = QListWidgetItem(f"{trip.name}\n{trip.folder}")
            item.setData(Qt.ItemDataRole.UserRole, trip)
            item.setToolTip(str(trip.folder))
            self.trip_list.addItem(item)
        self.empty_label.setVisible(not trips)
        for button in (self.open_button, self.rename_button, self.delete_button):
            button.setEnabled(bool(trips))
        if trips:
            self.trip_list.setCurrentRow(0)

    def _current(self):
        item = self.trip_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open(self):
        self.selected_trip = self._current()
        if self.selected_trip:
            self.accept()

    def _rename(self):
        trip = self._current()
        if not trip:
            return
        name, accepted = QInputDialog.getText(self, tr("trips.rename"), tr("trips.name"), text=trip.name)
        if accepted and name.strip():
            try:
                self.service.save(name, trip.folder, trip.state, trip.id)
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, tr("dialog.error"), str(exc))

    def _remove(self):
        trip = self._current()
        if not trip:
            return
        if QMessageBox.question(self, tr("trips.remove"), tr("trips.remove_confirm", name=trip.name)) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete(trip.id)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, tr("dialog.error"), str(exc))
