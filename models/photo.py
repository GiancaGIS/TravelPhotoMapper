
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class PhotoInfo:
    path: Path
    filename: str
    taken_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    taken_at_source: str = "unknown"
    metadata_error: str | None = None

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None
