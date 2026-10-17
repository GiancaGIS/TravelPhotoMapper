from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from travel_photo_mapper.services.saved_trip_service import SavedTripService


class SavedTripServiceTests(unittest.TestCase):
    def test_sessions_survive_restart_and_update_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = SavedTripService(root / "data")
            state = {"search": "città", "gps": False, "selected_path": "day-2/a.jpg",
                     "timeline_view": [100.0, 200.0]}
            first = service.save("  Vacanze in città  ", root / "photos", state)
            service.save("Montagna", root / "mountain", {})
            updated = service.save("Estate", first.folder, state, first.id)
            trips = SavedTripService(root / "data").list_trips()

            self.assertEqual(len(trips), 2)
            self.assertEqual(trips[0], updated)
            self.assertEqual(trips[0].state, state)
            self.assertTrue(trips[0].folder.is_absolute())

    def test_removing_trip_preserves_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "photo.jpg"
            original.write_bytes(b"original")
            service = SavedTripService(root / "data")
            trip = service.save("Trip", root, {})
            service.delete(trip.id)

            self.assertEqual(service.list_trips(), [])
            self.assertEqual(original.read_bytes(), b"original")

    def test_rejected_save_does_not_replace_previous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = SavedTripService(Path(tmp))
            trip = service.save("Trip", Path(tmp), {"search": "before"})
            with self.assertRaises(TypeError):
                service.save("After", trip.folder, {"bad": object()}, trip.id)
            self.assertEqual(service.list_trips()[0], trip)
            with self.assertRaises(ValueError):
                service.save("  ", trip.folder, {})
