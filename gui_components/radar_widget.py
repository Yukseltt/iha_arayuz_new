# -*- coding: utf-8 -*-
"""
Radar Widget (Revizyon)
Daha okunabilir, kontrollü ve görsel açıdan geliştirilen sürüm.
Mantık API'si korunur:
    update_own_position(lat, lon)
    update_teams_data(dict)
    lock_team(team_id)
    zoom_in()/zoom_out()/reset_zoom()
"""

import math
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QLinearGradient


class RadarWidget(QWidget):
    team_locked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.own_lat = 0.0
        self.own_lon = 0.0
        self.teams_data = {}
        self.teams_trails = {}     # {team_id: [(x,y),...]}
        self.locked_team = None
        self.zoom_level = 1.0
        self.max_range = 10000     # metre
        self.max_trail_length = 20
        self._pulse_phase = 0.0

        self.team_colors = {
            'takım_2': QColor(255, 120, 120),
            'takım_3': QColor(120, 255, 120),
            'takım_4': QColor(120, 120, 255),
            'takım_5': QColor(255, 255, 140),
            'takım_6': QColor(255, 140, 255),
            'takım_7': QColor(140, 255, 255),
            'takım_8': QColor(255, 170, 110),
            'takım_9': QColor(170, 120, 255),
        }

        self.setMinimumSize(280, 360)
        self._build_ui()

        # Yenileme timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._tick)
        self.update_timer.start(40)  # ~25 FPS

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # ÜST KONTROL BAR
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(4)

        self.title_label = QLabel("📡 Radar")
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label.setStyleSheet("color:#eee; font-weight:bold; font-size:12px;")
        ctrl_bar.addWidget(self.title_label, 1)

        self.lock_info = QLabel("Kilit: Yok")
        self.lock_info.setStyleSheet("color:#ccc; font-size:11px;")
        ctrl_bar.addWidget(self.lock_info)

        btn_zoom_in = QPushButton("+")
        btn_zoom_out = QPushButton("−")
        btn_reset = QPushButton("⟳")
        for b in (btn_zoom_in, btn_zoom_out, btn_reset):
            b.setFixedSize(26, 22)
            b.setStyleSheet("""
                QPushButton {
                    background:#222; color:#ddd; border:1px solid #444;
                    border-radius:3px; font-weight:bold;
                }
                QPushButton:hover { background:#333; }
                QPushButton:pressed { background:#555; }
            """)
        btn_zoom_in.clicked.connect(self.zoom_in)
        btn_zoom_out.clicked.connect(self.zoom_out)
        btn_reset.clicked.connect(self.reset_zoom)
        ctrl_bar.addWidget(btn_zoom_in)
        ctrl_bar.addWidget(btn_zoom_out)
        ctrl_bar.addWidget(btn_reset)

        root.addLayout(ctrl_bar)

        # ÇİZİM ALANI
        self.canvas = RadarCanvas(self)
        self.canvas.setMinimumHeight(220)
        root.addWidget(self.canvas, 1)

        # ALT BİLGİ PANELİ
        self.info_panel = TeamInfoPanel(self)
        root.addWidget(self.info_panel)

        self.setStyleSheet("background:#0d1216; border:1px solid #1f2a33;")

    def _tick(self):
        self._pulse_phase = (self._pulse_phase + 0.08) % (2*math.pi)
        self.canvas.pulse_phase = self._pulse_phase
        self.canvas.update()

    # Mantık API
    def update_own_position(self, lat, lon):
        self.own_lat = lat
        self.own_lon = lon
        self.canvas.own_lat = lat
        self.canvas.own_lon = lon
        self.canvas.update()

    def update_teams_data(self, teams_dict):
        self.teams_data = teams_dict
        self.canvas.teams_data = teams_dict
        # İz güncelle
        for tid, tdata in teams_dict.items():
            lat = tdata.get("lat"); lon = tdata.get("lon")
            if lat is None or lon is None:
                continue
            x, y = self.canvas.coord_to_grid(lat, lon)
            trail = self.teams_trails.setdefault(tid, [])
            trail.append((x, y))
            if len(trail) > self.max_trail_length:
                trail.pop(0)
        self.canvas.trails = self.teams_trails
        self.info_panel.update_teams(teams_dict)
        self.canvas.update()

    def lock_team(self, team_id):
        if self.locked_team == team_id:
            self.locked_team = None
        else:
            self.locked_team = team_id
            self.team_locked.emit(team_id)
        self.canvas.locked_team = self.locked_team
        self.lock_info.setText(f"Kilit: {self.locked_team or 'Yok'}")
        self.canvas.update()
        self.info_panel.update_lock_status(self.locked_team)

    def zoom_in(self):
        self.zoom_level = min(self.zoom_level * 1.25, 6.0)
        self.canvas.zoom_level = self.zoom_level
        self.canvas.update()

    def zoom_out(self):
        self.zoom_level = max(self.zoom_level / 1.25, 0.4)
        self.canvas.zoom_level = self.zoom_level
        self.canvas.update()

    def reset_zoom(self):
        self.zoom_level = 1.0
        self.canvas.zoom_level = self.zoom_level
        self.canvas.update()


