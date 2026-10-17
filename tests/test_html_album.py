from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

from travel_photo_mapper.models.photo import PhotoInfo
from travel_photo_mapper.services.html_album_service import (
    AlbumCancelled, AlbumExportWorker, album_folder_name, available_album_folder,
    export_html_album,
)


def album_data(document):
    return json.loads(re.search(r'<script id="album-data" type="application/json">(.*?)</script>',
                                document, re.DOTALL)[1])


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "img" and attributes.get("src"):
            self.assets.append(attributes["src"])
        if tag == "a" and attributes.get("href", "").startswith("photos/"):
            self.assets.append(attributes["href"])


class HtmlAlbumTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "original.jpg"
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "Private author"
        Image.new("RGB", (2400, 1200), "red").save(self.source, exif=exif)
        self.original_bytes = self.source.read_bytes()
        self.photo = PhotoInfo(self.source, self.source.name, datetime(2026, 8, 24, 10),
                               latitude=41.9, longitude=12.5, taken_at_source="exif")

    def tearDown(self):
        self.temporary.cleanup()

    def test_album_is_portable_and_derivatives_have_no_exif(self):
        progress = []
        path = export_html_album(self.root / "album", "Roma", [self.photo],
                                 progress=lambda current, total: progress.append((current, total)))
        relocated = self.root / "relocated"
        shutil.move(path.parent, relocated)
        document = (relocated / "index.html").read_text(encoding="utf-8")
        parser = AssetParser()
        parser.feed(document)
        self.assertGreater(len(parser.assets), 0)
        self.assertTrue(all((relocated / asset).is_file() for asset in parser.assets))
        with Image.open(relocated / "photos/00001.jpg") as derivative:
            self.assertEqual(derivative.size, (960, 1920))
            self.assertEqual(dict(derivative.getexif()), {})
        with Image.open(relocated / "thumbnails/00001.jpg") as thumbnail:
            self.assertLessEqual(thumbnail.width, 480)
            self.assertLessEqual(thumbnail.height, 360)
            self.assertEqual(dict(thumbnail.getexif()), {})
        self.assertEqual(self.source.read_bytes(), self.original_bytes)
        self.assertNotIn(str(self.root), document)
        self.assertNotIn("Private author", document)
        self.assertEqual(album_data(document)[0]["coordinates"], [41.9, 12.5])
        self.assertEqual(progress, [(1, 1)])

    def test_location_opt_out_removes_coordinates_and_hides_map(self):
        path = export_html_album(self.root / "album", "Roma", [self.photo], include_gps=False)
        document = path.read_text(encoding="utf-8")
        self.assertNotIn("coordinates", album_data(document)[0])
        self.assertNotIn("41.9", document)
        self.assertIn('<section id="map-section" hidden>', document)

    def test_local_album_uses_separate_map_service_with_visible_attribution(self):
        path = export_html_album(self.root / "album", "Roma", [self.photo])
        document = path.read_text(encoding="utf-8")
        self.assertIn('content="strict-origin-when-cross-origin"', document)
        self.assertNotIn('content="no-referrer"', document)
        self.assertNotIn("tile.openstreetmap.org", document)
        self.assertIn("https://tiles.openfreemap.org/styles/liberty", document)
        self.assertIn("https://openmaptiles.org/", document)
        self.assertIn("https://www.openstreetmap.org/copyright", document)

    def test_photos_without_gps_and_same_names_are_all_exported(self):
        other = self.root / "other"
        other.mkdir()
        second_source = other / "original.jpg"
        Image.new("RGBA", (100, 80), (0, 0, 0, 0)).save(second_source, format="PNG")
        second = PhotoInfo(second_source, "original.jpg")
        self.photo.latitude = self.photo.longitude = None
        path = export_html_album(self.root / "album", "Trip", [self.photo, second], language="en")
        data = album_data(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 2)
        self.assertNotEqual(data[0]["src"], data[1]["src"])
        self.assertEqual(data[1]["date"], "Unknown date")
        with Image.open(path.parent / data[1]["src"]) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_untrusted_titles_and_filenames_cannot_break_out_of_markup(self):
        payload = '</script><script>alert("oops")</script>&@@CARDS@@'
        self.photo.filename = payload
        path = export_html_album(self.root / "album", payload, [self.photo])
        document = path.read_text(encoding="utf-8")
        self.assertNotIn(payload, document)
        self.assertIn("&lt;/script&gt;", document)
        self.assertEqual(album_data(document)[0]["filename"], payload)

    def test_cancel_and_failed_image_leave_no_partial_album(self):
        for should_fail in (False, True):
            with self.subTest(should_fail=should_fail):
                destination = self.root / "album"
                if should_fail:
                    self.photo.path = self.root / "missing.jpg"
                    with self.assertRaises(OSError):
                        export_html_album(destination, "Trip", [self.photo])
                else:
                    stop = []
                    with self.assertRaises(AlbumCancelled):
                        export_html_album(destination, "Trip", [self.photo, self.photo],
                                          progress=lambda *_: stop.append(True), cancelled=lambda: bool(stop))
                self.assertFalse(destination.exists())
                self.assertEqual(list(self.root.glob(".travel-album-*")), [])

    def test_existing_output_is_not_overwritten_and_empty_export_is_rejected(self):
        destination = self.root / "album"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            export_html_album(destination, "Trip", [self.photo])
        self.assertEqual(marker.read_text(), "keep")
        with self.assertRaises(ValueError):
            export_html_album(self.root / "empty", "Trip", [])
        self.assertFalse((self.root / "empty").exists())

    def test_worker_cancel_before_start_creates_nothing(self):
        destination = self.root / "album"
        worker = AlbumExportWorker(destination, "Trip", [self.photo], "en", True)
        cancelled = []
        worker.cancelled.connect(lambda: cancelled.append(True))
        worker.request_cancel()
        worker.run()
        self.assertEqual(cancelled, [True])
        self.assertFalse(destination.exists())

    def test_album_destination_stays_within_parent_and_uses_new_folder(self):
        for title in ("../../escape", "CON", "...", "Travel / Rome", "Roma 😄"):
            self.assertEqual((self.root / album_folder_name(title)).parent, self.root)
        first = available_album_folder(self.root, "Roma")
        first.mkdir()
        self.assertEqual(available_album_folder(self.root, "Roma").name, "album-Roma-2")
