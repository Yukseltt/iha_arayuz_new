# -*- coding: utf-8 -*-
"""
IHA KONTROL PANELI - BASIT ASNC MOD (ANA YÖNETİCİ)
==================================================
Bu dosya:
- qasync kullanarak PyQt5 ile asyncio'yu entegre eder
- gui.py'den MainWindow'u yükler ve gösterir
- .env dosyasındaki bilgilere göre sunucuya OTOMATİK giriş yapar
- Tüm arka plan görevlerini (MAVLink, HTTP, WS) yönetir
- Gelen tüm verileri işler ve gui.py'deki 'handle_backend_message'e iletir

Kullanım:
    python main.py
"""

import sys
import asyncio
from PyQt5.QtWidgets import QApplication
import qasync

# ARAYÜZ ve SABİTLERİ İTHAL ET
from gui import MainWindow 
from constants import MsgType
from gui_components.login_window import LoginWindow

# GEREKLİ KÜTÜPHANELER
import functools
import logging
import os
import time
import json
import math

# --- Opsiyonel Kütüphaneler ---

# MAVLink (pip install pymavlink)
try:
    from pymavlink import mavutil
except Exception:
    mavutil = None

# WebSocket Sunucusu (pip install websockets)
try:
    import websockets
except Exception:
    websockets = None

# HTTP İstemcisi (pip install aiohttp)
try:
    import aiohttp
except Exception:
    aiohttp = None

# .env Yükleyici (pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()  # .env dosyasını yükler
except Exception:
    print("UYARI: python-dotenv yüklü değil, .env dosyası okunamadı.", file=sys.stderr)

# --- Global Durum Değişkenleri ---

# Sunucu oturum durumu
_SERVER_STATE = {
    "base_url": os.getenv("IHA_SERVER_URL", "http://192.168.1.10:5000/"), # .env'den
    "username": os.getenv("IHA_SERVER_USER"), # .env'den
    "team_number": None, # Giriş yapınca dolacak
    "admin_key": os.getenv("ADMIN_API_KEY"), # .env'den
}

# Telemetri derleme durumu (MAVLink → sunucu şeması)
_TELEM_STATE = {
    "lat": None, "lon": None, "alt": None,
    "pitch": None, "roll": None, "yaw": None,
    "speed": None, "battery": None, "autonomous": 0, "lock": 0,
    "target": {"hedef_merkez_X": 0, "hedef_merkez_Y": 0, "hedef_genislik": 0, "hedef_yukseklik": 0},
    "gps_time_ms": None
}
_TELEM_METRICS = {
    "last_send": None,
    "window_start": time.time(),
    "count": 0
}

# WebSocket istemcileri
_WS_CLIENTS = set()
_WS_SERVER = None

# ANA MESAJ YÖNLENDİRİCİSİ (main() içinde tanımlanacak)
_GLOBAL_ON_MESSAGE_HANDLER = None

# --- WebSocket Sunucu Fonksiyonları ---
async def _ws_handler(websocket, path):
    _WS_CLIENTS.add(websocket)
    logger = logging.getLogger("WS")
    logger.info(f"Yeni WS istemci: {websocket.remote_address}")
    try:
        if callable(_GLOBAL_ON_MESSAGE_HANDLER):
            _GLOBAL_ON_MESSAGE_HANDLER({"_type": MsgType.WS_CLIENTS, "count": len(_WS_CLIENTS)})
    except Exception: pass
    try:
        async for _ in websocket: pass
    except Exception as e:
        logger.debug(f"WS istemci hatası: {e}")
    finally:
        _WS_CLIENTS.discard(websocket)
        logger.info("WS istemci ayrıldı")
        try:
            if callable(_GLOBAL_ON_MESSAGE_HANDLER):
                _GLOBAL_ON_MESSAGE_HANDLER({"_type": MsgType.WS_CLIENTS, "count": len(_WS_CLIENTS)})
        except Exception: pass

