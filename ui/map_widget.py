from __future__ import annotations

import json

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView

from models.photo import PhotoInfo
from services.thumbnail_service import thumbnail_data_uri


HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
<style>
html,body,#map { width:100%; height:100%; margin:0; background:#eef3f5; }
.leaflet-container { font-family: Arial, sans-serif; }
.leaflet-tile-pane { filter:saturate(.72) contrast(.94) brightness(1.04); }
.leaflet-control { border-radius:5px !important; box-shadow:0 1px 5px rgba(28,48,51,.2) !important; }
.photo-marker { width:18px; height:18px; border:3px solid #fff; background:#f0ad00; border-radius:50%; box-shadow:0 1px 5px rgba(0,0,0,.35); }
.photo-marker.selected { width:24px; height:24px; border-width:4px; transform:translate(-3px,-3px); }

.selected-photo-marker-wrap {
    position: relative;
    width: 140px;
    height: 158px;
}
.selected-photo-marker {
    position: absolute;
    left: 0;
    top: 0;
    width: 132px;
    height: 132px;
    padding: 3px;
    background: white;
    border: 4px solid #f0ad00;
    border-radius: 6px;
    box-shadow: 0 5px 16px rgba(0,0,0,.35);
    overflow: hidden;
}
.selected-photo-marker img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 4px;
    display: block;
}
.selected-photo-marker-fallback {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #fff4c7;
    color: #4b3b00;
    font-size: 24px;
}
.selected-photo-marker-arrow {
    position: absolute;
    left: 61px;
    top: 144px;
    width: 0;
    height: 0;
    border-left: 9px solid transparent;
    border-right: 9px solid transparent;
    border-top: 12px solid #f0ad00;
    filter: drop-shadow(0 3px 2px rgba(0,0,0,.2));
}
.marker-cluster-small, .marker-cluster-medium, .marker-cluster-large { background-color:rgba(240,173,0,.25); }
.marker-cluster-small div, .marker-cluster-medium div, .marker-cluster-large div { background-color:rgba(240,173,0,.9); color:#222; font-weight:700; }
.popup-photo { width:320px; max-height:220px; object-fit:cover; border-radius:8px; display:block; margin-top:7px; }
.popup-meta { margin-top:5px; color:#555; font-size:12px; }
</style>
</head>
<body>
<div id="map"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
<script>
const map = L.map('map').setView([20, 0], 2);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom:19,
  attribution:'&copy; OpenStreetMap contributors'
}).addTo(map);

let bridge = null;
new QWebChannel(qt.webChannelTransport, function(channel) { bridge = channel.objects.bridge; });

let photoLayer = L.markerClusterGroup({
  showCoverageOnHover:false,
  maxClusterRadius:46,
  zoomToBoundsOnClick:false,
  spiderfyOnMaxZoom:false
});
map.addLayer(photoLayer);
photoLayer.on('clusterclick', function(event) {
  if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
  const cluster = event.layer;
  const bounds = cluster.getBounds();
  const diagonalMeters = bounds.getNorthEast().distanceTo(bounds.getSouthWest());
  const targetZoom = map.getBoundsZoom(bounds, false, L.point(70, 70));

  if (diagonalMeters < 10 || map.getZoom() >= map.getMaxZoom() || targetZoom <= map.getZoom()) {
    cluster.spiderfy();
  } else {
    cluster.zoomToBounds({padding:[50,50]});
  }
});
let routeLayer = null;
let heatLayer = null;
let markerByIndex = {};
let activeIndex = null;
let currentItems = [];
let photoBounds = null;
let geolocatedPhotoCount = 0;
let navigationRevision = 0;

function markerIcon(selected=false) {
  return L.divIcon({
    className:'',
    html:'<div class="photo-marker' + (selected ? ' selected' : '') + '"></div>',
    iconSize:selected ? [30,30] : [24,24],
    iconAnchor:selected ? [15,15] : [12,12]
  });
}

function selectedPhotoIcon(imageData='') {
  const content = imageData
    ? '<img src="' + imageData + '" alt="">'
    : '<div class="selected-photo-marker-fallback">📷</div>';

  return L.divIcon({
    className:'',
    html:
      '<div class="selected-photo-marker-wrap">' +
        '<div class="selected-photo-marker">' + content + '</div>' +
        '<div class="selected-photo-marker-arrow"></div>' +
      '</div>',
    iconSize:[140,158],
    // La punta del fumetto coincide esattamente con la coordinata GPS.
    iconAnchor:[70,158],
    popupAnchor:[0,-160]
  });
}

function clearPhotos() {
  photoLayer.clearLayers();
  markerByIndex = {};
  activeIndex = null;
  photoBounds = null;
  geolocatedPhotoCount = 0;
  if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
}

function popupHtml(p, imageData='') {
  const img = imageData ? '<img class="popup-photo" src="' + imageData + '">' : '';
  return '<b>' + escapeHtml(p.filename) + '</b>' + img +
    '<div class="popup-meta">' + (p.datetime || '') + '<br>' +
    p.lat.toFixed(6) + ', ' + p.lon.toFixed(6) + '</div>';
}

