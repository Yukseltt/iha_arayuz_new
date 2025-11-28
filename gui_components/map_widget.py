# -*- coding: utf-8 -*-
import os, math, tempfile
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import pyqtSlot, QTimer
import logging

try:
    import folium
except ImportError:
    folium = None

_LEAFLET_BASE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>IHA Harita</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
 html, body, #map { height:100%%; margin:0; padding:0; }
 .drone-icon { width:32px; height:32px; background:url('https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png') no-repeat center center; background-size:contain; }
 /* Yüzde içeren değerler kaçırıldı */
 .wp-num { background:#ff9800; color:#fff; font:bold 11px/16px Arial; width:18px; height:18px; text-align:center; border-radius:50%%; border:2px solid #fff; box-shadow:0 0 4px rgba(0,0,0,0.4); }
 .drone-circle { width:34px; height:34px; border-radius:50%%; }
</style>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
<div id="map"></div>
<script>
 var map = L.map('map').setView([%(lat)f, %(lon)f], 15);
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
   maxZoom: 19, attribution: '© OpenStreetMap'
 }).addTo(map);

 var missionLayerGroup = L.layerGroup().addTo(map);
 var droneIcon = L.divIcon({className:'drone-icon', iconSize:[32,32], iconAnchor:[16,16]});
 var droneMarker = L.marker([%(lat)f, %(lon)f], {icon: droneIcon}).addTo(map).bindTooltip('IHA', {permanent:true});

 function moveMarker(lat, lon, heading){
   droneMarker.setLatLng([lat, lon]);
   if(typeof heading === 'number'){
     var el = droneMarker.getElement();
     if(el){
       var t = el.style.transform || '';
       t = t.replace(/rotate\\([^)]*\\)/, '').trim();
       el.style.transform = (t + ' rotate(' + heading + 'deg)').trim();
     }
   }
 }

 function drawMission(pts){
   missionLayerGroup.clearLayers();
   if(!pts || pts.length === 0) return;
   console.log('drawMission: ' + pts.length + ' waypoint');
   var line = L.polyline(pts, {color:'orange'}).addTo(missionLayerGroup);
   for(var i=0; i<pts.length; i++){
     var numIcon = L.divIcon({html:'<div class="wp-num">'+(i+1)+'</div>', className:'', iconSize:[18,18], iconAnchor:[9,9]});
     L.marker(pts[i], {icon:numIcon, title:'WP '+(i+1)}).addTo(missionLayerGroup)
       .bindPopup('Waypoint ' + (i+1));
   }
   map.fitBounds(line.getBounds(), {maxZoom:17});
 }

 function missionLayerCount(){
   return missionLayerGroup.getLayers().length;
 }