async def broadcast_ws(msg: dict):
    if not _WS_CLIENTS: return
    payload = json.dumps(msg, default=str)
    dead = [ws for ws in list(_WS_CLIENTS) if not await ws.send(payload).exception()]
    for ws in dead: _WS_CLIENTS.discard(ws)

async def start_ws_server(host="localhost", port=8766):
    global _WS_SERVER
    if websockets is None:
        logging.getLogger("WS").info("websockets modülü yok. WS Sunucu pasif.")
        return
    _WS_SERVER = await websockets.serve(_ws_handler, host, port)
    logging.getLogger("WS").info(f"WS sunucu dinlemede: ws://{host}:{port}/")

async def shutdown_ws_server():
    global _WS_SERVER
    if _WS_SERVER is not None:
        _WS_SERVER.close()
        try: await _WS_SERVER.wait_closed()
        except Exception: pass
        logging.getLogger("WS").info("WS sunucu kapatıldı")
        _WS_SERVER = None

# --- Sunucu Yetkilendirme (Auth) Fonksiyonları ---
_AUTH_RELOGIN_EVENT = None
_AUTH_BACKOFF = {"attempt": 0, "max_delay": 30}

def request_relogin(reason: str = None):
    logger = logging.getLogger("AUTH")
    if reason: logger.info(f"Yeniden giriş isteniyor: {reason}")
    if _AUTH_RELOGIN_EVENT is not None: _AUTH_RELOGIN_EVENT.set()

def _reset_backoff(): _AUTH_BACKOFF["attempt"] = 0
def _next_delay():
    _AUTH_BACKOFF["attempt"] += 1
    return min(2 ** _AUTH_BACKOFF["attempt"], _AUTH_BACKOFF["max_delay"])

async def auth_watcher(on_message=None):
    logger = logging.getLogger("AUTH")
    global _AUTH_RELOGIN_EVENT
    if _AUTH_RELOGIN_EVENT is None: _AUTH_RELOGIN_EVENT = asyncio.Event()

    while True:
        try:
            await _AUTH_RELOGIN_EVENT.wait()
            _AUTH_RELOGIN_EVENT.clear()
            server_url = os.getenv("IHA_SERVER_URL", _SERVER_STATE["base_url"])
            user = os.getenv("IHA_SERVER_USER")
            pw = os.getenv("IHA_SERVER_PASS")
            if not (user and pw):
                logger.warning("Yeniden giriş için kimlik bilgileri yok (.env: IHA_SERVER_USER/PASS).")
                continue
            while True:
                team = await server_login(server_url, user, pw, on_message=on_message)
                if team:
                    logger.info("Yeniden giriş başarılı.")
                    _reset_backoff()
                    break
                delay = _next_delay()
                logger.warning(f"Yeniden giriş başarısız. {delay}s sonra tekrar denenecek.")
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("auth_watcher iptal edildi")
            raise
        except Exception as e:
            logger.debug(f"auth_watcher hata: {e}")
            await asyncio.sleep(1.0)

# --- HTTP İstemci Fonksiyonları (aiohttp) ---
def build_headers(admin: bool = False) -> dict:
    headers = {"Content-Type": "application/json"}
    if admin:
        key = _SERVER_STATE.get("admin_key")
        if key: headers["X-ADMIN-KEY"] = key
    return headers

