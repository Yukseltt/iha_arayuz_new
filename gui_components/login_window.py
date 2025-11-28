from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QMessageBox, 
                             QFrame, QCheckBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import asyncio
import os


class LoginWindow(QMainWindow):
    def __init__(self, on_success=None):
        super().__init__()
        self.on_success = on_success  # Başarılı giriş callback
        self.window_settings()

    def window_settings(self):
        background_color = "#3498db"    
        self.setGeometry(100, 100, 1000, 700)   # Pencere boyutu ve konumu
        self.setWindowTitle('Simurg İHA Kullanıcı Giriş Paneli')    # Pencere başlığı

        self.setStyleSheet(f"background-color: {background_color}; color: white;")  # Arka plan ve metin rengi ayarları
        self.login_form()  # Login formunu oluştur

        self.show() # Pencereyi ekranda göster
        
        
    def login_form(self):
        # Ana widget ve layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Login formu için frame (kutu)
        login_frame = QFrame()
        login_frame.setFixedSize(500, 500)
        login_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 0.9);
                border-radius: 15px;
                padding: 20px;
            }
        """)
        
        # Frame'i merkeze almak için layout
        main_layout.addStretch()
        frame_layout = QHBoxLayout()
        frame_layout.addStretch()
        frame_layout.addWidget(login_frame)
        frame_layout.addStretch()
        main_layout.addLayout(frame_layout)
        main_layout.addStretch()
        
        # Login formu içeriği
        form_layout = QVBoxLayout()
        login_frame.setLayout(form_layout)
        
        # Başlık
        baslik = QLabel("Kullanıcı Girişi")
        baslik.setAlignment(Qt.AlignCenter)
        baslik.setFont(QFont("Arial", 18, QFont.Bold))
        baslik.setStyleSheet("color: #2c3e50; margin-bottom: 20px; background-color: transparent;")
        form_layout.addWidget(baslik)
        

        # Kullanıcı adı alanı
        self.kullanici_adi = QLineEdit()
        self.kullanici_adi.setPlaceholderText("Kullanıcı adınızı giriniz")
        self.kullanici_adi.setFont(QFont("Arial", 12))
        self.kullanici_adi.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 3px solid #bdc3c7;
                border-radius: 5px;
                background-color: white;
                color: black;
                margin-bottom: 15px;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
        """)
        form_layout.addWidget(self.kullanici_adi)
        
        # Şifre alanı
        self.sifre = QLineEdit()
        self.sifre.setPlaceholderText("Şifrenizi giriniz")
        self.sifre.setFont(QFont("Arial", 12))
        self.sifre.setEchoMode(QLineEdit.Password)  # Şifreyi gizle
        self.sifre.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 3px solid #bdc3c7;
                border-radius: 5px;
                background-color: white;
                color: black;
                margin-bottom: 15px;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
        """)
        form_layout.addWidget(self.sifre)
        
        # Şifreyi göster/gizle checkbox
        self.sifre_goster = QCheckBox("Şifreyi göster")
        self.sifre_goster.setFont(QFont("Arial", 10))
        self.sifre_goster.setStyleSheet(" margin-bottom: 15px; color: black ;background-color: transparent;")
        self.sifre_goster.stateChanged.connect(self.sifre_gorunurluk_degistir)
        form_layout.addWidget(self.sifre_goster)
        
        # Giriş butonu
        giris_button = QPushButton("Giriş Yap")
        giris_button.setFont(QFont("Arial", 12, QFont.Bold))
        giris_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 5px;
                margin-bottom: 10px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
        giris_button.clicked.connect(self.giris_kontrol)
        form_layout.addWidget(giris_button)
        
        # Temizle butonu
        temizle_button = QPushButton("Temizle")
        temizle_button.setFont(QFont("Arial", 10))
        temizle_button.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #7f8c8d;
            }
        """)
        temizle_button.clicked.connect(self.alanlari_temizle)
        form_layout.addWidget(temizle_button)
        
        # Enter tuşu ile giriş
        self.kullanici_adi.returnPressed.connect(self.giris_kontrol)
        self.sifre.returnPressed.connect(self.giris_kontrol)
    
    def sifre_gorunurluk_degistir(self):
        """Şifre görünürlüğünü değiştirir"""
        if self.sifre_goster.isChecked():
            self.sifre.setEchoMode(QLineEdit.Normal)
        else:
            self.sifre.setEchoMode(QLineEdit.Password)
    
    def giris_kontrol(self):
        """Login bilgilerini kontrol eder"""
        kullanici = self.kullanici_adi.text().strip()
        sifre = self.sifre.text().strip()
        
        # Boş alan kontrolü
        if not kullanici or not sifre:
            QMessageBox.warning(self, "Uyarı", "Lütfen tüm alanları doldurunuz!")
            return
        
        # Env kullanıcı adı/şifre doğrulaması
        env_user = os.getenv("IHA_SERVER_USER")
        env_pass = os.getenv("IHA_SERVER_PASS")
        if kullanici == env_user and sifre == env_pass:
            QMessageBox.information(self, "Başarılı", f"Hoş geldiniz, {kullanici}!")
            self.giris_basarili()
        else:
            QMessageBox.critical(self, "Hata", "Kullanıcı adı veya şifre yanlış!")
            self.sifre.clear()  # Şifre alanını temizle
            self.sifre.setFocus()  # Şifre alanına odaklan
    
    def giris_basarili(self):
        """Giriş başarılıysa ana pencereyi dış callback ile açar"""
        if callable(self.on_success):
            self.on_success()
        self.hide()
    
    def alanlari_temizle(self):
        """Tüm alanları temizler"""
        self.kullanici_adi.clear()
        self.sifre.clear()
        self.sifre_goster.setChecked(False)
        self.kullanici_adi.setFocus()