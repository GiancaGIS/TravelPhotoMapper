from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

from i18n import tr, trn
from models.photo import PhotoInfo


@dataclass(slots=True)
class TripStage:
    number: int
    indices: list[int]
    start: datetime
    end: datetime
    latitude: float | None
    longitude: float | None

    @property
    def label(self) -> str:
        return tr(
            "stage.label",
            number=self.number,
            start=f"{self.start:%d/%m %H:%M}",
            photos=trn("count.photos", len(self.indices)),
        )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def build_stages(
    photos: list[PhotoInfo],
    time_gap_hours: float = 2.0,
    distance_gap_km: float = 30.0,
) -> list[TripStage]:
    """Inferisce tappe cronologiche. Non rappresenta una traccia GPS reale."""
    candidates = [
        (i, p) for i, p in enumerate(photos)
        if p.taken_at is not None and p.has_gps
    ]
    if not candidates:
        return []

    groups: list[list[tuple[int, PhotoInfo]]] = [[candidates[0]]]
    for current in candidates[1:]:
        prev_i, prev = groups[-1][-1]
        cur_i, cur = current
        dt_hours = (cur.taken_at - prev.taken_at).total_seconds() / 3600.0
        distance = haversine_km(prev.latitude, prev.longitude, cur.latitude, cur.longitude)
        if dt_hours > time_gap_hours or distance > distance_gap_km:
            groups.append([current])
        else:
            groups[-1].append(current)

    stages: list[TripStage] = []
    for n, group in enumerate(groups, start=1):
        indices = [i for i, _ in group]
        ps = [p for _, p in group]
        stages.append(TripStage(
            number=n,
            indices=indices,
            start=ps[0].taken_at,
            end=ps[-1].taken_at,
            latitude=sum(p.latitude for p in ps) / len(ps),
            longitude=sum(p.longitude for p in ps) / len(ps),
        ))
    return stages