async def server_login(base_url: str, username: str, password: str, on_message=None):
    logger = logging.getLogger("AUTH")
    base = (base_url or "").rstrip("/")
    if not base or not username or not password:
        logger.warning("Sunucu girişi için base_url/username/password eksik (.env kontrol edin)")
        return None
    if aiohttp is None:
        logger.error("aiohttp yüklü değil. (pip install aiohttp)")
        return None

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logger.info(f"Sunucuya giriş deneniyor: {base} kullanıcı={username}")
            async with session.post(f"{base}/api/giris", json={"kadi": username, "sifre": password}) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    team_num = data.get("takim_numarasi")
                    _SERVER_STATE["team_number"] = team_num
                    _SERVER_STATE["base_url"] = base
                    _SERVER_STATE["username"] = username
                    msg = {"_type": MsgType.SERVER_LOGIN_OK, "base_url": base, "username": username, "takim_numarasi": team_num}
                    if callable(on_message): on_message(msg)
                    logger.info(f"Sunucu girişi başarılı. Takım #{team_num}")
                    return team_num
                else:
                    text_body = await resp.text()
                    try: err_json = await resp.json(content_type=None)
                    except Exception: err_json = None
                    err = err_json if err_json else {"status": resp.status, "text": text_body}
                    msg = {"_type": MsgType.SERVER_LOGIN_ERROR, "base_url": base, "username": username, "error": err}
                    if callable(on_message): on_message(msg)
                    logger.warning(f"Giriş başarısız: {err}")
                    return None
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Bağlantı Hatası: Sunucuya erişilemiyor. URL: {base} Hata: {e}")
        if callable(on_message): on_message({"_type": MsgType.SERVER_LOGIN_ERROR, "base_url": base, "username": username, "error": f"Bağlantı Hatası: {e}"})
        return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"Giriş hatası: {e}")
        if callable(on_message): on_message({"_type": MsgType.SERVER_LOGIN_ERROR, "base_url": base, "username": username, "error": str(e)})
        return None

async def telemetry_sender(on_message=None, interval: float = 0.5):
    logger = logging.getLogger("TEL")
    if aiohttp is None:
        logger.info("aiohttp modülü yok. telemetri gönderimi pasif.")
        return
    timeout = aiohttp.ClientTimeout(total=10)
    last_warn = 0
    try:
        logger.info(f"Telemetri gönderici başladı: {1.0/interval:.1f} Hz")
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                base = (_SERVER_STATE.get("base_url") or "").rstrip("/")
                try:
                    team = _SERVER_STATE.get("team_number")
                    if not team:
                        await asyncio.sleep(interval)
                        continue
                    
                    required_data = (_TELEM_STATE["lat"], _TELEM_STATE["lon"], _TELEM_STATE["alt"], 
                                     _TELEM_STATE["pitch"], _TELEM_STATE["roll"], _TELEM_STATE["yaw"], 
                                     _TELEM_STATE["speed"], _TELEM_STATE["battery"])
                    if any(v is None for v in required_data):
                        await asyncio.sleep(interval)
                        continue

                    def to_gps_time(ms: int):
                        try:
                            sec, msec = divmod(int(ms), 1000)
                            tm = time.gmtime(sec)
                            return {"saat": tm.tm_hour, "dakika": tm.tm_min, "saniye": tm.tm_sec, "milisaniye": msec}
                        except Exception:
                            now = time.localtime()
                            return {"saat": now.tm_hour, "dakika": now.tm_min, "saniye": now.tm_sec, "milisaniye": int((time.time()*1000)%1000)}

                    gps_ms = _TELEM_STATE["gps_time_ms"]
                    gps_time = to_gps_time(gps_ms if gps_ms is not None else int(time.time()*1000))

                    payload = {
                        "takim_numarasi": team,
                        "iha_enlem": float(_TELEM_STATE["lat"]),
                        "iha_boylam": float(_TELEM_STATE["lon"]),
                        "iha_irtifa": float(_TELEM_STATE["alt"]),
                        "iha_dikilme": float(_TELEM_STATE["pitch"]),
                        "iha_yonelme": float(_TELEM_STATE["yaw"]),
                        "iha_yatis": float(_TELEM_STATE["roll"]),
                        "iha_hiz": float(_TELEM_STATE["speed"]),
                        "iha_batarya": int(max(0, min(100, int(_TELEM_STATE["battery"])))),
                        "iha_otonom": 1 if _TELEM_STATE.get("autonomous", 0) else 0,
                        "iha_kilitlenme": 1 if _TELEM_STATE.get("lock", 0) else 0,
                        "gps_saati": gps_time
                    }
                    if payload["iha_kilitlenme"] == 1:
                        payload.update(_TELEM_STATE.get("target", {}))

                    async with session.post(f"{base}/api/telemetri_gonder", json=payload, headers=build_headers()) as resp:
                        if resp.status == 200:
                            ack = await resp.json(content_type=None)
                            # KonumBilgileri ve sunucu saati çıkar
                            konum_list = ack.get("konumBilgileri", [])
                            if konum_list and callable(on_message):
                                on_message({"_type": MsgType.TEAMS_UPDATE, "payload": konum_list})
                            sunucusaati = ack.get("sunucusaati")
                            if sunucusaati and callable(on_message):
                                on_message({"_type": MsgType.SERVER_TIME, "payload": sunucusaati})
                            if callable(on_message): on_message({"_type": MsgType.TELEMETRY_ACK, "status": 200})
                            now_ts = time.time()
                            _TELEM_METRICS["last_send"] = now_ts
                            _TELEM_METRICS["count"] += 1
                            if (now_ts - _TELEM_METRICS["window_start"]) > 5.0:
                                _TELEM_METRICS["window_start"] = now_ts
                                _TELEM_METRICS["count"] = 0
                        elif resp.status == 400:
                            err = await resp.json(content_type=None)
                            if callable(on_message): on_message({"_type": MsgType.TELEMETRY_ERROR, "status": 400, "error": err})
                        elif resp.status == 401:
                            request_relogin("telemetri_gonder 401")
                            if time.time() - last_warn > 5:
                                logger.warning("401: Kimliksiz erişim. Yeniden giriş gerekli.")
                                last_warn = time.time()
                            if callable(on_message): on_message({"_type": MsgType.SERVER_AUTH_REQUIRED})
                        else:
                            if callable(on_message): on_message({"_type": MsgType.TELEMETRY_ERROR, "status": resp.status})
                except asyncio.CancelledError: raise
                except Exception as e:
                    if time.time() - last_warn > 5:
                        logger.debug(f"Telemetri gönderim hatası: {e}")
                        last_warn = time.time()
                await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logging.getLogger("TEL").info("Telemetri gönderici iptal edildi")
        raise

