from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QStandardPaths


@dataclass(slots=True)
class SavedTrip:
    id: str
    name: str
    folder: Path
    state: dict
    updated_at: str


class SavedTripService:
    """User-authored trip sessions, kept separate from disposable photo caches."""

    def __init__(self, app_data_dir: Path | None = None):
        self.base_dir = app_data_dir or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        )

    def _connect(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.base_dir / "saved_trips.sqlite")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE IF NOT EXISTS trips ("
            "id TEXT PRIMARY KEY, name TEXT NOT NULL, folder TEXT NOT NULL, "
            "state TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        return connection

    def list_trips(self) -> list[SavedTrip]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM trips ORDER BY updated_at DESC, name COLLATE NOCASE"
            ).fetchall()
            return [SavedTrip(row["id"], row["name"], Path(row["folder"]),
                              json.loads(row["state"]), row["updated_at"]) for row in rows]
        finally:
            connection.close()

    def save(self, name: str, folder: Path, state: dict, trip_id: str | None = None) -> SavedTrip:
        name = name.strip()
        if not name:
            raise ValueError("A trip name is required")
        trip = SavedTrip(trip_id or uuid4().hex, name, folder.resolve(), state,
                         datetime.now(timezone.utc).isoformat())
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO trips VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, folder=excluded.folder, "
                    "state=excluded.state, updated_at=excluded.updated_at",
                    (trip.id, trip.name, str(trip.folder),
                     json.dumps(state, ensure_ascii=False, allow_nan=False), trip.updated_at),
                )
        finally:
            connection.close()
        return trip

    def delete(self, trip_id: str):
        connection = self._connect()
        try:
            with connection:
                connection.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        finally:
            connection.close()