</script>
</body>
</html>
"""

class LoggingWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, msg, line, source):
        logging.getLogger("MAP.JS").info(f"[JS:{level}] {source}:{line} | {msg}")

class MapWidget(QWidget):
    def __init__(self, start_lat=39.92077, start_lon=32.85411, parent=None):
        super().__init__(parent)
        self._start_lat = start_lat
        self._start_lon = start_lon
        self._loaded = False
        self._ready = False
        self._pending_js = []
        self._last_mission = None      # [(lat,lon), ...]
        self._last_pos = None          # (lat, lon, heading or None)
        self._view = QWebEngineView()
        self._view.setPage(LoggingWebPage(self._view))  # JS console yakalama
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lay.addWidget(self._view)
        self._init_map()
        self._debug_timer = None

    def _init_map(self):
        if folium is not None:
            # (Folium örneği kullanılabilir; ancak dinamik JS kontrolü için manuel HTML kullanıyoruz.)
            pass
        html = _LEAFLET_BASE % {"lat": self._start_lat, "lon": self._start_lon}
        self._view.setHtml(html)
        self._view.loadFinished.connect(self._on_load_finished)
        self._loaded = True
        logging.getLogger("MAP").info(f"Harita init: lat={self._start_lat} lon={self._start_lon}")

    def _on_load_finished(self, ok: bool):
        self._ready = bool(ok)
        logging.getLogger("MAP").info(f"HTML loadFinished ok={ok}")
        if not self._ready:
            return
        # Sayfa hazır: varsa en son mission ve konumu uygula, sonra kuyruktaki JS'leri çalıştır
        try:
            if self._last_mission:
                pts_js = "[" + ",".join(f"[{lat},{lon}]" for lat, lon in self._last_mission) + "]"
                self._view.page().runJavaScript(f"drawMission({pts_js});")
            if self._last_pos:
                lat, lon, hdg = self._last_pos
                hdg_js = "null" if hdg is None else f"{hdg}"
                self._view.page().runJavaScript(f"moveMarker({lat},{lon},{hdg_js});")
            self._flush_pending_js()
        finally:
            if self._last_mission:
                self.start_mission_debug()

    def _run_js(self, js: str, callback=None):
        logging.getLogger("MAP").debug(f"JS queue/run: {js[:120]}")
        if self._ready:
            self._view.page().runJavaScript(js, callback)
        else:
            # callback gerekirse paketleyip sakla
            if callback:
                self._pending_js.append((js, callback))
            else:
                self._pending_js.append(js)

    def _flush_pending_js(self):
        for item in self._pending_js:
            if isinstance(item, tuple):
                js, cb = item
                self._view.page().runJavaScript(js, cb)
            else:
                self._view.page().runJavaScript(item)
        self._pending_js.clear()

    @pyqtSlot(list)
    def draw_mission(self, waypoints):
        logging.getLogger("MAP").info(f"draw_mission çağrıldı. Waypoint sayısı={len(waypoints) if waypoints else 0}")
        if not self._loaded:
            return
        self._last_mission = waypoints[:] if waypoints else []
        pts_js = "[" + ",".join(f"[{lat},{lon}]" for lat, lon in self._last_mission) + "]"
        self._run_js(f"drawMission({pts_js});")
        self.start_mission_debug()

    @pyqtSlot(float, float, float)
    def update_drone_position(self, lat, lon, heading=None):
        logging.getLogger("MAP").debug(f"update_drone_position lat={lat:.6f} lon={lon:.6f} heading={heading}")
        if not self._loaded:
            return
        self._last_pos = (lat, lon, heading)
        hdg_js = "null" if heading is None else f"{heading}"
        self._run_js(f"moveMarker({lat},{lon},{hdg_js});")

    def start_mission_debug(self):
        if self._debug_timer is None:
            self._debug_timer = QTimer(self)
            self._debug_timer.timeout.connect(self._debug_check_mission)
            self._debug_timer.start(2000)

    def stop_mission_debug(self):
        """Waypoint layer sayısı izleme timer'ını durdur."""
        if self._debug_timer:
            self._debug_timer.stop()
            self._debug_timer = None
            logging.getLogger("MAP").info("Mission debug durduruldu.")

    def _debug_check_mission(self):
        if not self._last_mission:
            return
        self._run_js("missionLayerCount();", self._on_mission_count)

    def _on_mission_count(self, count):
        logging.getLogger("MAP").info(f"missionLayerCount={count}")
        try:
            if isinstance(count, int):
                if count == 0 and self._last_mission:
                    # Yeniden çiz
                    pts_js = "[" + ",".join(f"[{lat},{lon}]" for lat, lon in self._last_mission) + "]"
                    self._view.page().runJavaScript(f"drawMission({pts_js});")
            else:
                pass
        except Exception:
            pass

    def set_mission_autofit(self, enabled: bool):
        """Görev çiziminde otomatik harita konumlandırmayı aç/kapat."""
        self._run_js(f"setMissionAutoFit({str(bool(enabled)).lower()});")

    def load_dummy_mission(self):
        demo = [(self._start_lat + 0.0005*i, self._start_lon + 0.0003*i) for i in range(5)]
        self.draw_mission(demo)