async def poll_server_data(endpoint: str, msg_type: str, on_message=None, interval: float = 2.0, require_login: bool = False):
    """ Genel bir sunucu veri çekme (poller) fonksiyonu """
    if aiohttp is None:
        logging.getLogger("HTTP").info(f"aiohttp yok; {msg_type} poller pasif.")
        return
    logger = logging.getLogger("HTTP")
    timeout = aiohttp.ClientTimeout(total=10)
    last_warn = 0
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                base = (_SERVER_STATE.get("base_url") or "").rstrip("/")
                if require_login and not _SERVER_STATE.get("team_number"):
                    await asyncio.sleep(interval) # Giriş yapılana kadar bekle
                    continue
                try:
                    async with session.get(f"{base}{endpoint}", headers=build_headers()) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if callable(on_message):
                                on_message({"_type": msg_type, "payload": data, "_endpoint": endpoint})
                        elif resp.status == 401 and require_login:
                            if callable(on_message): on_message({"_type": MsgType.SERVER_AUTH_REQUIRED})
                            request_relogin(f"{endpoint} 401")
                            if time.time() - last_warn > 5:
                                logger.warning(f"{msg_type} 401: Giriş gerekli")
                                last_warn = time.time()
                        else:
                            if time.time() - last_warn > 5:
                                logger.debug(f"{msg_type} HTTP {resp.status}")
                                last_warn = time.time()
                except asyncio.CancelledError: raise
                except Exception as e:
                    if time.time() - last_warn > 5:
                        logger.debug(f"{msg_type} hata: {e}")
                        last_warn = time.time()
                await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logging.getLogger("HTTP").info(f"{msg_type} poller iptal edildi")
        raise

