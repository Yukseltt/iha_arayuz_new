# -*- coding: utf-8 -*-
"""
IHA KONTROL PANELI - YENI ARAYÜZ (GUI)
========================================
Sadece arayüz bileşenlerini (PyQt5) içerir.
Hiçbir MAVLink/HTTP/Asyncio mantığı içermez.

(Versiyon: Sunucu Saati ve QR Hedef Sekmesi Eklendi)
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QGroupBox, QFrame, QTextEdit, QTabWidget
)
from PyQt5.QtCore import Qt, QTimer
from constants import MsgType # Ortak sabitleri import et
from gui_components.dashboard import DashboardWidget, ServerStatusComponent, PoseComponent, MiniTelemetryComponent, MiniRadarComponent
from gui_components.flight_panel import FlightInfoWidget
from gui_components.radar_widget import RadarWidget
from gui_components.map_widget import MapWidget
from gui_components.mavlink_thread import MavlinkPositionThread
from telemetry_store import telemetry_store

class MainWindow(QMainWindow):
    """
    Ana Kontrol Paneli Penceresi.
    Login ekranı olmadan doğrudan açılır.
    """
    def __init__(self, loop=None):
        super().__init__()
        self.loop = loop  # AdminAPI gibi özellikler için opsiyonel
        self.setWindowTitle("İHA Kontrol Paneli V3 (Async)")
        self.setGeometry(100, 100, 1400, 800)
        
        self.admin_api = None

        self.qr_label_style_bekleniyor = "font-size: 24px; font-weight: bold; color: #9E9E9E; background-color: #424242; padding: 10px; border-radius: 5px;"
        self.qr_label_style_geldi = "font-size: 24px; font-weight: bold; color: #66BB6A; background-color: #333; padding: 10px; border-radius: 5px;"
        
        self.initUI()
        
        self.mavlink_timer = QTimer(self)
        self.mavlink_timer.timeout.connect(self._on_mavlink_timeout)
        self.mavlink_timeout_ms = 3000 # 3 saniye
        
        # --- YENİ EKLENEN QR LABEL STİLLERİ ---
        self.qr_label_style_bekleniyor = "font-size: 24px; font-weight: bold; color: #9E9E9E; background-color: #424242; padding: 10px; border-radius: 5px;"
        self.qr_label_style_geldi = "font-size: 24px; font-weight: bold; color: #66BB6A; background-color: #333; padding: 10px; border-radius: 5px;"
        # --- BİTİŞ ---

        self.dashboard = None  # Yeni ana modüler bileşen konteyneri
        self.suppress_unknown = {
            "SCALED_PRESSURE","SCALED_PRESSURE2","WIND","TERRAIN_REPORT","EKF_STATUS_REPORT","VIBRATION",
            "BATTERY_STATUS","RADIO_STATUS","AHRS","POWER_STATUS","MEMINFO","MISSION_CURRENT","SERVO_OUTPUT_RAW",
            "RC_CHANNELS","RC_CHANNELS_RAW","RAW_IMU","SCALED_IMU2","SCALED_IMU3"
        }

    def initUI(self):
        # Ana widget ve dikey layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. Bölüm: Durum Göstergeleri
        status_group = QGroupBox("Genel Durum")
        status_layout = QHBoxLayout()
        
        self.mavlink_status_label = self._create_status_label("MAVLink: BEKLENİYOR")
        self.server_status_label = self._create_status_label("Sunucu: BEKLENİYOR")
        self.server_time_label = self._create_status_label("Sunucu Saati: --:--:--")
        self._set_status_label(self.server_time_label, "Sunucu Saati: --:--:--", "#B0BEC5", "black")
        self.telemetry_hz_label = self._create_status_label("Telemetri: 0.0 Hz")
        self.ws_status_label = self._create_status_label("WS: 0 İstemci")
        
        status_layout.addWidget(self.mavlink_status_label)
        status_layout.addWidget(self.server_status_label)
        status_layout.addWidget(self.server_time_label) 
        status_layout.addWidget(self.telemetry_hz_label)
        status_layout.addWidget(self.ws_status_label)
        status_group.setLayout(status_layout)
        
        main_layout.addWidget(status_group)

        # 2. Bölüm: Ana İçerik (Tab'lar)
        self.tabs = QTabWidget()
        # --- Yeni: Dashboard Tab ---
        self.dashboard = DashboardWidget(self.loop)
        self.tabs.addTab(self.dashboard, "Dashboard")
        self.dashboard.register_component(ServerStatusComponent())
        self.dashboard.register_component(PoseComponent())
        self.dashboard.register_component(MiniTelemetryComponent())
        self.dashboard.register_component(MiniRadarComponent())
        # Uçuş Bilgileri sekmesi
        self.flight_info = FlightInfoWidget()
        self.tabs.addTab(self.flight_info, "Uçuş Bilgileri")
        # Radar sekmesi
        self.radar_widget = RadarWidget()
        self.tabs.addTab(self.radar_widget, "Radar")
        # Gelişmiş Harita sekmesi (placeholder yerine)
        self.map_widget = MapWidget()
        self.tabs.addTab(self.map_widget, "Görev Haritası")
        self.map_widget.load_dummy_mission()
        self.map_widget.start_mission_debug()
        # MAVLink konum thread'i
        self.mavlink_pos_thread = MavlinkPositionThread()
        self.mavlink_pos_thread.position_update.connect(self._on_thread_position)
        self.mavlink_pos_thread.start()
        
        # --- Tab 1: Ham Veri Logları ---
        log_widget = QWidget()
        log_layout = QHBoxLayout(log_widget)
        
        self.mavlink_log_text = QTextEdit()
        self.mavlink_log_text.setReadOnly(True)
        self.mavlink_log_text.setPlaceholderText("Gelen MAVLink mesajları...")
        
        self.server_log_text = QTextEdit()
        self.server_log_text.setReadOnly(True)
        self.server_log_text.setPlaceholderText("Sunucu ve API mesajları...")
        
        log_layout.addWidget(QGroupBox("MAVLink Log"), 1)
        log_layout.itemAt(0).widget().setLayout(QVBoxLayout())
        log_layout.itemAt(0).widget().layout().addWidget(self.mavlink_log_text)

        log_layout.addWidget(QGroupBox("Sunucu Log"), 1)
        log_layout.itemAt(1).widget().setLayout(QVBoxLayout())
        log_layout.itemAt(1).widget().layout().addWidget(self.server_log_text)

        self.tabs.addTab(log_widget, "Veri Logları")
        
        # --- YENİ EKLENEN TAB 2: QR HEDEF ---
        qr_widget = QWidget()
        qr_layout = QVBoxLayout(qr_widget)
        
        qr_group = QGroupBox("QR Hedef Koordinatları")
        qr_group.setStyleSheet("font-size: 16px;")
        qr_group_layout = QVBoxLayout(qr_group)
        
        self.qr_enlem_label = QLabel("QR Enlem: BEKLENİYOR")
        self.qr_boylam_label = QLabel("QR Boylam: BEKLENİYOR")
        
        self.qr_enlem_label.setStyleSheet(self.qr_label_style_bekleniyor)
        self.qr_boylam_label.setStyleSheet(self.qr_label_style_bekleniyor)
        
        self.qr_enlem_label.setAlignment(Qt.AlignCenter)
        self.qr_boylam_label.setAlignment(Qt.AlignCenter)

        qr_group_layout.addWidget(self.qr_enlem_label)
        qr_group_layout.addWidget(self.qr_boylam_label)
        
        qr_layout.addWidget(qr_group)
        qr_layout.addStretch(1) # Grubu yukarı iter
        
        self.tabs.addTab(qr_widget, "QR Hedef")
        # --- YENİ TAB BİTİŞİ ---
        
        # --- Tab 3: Harita (Gelecek için yer tutucu) ---
        map_placeholder = QLabel("Harita Alanı (Gelecekte Eklenecek)")
        map_placeholder.setAlignment(Qt.AlignCenter)
        map_placeholder.setStyleSheet("background-color: #333; color: white; font-size: 20px;")
        self.tabs.addTab(map_placeholder, "Harita")

        main_layout.addWidget(self.tabs, 1) # 1 = Esneme faktörü
        
        # 3. Bölüm: StatusBar
        self.statusBar().showMessage("Arayüz başlatıldı. Arka plan servisleri yükleniyor...")

    def _create_status_label(self, text: str):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setFrameShape(QFrame.StyledPanel)
        label.setStyleSheet("background-color: #FFA726; color: black; font-weight: bold; padding: 6px;")
        return label

    def _set_status_label(self, label: QLabel, text: str, color: str, text_color: str = "white"):
        label.setText(text)
        label.setStyleSheet(f"background-color: {color}; color: {text_color}; font-weight: bold; padding: 6px;")

    def _on_mavlink_timeout(self):
        self._set_status_label(self.mavlink_status_label, "MAVLink: BAĞLANTI YOK", "#D32F2F")
        self.mavlink_timer.stop()

    def _on_thread_position(self, lat, lon, heading):
        try:
            if self.map_widget:
                self.map_widget.update_drone_position(lat, lon, heading)
            if self.radar_widget:
                self.radar_widget.update_own_position(lat, lon)
        except Exception:
            pass

    # --- main.py Tarafından Çağrılacak Ana İşleyici ---

    def handle_backend_message(self, msg_dict: dict):
        msg_type = msg_dict.get("_type")

        # Dashboard’a tüm mesajları ilet (önce)
        if self.dashboard:
            try:
                self.dashboard.forward_message(msg_dict)
            except Exception:
                pass

        mavlink_types = ["HEARTBEAT","GLOBAL_POSITION_INT","ATTITUDE","SYS_STATUS","VFR_HUD","GPS_RAW_INT","SYSTEM_TIME"]
        if msg_type in mavlink_types:
            if not self.mavlink_timer.isActive():
                self._set_status_label(self.mavlink_status_label, "MAVLink: BAĞLANDI", "#4CAF50")
            self.mavlink_timer.start(self.mavlink_timeout_ms)
            
            if msg_type == "GLOBAL_POSITION_INT":
                lat = msg_dict.get('lat', 0) / 1e7
                lon = msg_dict.get('lon', 0) / 1e7
                alt = msg_dict.get('relative_alt', 0) / 1000.0
                self.mavlink_log_text.append(f"[{msg_type}] Lat: {lat:.6f}, Lon: {lon:.6f}, Alt: {alt:.2f}m")
            elif msg_type == "ATTITUDE":
                roll = msg_dict.get('roll', 0)
                pitch = msg_dict.get('pitch', 0)
                self.mavlink_log_text.append(f"[{msg_type}] Roll: {roll:.2f}, Pitch: {pitch:.2f}")
            elif msg_type != "HEARTBEAT":
                 self.mavlink_log_text.append(f"[{msg_type}] Alındı.")
            
            self.mavlink_log_text.verticalScrollBar().setValue(self.mavlink_log_text.verticalScrollBar().maximum())
            return

        elif msg_type == MsgType.STATUS_UPDATE:
            payload = msg_dict.get("payload", {})
            if payload.get("connected"):
                team = payload.get("team_number", "?")
                self._set_status_label(self.server_status_label, f"Sunucu: BAĞLI (Takım #{team})", "#4CAF50")
            else:
                if "HATASI" not in self.server_status_label.text():
                    self._set_status_label(self.server_status_label, "Sunucu: BAĞLI DEĞİL", "#D32F2F")
            hz = payload.get("telemetry_hz", 0)
            color = "#4CAF50" if hz > 0.1 else "#FFA726"
            self._set_status_label(self.telemetry_hz_label, f"Telemetri: {hz:.1f} Hz", color, "black")
            
        elif msg_type == MsgType.WS_CLIENTS:
            count = msg_dict.get("count", 0)
            self._set_status_label(self.ws_status_label, f"WS: {count} İstemci", "#2196F3")

        elif msg_type == MsgType.SERVER_LOGIN_OK:
            team = msg_dict.get("takim_numarasi", "?")
            self._set_status_label(self.server_status_label, f"Sunucu: GİRİŞ BAŞARILI (Takım #{team})", "#4CAF50")
            self.server_log_text.append(f"GİRİŞ BAŞARILIDIR: {msg_dict.get('base_url')}")
            
        elif msg_type == MsgType.SERVER_LOGIN_ERROR:
            self._set_status_label(self.server_status_label, "Sunucu: GİRİŞ HATASI", "#D32F2F")
            self.server_log_text.append(f"SUNUCU GİRİŞ HATASI: {msg_dict.get('error')}")

        elif msg_type == MsgType.SERVER_AUTH_REQUIRED:
            self._set_status_label(self.server_status_label, "Sunucu: YETKİ GEREKLİ (Yeniden deneniyor...)", "#FFA726", "black")
            self.server_log_text.append("Sunucu yetkisi kayboldu. Yeniden giriş denenecek.")
            
        elif msg_type == MsgType.SERVER_TIME:
            payload = msg_dict.get('payload', {})
            try:
                saat = payload.get('saat', 0)
                dakika = payload.get('dakika', 0)
                saniye = payload.get('saniye', 0)
                time_str = f"{saat:02d}:{dakika:02d}:{saniye:02d}"
                self._set_status_label(self.server_time_label, f"Sunucu Saati: {time_str}", "#0288D1", "white")
                self.server_log_text.append(f"[{msg_type}] {time_str}")
            except Exception as e:
                self.server_log_text.append(f"[{msg_type}] Zaman formatı hatası: {e}")
        
        elif msg_type == MsgType.SERVER_QR:
            payload = msg_dict.get('payload', {})
            enlem = payload.get('qrEnlem')
            boylam = payload.get('qrBoylam')

            if enlem is not None and boylam is not None:
                self.qr_enlem_label.setText(f"QR Enlem: {enlem}")
                self.qr_boylam_label.setText(f"QR Boylam: {boylam}")
                # Stilini "veri geldi" olarak güncelle
                self.qr_enlem_label.setStyleSheet(self.qr_label_style_geldi)
                self.qr_boylam_label.setStyleSheet(self.qr_label_style_geldi)
            else:
                self.qr_enlem_label.setText("QR Enlem: VERİ YOK")
                self.qr_boylam_label.setText("QR Boylam: VERİ YOK")
                # Stilini "bekleniyor" olarak ayarla
                self.qr_enlem_label.setStyleSheet(self.qr_label_style_bekleniyor)
                self.qr_boylam_label.setStyleSheet(self.qr_label_style_bekleniyor)
            
            # Veriyi ayrıca log sekmesine de yaz
            self.server_log_text.append(f"[{msg_type}] Veri alındı: {payload}")

        # HSS (artık QR'dan ayrı)
        elif msg_type == MsgType.SERVER_HSS:
            payload = msg_dict.get('payload', {})
            hss_list = payload.get("hss_koordinat_bilgileri") if isinstance(payload, dict) else None
            if hss_list is not None:
                self.server_log_text.append(f"[{msg_type}] HSS adet: {len(hss_list)}")
            else:
                self.server_log_text.append(f"[{msg_type}] Veri alındı: {payload}")

        elif msg_type == MsgType.TELEMETRY_ACK:
            pass # Loglamıyoruz
        
        elif msg_type == MsgType.TELEMETRY_ERROR:
            self.server_log_text.append(f"TELEMETRİ HATASI: {msg_dict.get('error')}")
            
        elif msg_type in (MsgType.ADMIN_HSS_OK, MsgType.ADMIN_QR_OK, MsgType.ADMIN_STATS, MsgType.ADMIN_CLEAR_OK):
            self.server_log_text.append(f"ADMIN BAŞARILI: [{msg_type}] {msg_dict.get('payload')}")
            
        elif msg_type == MsgType.ADMIN_ERROR:
            self.server_log_text.append(f"ADMIN HATASI: [{msg_type}] {msg_dict.get('error')}")

        # SELF_POSE: Uçuş bilgileri panelini güncelle
        elif msg_type == MsgType.SELF_POSE:
            payload = msg_dict.get("payload", {})
            telemetry_store.update(payload)
            if getattr(self, "map_widget", None):
                try:
                    lat = payload.get("lat"); lon = payload.get("lon"); hdg = payload.get("yaw")
                    if None not in (lat, lon, hdg):
                        self.map_widget.update_drone_position(lat, lon, hdg)
                except Exception: pass
            if getattr(self, "radar_widget", None):
                try:
                    lat = payload.get("lat"); lon = payload.get("lon")
                    if lat is not None and lon is not None:
                        self.radar_widget.update_own_position(lat, lon)
                except Exception: pass
            self.server_log_text.append("[SELF_POSE] Güncellendi.")
        
        elif msg_type == MsgType.TEAMS_UPDATE:
            raw_list = msg_dict.get("payload", [])
            teams_dict = {}
            for item in raw_list:
                tno = item.get("takim_numarasi")
                if tno is None:
                    continue
                teams_dict[f"takım_{tno}"] = {
                    "lat": item.get("iha_enlem"),
                    "lon": item.get("iha_boylam"),
                    "alt": item.get("iha_irtifa"),
                    "pitch": item.get("iha_dikilme"),
                    "yaw": item.get("iha_yonelme"),
                    "roll": item.get("iha_yatis"),
                    "speed": item.get("iha_hizi"),
                    "aktif": True
                }
            if getattr(self, "radar_widget", None):
                try:
                    self.radar_widget.update_teams_data(teams_dict)
                except Exception:
                    pass
            self.server_log_text.append(f"[TEAMS_UPDATE] Takım sayısı: {len(teams_dict)}")

        else:
            if msg_type in self.suppress_unknown:
                pass
            else:
                self.server_log_text.append(f"Bilinmeyen sistem mesajı: {msg_type}")

        self.server_log_text.verticalScrollBar().setValue(self.server_log_text.verticalScrollBar().maximum())

    def closeEvent(self, event):
        try:
            if hasattr(self, "mavlink_pos_thread") and self.mavlink_pos_thread.isRunning():
                self.mavlink_pos_thread.stop()
        except Exception:
            pass
        # Dashboard görevlerini sonlandır
        try:
            if self.dashboard:
                self.dashboard.shutdown()
        except Exception:
            pass
        super().closeEvent(event)