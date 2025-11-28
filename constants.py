# -*- coding: utf-8 -*-
"""
Kontrol Paneli için Ortak Sabitler
"""

class MsgType:
    """ 
    main.py (mantık) ve gui.py (arayüz) arasında kullanılan
    mesaj tiplerini tanımlar.
    """
    # Sunucu kimlik/doğrulama
    SERVER_LOGIN_OK = "SERVER_LOGIN_OK"
    SERVER_LOGIN_ERROR = "SERVER_LOGIN_ERROR"
    SERVER_AUTH_REQUIRED = "SERVER_AUTH_REQUIRED"
    
    # Telemetri
    TELEMETRY_ACK = "TELEMETRY_ACK"
    TELEMETRY_ERROR = "TELEMETRY_ERROR"
    
    # Sunucu poller'ları
    SERVER_TIME = "SERVER_TIME"
    SERVER_HSS = "SERVER_HSS"
    SERVER_QR = "SERVER_QR"
    
    # Admin
    ADMIN_HSS_OK = "ADMIN_HSS_OK"
    ADMIN_QR_OK = "ADMIN_QR_OK"
    ADMIN_STATS = "ADMIN_STATS"
    ADMIN_CLEAR_OK = "ADMIN_CLEAR_OK"
    ADMIN_ERROR = "ADMIN_ERROR"
    
    # Görsel/katman ve durum
    SELF_POSE = "SELF_POSE"
    WS_CLIENTS = "WS_CLIENTS"
    STATUS_UPDATE = "STATUS_UPDATE"
    TEAMS_UPDATE = "TEAMS_UPDATE"