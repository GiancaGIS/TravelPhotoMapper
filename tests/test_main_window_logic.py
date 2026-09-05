from __future__ import annotations

import unittest
from pathlib import Path

from models.photo import PhotoInfo
from ui.main_window import MainWindow
from ui.map_widget import HTML, MapWidget


class ExportSelectionTests(unittest.TestCase):
    def test_empty_filter_does_not_fall_back_to_all_photos(self):
        window_state = type("WindowState", (), {})()
        window_state.photos = [PhotoInfo(Path("a.jpg"), "a.jpg")]
        window_state.visible_indices = []

        selected = MainWindow._photos_for_export(window_state)

        self.assertEqual(selected, [])

    def test_export_uses_only_visible_photos(self):
        window_state = type("WindowState", (), {})()
        window_state.photos = [
            PhotoInfo(Path("a.jpg"), "a.jpg"),
            PhotoInfo(Path("b.jpg"), "b.jpg"),
        ]
        window_state.visible_indices = [1]

        selected = MainWindow._photos_for_export(window_state)

        self.assertEqual([item.filename for item in selected], ["b.jpg"])


class MapInteractionTests(unittest.TestCase):
    def test_cluster_click_has_explicit_zoom_and_spiderfy_behavior(self):
        self.assertIn("zoomToBoundsOnClick:false", HTML)
        self.assertIn("photoLayer.on('clusterclick'", HTML)
        self.assertIn("cluster.spiderfy()", HTML)

    def test_map_exposes_full_extent_action(self):
        self.assertIn("function fitAllPhotos()", HTML)
        self.assertIn("function fitPhotoCoordinates(coordinates)", HTML)

    def test_full_extent_uses_only_latest_folder_coordinates(self):
        scripts = []
        state = type("MapState", (), {})()
        state.photos = []
        state._fit_coordinates = []
        state._run_javascript = scripts.append
        first_folder = [
            PhotoInfo(Path("first.jpg"), "first.jpg", latitude=45.0, longitude=9.0)
        ]
        second_folder = [
            PhotoInfo(Path("second.jpg"), "second.jpg", latitude=41.9, longitude=12.5)
        ]

        MapWidget.set_photos(state, first_folder)
        MapWidget.set_photos(state, second_folder)
        MapWidget.fit_all_photos(state)

        self.assertEqual(state.photos, second_folder)
        self.assertEqual(state._fit_coordinates, [[41.9, 12.5]])
        self.assertIn("[[41.9, 12.5]]", scripts[-1])
        self.assertNotIn("45.0", scripts[-1])

    def test_new_dataset_invalidates_pending_map_navigation(self):
        self.assertIn("let navigationRevision = 0", HTML)
        self.assertIn("requestRevision !== navigationRevision", HTML)

    def test_automatic_filter_selection_does_not_focus_photo(self):
        focused = []
        state = type("WindowState", (), {})()
        state.photos = [
            PhotoInfo(Path("a.jpg"), "a.jpg", latitude=45.0, longitude=9.0)
        ]
        state.visible_indices = [0]
        state._play_pos = 0
        state._suppress_map_focus = True
        state.show_photo = lambda photo, index: None
        state.timeline = type("Timeline", (), {"set_selected": lambda self, index: None})()
        state.map_widget = type("Map", (), {"focus_photo": lambda self, index: focused.append(index)})()

        MainWindow._show_index(state, 0)

        self.assertEqual(focused, [])


if __name__ == "__main__":
    unittest.main()
