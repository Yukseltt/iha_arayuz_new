from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QGridLayout, QGroupBox
from PyQt5.QtCore import Qt
from telemetry_store import telemetry_store

class FlightInfoWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._labels = {}
        self._build_ui()
        telemetry_store.register(self.handle_pose)  # Yeni: store aboneliği

    def _build_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox("Uçuş Bilgileri (Telemetri)")
        grid = QGridLayout(group)
        fields = [
            ("lat", "Enlem"), ("lon", "Boylam"), ("alt", "İrtifa (m)"),
            ("speed", "Hız (m/s)"), ("roll", "Roll (°)"), ("pitch", "Pitch (°)"),
            ("yaw", "Yaw / Heading (°)"), ("battery", "Batarya (%)"),
            ("autonomous", "Otonom"), ("lock", "Kilitlenme"), ("gps_time_ms", "GPS Zaman (ms)")
        ]
        for i,(key,title) in enumerate(fields):
            t_lbl = QLabel(title + ":")
            t_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            v_lbl = QLabel("—")
            v_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            t_lbl.setStyleSheet("color:#ccc;")
            v_lbl.setStyleSheet("color:#fff; font-weight:bold;")
            grid.addWidget(t_lbl, i, 0)
            grid.addWidget(v_lbl, i, 1)
            self._labels[key] = v_lbl
        group.setStyleSheet("QGroupBox{font-size:16px; color:#eee;}")
        layout.addWidget(group)
        layout.addStretch(1)
        self.setStyleSheet("background:#202020;")

    def handle_pose(self, payload: dict):
        def fmt(v, f=None):
            if v is None: return "—"
            if f: return f(v)
            return str(v)

        updates = {
            "lat": fmt(payload.get("lat"), lambda x: f"{x:.6f}"),
            "lon": fmt(payload.get("lon"), lambda x: f"{x:.6f}"),
            "alt": fmt(payload.get("alt"), lambda x: f"{x:.1f}"),
            "speed": fmt(payload.get("speed"), lambda x: f"{x:.2f}"),
            "roll": fmt(payload.get("roll"), lambda x: f"{x:.1f}"),
            "pitch": fmt(payload.get("pitch"), lambda x: f"{x:.1f}"),
            "yaw": fmt(payload.get("yaw"), lambda x: f"{x:.1f}"),
            "battery": fmt(payload.get("battery"), lambda x: f"{int(x)}"),
            "autonomous": "Evet" if payload.get("autonomous") else "Hayır",
            "lock": "Evet" if payload.get("lock") else "Hayır",
            "gps_time_ms": fmt(payload.get("gps_time_ms"))
        }
        for k,v in updates.items():
            lbl = self._labels.get(k)
            if lbl:
                lbl.setText(v)