class RadarCanvas(QWidget):
    def __init__(self, radar):
        super().__init__()
        self.radar = radar
        self.own_lat = 0.0
        self.own_lon = 0.0
        self.teams_data = {}
        self.trails = {}
        self.locked_team = None
        self.zoom_level = 1.0
        self.max_range = radar.max_range
        self.pulse_phase = 0.0
        self.setMouseTracking(True)
        self.setToolTip("Merkez: Kendi takım konumu")

    def coord_to_grid(self, lat, lon):
        if self.own_lat == 0 and self.own_lon == 0:
            return self.width()//2, self.height()//2
        dist = self._haversine(self.own_lat, self.own_lon, lat, lon)
        brg = self._bearing(self.own_lat, self.own_lon, lat, lon)
        radius = min(self.width(), self.height()) / 2 - 18
        meters_per_pixel = (self.max_range / self.zoom_level) / radius
        r_pixels = dist / meters_per_pixel
        ang = math.radians(brg - 90)
        cx = self.width()//2; cy = self.height()//2
        x = cx + r_pixels * math.cos(ang)
        y = cy + r_pixels * math.sin(ang)
        return int(x), int(y)

    def _haversine(self, lat1, lon1, lat2, lon2):
        R=6371000
        dlat=math.radians(lat2-lat1)
        dlon=math.radians(lon2-lon1)
        a=math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
        return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _bearing(self, lat1, lon1, lat2, lon2):
        lat1_r=math.radians(lat1); lat2_r=math.radians(lat2)
        dlon=math.radians(lon2-lon1)
        y=math.sin(dlon)*math.cos(lat2_r)
        x=math.cos(lat1_r)*math.sin(lat2_r)-math.sin(lat1_r)*math.cos(lat2_r)*math.cos(dlon)
        return (math.degrees(math.atan2(y,x))+360)%360

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._draw_background(p)
        self._draw_rings_grid(p)
        self._draw_own(p)
        self._draw_trails(p)
        self._draw_teams(p)
        self._draw_overlay(p)

    def _draw_background(self, p):
        g = QLinearGradient(0,0,0,self.height())
        g.setColorAt(0.0, QColor(10,18,24))
        g.setColorAt(1.0, QColor(6,10,14))
        p.fillRect(self.rect(), g)

    def _draw_rings_grid(self, p):
        p.save()
        cx = self.width()//2; cy = self.height()//2
        radius = min(self.width(), self.height())/2 - 18
        ring_count = 4
        p.setPen(QPen(QColor(40,70,80),1))
        # Dairesel halkalar
        for i in range(1, ring_count+1):
            r = radius * i / ring_count
            p.drawEllipse(int(cx-r), int(cy-r), int(2*r), int(2*r))
        # Ana eksenler
        p.setPen(QPen(QColor(70,110,120),1))
        p.drawLine(cx, cy-int(radius), cx, cy+int(radius))
        p.drawLine(cx-int(radius), cy, cx+int(radius), cy)
        p.restore()

    def _draw_own(self, p):
        p.save()
        cx = self.width()//2; cy = self.height()//2
        pulse = (math.sin(self.pulse_phase)+1)/2  # 0..1
        base_col = QColor(240, 220, 0)
        glow_alpha = int(80 + 70*pulse)
        glow_col = QColor(base_col.red(), base_col.green(), base_col.blue(), glow_alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(glow_col)
        p.drawEllipse(cx-14, cy-14, 28, 28)
        p.setBrush(base_col)
        p.setPen(QPen(QColor(255,255,255),2))
        p.drawEllipse(cx-7, cy-7, 14, 14)
        p.restore()

    def _draw_trails(self, p):
        p.save()
        p.setPen(QPen(QColor(140,140,140),1, Qt.DotLine))
        for tid, pts in self.trails.items():
            if len(pts) < 2:
                continue
            for i in range(1, len(pts)):
                x1,y1 = pts[i-1]; x2,y2 = pts[i]
                p.drawLine(x1,y1,x2,y2)
        p.restore()

    def _draw_teams(self, p):
        p.save()
        font = QFont("Arial", 8, QFont.Bold)
        p.setFont(font)
        for team_id, tdata in self.teams_data.items():
            lat = tdata.get("lat"); lon = tdata.get("lon")
            if lat is None or lon is None:
                continue
            x,y = self.coord_to_grid(lat, lon)
            col = self.radar.team_colors.get(team_id, QColor(255,180,110))
            aktif = tdata.get("aktif", True)
            if not aktif:
                col = QColor(90,90,90)
            # Kilit efekti
            if team_id == self.locked_team:
                pulse = (math.sin(self.pulse_phase*2)+1)/2
                outline = QColor(255, 60, 60, 180)
                p.setPen(QPen(outline, 3))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(x-11, y-11, 22, 22)
                col = QColor(
                    min(255, col.red()+60),
                    min(255, col.green()),
                    min(255, col.blue()+60)
                )
            # Nokta
            p.setPen(QPen(QColor(255,255,255),1))
            p.setBrush(QBrush(col))
            p.drawEllipse(x-6, y-6, 12, 12)
            # Etiket
            p.setPen(QPen(QColor(230,230,230),1))
            label = team_id.replace("takım_", "T")
            p.drawText(x+8, y+4, label)
        p.restore()

    def _draw_overlay(self, p):
        p.save()
        p.setPen(QPen(QColor(160,190,200),1))
        p.setFont(QFont("Arial",8))
        meters_per_pixel = (self.max_range / self.zoom_level) / (min(self.width(), self.height())/2 - 18)
        p.drawText(6, 14, f"Zoom: {self.zoom_level:.2f}x")
        p.drawText(6, 28, f"Ölçek: {int(meters_per_pixel)} m/px")
        p.drawText(6, 42, f"Takımlar: {len(self.teams_data)}")
        p.restore()


class TeamInfoPanel(QWidget):
    def __init__(self, radar):
        super().__init__()
        self.radar = radar
        self.team_widgets = {}
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(2,2,2,2)
        self.container_layout.setSpacing(2)
        self.scroll.setWidget(self.container)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2,2,2,2)
        lay.addWidget(self.scroll)

        self.setMaximumHeight(120)
        self.setStyleSheet("background:#111a20; border:1px solid #23343e;")

    def update_teams(self, teams):
        for w in self.team_widgets.values():
            w.setParent(None)
        self.team_widgets.clear()
        for tid, data in teams.items():
            w = TeamRow(tid, data, self.radar)
            self.team_widgets[tid] = w
            self.container_layout.addWidget(w)
        self.container_layout.addStretch(1)

    def update_lock_status(self, locked):
        for tid, w in self.team_widgets.items():
            w.set_locked(tid == locked)