function setPhotos(items) {
  navigationRevision += 1;
  clearPhotos();
  currentItems = items;
  const bounds = [];
  const route = [];
  const heat = [];

  items.forEach(p => {
    if (p.lat === null || p.lon === null) return;
    const marker = L.marker([p.lat, p.lon], {icon:markerIcon(false)});
    marker.bindPopup(popupHtml(p), {maxWidth:360});
    marker.on('click', function() {
      if (bridge) bridge.photoClicked(p.index);
    });
    marker.on('popupopen', function() {
      if (!bridge) return;
      bridge.thumbnailData(p.index, function(data) {
        marker.setPopupContent(popupHtml(p, data || ''));
      });
    });
    photoLayer.addLayer(marker);
    markerByIndex[p.index] = marker;
    bounds.push([p.lat,p.lon]);
    route.push([p.lat,p.lon]);
    heat.push([p.lat,p.lon,1.0]);
  });

  if (route.length >= 2) {
    routeLayer = L.polyline(route, {color:'#0b8790',weight:3,opacity:.88}).addTo(map);
  }
  if (heat.length) {
    heatLayer = L.heatLayer(heat, {
      radius:24,
      blur:18,
      maxZoom:12,
      gradient:{0.2:'#0b8790',0.55:'#ffc928',1.0:'#e45b3f'}
    });
  }

  geolocatedPhotoCount = bounds.length;
  photoBounds = bounds.length ? L.latLngBounds(bounds) : null;
  fitAllPhotos();
}

function fitAllPhotos() {
  navigationRevision += 1;
  if (!photoBounds) return;
  if (geolocatedPhotoCount === 1) map.setView(photoBounds.getCenter(),14);
  else map.fitBounds(photoBounds,{padding:[50,50]});
}

function fitPhotoCoordinates(coordinates) {
  navigationRevision += 1;
  if (!coordinates.length) return;
  const bounds = L.latLngBounds(coordinates);
  if (coordinates.length === 1) map.setView(bounds.getCenter(),14);
  else map.fitBounds(bounds,{padding:[50,50]});
}

function setHeatmapVisible(visible) {
  if (!heatLayer) return;
  if (visible) heatLayer.addTo(map);
  else if (map.hasLayer(heatLayer)) map.removeLayer(heatLayer);
}

function setRouteVisible(visible) {
  if (!routeLayer) return;
  if (visible) routeLayer.addTo(map);
  else if (map.hasLayer(routeLayer)) map.removeLayer(routeLayer);
}

function focusPhoto(index) {
  if (activeIndex !== null && markerByIndex[activeIndex]) {
    markerByIndex[activeIndex].setIcon(markerIcon(false));
  }

  activeIndex = index;
  const marker = markerByIndex[index];
  if (!marker) return;
  const requestRevision = ++navigationRevision;

  // Mostriamo subito un marker fotografico placeholder, poi carichiamo
  // la thumbnail dalla cache Python in modo asincrono.
  marker.setIcon(selectedPhotoIcon(''));

  photoLayer.zoomToShowLayer(marker, function() {
    if (requestRevision !== navigationRevision || markerByIndex[index] !== marker) return;
    map.setView(marker.getLatLng(), Math.max(map.getZoom(),14), {animate:true});

    if (bridge) {
      bridge.thumbnailData(index, function(data) {
        // La callback può arrivare dopo che l'utente ha selezionato un'altra foto.
        if (requestRevision === navigationRevision && activeIndex === index && markerByIndex[index] === marker) {
          markerByIndex[index].setIcon(selectedPhotoIcon(data || ''));
        }
      });
    }

    marker.openPopup();
  });
}

function escapeHtml(s) {
  return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
}
</script>
</body>
</html>
"""


class MapBridge(QObject):
    photo_selected = pyqtSignal(int)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    @pyqtSlot(int)
    def photoClicked(self, index: int):
        self.photo_selected.emit(index)

    @pyqtSlot(int, result=str)
    def thumbnailData(self, index: int) -> str:
        if 0 <= index < len(self.owner.photos):
            return thumbnail_data_uri(self.owner.photos[index].path)
        return ""


class MapWidget(QWebEngineView):
    photo_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.photos: list[PhotoInfo] = []
        self._fit_coordinates: list[list[float]] = []
        self._page_ready = False
        self._pending_scripts: list[str] = []
        self.bridge = MapBridge(self)
        self.bridge.photo_selected.connect(self.photo_selected)
        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.loadFinished.connect(self._on_load_finished)
        self.setHtml(HTML)

    def _on_load_finished(self, loaded: bool):
        if not loaded:
            return
        self._page_ready = True
        scripts, self._pending_scripts = self._pending_scripts, []
        for script in scripts:
            self.page().runJavaScript(script)

    def _run_javascript(self, script: str):
        if self._page_ready:
            self.page().runJavaScript(script)
        else:
            self._pending_scripts.append(script)

    def set_photos(self, photos: list[PhotoInfo], visible_indices: list[int] | None = None):
        self.photos = photos
        if visible_indices is None:
            visible_indices = list(range(len(photos)))
        payload = []
        fit_coordinates = []
        for i in visible_indices:
            p = photos[i]
            payload.append({
                "index": i,
                "filename": p.filename,
                "datetime": p.taken_at.strftime("%d/%m/%Y %H:%M:%S") if p.taken_at else "",
                "lat": p.latitude,
                "lon": p.longitude,
            })
            if p.latitude is not None and p.longitude is not None:
                fit_coordinates.append([p.latitude, p.longitude])
        self._fit_coordinates = fit_coordinates
        self._run_javascript(f"setPhotos({json.dumps(payload)});")

    def focus_photo(self, index: int):
        self._run_javascript(f"focusPhoto({int(index)});")

    def set_heatmap_visible(self, visible: bool):
        self._run_javascript(f"setHeatmapVisible({str(bool(visible)).lower()});")

    def set_route_visible(self, visible: bool):
        self._run_javascript(f"setRouteVisible({str(bool(visible)).lower()});")

    def fit_all_photos(self):
        self._run_javascript(
            f"fitPhotoCoordinates({json.dumps(self._fit_coordinates)});"
        )