# --- Admin API Çağrıları (UI tarafından tetiklenir) ---
async def _admin_api_call(endpoint: str, method: str, payload: dict, on_message=None, ok_msg_type: str = "ADMIN_OK"):
    logger = logging.getLogger("ADMIN")
    if aiohttp is None:
        logger.info("aiohttp yok; admin çağrısı pasif.")
        return
    base = (_SERVER_STATE.get("base_url") or "").rstrip("/")
    key = _SERVER_STATE.get("admin_key")
    if not key:
        logger.warning("ADMIN_API_KEY tanımlı değil.")
        if callable(on_message): on_message({"_type": MsgType.ADMIN_ERROR, "error": "ADMIN_API_KEY missing"})
        return
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"{base}{endpoint}", json=payload, headers=build_headers(admin=True)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if callable(on_message): on_message({"_type": ok_msg_type, "payload": data})
                else:
                    try: err = await resp.json(content_type=None)
                    except Exception: err = {"status": resp.status}
                    if resp.status == 403: logger.warning("Admin yetkisiz (403).")
                    if callable(on_message): on_message({"_type": MsgType.ADMIN_ERROR, "error": err, "action": endpoint})
    except asyncio.CancelledError: raise
    except Exception as e:
        logger.debug(f"Admin çağrı hatası ({endpoint}): {e}")
        if callable(on_message): on_message({"_type": MsgType.ADMIN_ERROR, "error": str(e), "action": endpoint})

class AdminAPI:
    """ GUI'nin async admin fonksiyonlarını çağırması için proxy sınıfı """
    def __init__(self, loop, on_message):
        self.loop = loop
        self.on_message = on_message
    
    def set_hss(self, aktif: bool, koordinatlar=None):
        payload = {"aktif": bool(aktif)}
        if aktif and koordinatlar: payload["koordinatlar"] = koordinatlar
        self.loop.create_task(_admin_api_call(
            "/admin/hss_aktif", "POST", payload, self.on_message, MsgType.ADMIN_HSS_OK
        ))
    
    def update_qr(self, qr_enlem: float, qr_boylam: float):
        payload = {"qrEnlem": float(qr_enlem), "qrBoylam": float(qr_boylam)}
        self.loop.create_task(_admin_api_call(
            "/admin/qr_koordinat_guncelle", "POST", payload, self.on_message, MsgType.ADMIN_QR_OK
        ))
    
    def get_stats(self):
        self.loop.create_task(_admin_api_call(
            "/admin/stats", "GET", None, self.on_message, MsgType.ADMIN_STATS
        ))
    
    def clear_data(self):
        self.loop.create_task(_admin_api_call(
            "/admin/clear_data", "POST", {}, self.on_message, MsgType.ADMIN_CLEAR_OK
        ))

# --- MAVLink Dinleyici ---
async def mavlink_listener(uri: str = 'udp:127.0.0.1:14555', on_message=None):
    logger = logging.getLogger("MAVLink")
    if mavutil is None:
        logger.info("pymavlink yok; MAVLink dinleyici pasif. (pip install pymavlink)")
        return
    loop = asyncio.get_event_loop()
    logger.info(f"MAVLink bağlantısı deneniyor: {uri}")
    try:
        conn = mavutil.mavlink_connection(uri, source_system=255)
        logger.info("Bağlantı açıldı, ilk mesaj (heartbeat) bekleniyor...")
        get_msg = functools.partial(conn.recv_match, blocking=True, timeout=1.0)
        last_stat = time.time()
        stat_count = 0
        while True:
            msg = await loop.run_in_executor(None, get_msg)
            now = time.time()
            if not msg or msg.get_type() == 'BAD_DATA':
                if (now - last_stat) > 5 and stat_count == 0:
                    logger.warning(f"MAVLink verisi gelmiyor. {uri} adresini kontrol edin.")
                    last_stat = now
                continue
            
            if stat_count == 0:
                logger.info("İlk MAVLink mesajı alındı!")
            stat_count += 1
            
            msg_type = msg.get_type()
            try: data = msg.to_dict()
            except Exception: data = {}
            data["_type"] = msg_type

            if callable(on_message):
                try: on_message(data)
                except Exception as e: logger.error(f"UI handler hatası: {e}")
            
            if (now - last_stat) > 5:
                logger.debug(f"Son 5 sn'de {stat_count} MAVLink mesajı alındı.")
                last_stat = now
                stat_count = 0
    except asyncio.CancelledError:
        logger.info("MAVLink dinleyici iptal edildi")
        raise
    except Exception as e:
        logger.error(f"MAVLink bağlantı hatası: {e}")
    finally:
        try: conn.close()
        except Exception: pass
        logger.info("MAVLink bağlantısı kapatıldı")

