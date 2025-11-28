# -*- coding: utf-8 -*-
from PyQt5.QtCore import QThread, pyqtSignal
import math

try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None

class MavlinkPositionThread(QThread):
    position_update = pyqtSignal(float, float, float)  # lat, lon, heading
    def __init__(self, uri='udp:127.0.0.1:14555', parent=None):
        super().__init__(parent)
        self._uri = uri
        self._running = True
        self._conn = None

    def run(self):
        if mavutil is None:
            return
        try:
            self._conn = mavutil.mavlink_connection(self._uri, source_system=255)
            while self._running:
                msg = self._conn.recv_match(blocking=True, timeout=0.5)
                if not msg:
                    continue
                mtype = msg.get_type()
                if mtype == 'GLOBAL_POSITION_INT':
                    try:
                        lat = msg.lat / 1e7
                        lon = msg.lon / 1e7
                        rel_alt = msg.relative_alt / 1000.0
                        # Heading türetme (cog yoksa yaw yok); burada vx,vy kullanılabilir.
                        # Basit: heading = (msg.hdg / 100) if mevcut.
                        heading = getattr(msg, 'hdg', None)
                        if heading is not None:
                            heading = (heading / 100.0) % 360.0
                        else:
                            heading = 0.0
                        self.position_update.emit(lat, lon, heading)
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            try:
                if self._conn:
                    self._conn.close()
            except Exception:
                pass

    def stop(self):
        self._running = False
        self.wait(1500)
