from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor
import asyncio
import time
from telemetry_store import telemetry_store
import math

class BaseAsyncComponent:
    """
    Modüler bileşen arayüzü.
    - widget: Qt görseli
    - interested_types: (opsiyonel) dinlemek istediği MsgType veya MAVLink string listesi
    - async_update_interval: periyodik güncelleme süresi (sn) (opsiyonel)
    """
    def __init__(self, name: str):
        self.name = name
        self.widget = QWidget()
        self.interested_types = []
        self.async_update_interval = None
        self._running = True

    async def async_update(self):
        """Periyodik görev (opsiyonel)."""
        await asyncio.sleep(0)  # Placeholder

    def handle_message(self, msg: dict):
        """Gelen mesajı işlemek (opsiyonel)."""
        pass

    def shutdown(self):
        self._running = False

class DashboardWidget(QWidget):
    """
    Ana sayfa modüler bileşen yöneticisi.
    Birden fazla bileşeni yatay/dikey yerleştirir, asenkron update görevlerini yönetir.
    """
    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.loop = loop
        self._components = []
        self._tasks = []
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(12)

    def register_component(self, component: BaseAsyncComponent):
        box = QGroupBox(component.name)
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(component.widget)
        self._layout.addWidget(box)
        self._components.append(component)
        if component.async_update_interval and component.async_update_interval > 0:
            self._tasks.append(self.loop.create_task(self._run_periodic(component)))

    async def _run_periodic(self, component: BaseAsyncComponent):
        try:
            while component._running:
                start = time.time()
                try:
                    await component.async_update()
                except Exception:
                    pass
                elapsed = time.time() - start
                wait = max(0.01, component.async_update_interval - elapsed)
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            pass

    def forward_message(self, msg: dict):
        t = msg.get("_type")
        for c in self._components:
            if (not c.interested_types) or (t in c.interested_types):
                try:
                    c.handle_message(msg)
                except Exception:
                    pass

    def shutdown(self):
        for c in self._components:
            c.shutdown()
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

# ÖRNEK BİLEŞENLER (Minimal)

class ServerStatusComponent(BaseAsyncComponent):
    def __init__(self):
        super().__init__("Sunucu / Telemetri Durumu")
        self.label = QLabel("Bekleniyor...")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size:16px; padding:6px; background:#333; color:#fff;")
        layout = QVBoxLayout(self.widget)
        layout.addWidget(self.label)
        self.interested_types = ["STATUS_UPDATE"]

    def handle_message(self, msg: dict):
        if msg.get("_type") == "STATUS_UPDATE":
            p = msg.get("payload", {})
            hz = p.get("telemetry_hz", 0)
            team = p.get("team_number")
            conn = "BAĞLI" if p.get("connected") else "BAĞLI DEĞİL"
            self.label.setText(f"Takım: {team} | {conn} | Telemetri: {hz:.1f} Hz")

class PoseComponent(BaseAsyncComponent):
    def __init__(self):
        super().__init__("Pozisyon")
        self.label = QLabel("Pozisyon bekleniyor...")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size:16px; padding:6px; background:#222; color:#eee;")
        layout = QVBoxLayout(self.widget)
        layout.addWidget(self.label)
        self.interested_types = ["SELF_POSE"]

    def handle_message(self, msg: dict):
        if msg.get("_type") == "SELF_POSE":
            p = msg.get("payload", {})
            lat = p.get("lat"); lon = p.get("lon"); alt = p.get("alt"); yaw = p.get("yaw")
            if None not in (lat, lon, alt, yaw):
                self.label.setText(f"Lat:{lat:.6f} Lon:{lon:.6f} Alt:{alt:.1f} Yaw:{yaw:.1f}")

class MiniTelemetryComponent(BaseAsyncComponent):
    def __init__(self):
        super().__init__("Mini Telemetri")
        self.label = QLabel("Batarya: %— | Hız: — m/s | Roll: —° | Pitch: —° | Yaw: —°")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size:14px; padding:4px; background:#1e1e1e; color:#e0e0e0;")
        layout = QVBoxLayout(self.widget)
        layout.addWidget(self.label)
        self.interested_types = ["SELF_POSE"]
        telemetry_store.register(self._on_store_update)  # Yeni abonelik

    def _on_store_update(self, payload: dict):
        b = payload.get("battery")
        r = payload.get("roll")
        pi = payload.get("pitch")
        y = payload.get("yaw")
        s = payload.get("speed")
        def fmt(val, unit="", is_deg=False, prec=1):
            if val is None:
                return "—" + (unit if unit else "")
            if is_deg:
                return f"{val:.0f}°"
            return f"{val:.{prec}f}{unit}"
        bat_str = f"%{b if b is not None else '—'}"
        hiz_str = fmt(s, " m/s", False, 1)
        roll_str = fmt(r, "", True)
        pitch_str = fmt(pi, "", True)
        yaw_str = fmt(y, "", True)
        self.label.setText(f"Batarya: {bat_str} | Hız: {hiz_str} | Roll: {roll_str} | Pitch: {pitch_str} | Yaw: {yaw_str}")

    def handle_message(self, msg: dict):
        # Artık kullanılmıyor; store üzerinden geliyor
        pass

class MiniRadarComponent(BaseAsyncComponent):
    def __init__(self):
        super().__init__("Mini Radar")
        self.canvas = _MiniRadarCanvas()
        lay = QVBoxLayout(self.widget)
        lay.setContentsMargins(4,4,4,4)
        lay.addWidget(self.canvas)
        telemetry_store.register(self.canvas.update_pose)

class _MiniRadarCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.lat = None
        self.lon = None
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60)  # ~16 FPS

    def update_pose(self, payload: dict):
        self.lat = payload.get("lat")
        self.lon = payload.get("lon")
        self.update()

    def _tick(self):
        self.phase = (self.phase + 0.08) % (2*3.14159)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        p.fillRect(rect, QColor(16,22,28))
        cx = rect.width()//2
        cy = rect.height()//2

        # Dış halkalar
        p.setPen(QPen(QColor(40,70,80),1))
        for r in (40, 30, 20, 10):
            p.drawEllipse(cx-r, cy-r, 2*r, 2*r)

        # Merkez puls
        pulse = (1 + math.sin(self.phase)) / 2
        glow = QColor(255, 230, 70, int(60 + 120*pulse))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(cx-16, cy-16, 32, 32)

        p.setBrush(QColor(255, 220, 0))
        p.setPen(QPen(QColor(255,255,255),2))
        p.drawEllipse(cx-8, cy-8, 16, 16)

        # Koordinat metni
        p.setPen(QColor(180,200,210))
        if self.lat is not None and self.lon is not None:
            p.drawText(6, rect.height()-8, f"{self.lat:.5f}, {self.lon:.5f}")
        else:
            p.drawText(6, rect.height()-8, "Konum bekleniyor...")

# Gelecekte: Yeni bileşenler buraya eklenecek (ör. Görev Durumu, Video Akışı, Hedef Takibi)
