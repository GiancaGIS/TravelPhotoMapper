from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

from app_info import APP_NAME, APP_VERSION
from models.photo import PhotoInfo
from services.cache_service import CacheService
from services.exif_reader import _dms_to_decimal, _parse_datetime
from services.export_service import export_geojson, export_gpx
from services.trip_service import build_stages


def photo(
    path: Path,
    taken_at: datetime,
    latitude: float | None = None,
    longitude: float | None = None,
) -> PhotoInfo:
    return PhotoInfo(
        path=path,
        filename=path.name,
        taken_at=taken_at,
        latitude=latitude,
        longitude=longitude,
        taken_at_source="exif",
    )


class ExifParsingTests(unittest.TestCase):
    def test_parses_supported_datetime(self):
        self.assertEqual(
            _parse_datetime("2026:08:24 15:16:17"),
            datetime(2026, 8, 24, 15, 16, 17),
        )

    def test_converts_southern_coordinate(self):
        self.assertAlmostEqual(_dms_to_decimal((33, 30, 0), "S"), -33.5)


class TripServiceTests(unittest.TestCase):
    def test_splits_stages_on_time_and_distance(self):
        start = datetime(2026, 8, 24, 10)
        photos = [
            photo(Path("a.jpg"), start, 45.0, 9.0),
            photo(Path("b.jpg"), start + timedelta(minutes=20), 45.01, 9.01),
            photo(Path("c.jpg"), start + timedelta(hours=3), 45.02, 9.02),
            photo(Path("d.jpg"), start + timedelta(hours=3, minutes=10), 46.0, 10.0),
        ]

        stages = build_stages(photos)

        self.assertEqual([stage.indices for stage in stages], [[0, 1], [2], [3]])


class ExportServiceTests(unittest.TestCase):
    def test_geojson_contains_only_geolocated_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "photos.geojson"
            now = datetime(2026, 8, 24, 10)
            export_geojson(
                target,
                [
                    photo(Path("a.jpg"), now, 45.0, 9.0),
                    photo(Path("b.jpg"), now),
                ],
            )

            payload = json.loads(target.read_text(encoding="utf-8"))
            points = [
                feature for feature in payload["features"]
                if feature["geometry"]["type"] == "Point"
            ]
            self.assertEqual(len(points), 1)
            self.assertEqual(points[0]["properties"]["taken_at_source"], "exif")

    def test_gpx_writes_waypoints_and_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "photos.gpx"
            now = datetime(2026, 8, 24, 10)
            export_gpx(
                target,
                [
                    photo(Path("a.jpg"), now, 45.0, 9.0),
                    photo(Path("b.jpg"), now + timedelta(minutes=5), 45.1, 9.1),
                ],
            )

            root = ElementTree.parse(target).getroot()
            namespace = {"g": "http://www.topografix.com/GPX/1/1"}
            self.assertEqual(root.attrib["creator"], f"{APP_NAME} {APP_VERSION}")
            self.assertEqual(len(root.findall("g:wpt", namespace)), 2)
            self.assertEqual(len(root.findall(".//g:trkpt", namespace)), 2)


class CacheServiceTests(unittest.TestCase):
    def test_persists_metadata_after_explicit_batch_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            app_data = root / "app-data"
            source.mkdir()
            image_path = source / "a.jpg"
            image_path.write_bytes(b"not needed for the cache test")
            expected = photo(image_path, datetime(2026, 8, 24, 10), 45.0, 9.0)
            expected.metadata_error = "test warning"

            cache = CacheService(source, app_data)
            cache.put(expected, commit=False)
            cache.commit()
            cache.close()

            cache = CacheService(source, app_data)
            actual = cache.get(image_path)
            cache.close()

            self.assertIsNotNone(actual)
            self.assertEqual(actual.taken_at_source, "exif")
            self.assertEqual(actual.metadata_error, "test warning")


if __name__ == "__main__":
    unittest.main()
