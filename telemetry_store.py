import threading

class TelemetryStore:
    def __init__(self):
        self._last = {}
        self._listeners = []
        self._lock = threading.Lock()

    def register(self, callback):
        with self._lock:
            self._listeners.append(callback)
        # İlk değer varsa hemen gönder
        if self._last:
            try: callback(self._last)
            except: pass

    def update(self, payload: dict):
        if not isinstance(payload, dict):
            return
        with self._lock:
            self._last = payload
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(payload)
            except:
                pass

    def get_last(self):
        with self._lock:
            return dict(self._last)

telemetry_store = TelemetryStore()
