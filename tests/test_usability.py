from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QListView, QWidget

from models.photo import PhotoInfo
from services.photo_scanner import PhotoScannerWorker
from ui.main_window import MainWindow
from ui.photo_viewer import load_original_image
from ui.timeline_widget import TimelineWidget


APP = QApplication.instance() or QApplication([])


class DummyMapWidget(QWidget):
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


class MainWindowLayoutTests(unittest.TestCase):
    @patch("ui.main_window.MapWidget", DummyMapWidget)
    def test_gallery_uses_vertical_photo_rows(self):
        window = MainWindow()

        self.assertEqual(window.splitter.count(), 3)
        self.assertEqual(window.photo_list.viewMode(), QListView.ViewMode.ListMode)
        self.assertFalse(window.photo_list.isWrapping())
        self.assertEqual(window.photo_list.iconSize().width(), 120)
        self.assertEqual(window.photo_list.iconSize().height(), 72)
        self.assertNotIn("📁", window.open_btn.text())
        self.assertEqual(window.map_home_btn.text(), "🏠")

        window.close()

    @patch("ui.main_window.MapWidget", DummyMapWidget)
    def test_gallery_shows_filename_date_and_time_on_separate_lines(self):
        window = MainWindow()
        photo = PhotoInfo(
            Path("a-very-long-photo-filename.jpg"),
            "a-very-long-photo-filename.jpg",
            datetime(2026, 8, 24, 17, 35),
        )
        window.photos = [photo]
        window.visible_indices = [0]

        window.populate_list()

        item = window.photo_list.item(0)
        self.assertEqual(
            item.text().splitlines(),
            ["a-very-long-photo-filename.jpg", "24/08/2026", "17:35"],
        )
        self.assertIn("24/08/2026  17:35", item.toolTip())
        window.close()


class OriginalImageTests(unittest.TestCase):
    def test_loads_original_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "original.jpg"
            Image.new("RGB", (321, 123), "red").save(path)

            image = load_original_image(path)

            self.assertEqual((image.width(), image.height()), (321, 123))


class TimelineInteractionTests(unittest.TestCase):
    def test_zoom_and_reset_preserve_full_range(self):
        start = datetime(2026, 8, 24, 10)
        photos = [
            PhotoInfo(Path(f"{index}.jpg"), f"{index}.jpg", start + timedelta(hours=index))
            for index in range(6)
        ]
        timeline = TimelineWidget()
        timeline.set_photos(photos, list(range(len(photos))))
        full_span = timeline._full_end - timeline._full_start

        timeline.zoom_in()
        zoomed_span = timeline._view_end - timeline._view_start
        timeline.reset_view()

        self.assertLess(zoomed_span, full_span)
        self.assertEqual(timeline._view_start, timeline._full_start)
        self.assertEqual(timeline._view_end, timeline._full_end)

    def test_timeline_can_be_rendered(self):
        start = datetime(2026, 8, 24, 10)
        photos = [
            PhotoInfo(
                Path(f"{index}.jpg"),
                f"{index}.jpg",
                start + timedelta(hours=index),
                taken_at_source="file_mtime" if index == 0 else "exif",
            )
            for index in range(8)
        ]
        timeline = TimelineWidget()
        timeline.resize(900, 160)
        timeline.set_photos(photos, list(range(len(photos))))
        timeline.show()
        APP.processEvents()

        rendered = timeline.grab()

        self.assertFalse(rendered.isNull())


class ScannerCancellationTests(unittest.TestCase):
    def test_can_cancel_before_scanning_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker = PhotoScannerWorker(Path(tmp))
            cancelled = []
            worker.cancelled.connect(lambda: cancelled.append(True))

            worker.request_cancel()
            worker.run()

            self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