# --- Periyodik Durum Yayıncıları ---
async def status_publisher(on_message=None, interval: float = 1.0):
    """ Periyodik durum özeti yayınlar (UI ve WS için) """
    logger = logging.getLogger("STATUS")
    try:
        while True:
            try:
                now = time.time()
                win = max(0.1, now - _TELEM_METRICS.get("window_start", now))
                hz = _TELEM_METRICS.get("count", 0) / win
                last_ts = _TELEM_METRICS.get("last_send")
                payload = {
                    "server_url": _SERVER_STATE.get("base_url"),
                    "team_number": _SERVER_STATE.get("team_number"),
                    "ws_clients": len(_WS_CLIENTS),
                    "telemetry_hz": round(hz, 2),
                    "telemetry_last": time.strftime("%H:%M:%S", time.localtime(last_ts)) if last_ts else None,
                    "connected": bool(_SERVER_STATE.get("team_number"))
                }
                if callable(on_message):
                    on_message({"_type": MsgType.STATUS_UPDATE, "payload": payload})
            except asyncio.CancelledError: raise
            except Exception as e: logger.debug(f"status_publisher hata: {e}")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logging.getLogger("STATUS").info("status_publisher iptal edildi")
        raise

async def self_pose_publisher(on_message=None, interval: float = 1.0):
    """ Periyodik kendi İHA pozunu yayınlar (harita katmanına uygun) """
    logger = logging.getLogger("POSE")
    try:
        while True:
            try:
                data = {
                    "lat": _TELEM_STATE.get("lat"), "lon": _TELEM_STATE.get("lon"),
                    "alt": _TELEM_STATE.get("alt"), "yaw": _TELEM_STATE.get("yaw"),
                    "pitch": _TELEM_STATE.get("pitch"), "roll": _TELEM_STATE.get("roll"),
                    "speed": _TELEM_STATE.get("speed"), "battery": _TELEM_STATE.get("battery"),
                    "autonomous": _TELEM_STATE.get("autonomous"),
                    "lock": _TELEM_STATE.get("lock"),
                    "gps_time_ms": _TELEM_STATE.get("gps_time_ms")
                }
                if not any(v is None for v in [data["lat"], data["lon"], data["alt"], data["yaw"]]):
                    msg = {"_type": MsgType.SELF_POSE, "payload": data}
                    if callable(on_message): on_message(msg)
            except asyncio.CancelledError: raise
            except Exception as e: logger.debug(f"self_pose_publisher hata: {e}")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logging.getLogger("POSE").info("self_pose_publisher iptal edildi")
        raise

