from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PyQt6.QtCore import QSettings, Qt, QUrl, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PyQt6.QtWebEngineWidgets import QWebEngineView

from travel_photo_mapper.i18n import set_language, tr
from travel_photo_mapper.models.photo import PhotoInfo
from travel_photo_mapper.services.cache_service import CacheService
from travel_photo_mapper.services.html_album_service import export_html_album
from travel_photo_mapper.services.saved_trip_service import SavedTripService
from travel_photo_mapper.ui.album_export_dialog import AlbumExportDialog
from travel_photo_mapper.ui.main_window import MainWindow
from travel_photo_mapper.ui.saved_trips_dialog import SavedTripsDialog


APP = QApplication.instance() or QApplication(["TravelPhotoMapper-tests"])


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    if not predicate():
        raise AssertionError("Timed out waiting for Qt")


class DummyMap(QWidget):
    photo_selected = pyqtSignal(int)

    def set_photos(self, *_args):
        pass

    def fit_all_photos(self):
        pass

    def set_heatmap_visible(self, _visible):
        pass

    def set_route_visible(self, _visible):
        pass

    def focus_photo(self, _index):
        pass


class TripAlbumUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.folder = self.root / "photos"
        self.folder.mkdir()
        self.service = SavedTripService(self.root / "data")
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("language", "en")
        self.patches = [patch("travel_photo_mapper.ui.main_window.MapWidget", DummyMap),
                        patch("travel_photo_mapper.ui.main_window.SavedTripService", return_value=self.service),
                        patch("travel_photo_mapper.ui.main_window.QSettings", return_value=self.settings),
                        patch("travel_photo_mapper.ui.main_window.QMessageBox.critical")]
        for item in self.patches:
            item.start()
        self.windows = []
        self.photos = []
        for index in range(3):
            path = self.folder / f"shot-{index}.jpg"
            Image.new("RGB", (80, 60), "teal").save(path)
            self.photos.append(PhotoInfo(path, path.name,
                                        datetime(2026, 8, 24, 10) + timedelta(minutes=20 * index),
                                        latitude=41.9, longitude=12.5))

    def tearDown(self):
        for window in self.windows:
            if window._album_thread:
                window._album_worker.request_cancel()
                wait_for(lambda: window._album_thread is None)
            if window._thread:
                wait_for(lambda: window._thread is None)
            window.close()
        APP.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()
        set_language("it")

    def window(self, photos=None):
        window = MainWindow()
        self.windows.append(window)
        window._current_folder = self.folder
        window.on_scan_finished(self.photos if photos is None else photos, 0, 3)
        return window

    def test_saved_session_restores_filters_selection_timeline_and_playback(self):
        first = self.window()
        first.search_edit.setText("shot")
        first.day_filter.setCurrentIndex(1)
        first.stage_filter.setCurrentIndex(1)
        first.gps_filter.setCurrentIndex(first.gps_filter.findData(True))
        first.route_check.setChecked(False)
        first.heat_check.setChecked(True)
        first.play_speed.setCurrentIndex(first.play_speed.findData(500))
        first.apply_filter()
        first.select_original_index(1)
        first.timeline.zoom_in()
        state = first._trip_state()
        with patch("travel_photo_mapper.ui.main_window.QInputDialog.getText", return_value=("Summer in Rome", True)):
            first.save_trip_clicked()
        self.assertEqual(len(self.service.list_trips()), 1)
        trip = self.service.list_trips()[0]
        self.assertEqual(trip.state, state)

        second = MainWindow()
        self.windows.append(second)
        second._current_folder = self.folder
        second._pending_trip = trip
        second.on_scan_finished(self.photos, 3, 0)
        self.assertEqual(second._trip_state(), state)
        self.assertIn("Summer in Rome", second.windowTitle())
        second.search_edit.setText("shot-2")
        second.apply_filter()
        second.close()
        self.assertEqual(self.service.list_trips()[0].state["selected_path"], "shot-2.jpg")

    def test_session_selection_survives_reordering_and_removed_files(self):
        window = self.window()
        window.select_original_index(2)
        state = window._trip_state()
        reordered = self.window([self.photos[2], self.photos[0]])
        reordered._restore_trip_state(state)
        self.assertEqual(reordered.photo_list.currentRow(), 0)
        self.assertEqual(reordered._trip_state()["selected_path"], "shot-2.jpg")
        missing = self.window([self.photos[0]])
        missing._restore_trip_state(state)
        self.assertEqual(missing.photo_list.currentRow(), 0)

    def test_fresh_folder_load_clears_search_and_saves_active_session(self):
        window = self.window()
        window.search_edit.setText("shot-1")
        window.apply_filter()
        window._active_trip = self.service.save("Rome", self.folder, {})
        other = self.root / "other"
        other.mkdir()
        with patch("travel_photo_mapper.services.photo_scanner.CacheService", side_effect=lambda folder: CacheService(folder, self.root / "cache")):
            window.load_folder(other)
            wait_for(lambda: window._thread is None)
        self.assertEqual(window.search_edit.text(), "")
        self.assertEqual(window.photos, [])
        self.assertIsNone(window._active_trip)
        self.assertEqual(self.service.list_trips()[0].state["search"], "shot-1")

    def test_trip_dialog_rename_and_remove_do_not_touch_photos(self):
        trip = self.service.save("Old name", self.folder, {"search": "shot"})
        dialog = SavedTripsDialog(self.service)
        with patch("travel_photo_mapper.ui.saved_trips_dialog.QInputDialog.getText", return_value=("New name", True)):
            dialog._rename()
        self.assertEqual(self.service.list_trips()[0].id, trip.id)
        self.assertEqual(self.service.list_trips()[0].name, "New name")
        with patch("travel_photo_mapper.ui.saved_trips_dialog.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            dialog._remove()
        self.assertEqual(self.service.list_trips(), [])
        self.assertEqual(len(list(self.folder.glob("*.jpg"))), 3)
        self.assertFalse(dialog.open_button.isEnabled())

    def test_album_export_uses_only_filtered_photos_without_requiring_gps(self):
        window = self.window()
        window.search_edit.setText("shot-1")
        window.apply_filter()
        dialog = AlbumExportDialog("My trip", 1, str(self.root))
        dialog.gps_check.setChecked(False)
        with patch("travel_photo_mapper.ui.main_window.AlbumExportDialog", return_value=dialog), \
             patch.object(dialog, "exec", return_value=QDialog.DialogCode.Accepted), \
             patch("travel_photo_mapper.ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            window.export_album_clicked()
            wait_for(lambda: window._album_thread is None)
        document = (self.root / "album-My-trip/index.html").read_text(encoding="utf-8")
        self.assertIn("shot-1.jpg", document)
        self.assertNotIn("shot-0.jpg", document)
        self.assertNotIn("shot-2.jpg", document)
        self.assertTrue(window.export_album_btn.isEnabled())
        self.assertIsNone(window._album_progress)

    def test_cancelled_and_failed_scan_do_not_overwrite_saved_trip(self):
        window = self.window()
        trip = self.service.save("Rome", self.folder, {"search": "before"})
        window._pending_trip = trip
        window.on_scan_cancelled()
        self.assertIsNone(window._pending_trip)
        window._pending_trip = trip
        window.on_scan_failed("Test failure")
        self.assertIsNone(window._pending_trip)
        self.assertEqual(self.service.list_trips()[0], trip)


class BlockNetwork(QWebEngineUrlRequestInterceptor):
    def __init__(self):
        super().__init__()
        self.blocked = []

    def interceptRequest(self, info):
        if info.requestUrl().scheme() in ("http", "https"):
            self.blocked.append(info.requestUrl().toString())
            info.block(True)


class AlbumRendererTests(unittest.TestCase):
    def test_offline_album_opens_images_navigates_and_handles_unavailable_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            Image.new("RGB", (100, 70), "gold").save(source)
            filename = '<script>alert("x")</script>.jpg'
            photos = [PhotoInfo(source, filename, latitude=41.9, longitude=12.5),
                      PhotoInfo(source, "second.jpg")]
            path = export_html_album(root / "album", "Rome <2026>", photos, language="en")
            view = QWebEngineView()
            view.resize(1200, 900)
            view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            view.show()
            blocker = BlockNetwork()
            view.page().profile().setUrlRequestInterceptor(blocker)

            def evaluate(script):
                result = []
                view.page().runJavaScript(script, result.append)
                wait_for(lambda: bool(result))
                return result[0]

            try:
                loaded = []
                view.loadFinished.connect(loaded.append)
                view.load(QUrl.fromLocalFile(str(path)))
                wait_for(lambda: bool(loaded))
                self.assertTrue(loaded[0])
                self.assertEqual(evaluate("document.querySelector('h1').textContent"), "Rome <2026>")
                wait_for(lambda: evaluate("Array.from(document.querySelectorAll('.card img')).every(img => img.complete && img.naturalWidth > 0)"))
                self.assertEqual(blocker.blocked, [])
                view.resize(390, 900)
                wait_for(lambda: evaluate("window.innerWidth <= 390"))
                self.assertTrue(evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
                evaluate("document.querySelector('.card').click()")
                self.assertTrue(evaluate("document.getElementById('viewer').open"))
                self.assertIn(filename, evaluate("document.getElementById('viewer-caption').textContent"))
                evaluate("document.getElementById('next').click()")
                self.assertEqual(evaluate("document.getElementById('viewer-count').textContent"), "2 / 2")
                evaluate("document.getElementById('viewer').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft'}))")
                self.assertEqual(evaluate("document.getElementById('viewer-count').textContent"), "1 / 2")
                evaluate("document.getElementById('close-viewer').click()")
                self.assertFalse(evaluate("document.getElementById('viewer').open"))
                evaluate("document.getElementById('load-map').click()")
                wait_for(lambda: bool(blocker.blocked))
                wait_for(lambda: evaluate("!document.getElementById('load-map').disabled"))
                self.assertIn("Map unavailable", evaluate("document.getElementById('map-status').textContent"))
                blocked_count = len(blocker.blocked)
                evaluate("document.getElementById('load-map').click()")
                wait_for(lambda: len(blocker.blocked) > blocked_count)
                wait_for(lambda: evaluate("!document.getElementById('load-map').disabled"))
                evaluate("document.querySelector('.card').click()")
                self.assertTrue(evaluate("document.getElementById('viewer').open"))
                self.assertFalse(any('tile.openstreetmap.org' in url for url in blocker.blocked))
            finally:
                view.page().profile().setUrlRequestInterceptor(None)
                view.close()
                view.deleteLater()
                APP.processEvents()
