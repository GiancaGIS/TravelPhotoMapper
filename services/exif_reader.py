
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ExifTags
from pillow_heif import register_heif_opener

from i18n import tr
from models.photo import PhotoInfo

register_heif_opener()

GPS_TAG = 34853
DATETIME_ORIGINAL_TAG = 36867
DATETIME_DIGITIZED_TAG = 36868
DATETIME_TAG = 306
MAKE_TAG = 271
MODEL_TAG = 272
LENS_MODEL_TAG = 42036


def _ratio_to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0]) / float(value[1])
        raise


def _dms_to_decimal(dms, ref: str | bytes | None) -> float | None:
    if not dms or len(dms) < 3:
        return None
    degrees = _ratio_to_float(dms[0])
    minutes = _ratio_to_float(dms[1])
    seconds = _ratio_to_float(dms[2])
    value = degrees + minutes / 60.0 + seconds / 3600.0

    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    if ref in ("S", "W"):
        value *= -1
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode(errors="ignore")
    value = str(value).strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _decode_gps(gps_raw: Any) -> dict:
    if not gps_raw:
        return {}
    gps = {}
    try:
        items = gps_raw.items()
    except AttributeError:
        return {}

    for key, value in items:
        gps[ExifTags.GPSTAGS.get(key, key)] = value
    return gps


def read_photo_metadata(path: Path) -> PhotoInfo:
    stat = path.stat()
    info = PhotoInfo(
        path=path,
        filename=path.name,
        file_size=stat.st_size,
    )

    warnings: list[str] = []
    try:
        with Image.open(path) as image:
            info.width, info.height = image.size
            exif = image.getexif()

            dt = (
                exif.get(DATETIME_ORIGINAL_TAG)
                or exif.get(DATETIME_DIGITIZED_TAG)
                or exif.get(DATETIME_TAG)
            )
            info.taken_at = _parse_datetime(dt)
            if info.taken_at is not None:
                info.taken_at_source = "exif"

            make = exif.get(MAKE_TAG)
            model = exif.get(MODEL_TAG)
            if isinstance(make, bytes):
                make = make.decode(errors="ignore")
            if isinstance(model, bytes):
                model = model.decode(errors="ignore")
            camera = " ".join(
                str(x).strip() for x in (make, model) if x and str(x).strip()
            ).strip()
            info.camera_model = camera or None

            lens = exif.get(LENS_MODEL_TAG)
            if isinstance(lens, bytes):
                lens = lens.decode(errors="ignore")
            info.lens_model = str(lens).strip() if lens else None

            gps = _decode_gps(exif.get_ifd(GPS_TAG) if GPS_TAG in exif else None)
            if gps:
                info.latitude = _dms_to_decimal(
                    gps.get("GPSLatitude"), gps.get("GPSLatitudeRef")
                )
                info.longitude = _dms_to_decimal(
                    gps.get("GPSLongitude"), gps.get("GPSLongitudeRef")
                )

                altitude = gps.get("GPSAltitude")
                if altitude is not None:
                    try:
                        alt = _ratio_to_float(altitude)
                        if gps.get("GPSAltitudeRef") in (1, b"\x01"):
                            alt *= -1
                        info.altitude = alt
                    except Exception as exc:
                        warnings.append(tr("metadata.altitude_error", error=exc))

    except Exception as exc:
        # La singola foto non deve interrompere la scansione dell'intera cartella.
        warnings.append(tr("metadata.read_error", error=exc))

    if info.taken_at is None:
        info.taken_at = datetime.fromtimestamp(stat.st_mtime)
        info.taken_at_source = "file_mtime"

    info.metadata_error = "; ".join(warnings) or None

    return info