# --- ANA PROGRAM ---
def main():
    """
    Ana program fonksiyonu - Uygulamayı başlatır ve async event loop yönetir
    """
    # +++ Konsol log yapılandırması +++
    log_level = logging.DEBUG if os.getenv("IHA_DEBUG", "0").lower() in ("1", "true", "on") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger("MAIN")
    
    logger.info("IHA KONTROL PANELI V3 (Async) Başlatılıyor...")
    
    # Gerekli kütüphaneleri kontrol et
    if aiohttp is None:
        logger.critical("Kritik Hata: aiohttp kütüphanesi bulunamadı. (pip install aiohttp)")
        return 1
    if mavutil is None:
        logger.warning("pymavlink kütüphanesi bulunamadı. MAVLink dinleyicisi pasif olacak. (pip install pymavlink)")
    
    try:
        # PyQt5 uygulamasını qasync ile oluştur (async uyumlu)
        app = qasync.QApplication(sys.argv)
        app.setApplicationName("IHA Kontrol Paneli")
        
        # Async event loop oluştur ve asyncio ile entegre et
        loop = qasync.QEventLoop(app)
        asyncio.set_event_loop(loop)
        
        main_window = None  # Başta yok
        # --- Ana Mesaj İşleyici (_on_msg) ---
        def _on_msg(msg_dict):
            # MAVLink verilerini al, işle ve _TELEM_STATE'i güncelle
            try:
                t = msg_dict.get("_type")
                if t == "GLOBAL_POSITION_INT":
                    if msg_dict.get("lat") is not None: _TELEM_STATE["lat"] = float(msg_dict.get("lat")) / 1e7
                    if msg_dict.get("lon") is not None: _TELEM_STATE["lon"] = float(msg_dict.get("lon")) / 1e7
                    if msg_dict.get("relative_alt") is not None: _TELEM_STATE["alt"] = float(msg_dict.get("relative_alt")) / 1000.0
                    vx = msg_dict.get("vx"); vy = msg_dict.get("vy")
                    if vx is not None and vy is not None: _TELEM_STATE["speed"] = max(0.0, math.sqrt(float(vx)**2 + float(vy)**2) / 100.0)
                elif t == "ATTITUDE":
                    if msg_dict.get("roll") is not None: _TELEM_STATE["roll"] = math.degrees(float(msg_dict.get("roll")))
                    if msg_dict.get("pitch") is not None: _TELEM_STATE["pitch"] = math.degrees(float(msg_dict.get("pitch")))
                    if msg_dict.get("yaw") is not None: _TELEM_STATE["yaw"] = (math.degrees(float(msg_dict.get("yaw"))) + 360.0) % 360.0
                elif t == "SYS_STATUS":
                    if msg_dict.get("battery_remaining") is not None: _TELEM_STATE["battery"] = int(msg_dict.get("battery_remaining"))
                elif t == "HEARTBEAT":
                    if msg_dict.get("base_mode") is not None: _TELEM_STATE["autonomous"] = 1 if (int(msg_dict.get("base_mode")) & (1 << 4)) else 0
                elif t == "SYSTEM_TIME":
                    if msg_dict.get("time_unix_usec") is not None: _TELEM_STATE["gps_time_ms"] = int(int(msg_dict.get("time_unix_usec")) / 1000)
                elif t == "GPS_RAW_INT":
                    if msg_dict.get("time_usec") is not None: _TELEM_STATE["gps_time_ms"] = int(int(msg_dict.get("time_usec")) / 1000)
                    if msg_dict.get("vel") is not None: _TELEM_STATE["speed"] = max(0.0, float(msg_dict.get("vel")) / 100.0)
                    if msg_dict.get("cog") is not None: _TELEM_STATE["yaw"] = (float(msg_dict.get("cog")) / 100.0) % 360.0
                elif t == "VFR_HUD":
                    if msg_dict.get("groundspeed") is not None: _TELEM_STATE["speed"] = max(0.0, float(msg_dict.get("groundspeed")))
                    if msg_dict.get("alt") is not None: _TELEM_STATE["alt"] = float(msg_dict.get("alt"))
                    if msg_dict.get("heading") is not None: _TELEM_STATE["yaw"] = float(msg_dict.get("heading")) % 360.0
            except Exception as e:
                logging.getLogger("TEL").debug(f"Telemetri state güncelle hatası: {e}")

            # 1. Mesajı Arayüze İlet (sadece main_window hazırsa)
            if main_window is not None:
                try:
                    main_window.handle_backend_message(msg_dict)
                except Exception as e:
                    logger.error(f"GUI handler (handle_backend_message) hatası: {e}")
            
            # 2. Mesajı WebSocket istemcilerine yayınla
            if websockets is not None:
                asyncio.get_event_loop().create_task(broadcast_ws(msg_dict))

        # Login sonrası ana pencereyi oluşturan fonksiyon
        def _create_main_window():
            nonlocal main_window
            if main_window is not None:
                return
            main_window = MainWindow(loop)
            main_window.show()
            logger.info("Arayüz (gui.py) login sonrası yüklendi.")
            main_window.admin_api = AdminAPI(loop, on_message=lambda m: _on_msg(m))
            logger.info("Admin API proxy eklendi.")

        # Login penceresini aç
        login_window = LoginWindow(on_success=_create_main_window)
        login_window.show()
        logger.info("Login ekranı gösterildi. Giriş bekleniyor...")

        # Global işleyici kaydı
        global _GLOBAL_ON_MESSAGE_HANDLER
        _GLOBAL_ON_MESSAGE_HANDLER = _on_msg

        # Sunucu otomatik giriş (.env) login öncesi başlayabilir
        server_url = os.getenv("IHA_SERVER_URL")
        server_user = os.getenv("IHA_SERVER_USER")
        server_pass = os.getenv("IHA_SERVER_PASS")
        if server_user and server_pass and server_url:
            login_task = loop.create_task(server_login(server_url, server_user, server_pass, on_message=_on_msg))
            app.aboutToQuit.connect(login_task.cancel)
        else:
            logger.error("Sunucu girişi atlandı: .env IHA_SERVER_URL/USER/PASS eksik.")
            _on_msg({"_type": MsgType.SERVER_LOGIN_ERROR, "error": ".env eksik veya hatalı."})

        # Arka plan görevleri (MainWindow henüz yoksa GUI iletimi atlanır)
        mav_task = loop.create_task(mavlink_listener('udp:127.0.0.1:14555', on_message=_on_msg))
        app.aboutToQuit.connect(mav_task.cancel)
        tel_task = loop.create_task(telemetry_sender(on_message=_on_msg, interval=0.5))
        app.aboutToQuit.connect(tel_task.cancel)
        status_task = loop.create_task(status_publisher(on_message=_on_msg, interval=1.0))
        pose_task = loop.create_task(self_pose_publisher(on_message=_on_msg, interval=1.0))
        app.aboutToQuit.connect(status_task.cancel)
        app.aboutToQuit.connect(pose_task.cancel)
        time_task = loop.create_task(poll_server_data("/api/sunucusaati", MsgType.SERVER_TIME, _on_msg, interval=2.0, require_login=False))
        hss_task = loop.create_task(poll_server_data("/api/hss_koordinatlari", MsgType.SERVER_HSS, _on_msg, interval=3.0, require_login=True))
        qr_task = loop.create_task(poll_server_data("/api/qr_koordinati", MsgType.SERVER_QR, _on_msg, interval=5.0, require_login=True))
        app.aboutToQuit.connect(time_task.cancel)
        app.aboutToQuit.connect(hss_task.cancel)
        app.aboutToQuit.connect(qr_task.cancel)
        global _AUTH_RELOGIN_EVENT
        _AUTH_RELOGIN_EVENT = asyncio.Event()
        auth_task = loop.create_task(auth_watcher(on_message=_on_msg))
        app.aboutToQuit.connect(auth_task.cancel)
        loop.create_task(start_ws_server("localhost", 8766))
        app.aboutToQuit.connect(lambda: asyncio.get_event_loop().create_task(shutdown_ws_server()))
        # --- Ana Döngüyü Başlat ---
        logger.info("Tüm servisler başlatıldı. Ana event loop çalışıyor...")
        with loop:
            loop.run_forever()
        
        return 0 # Başarılı çıkış
        
    except Exception as e:
        # Beklenmeyen hatalar için güvenli hata yönetimi
        logger.critical(f"Kritik uygulama hatasi: {e}", exc_info=True)
        return 1  # Hata kodu


if __name__ == "__main__":
    # Program başlangıç noktası
    exit_code = main()
    sys.exit(exit_code)