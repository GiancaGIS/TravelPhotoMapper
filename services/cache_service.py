from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

from models.photo import PhotoInfo


class CacheService:
    def __init__(self, source_folder: Path, app_data_dir: Path | None = None):
        app_data = app_data_dir or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        )
        folder_hash = hashlib.sha256(str(source_folder.resolve()).encode("utf-8")).hexdigest()[:16]
        self.base_dir = app_data / "catalogs" / folder_hash
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.thumb_dir = self.base_dir / "thumbnails"
        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "catalog.sqlite"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS photos (
                path TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_size INTEGER,
                mtime_ns INTEGER,
                taken_at TEXT,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                camera_model TEXT,
                lens_model TEXT,
                width INTEGER,
                height INTEGER,
                taken_at_source TEXT NOT NULL DEFAULT 'unknown',
                metadata_error TEXT
            )
            """
        )
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(photos)")
        }
        if "taken_at_source" not in columns:
            self.conn.execute(
                "ALTER TABLE photos ADD COLUMN taken_at_source TEXT NOT NULL DEFAULT 'unknown'"
            )
        if "metadata_error" not in columns:
            self.conn.execute("ALTER TABLE photos ADD COLUMN metadata_error TEXT")
        self.conn.commit()

    def get(self, path: Path) -> PhotoInfo | None:
        stat = path.stat()
        row = self.conn.execute(
            "SELECT * FROM photos WHERE path = ?", (str(path.resolve()),)
        ).fetchone()
        if row is None:
            return None
        if row["file_size"] != stat.st_size or row["mtime_ns"] != stat.st_mtime_ns:
            return None

        return PhotoInfo(
            path=path,
            filename=row["filename"],
            taken_at=datetime.fromisoformat(row["taken_at"]) if row["taken_at"] else None,
            latitude=row["latitude"],
            longitude=row["longitude"],
            altitude=row["altitude"],
            camera_model=row["camera_model"],
            lens_model=row["lens_model"],
            width=row["width"],
            height=row["height"],
            file_size=row["file_size"],
            taken_at_source=row["taken_at_source"] or "unknown",
            metadata_error=row["metadata_error"],
        )

    def put(self, photo: PhotoInfo, *, commit: bool = True):
        stat = photo.path.stat()
        self.conn.execute(
            """
            INSERT INTO photos (
                path, filename, file_size, mtime_ns, taken_at, latitude, longitude,
                altitude, camera_model, lens_model, width, height,
                taken_at_source, metadata_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename,
                file_size=excluded.file_size,
                mtime_ns=excluded.mtime_ns,
                taken_at=excluded.taken_at,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                altitude=excluded.altitude,
                camera_model=excluded.camera_model,
                lens_model=excluded.lens_model,
                width=excluded.width,
                height=excluded.height,
                taken_at_source=excluded.taken_at_source,
                metadata_error=excluded.metadata_error
            """,
            (
                str(photo.path.resolve()), photo.filename, stat.st_size, stat.st_mtime_ns,
                photo.taken_at.isoformat() if photo.taken_at else None,
                photo.latitude, photo.longitude, photo.altitude,
                photo.camera_model, photo.lens_model, photo.width, photo.height,
                photo.taken_at_source, photo.metadata_error,
            ),
        )
        if commit:
            self.conn.commit()

    def commit(self):
        self.conn.commit()

    def thumbnail_path(self, path: Path) -> Path:
        key = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
        return self.thumb_dir / f"{key}.jpg"

    def close(self):
        self.conn.close()
