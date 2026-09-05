from __future__ import annotations

import json
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree

from app_info import APP_NAME, APP_VERSION
from i18n import tr
from models.photo import PhotoInfo


def export_geojson(path: Path, photos: list[PhotoInfo]) -> None:
    features = []
    route_coords = []
    for p in photos:
        if not p.has_gps:
            continue
        coord = [p.longitude, p.latitude]
        route_coords.append(coord)
        props = {
            "filename": p.filename,
            "path": str(p.path),
            "taken_at": p.taken_at.isoformat() if p.taken_at else None,
            "taken_at_source": p.taken_at_source,
            "altitude": p.altitude,
            "camera_model": p.camera_model,
            "lens_model": p.lens_model,
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coord},
            "properties": props,
        })

    if len(route_coords) >= 2:
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": route_coords},
            "properties": {
                "kind": "photo_sequence",
                "warning": tr("export.route_warning"),
            },
        })

    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_gpx(path: Path, photos: list[PhotoInfo]) -> None:
    gpx = Element("gpx", {
        "version": "1.1",
        "creator": f"{APP_NAME} {APP_VERSION}",
        "xmlns": "http://www.topografix.com/GPX/1/1",
    })

    gps_photos = [p for p in photos if p.has_gps]
    for p in gps_photos:
        wpt = SubElement(gpx, "wpt", lat=f"{p.latitude:.8f}", lon=f"{p.longitude:.8f}")
        SubElement(wpt, "name").text = p.filename
        if p.altitude is not None:
            SubElement(wpt, "ele").text = f"{p.altitude:.2f}"
        if p.taken_at:
            SubElement(wpt, "time").text = p.taken_at.isoformat()

    if len(gps_photos) >= 2:
        trk = SubElement(gpx, "trk")
        SubElement(trk, "name").text = tr("export.gpx_track_name")
        seg = SubElement(trk, "trkseg")
        for p in gps_photos:
            pt = SubElement(seg, "trkpt", lat=f"{p.latitude:.8f}", lon=f"{p.longitude:.8f}")
            if p.altitude is not None:
                SubElement(pt, "ele").text = f"{p.altitude:.2f}"
            if p.taken_at:
                SubElement(pt, "time").text = p.taken_at.isoformat()

    tree = ElementTree(gpx)
    tree.write(path, encoding="utf-8", xml_declaration=True)
