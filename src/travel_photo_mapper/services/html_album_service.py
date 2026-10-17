from __future__ import annotations

import html
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from pillow_heif import register_heif_opener

from travel_photo_mapper.i18n import TRANSLATIONS
from travel_photo_mapper.models.photo import PhotoInfo


register_heif_opener()


class AlbumCancelled(Exception):
    pass


def album_folder_name(title: str) -> str:
    # Avoid Windows reserved names and keep user input inside the chosen parent.
    name = re.sub(r"[^\w-]+", "-", title, flags=re.UNICODE).strip("-_")[:70]
    return f"album-{name or 'photos'}"


def available_album_folder(parent: Path, title: str) -> Path:
    base = parent / album_folder_name(title)
    candidate = base
    number = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{number}")
        number += 1
    return candidate


def export_html_album(
    destination: Path,
    title: str,
    photos: list[PhotoInfo],
    language: str = "it",
    include_gps: bool = True,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Publish a complete, relocatable album only after every image is ready."""
    if not photos:
        raise ValueError("No photos to export")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(str(destination))
    messages = TRANSLATIONS[language]
    escape = html.escape

    def check_cancelled():
        if cancelled and cancelled():
            raise AlbumCancelled()

    check_cancelled()
    # Staging on the same filesystem makes the final rename atomic.
    with tempfile.TemporaryDirectory(prefix=".travel-album-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "album"
        (stage / "photos").mkdir(parents=True)
        (stage / "thumbnails").mkdir()
        entries = []
        cards = []
        for index, photo in enumerate(photos):
            check_cancelled()
            filename = f"{index + 1:05d}.jpg"
            try:
                with Image.open(photo.path) as original:
                    oriented = ImageOps.exif_transpose(original)
                    oriented.thumbnail((1920, 1920))
                    rgba = oriented.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                    image.save(stage / "photos" / filename, quality=88, optimize=True, exif=b"")
                    image.thumbnail((480, 360))
                    image.save(stage / "thumbnails" / filename, quality=83, optimize=True, exif=b"")
            except Exception as exc:
                raise OSError(f"{photo.filename}: {exc}") from exc
            date_text = photo.taken_at.strftime("%d/%m/%Y %H:%M") if photo.taken_at else messages["date.unknown"]
            if photo.taken_at and photo.taken_at_source == "file_mtime":
                date_text += f" · {messages['date.source.file_mtime']}"
            entry = {"src": f"photos/{filename}", "filename": photo.filename, "date": date_text}
            if (include_gps and photo.has_gps and math.isfinite(photo.latitude)
                    and math.isfinite(photo.longitude) and -90 <= photo.latitude <= 90
                    and -180 <= photo.longitude <= 180):
                entry["coordinates"] = [photo.latitude, photo.longitude]
            entries.append(entry)
            cards.append(
                f'<a class="card" id="photo-{index}" href="photos/{filename}" data-index="{index}">'
                f'<div class="image-wrap"><img src="thumbnails/{filename}" loading="lazy" '
                f'alt="{escape(photo.filename, quote=True)}" width="480" height="360"></div>'
                f'<div class="caption"><span class="number">{index + 1:02d}</span><div>'
                f'<h2>{escape(photo.filename)}</h2><p>{escape(date_text)}</p></div></div></a>'
            )
            if progress:
                progress(index + 1, len(photos))
        check_cancelled()
        gps_count = sum("coordinates" in entry for entry in entries)
        dated = [photo.taken_at for photo in photos if photo.taken_at]
        dates = f"{min(dated):%d/%m/%Y} — {max(dated):%d/%m/%Y}" if dated else ""
        count_key = "count.photos.one" if len(photos) == 1 else "count.photos.other"
        count = messages[count_key].format(count=len(photos))
        tokens = {
            "LANG": language,
            "TITLE": escape(title),
            "DATES": escape(dates),
            "COUNT": escape(count),
            "CARDS": "\n".join(cards),
            "DATA": json.dumps(entries, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"),
            "MAP_HIDDEN": "" if gps_count else " hidden",
        }
        for key in ("eyebrow", "gallery", "map", "load_map", "map_hint", "map_loading", "map_error", "previous", "next", "close", "footer"):
            tokens[key.upper()] = escape(messages[f"album.page.{key}"])
        tokens["ROUTE_WARNING"] = escape(messages["export.route_warning"])
        # One-pass replacement: titles and filenames may themselves contain token-like text.
        document = re.sub(r"@@([A-Z_]+)@@", lambda match: tokens[match[1]], ALBUM_HTML)
        (stage / "index.html").write_text(document, encoding="utf-8")
        check_cancelled()
        stage.rename(destination)
    return destination / "index.html"


class AlbumExportWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, destination, title, photos, language, include_gps):
        super().__init__()
        self.arguments = (destination, title, list(photos), language, include_gps)
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    @pyqtSlot()
    def run(self):
        try:
            result = export_html_album(*self.arguments, progress=self.progress.emit,
                                       cancelled=lambda: self._cancel_requested)
            self.finished.emit(str(result))
        except AlbumCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


ALBUM_HTML = r'''<!doctype html>
<html lang="@@LANG@@">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>@@TITLE@@ · Travel Photo Mapper</title>
<style>
:root{color-scheme:light;--ink:#253d3b;--teal:#21695f;--paper:#f7f5ef;--muted:#667875}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,sans-serif}
button,a{-webkit-tap-highlight-color:transparent}button{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid #d6a333;outline-offset:4px}
header,main,footer{max-width:1240px;margin:auto;padding:0 36px}header{padding-top:62px;padding-bottom:36px;border-bottom:1px solid #d8ded4}
.eyebrow{text-transform:uppercase;letter-spacing:.2em;font-size:11px;font-weight:700;color:var(--teal);margin:0 0 16px}
h1{font:clamp(36px,6vw,76px)/1.1 Georgia,serif;margin:0 0 22px;overflow-wrap:anywhere;max-width:1000px}
.meta{display:flex;flex-wrap:wrap;gap:12px 26px;color:var(--muted);font-size:14px}.meta span:first-child{color:var(--teal);font-weight:600}
nav{display:flex;gap:24px;margin-top:28px}nav a{font-size:13px;color:var(--ink);text-decoration:none;border-bottom:2px solid var(--teal);padding-bottom:5px}
.section-heading{display:flex;align-items:center;gap:14px;margin:36px 0 22px}.section-heading span{font-size:11px;letter-spacing:.12em;color:var(--teal)}
.section-heading h2{font:26px Georgia,serif;margin:0}.section-heading:after{content:"";height:1px;background:#d8ded4;flex:1}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:26px 22px}.card{color:inherit;text-decoration:none;background:#fff;border:1px solid #e2e5dc;border-radius:8px;overflow:hidden;transition:transform .15s,box-shadow .15s;min-width:0}
.card:hover{transform:translateY(-3px);box-shadow:0 8px 22px #253d3b12}.card.selected{outline:3px solid var(--teal);outline-offset:3px}
.image-wrap{aspect-ratio:4/3;overflow:hidden;background:#e6eae1}.image-wrap img{display:block;width:100%;height:100%;object-fit:cover}
.caption{display:flex;gap:13px;padding:18px}.caption>div{min-width:0}.number{font:20px Georgia,serif;color:#8c9d8c}.caption h2{font-size:13px;margin:0 0 5px;overflow-wrap:anywhere;font-weight:600}.caption p{font-size:11px;color:var(--muted);margin:0}
#map{height:420px;background:#e5eae1;border:1px solid #d8ded4;border-radius:8px;position:relative}.map-placeholder{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px;gap:14px}
.primary{background:var(--teal);border:0;color:#fff;padding:12px 22px;border-radius:5px}.map-placeholder p{max-width:460px;font-size:13px;color:var(--muted);margin:0}
.map-note{font-size:12px;color:var(--muted);margin:12px 0 0}footer{margin-top:54px;padding-top:24px;padding-bottom:36px;border-top:1px solid #d8ded4;font-size:12px;color:var(--muted)}
dialog{border:0;border-radius:10px;padding:16px;background:#142724;color:#fff;width:min(1100px,94vw);max-height:95vh}dialog::backdrop{background:#0c1816e8}
.viewer-top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}#viewer-caption{font-size:13px;overflow-wrap:anywhere;margin:0}
dialog button{background:#ffffff14;color:#fff;border:1px solid #ffffff40;border-radius:5px;padding:8px 14px}#viewer-image{display:block;width:100%;height:min(68vh,800px);object-fit:contain}.viewer-controls{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:12px}
[hidden]{display:none!important}@media(max-width:600px){header,main,footer{padding-left:20px;padding-right:20px}header{padding-top:36px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.caption{padding:12px;gap:8px}.number{display:none}.caption p{font-size:10px}#map{height:320px}}
@media(prefers-reduced-motion:reduce){.card{transition:none}}
</style>
</head>
<body>
<header><p class="eyebrow">@@EYEBROW@@ · Travel Photo Mapper</p><h1>@@TITLE@@</h1>
<div class="meta"><span>@@COUNT@@</span><span>@@DATES@@</span></div>
<nav><a href="#gallery">@@GALLERY@@</a><a href="#map-section"@@MAP_HIDDEN@@>@@MAP@@</a></nav></header>
<main>
<section id="map-section"@@MAP_HIDDEN@@><div class="section-heading"><span>01</span><h2>@@MAP@@</h2></div>
<div id="map"><div class="map-placeholder"><button class="primary" id="load-map">@@LOAD_MAP@@</button><p id="map-status" role="status" data-loading="@@MAP_LOADING@@" data-error="@@MAP_ERROR@@">@@MAP_HINT@@</p></div></div>
<p class="map-note">@@ROUTE_WARNING@@</p></section>
<section id="gallery"><div class="section-heading"><h2>@@GALLERY@@</h2></div><div class="grid">@@CARDS@@</div></section>
</main>
<footer>@@FOOTER@@ · Travel Photo Mapper</footer>
<dialog id="viewer" aria-label="@@GALLERY@@"><div class="viewer-top"><p id="viewer-caption"></p><button id="close-viewer">@@CLOSE@@</button></div>
<img id="viewer-image" alt=""><div class="viewer-controls"><button id="previous">← @@PREVIOUS@@</button><span id="viewer-count"></span><button id="next">@@NEXT@@ →</button></div></dialog>
<script id="album-data" type="application/json">@@DATA@@</script>
<script>
'use strict';
const photos = JSON.parse(document.getElementById('album-data').textContent);
const viewer = document.getElementById('viewer');
const markers = new Map();
let selected = 0, map;
function selectPhoto(index) {
  selected = (index + photos.length) % photos.length;
  const photo = photos[selected];
  document.getElementById('viewer-image').src = photo.src;
  document.getElementById('viewer-image').alt = photo.filename;
  document.getElementById('viewer-caption').textContent = photo.filename + ' · ' + photo.date;
  document.getElementById('viewer-count').textContent = (selected + 1) + ' / ' + photos.length;
  document.querySelector('.card.selected')?.classList.remove('selected');
  document.getElementById('photo-' + selected).classList.add('selected');
  if (map && photo.coordinates) map.panTo(photo.coordinates);
  if (!viewer.open) viewer.showModal();
}
document.querySelectorAll('.card').forEach(card => card.addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); selectPhoto(Number(card.dataset.index));
}));
document.getElementById('close-viewer').onclick = () => viewer.close();
document.getElementById('previous').onclick = () => selectPhoto(selected - 1);
document.getElementById('next').onclick = () => selectPhoto(selected + 1);
viewer.addEventListener('keydown', event => {
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault(); selectPhoto(selected + (event.key === 'ArrowLeft' ? -1 : 1));
  }
});
const loadMap = document.getElementById('load-map');
let mapContainer = document.getElementById('map');
const mapPlaceholder = mapContainer.firstElementChild;
const mapStatus = document.getElementById('map-status');
const mapResources = new Map();
function loadMapResource(url, stylesheet = false) {
  if (mapResources.has(url)) return mapResources.get(url);
  const promise = new Promise((resolve, reject) => {
    const element = document.createElement(stylesheet ? 'link' : 'script');
    const fail = () => {
      clearTimeout(timeout); element.remove(); mapResources.delete(url);
      reject(new Error('Map resource unavailable'));
    };
    const timeout = setTimeout(fail, 15000);
    element.onload = () => { clearTimeout(timeout); resolve(); };
    element.onerror = fail;
    if (stylesheet) { element.rel = 'stylesheet'; element.href = url; }
    else element.src = url;
    document.head.appendChild(element);
  });
  mapResources.set(url, promise);
  return promise;
}
loadMap.onclick = async () => {
  loadMap.disabled = true;
  mapStatus.textContent = mapStatus.dataset.loading;
  let failed = false;
  const showError = () => {
    if (failed) return;
    failed = true;
    if (map) {
      const previousMap = map; map = null;
      // A WebGL startup failure may leave a partially initialized layer.
      try { previousMap.remove(); } catch (_error) { /* Restore the retry UI. */ }
    }
    markers.clear();
    const replacement = document.createElement('div');
    replacement.id = 'map';
    mapContainer.replaceWith(replacement);
    mapContainer = replacement;
    mapContainer.replaceChildren(mapPlaceholder);
    mapStatus.textContent = mapStatus.dataset.error;
    loadMap.disabled = false;
  };
  try {
    await Promise.all([
      loadMapResource('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css', true),
      loadMapResource('https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css', true),
      loadMapResource('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'),
      loadMapResource('https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js')
    ]);
    await loadMapResource('https://unpkg.com/@maplibre/maplibre-gl-leaflet@0.1.4/leaflet-maplibre-gl.js');
    mapContainer.replaceChildren();
    const coordinates = photos.filter(photo => photo.coordinates).map(photo => photo.coordinates);
    map = L.map('map', {scrollWheelZoom:false, maxZoom:19});
    map.fitBounds(L.latLngBounds(coordinates), {padding:[28,28],maxZoom:14});
    // OSM's standard tile service requires a web Referer, which file:// albums cannot send.
    // OpenFreeMap provides a separate public vector service for maps in websites and apps.
    const basemap = L.maplibreGL({
      style:'https://tiles.openfreemap.org/styles/liberty',
      attributionControl:{customAttribution:
        '<a href="https://openfreemap.org/">OpenFreeMap</a> · &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> · &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}
    }).addTo(map);
    basemap.getMaplibreMap().on('error', showError);
    photos.forEach((photo, index) => {
      if (!photo.coordinates) return;
      const marker = L.circleMarker(photo.coordinates, {radius:7,color:'#fff',weight:2,fillColor:'#21695f',fillOpacity:1});
      marker.addTo(map);
      const label = document.createElement('span'); label.textContent = photo.filename;
      marker.bindTooltip(label); marker.on('click', () => selectPhoto(index)); markers.set(index, marker);
    });
    if (coordinates.length > 1) L.polyline(coordinates, {color:'#b48b32',weight:3,opacity:.8}).addTo(map);
  } catch (_error) { showError(); }
};
</script>
</body></html>'''