class TeamRow(QWidget):
    def __init__(self, team_id, data, radar):
        super().__init__()
        self.team_id = team_id
        self.radar = radar
        self.setFixedHeight(26)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4,0,4,0)
        lay.setSpacing(6)

        color = radar.team_colors.get(team_id, QColor(255,180,110))
        self.color_box = QLabel("●")
        self.color_box.setStyleSheet(f"color: rgb({color.red()},{color.green()},{color.blue()}); font-size:14px;")
        lay.addWidget(self.color_box)

        self.id_lbl = QLabel(team_id.replace("takım_", "T"))
        self.id_lbl.setStyleSheet("color:#eee; font-size:11px; font-weight:bold;")
        lay.addWidget(self.id_lbl)

        lat = data.get("lat"); lon = data.get("lon"); spd = data.get("speed")
        self.pos_lbl = QLabel(f"{lat:.5f},{lon:.5f}" if lat and lon else "—")
        self.pos_lbl.setStyleSheet("color:#66ddee; font-size:10px;")
        lay.addWidget(self.pos_lbl, 1)

        self.speed_lbl = QLabel(f"{spd:.1f} m/s" if spd is not None else "—")
        self.speed_lbl.setStyleSheet("color:#f5d86d; font-size:10px;")
        lay.addWidget(self.speed_lbl)

        self.lock_btn = QPushButton("Kilit")
        self.lock_btn.setFixedWidth(46)
        self.lock_btn.setStyleSheet(self._style(False))
        self.lock_btn.clicked.connect(lambda: radar.lock_team(team_id))
        lay.addWidget(self.lock_btn)

    def _style(self, locked):
        if locked:
            return ("QPushButton {background:#c62828; color:#fff; border:1px solid #a00; "
                    "border-radius:3px; font-size:10px;} QPushButton:hover{background:#b71c1c;}")
        return ("QPushButton {background:#263238; color:#ddd; border:1px solid #37474f; "
                "border-radius:3px; font-size:10px;} QPushButton:hover{background:#37474f;}")

    def set_locked(self, locked):
        self.lock_btn.setText("Kilitli" if locked else "Kilit")
        self.lock_btn.setStyleSheet(self._style(locked))
