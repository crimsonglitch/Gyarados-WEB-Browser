import os
import sys
import json
import logging
import importlib.util
import base64
import re
import platform
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from logging.handlers import RotatingFileHandler
from googletrans import Translator, LANGUAGES
import openai

from PyQt5.QtCore import (QUrl, QSize, Qt, QSettings, QFile, QTextStream, 
                          QStandardPaths, QTimer, QObject, pyqtSignal)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QToolButton, QTabWidget, 
                            QMenu, QAction, QMessageBox, QInputDialog, 
                            QFileDialog, QLabel, QDialog, QListWidget, 
                            QListWidgetItem, QPushButton, QDialogButtonBox,
                            QTableWidget, QTableWidgetItem, QCheckBox,
                            QComboBox, QGroupBox, QSlider, QTextEdit, QScrollArea,
                            QGridLayout, QTabBar)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo
from PyQt5.QtGui import QIcon, QKeySequence, QPalette, QColor, QCursor
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog

# Constants
APP_NAME = "Gyarados Browser"
VERSION = "3.4.0"
DEFAULT_WINDOW_SIZE = QSize(1280, 720)

# Logging Setup
def setup_logging():
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.DEBUG)
    
    file_handler = RotatingFileHandler(
        logs_dir / "gyarados.log",
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

class ErrorHandler:
    ERROR_TYPES = {
        "ui": ("UI Error", "An error occurred in the interface. Please try again."),
        "file": ("File Error", "An error occurred during file operation."),
        "network": ("Network Error", "Could not establish network connection."),
        "general": ("Error", "An unexpected error occurred. Please restart the application."),
        "plugin": ("Plugin Error", "An error occurred in a plugin."),
        "profile": ("Profile Error", "An error occurred with profile operations."),
        "ai": ("AI Error", "An error occurred with AI services."),
        "translation": ("Translation Error", "Could not translate the content.")
    }

    @classmethod
    def handle(cls, error_type: str, error: Exception, show_user: bool = False):
        error_title, error_msg = cls.ERROR_TYPES.get(error_type, cls.ERROR_TYPES["general"])
        logger.error(f"{error_type.upper()} - {str(error)}", exc_info=True)
        if show_user:
            QMessageBox.warning(None, error_title, error_msg)

@dataclass
class Config:
    HOME_PAGE: str = "https://duckduckgo.com"
    SEARCH_ENGINES: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        "DuckDuckGo": {
            "url": "https://duckduckgo.com/?q={}&kl={lang}",
            "lang_param": True
        },
        "Google": {
            "url": "https://www.google.com/search?q={}&hl={lang}",
            "lang_param": True
        },
        "Bing": {
            "url": "https://www.bing.com/search?q={}&setlang={lang}",
            "lang_param": True
        },
        "Yandex": {
            "url": "https://yandex.com/search/?text={}&lang={lang}",
            "lang_param": True
        },
        "Baidu": {
            "url": "https://www.baidu.com/s?wd={}",
            "lang_param": False
        },
        "Naver": {
            "url": "https://search.naver.com/search.naver?query={}",
            "lang_param": False
        },
        "Ecosia": {
            "url": "https://www.ecosia.org/search?q={}",
            "lang_param": False
        },
        "Brave": {
            "url": "https://search.brave.com/search?q={}",
            "lang_param": False
        },
        "Firefox": {
            "url": "https://www.mozilla.org/en-US/firefox/new/?q={}",
            "lang_param": False
        },
        "Yahoo": {
            "url": "https://search.yahoo.com/search?p={}",
            "lang_param": False
        }
    })
    DEFAULT_SEARCH_ENGINE: str = "DuckDuckGo"
    SUPPORTED_LANGUAGES: Dict[str, str] = field(default_factory=lambda: {
        "en": "English", "es": "Español", "fr": "Français", "de": "Deutsch",
        "it": "Italiano", "pt": "Português", "ru": "Русский", "zh": "中文",
        "ja": "日本語", "ko": "한국어", "ar": "العربية", "hi": "हिन्दी",
        "tr": "Türkçe", "fa": "فارسی", "ur": "اردو", "vi": "Tiếng Việt",
        "th": "ไทย", "nl": "Nederlands", "pl": "Polski", "uk": "Українська",
        "el": "Ελληνικά", "he": "עברית", "sv": "Svenska", "fi": "Suomi",
        "da": "Dansk", "no": "Norsk", "hu": "Magyar", "cs": "Čeština",
        "ro": "Română", "id": "Bahasa Indonesia", "ms": "Bahasa Melayu",
        "bn": "বাংলা", "ta": "தமிழ்", "te": "తెలుగు", "mr": "मराठी",
        "gu": "ગુજરાતી", "kn": "ಕನ್ನಡ", "ml": "മലയാളം", "pa": "ਪੰਜਾਬੀ"
    })
    CURRENT_LANGUAGE: str = "en"
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    WINDOW_SIZE: QSize = DEFAULT_WINDOW_SIZE
    PRIVATE_MODE: bool = False
    ADBLOCK_ENABLED: bool = True
    ADBLOCK_LISTS: List[str] = field(default_factory=lambda: [
        "https://easylist.to/easylist/easylist.txt",
        "https://easylist.to/easylist/easyprivacy.txt",
        "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=0&mimetype=plaintext"
    ])
    COOKIES_ENABLED: bool = True
    JAVASCRIPT_ENABLED: bool = True
    WEBGL_ENABLED: bool = False
    SAVE_SESSION: bool = True
    DARK_THEME: bool = False
    BOOKMARKS: List[Dict[str, str]] = field(default_factory=list)
    CURRENT_PROFILE: str = "default"
    PROFILES: List[str] = field(default_factory=lambda: ["default"])
    PROFILE_ENCRYPTED: bool = False
    AUTO_SWITCH_PROFILES: Dict[str, str] = field(default_factory=dict)
    OPENAI_API_KEY: Optional[str] = None
    BACKGROUND_IMAGE: Optional[str] = None
    BACKGROUND_OPACITY: float = 0.5
    CUSTOM_CSS: str = ""
    TRANSLATE_TARGET_LANG: str = "en"
    PINNED_TABS: List[Dict[str, str]] = field(default_factory=list)
    APPS: List[Dict[str, str]] = field(default_factory=lambda: [
        {"name": "Gmail", "url": "https://mail.google.com", "icon": "mail"},
        {"name": "YouTube", "url": "https://youtube.com", "icon": "video"},
        {"name": "GitHub", "url": "https://github.com", "icon": "code"}
    ])

    @classmethod
    def load(cls, profile_name="default"):
        profile_dir = Path(f"profiles/{profile_name}")
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        meta_file = profile_dir / "profile.meta"
        if meta_file.exists() and meta_file.read_bytes().startswith(b"ENCRYPTED:"):
            password, ok = QInputDialog.getText(
                None,
                "Profile Password",
                f"Enter password for '{profile_name}':",
                echo=QLineEdit.Password
            )
            if ok and password:
                return cls.load_encrypted_profile(profile_name, password)
            return None
        
        settings = QSettings(APP_NAME, f"Browser/{profile_name}")
        config = cls()
        
        for field in cls.__dataclass_fields__:
            if settings.contains(field):
                value = settings.value(field)
                if field == "WINDOW_SIZE":
                    value = QSize(value)
                setattr(config, field, value)
        
        config.CURRENT_PROFILE = profile_name
        config.load_bookmarks(profile_name)
        config.load_pinned_tabs(profile_name)
        config.load_apps(profile_name)
        return config

    def save(self):
        if self.PROFILE_ENCRYPTED:
            return
            
        profile_dir = Path(f"profiles/{self.CURRENT_PROFILE}")
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        settings = QSettings(APP_NAME, f"Browser/{self.CURRENT_PROFILE}")
        for field in self.__dataclass_fields__:
            value = getattr(self, field)
            if isinstance(value, QSize):
                value = [value.width(), value.height()]
            settings.setValue(field, value)
        
        self.save_bookmarks(self.CURRENT_PROFILE)
        self.save_pinned_tabs(self.CURRENT_PROFILE)
        self.save_apps(self.CURRENT_PROFILE)

    @classmethod
    def create_encrypted_profile(cls, profile_name, password, config_data=None):
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        
        if config_data is None:
            config_data = {f: getattr(cls(), f) for f in cls.__dataclass_fields__}
            config_data["CURRENT_PROFILE"] = profile_name
        
        cipher = Fernet(key)
        encrypted = cipher.encrypt(json.dumps(config_data).encode())
        
        profile_dir = Path(f"profiles/{profile_name}")
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        with open(profile_dir / "profile.meta", "wb") as f:
            f.write(b"ENCRYPTED:" + salt)
        
        with open(profile_dir / "config.enc", "wb") as f:
            f.write(encrypted)

    @classmethod
    def load_encrypted_profile(cls, profile_name, password):
        profile_dir = Path(f"profiles/{profile_name}")
        
        try:
            with open(profile_dir / "profile.meta", "rb") as f:
                data = f.read()
                if not data.startswith(b"ENCRYPTED:"):
                    raise ValueError("Not an encrypted profile")
                salt = data[10:]
                
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            
            with open(profile_dir / "config.enc", "rb") as f:
                cipher = Fernet(key)
                decrypted = cipher.decrypt(f.read())
                config_data = json.loads(decrypted.decode())
                
            config = cls()
            for k, v in config_data.items():
                setattr(config, k, v)
                
            return config
            
        except InvalidToken:
            ErrorHandler.handle("profile", Exception("Invalid password"), show_user=True)
            return None
        except Exception as e:
            ErrorHandler.handle("profile", e, show_user=True)
            return None

    def load_bookmarks(self, profile_name):
        try:
            bookmarks_file = Path(f"profiles/{profile_name}/bookmarks.json")
            if bookmarks_file.exists():
                with open(bookmarks_file, 'r', encoding='utf-8') as f:
                    self.BOOKMARKS = json.load(f)
        except Exception as e:
            ErrorHandler.handle("file", e)
            self.BOOKMARKS = []

    def save_bookmarks(self, profile_name):
        try:
            profile_dir = Path(f"profiles/{profile_name}")
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            temp_file = profile_dir / "bookmarks_temp.json"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.BOOKMARKS, f, ensure_ascii=False, indent=2)
            
            bookmarks_file = profile_dir / "bookmarks.json"
            if bookmarks_file.exists():
                bookmarks_file.unlink()
            temp_file.rename(bookmarks_file)
        except Exception as e:
            ErrorHandler.handle("file", e)

    def delete_bookmarks(self, indices):
        """Delete specific bookmarks by their indices"""
        try:
            # Delete in reverse order to avoid index issues
            for index in sorted(indices, reverse=True):
                if 0 <= index < len(self.BOOKMARKS):
                    self.BOOKMARKS.pop(index)
            self.save_bookmarks(self.CURRENT_PROFILE)
            return True
        except Exception as e:
            ErrorHandler.handle("file", e)
            return False

    def clear_bookmarks(self):
        """Completely clear bookmarks"""
        try:
            self.BOOKMARKS = []
            self.save_bookmarks(self.CURRENT_PROFILE)
            return True
        except Exception as e:
            ErrorHandler.handle("file", e)
            return False

    def load_history(self, profile_name):
        """Load history from JSON file with error handling"""
        history_file = Path(f"profiles/{profile_name}/history.json")
        try:
            if history_file.exists():
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception as e:
            ErrorHandler.handle("file", e)
            return []

    def save_history(self, profile_name, history_data=None):
        """Save history to JSON file with atomic write"""
        try:
            profile_dir = Path(f"profiles/{profile_name}")
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            history_file = profile_dir / "history.json"
            temp_file = profile_dir / "history_temp.json"
            
            history = history_data if history_data else self.load_history(profile_name)
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            if history_file.exists():
                history_file.unlink()
            temp_file.rename(history_file)
        except Exception as e:
            ErrorHandler.handle("file", e)

    def clear_history(self, profile_name):
        """Completely clear history"""
        try:
            self.save_history(profile_name, [])
            return True
        except Exception as e:
            ErrorHandler.handle("file", e)
            return False

    def delete_history_items(self, profile_name, indices):
        """Delete specific history items by their indices"""
        try:
            history = self.load_history(profile_name)
            # Delete in reverse order to avoid index issues
            for index in sorted(indices, reverse=True):
                if 0 <= index < len(history):
                    history.pop(index)
            self.save_history(profile_name, history)
            return True
        except Exception as e:
            ErrorHandler.handle("file", e)
            return False

    def load_pinned_tabs(self, profile_name):
        try:
            pinned_file = Path(f"profiles/{profile_name}/pinned_tabs.json")
            if pinned_file.exists():
                with open(pinned_file, 'r', encoding='utf-8') as f:
                    self.PINNED_TABS = json.load(f)
        except Exception as e:
            ErrorHandler.handle("file", e)
            self.PINNED_TABS = []

    def save_pinned_tabs(self, profile_name):
        try:
            profile_dir = Path(f"profiles/{profile_name}")
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            pinned_file = profile_dir / "pinned_tabs.json"
            temp_file = profile_dir / "pinned_tabs_temp.json"
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.PINNED_TABS, f, ensure_ascii=False, indent=2)
            
            if pinned_file.exists():
                pinned_file.unlink()
            temp_file.rename(pinned_file)
        except Exception as e:
            ErrorHandler.handle("file", e)

    def load_apps(self, profile_name):
        try:
            apps_file = Path(f"profiles/{profile_name}/apps.json")
            if apps_file.exists():
                with open(apps_file, 'r', encoding='utf-8') as f:
                    self.APPS = json.load(f)
        except Exception as e:
            ErrorHandler.handle("file", e)
            self.APPS = [
                {"name": "Gmail", "url": "https://mail.google.com", "icon": "mail"},
                {"name": "YouTube", "url": "https://youtube.com", "icon": "video"},
                {"name": "GitHub", "url": "https://github.com", "icon": "code"}
            ]

    def save_apps(self, profile_name):
        try:
            profile_dir = Path(f"profiles/{profile_name}")
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            apps_file = profile_dir / "apps.json"
            temp_file = profile_dir / "apps_temp.json"
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.APPS, f, ensure_ascii=False, indent=2)
            
            if apps_file.exists():
                apps_file.unlink()
            temp_file.rename(apps_file)
        except Exception as e:
            ErrorHandler.handle("file", e)

    def get_available_profiles(self):
        profiles_dir = Path("profiles")
        profiles_dir.mkdir(exist_ok=True)
        
        profiles = ["default"]
        
        for item in profiles_dir.iterdir():
            if item.is_dir() and item.name != "default":
                profiles.append(item.name)
        
        return sorted(profiles)

    def switch_profile(self, profile_name):
        if profile_name == self.CURRENT_PROFILE:
            return
        
        self.save()
        return self.load(profile_name)

class DesktopShortcut:
    @staticmethod
    def create(app_name, exec_path, icon_path=None):
        if platform.system() == "Windows":
            try:
                import winshell
                desktop = winshell.desktop()
                shortcut_path = os.path.join(desktop, f"{app_name}.lnk")
                with winshell.shortcut(shortcut_path) as shortcut:
                    shortcut.path = exec_path
                    shortcut.description = app_name
                    if icon_path:
                        shortcut.icon_location = (icon_path, 0)
                return True
            except Exception as e:
                ErrorHandler.handle("file", e)
                return False
                
        elif platform.system() == "Linux":
            desktop_file = f"""
            [Desktop Entry]
            Version=1.0
            Type=Application
            Name={app_name}
            Exec={exec_path}
            Icon={icon_path if icon_path else 'web-browser'}
            Terminal=false
            """
            
            desktop_path = Path.home() / "Desktop" / f"{app_name}.desktop"
            try:
                with open(desktop_path, 'w') as f:
                    f.write(desktop_file)
                os.chmod(desktop_path, 0o755)
                return True
            except Exception as e:
                ErrorHandler.handle("file", e)
                return False
                
        return False

class AdBlocker(QWebEngineUrlRequestInterceptor):
    def __init__(self, rules=None):
        super().__init__()
        self.rules = rules or []
        self.load_rules()

    def load_rules(self):
        self.blocked_domains = set()
        for rule in self.rules:
            if rule.startswith('http'):
                self.blocked_domains.add(QUrl(rule).host())
            else:
                self.blocked_domains.add(rule)

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        url = info.requestUrl().toString().lower()
        domain = info.requestUrl().host()
        
        # Block ads based on URL patterns
        if any(ad_pattern in url for ad_pattern in ['/ad.', 'ads.', 'banner', 'doubleclick', 'track', 'analytics']):
            info.block(True)
            return
            
        # Block domains from the block lists
        if domain in self.blocked_domains:
            info.block(True)
            return

class PDFExporter:
    @staticmethod
    def export_to_pdf(browser, parent=None):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setPageSize(QPrinter.A4)
        
        file_path, _ = QFileDialog.getSaveFileName(
            parent,
            "Export as PDF",
            str(Path.home() / "webpage.pdf"),
            "PDF Files (*.pdf)"
        )
        
        if not file_path:
            return
            
        printer.setOutputFileName(file_path)
        
        print_dialog = QPrintDialog(printer, parent)
        if print_dialog.exec_() == QPrintDialog.Accepted:
            # Use printToPdf for better quality
            def handle_pdf_print(finished):
                if finished:
                    QMessageBox.information(parent, "Success", f"PDF saved to:\n{file_path}")
                else:
                    QMessageBox.warning(parent, "Error", "Failed to save PDF")
            
            browser.page().printToPdf(file_path, QPrinter.HighResolution)
            QTimer.singleShot(1000, lambda: handle_pdf_print(Path(file_path).exists()))

class LanguageManager:
    def __init__(self, config):
        self.config = config
        self.translations = {}
        self.load_translations()
    
    def load_translations(self):
        lang_dir = Path("locales")
        lang_dir.mkdir(exist_ok=True)
        
        # Create default English translations if not exists
        default_locale = lang_dir / "en.json"
        if not default_locale.exists():
            with open(default_locale, 'w', encoding='utf-8') as f:
                json.dump({
                    "New Tab": "New Tab",
                    "Private Tab": "Private Tab",
                    "Bookmarks": "Bookmarks",
                    "History": "History",
                    "Settings": "Settings"
                }, f, ensure_ascii=False, indent=2)
        
        for lang_file in lang_dir.glob("*.json"):
            with open(lang_file, 'r', encoding='utf-8') as f:
                self.translations[lang_file.stem] = json.load(f)
    
    def tr(self, text):
        return self.translations.get(self.config.CURRENT_LANGUAGE, {}).get(text, text)
    
    def set_language(self, lang_code):
        if lang_code in self.config.SUPPORTED_LANGUAGES:
            self.config.CURRENT_LANGUAGE = lang_code
            return True
        return False

class TranslatePlugin(QObject):
    translation_complete = pyqtSignal(str)
    
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.translator = Translator(service_urls=[
            'translate.google.com',
            'translate.google.co.kr',
            'translate.google.de'
        ])
        self.target_lang = self.browser.config.TRANSLATE_TARGET_LANG
        self.setup_ui()
    
    def setup_ui(self):
        self.translate_action = QAction("Translate Page", self.browser)
        self.translate_action.setShortcut("Ctrl+Shift+T")
        self.translate_action.triggered.connect(self.translate_page)
        self.browser.addAction(self.translate_action)
        
        self.language_menu = QMenu("Translation Language", self.browser)
        
        # Add all supported languages
        for code, name in LANGUAGES.items():
            action = self.language_menu.addAction(f"{name} ({code})")
            action.setData(code)
            action.triggered.connect(lambda _, c=code: self.set_target_language(c))
        
        self.translate_action.setMenu(self.language_menu)
    
    def set_target_language(self, lang_code):
        self.target_lang = lang_code
        self.browser.config.TRANSLATE_TARGET_LANG = lang_code
        self.browser.config.save()
    
    def translate_page(self):
        current_tab = self.browser.current_tab()
        if current_tab:
            current_tab.browser.page().toPlainText(self.handle_page_text)
    
    def handle_page_text(self, text):
        try:
            # Split large text into chunks
            max_chunk_size = 5000
            chunks = [text[i:i+max_chunk_size] for i in range(0, len(text), max_chunk_size)]
            translated_text = ""
            
            for chunk in chunks:
                translated = self.translator.translate(chunk, dest=self.target_lang)
                translated_text += translated.text + "\n\n"
            
            self.show_translation(text, translated_text)
        except Exception as e:
            ErrorHandler.handle("translation", e, show_user=True)
    
    def show_translation(self, original, translated):
        tab = self.browser.new_tab()
        html = f"""
        <html>
            <head>
                <title>Translation Result</title>
                <style>
                    body {{ 
                        font-family: Arial; 
                        margin: 0;
                        padding: 0;
                        display: flex;
                        height: 100vh;
                    }}
                    .column {{
                        flex: 1;
                        padding: 20px;
                        overflow-y: auto;
                        height: 100%;
                        box-sizing: border-box;
                    }}
                    .original {{
                        background-color: #f5f5f5;
                        border-right: 1px solid #ddd;
                    }}
                    h2 {{
                        color: #2a82da;
                        margin-top: 0;
                    }}
                    @media (max-width: 768px) {{
                        body {{ flex-direction: column; height: auto; }}
                        .column {{ flex: none; height: 50vh; }}
                    }}
                </style>
            </head>
            <body>
                <div class="column original">
                    <h2>Original Text</h2>
                    <div>{original[:2000]}{'...' if len(original) > 2000 else ''}</div>
                </div>
                <div class="column">
                    <h2>Translation ({LANGUAGES.get(self.target_lang, self.target_lang)})</h2>
                    <div>{translated}</div>
                </div>
            </body>
        </html>
        """
        tab.browser.setHtml(html)

class AISummaryPlugin(QObject):
    summary_ready = pyqtSignal(str)
    
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.api_key = browser.config.OPENAI_API_KEY
        self.setup_ui()
    
    def setup_ui(self):
        self.summary_action = QAction("Summarize Content", self.browser)
        self.summary_action.setShortcut("Ctrl+Shift+S")
        self.summary_action.triggered.connect(self.summarize_page)
        self.browser.addAction(self.summary_action)
        
        self.settings_action = QAction("AI Settings", self.browser)
        self.settings_action.triggered.connect(self.configure_api)
        self.browser.addAction(self.settings_action)
    
    def configure_api(self):
        key, ok = QInputDialog.getText(
            self.browser,
            "OpenAI API Key",
            "Enter your API key:",
            text=self.api_key or ""
        )
        if ok:
            self.api_key = key
            self.browser.config.OPENAI_API_KEY = key
            self.browser.config.save()
    
    def summarize_page(self):
        if not self.api_key:
            self.configure_api()
            if not self.api_key:
                return
        
        self.browser.current_tab().browser.page().toPlainText(self.handle_page_text)
    
    def handle_page_text(self, text):
        try:
            openai.api_key = self.api_key
            
            # Clean and prepare text
            clean_text = self.clean_text(text[:6000])  # Limit to token budget
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Summarize this content concisely in 3-5 bullet points in the same language as the content."},
                    {"role": "user", "content": clean_text}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            summary = response.choices[0].message.content
            self.show_summary(summary)
        except openai.error.AuthenticationError:
            ErrorHandler.handle("ai", Exception("Invalid API key"), show_user=True)
            self.configure_api()
        except Exception as e:
            ErrorHandler.handle("ai", e, show_user=True)
    
    def clean_text(self, text):
        # Remove excessive whitespace and noise
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove common webpage noise
        noise_phrases = ["cookie policy", "privacy policy", "terms of service", 
                        "click here", "read more", "sign up", "log in"]
        for phrase in noise_phrases:
            text = text.replace(phrase, "")
        return text
    
    def show_summary(self, summary):
        tab = self.browser.new_tab()
        html = f"""
        <html>
            <head>
                <title>AI Content Summary</title>
                <style>
                    body {{
                        font-family: Arial;
                        padding: 20px;
                        line-height: 1.6;
                        max-width: 800px;
                        margin: 0 auto;
                        color: #333;
                    }}
                    h1 {{
                        color: #2a82da;
                        border-bottom: 1px solid #eee;
                        padding-bottom: 10px;
                    }}
                    ul {{
                        padding-left: 20px;
                    }}
                    li {{
                        margin-bottom: 10px;
                    }}
                    .meta {{
                        font-size: 0.9em;
                        color: #666;
                        margin-top: 20px;
                    }}
                </style>
            </head>
            <body>
                <h1>AI Content Summary</h1>
                {summary}
                <div class="meta">
                    <p>Generated by Gyarados Browser using OpenAI</p>
                </div>
            </body>
        </html>
        """
        tab.browser.setHtml(html)

class AppLauncher(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()
        
    def setup_ui(self):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.widget = QWidget()
        self.widget_layout = QGridLayout()
        self.widget.setLayout(self.widget_layout)
        
        self.load_apps()
        self.scroll.setWidget(self.widget)
        self.layout.addWidget(self.scroll)
        
    def load_apps(self):
        self.widget_layout.setSpacing(10)
        self.widget_layout.setContentsMargins(5, 5, 5, 5)
        
        for i, app in enumerate(self.parent.config.APPS):
            btn = QToolButton()
            btn.setText(app["name"])
            btn.setIcon(QIcon.fromTheme(app.get("icon", "web-browser")))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(48, 48))
            btn.clicked.connect(lambda _, u=app["url"]: self.parent.new_tab(u))
            btn.setStyleSheet("""
                QToolButton {
                    padding: 5px;
                    border-radius: 5px;
                }
                QToolButton:hover {
                    background-color: #e0e0e0;
                }
            """)
            self.widget_layout.addWidget(btn, i//4, i%4)

class WebTab(QWidget):
    def __init__(self, parent=None, config: Config = None, private_mode=False, custom_title=None, pinned=False):
        super().__init__(parent)
        self.parent_window = parent
        self.config = config or Config()
        self.private_mode = private_mode
        self.custom_title = custom_title
        self.pinned = pinned
        self.reading_mode = False
        self.browser = QWebEngineView()
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.setup_web_engine()
        self.setup_actions()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.setLayout(layout)
        
        if not custom_title and not pinned:
            self.browser.setUrl(QUrl(self.config.HOME_PAGE))
        self.browser.urlChanged.connect(self.on_url_changed)
        self.browser.titleChanged.connect(self.on_title_changed)
        
        if private_mode:
            self.setStyleSheet("background-color: #2d2d2d;")

    def setup_web_engine(self):
        settings = self.browser.settings()
        
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, self.config.JAVASCRIPT_ENABLED)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, self.config.WEBGL_ENABLED)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, False)
        
        settings.setAttribute(QWebEngineSettings.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        
        if self.private_mode:
            profile = QWebEngineProfile("Private_" + str(id(self)), self)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
            profile.setCachePath("")
            page = QWebEnginePage(profile, self)
            self.browser.setPage(page)
        else:
            profile = self.browser.page().profile()
            profile.setHttpUserAgent(self.config.USER_AGENT)
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.AllowPersistentCookies if self.config.COOKIES_ENABLED
                else QWebEngineProfile.NoPersistentCookies
            )
        
        if self.config.ADBLOCK_ENABLED:
            interceptor = AdBlocker(self.config.ADBLOCK_LISTS)
            profile.setUrlRequestInterceptor(interceptor)
        
        # Dark theme favicon adjustment
        if self.config.DARK_THEME:
            js = """
            document.addEventListener('DOMContentLoaded', function() {
                const style = document.createElement('style');
                style.textContent = `
                    img[src*="favicon"], 
                    link[rel*="icon"] {
                        filter: invert(1) hue-rotate(180deg) brightness(1.2) contrast(0.8);
                    }
                `;
                document.head.appendChild(style);
            });
            """
            self.browser.page().runJavaScript(js)

    def setup_actions(self):
        self.reading_mode_action = QAction("Reading Mode", self)
        self.reading_mode_action.setShortcut("Ctrl+Shift+R")
        self.reading_mode_action.triggered.connect(self.toggle_reading_mode)
        self.addAction(self.reading_mode_action)

        self.pin_action = QAction("Pin Tab" if not self.pinned else "Unpin Tab", self)
        self.pin_action.triggered.connect(self.toggle_pinned)
        self.addAction(self.pin_action)

    def toggle_pinned(self):
        self.pinned = not self.pinned
        if self.pinned:
            self.setFixedWidth(150)
            self.browser.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.parent_window.tabs.tabBar().setTabButton(
                self.parent_window.tabs.indexOf(self), 
                QTabBar.LeftSide, 
                None
            )
            self.parent_window.tabs.tabBar().setTabIcon(
                self.parent_window.tabs.indexOf(self), 
                QIcon.fromTheme("pin")
            )
            self.parent_window.tabs.setTabEnabled(self.parent_window.tabs.indexOf(self), False)
        else:
            self.setFixedWidth(QWIDGETSIZE_MAX)
            self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.parent_window.tabs.setTabEnabled(self.parent_window.tabs.indexOf(self), True)
            self.parent_window.tabs.tabBar().setTabIcon(
                self.parent_window.tabs.indexOf(self), 
                QIcon()
            )
        self.parent_window.update_tab_title(self.parent_window.tabs.indexOf(self))

    def toggle_reading_mode(self):
        self.reading_mode = not self.reading_mode
        if self.reading_mode:
            self.enter_reading_mode()
        else:
            self.exit_reading_mode()

    def enter_reading_mode(self):
        js = """
        function getReadingContent() {
            const selectorsToHide = [
                'header', 'footer', 'nav', 'aside', 'iframe', 
                'script', 'form', 'button', 'video', 'audio',
                '.ad', '.popup', '.banner', '.navbar', '.sidebar',
                '.comments', '.social-share', '.newsletter', '.modal',
                '.cookie-consent', '.ad-container', '.recommendations',
                '[role="alert"]', '[role="banner"]', '[role="complementary"]'
            ];
            
            selectorsToHide.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => {
                    el.style.display = 'none';
                });
            });
            
            const content = document.querySelector('article') || 
                          document.querySelector('main') || 
                          document.querySelector('.content') || 
                          document.querySelector('.post-content') || 
                          document.querySelector('.article-body') ||
                          document.querySelector('[itemprop="articleBody"]') ||
                          document.body;
            
            const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const bgColor = isDark ? '#1e1e1e' : '#f9f9f9';
            const textColor = isDark ? '#e0e0e0' : '#333333';
            
            content.style.maxWidth = '800px';
            content.style.margin = '0 auto';
            content.style.padding = '20px';
            content.style.fontFamily = 'sans-serif';
            content.style.lineHeight = '1.6';
            content.style.fontSize = '18px';
            content.style.backgroundColor = bgColor;
            content.style.color = textColor;
            
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.position === 'fixed' || style.position === 'sticky') {
                    el.style.display = 'none';
                }
            });
            
            document.querySelectorAll('*').forEach(el => {
                if (el.children.length === 0 && el.textContent.trim() === '') {
                    el.style.display = 'none';
                }
            });
            
            return content.outerHTML;
        }
        getReadingContent();
        """
        
        def process_content(content):
            new_tab = self.parent_window.new_tab(private_mode=self.private_mode)
            new_tab.browser.setHtml(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Reading Mode: {self.browser.title()}</title>
                    <style>
                        body {{ 
                            margin: 0; 
                            padding: 0; 
                            background-color: {'#1e1e1e' if self.config.DARK_THEME else '#f9f9f9'};
                            color: {'#e0e0e0' if self.config.DARK_THEME else '#333333'};
                        }}
                        #reader-content {{ 
                            width: 100%; 
                            height: 100%; 
                            padding: 20px; 
                            box-sizing: border-box;
                            max-width: 800px;
                            margin: 0 auto;
                            line-height: 1.6;
                            font-size: 18px;
                        }}
                        img {{ max-width: 100%; height: auto; }}
                    </style>
                </head>
                <body>
                    <div id="reader-content">{content}</div>
                </body>
                </html>
            """)
            
            if self.parent_window.tabs.count() > 1:
                QTimer.singleShot(0, lambda: self.parent_window.close_tab(
                    self.parent_window.tabs.indexOf(self)
                ))
        
        self.browser.page().runJavaScript(js, process_content)

    def exit_reading_mode(self):
        self.browser.reload()

    def on_url_changed(self, url):
        if hasattr(self.parent_window, 'update_url_bar'):
            self.parent_window.update_url_bar(url.toString())
            
        if not self.private_mode and self.parent_window:
            self.parent_window.add_to_history(url.toString(), self.browser.title())

    def on_title_changed(self, title):
        if not self.private_mode and self.parent_window:
            self.parent_window.add_to_history(self.browser.url().toString(), title)

    def get_display_title(self):
        return self.custom_title if self.custom_title else self.browser.title()

    def contextMenuEvent(self, event):
        menu = QMenu()
        
        pin_action = QAction("Pin Tab" if not self.pinned else "Unpin Tab", self)
        pin_action.triggered.connect(self.toggle_pinned)
        menu.addAction(pin_action)
        
        reading_action = QAction("Reading Mode", self)
        reading_action.triggered.connect(self.toggle_reading_mode)
        menu.addAction(reading_action)
        
        menu.addSeparator()
        
        back_action = QAction("Back", self)
        back_action.setShortcut("Alt+Left")
        back_action.triggered.connect(self.parent_window.nav_bar.navigate_back)
        menu.addAction(back_action)
        
        forward_action = QAction("Forward", self)
        forward_action.setShortcut("Alt+Right")
        forward_action.triggered.connect(self.parent_window.nav_bar.navigate_forward)
        menu.addAction(forward_action)
        
        reload_action = QAction("Reload", self)
        reload_action.setShortcut("F5")
        reload_action.triggered.connect(self.parent_window.nav_bar.reload_page)
        menu.addAction(reload_action)
        
        menu.exec_(event.globalPos())

class NavigationBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setup_ui()

    def setup_ui(self):
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(5)
        
        self.back_btn = self.create_tool_btn("go-previous", self.navigate_back)
        self.forward_btn = self.create_tool_btn("go-next", self.navigate_forward)
        self.reload_btn = self.create_tool_btn("view-refresh", self.reload_page)
        self.home_btn = self.create_tool_btn("go-home", self.go_home)
        
        self.bookmark_btn = self.create_tool_btn("bookmark-new", self.toggle_bookmark)
        self.bookmark_btn.setCheckable(True)
        self.bookmarks_menu = QMenu()
        self.bookmark_btn.setMenu(self.bookmarks_menu)
        self.bookmark_btn.setPopupMode(QToolButton.InstantPopup)
        
        self.theme_btn = self.create_tool_btn("color-management", self.toggle_theme)
        
        self.private_btn = self.create_tool_btn("security-high", self.new_private_tab)
        self.private_btn.setToolTip("New Private Tab (Ctrl+Shift+N)")
        
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Search or enter URL")
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        
        self.search_btn = self.create_tool_btn("system-search", self.navigate_to_url)
        
        self.pdf_btn = self.create_tool_btn("document-export", self.export_pdf)
        self.pdf_btn.setToolTip("Export to PDF")
        
        self.history_btn = self.create_tool_btn("view-history", self.show_history_manager)
        self.history_btn.setToolTip("History Manager")
        
        self.apps_btn = self.create_tool_btn("applications-other", self.show_app_launcher)
        self.apps_btn.setToolTip("Quick Apps")
        
        self.layout.addWidget(self.back_btn)
        self.layout.addWidget(self.forward_btn)
        self.layout.addWidget(self.reload_btn)
        self.layout.addWidget(self.home_btn)
        self.layout.addWidget(self.bookmark_btn)
        self.layout.addWidget(self.theme_btn)
        self.layout.addWidget(self.private_btn)
        self.layout.addWidget(self.url_bar, 1)
        self.layout.addWidget(self.search_btn)
        self.layout.addWidget(self.pdf_btn)
        self.layout.addWidget(self.history_btn)
        self.layout.addWidget(self.apps_btn)
        
        self.setLayout(self.layout)
        self.update_bookmarks_menu()

    def create_tool_btn(self, icon_name, callback):
        btn = QToolButton()
        btn.setIcon(QIcon.fromTheme(icon_name))
        btn.clicked.connect(callback)
        btn.setStyleSheet("""
            QToolButton {
                padding: 3px;
                border-radius: 3px;
            }
            QToolButton:hover {
                background-color: #e0e0e0;
            }
        """)
        return btn

    def navigate_back(self):
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.back()

    def navigate_forward(self):
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.forward()

    def reload_page(self):
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.reload()

    def go_home(self):
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.setUrl(QUrl(self.parent_window.config.HOME_PAGE))

    def navigate_to_url(self):
        url = self.url_bar.text()
        if not self.parent_window.current_tab():
            return
            
        if '.' in url and ' ' not in url:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            self.parent_window.current_tab().browser.setUrl(QUrl(url))
        else:
            search_engine = self.parent_window.config.SEARCH_ENGINES.get(
                self.parent_window.config.DEFAULT_SEARCH_ENGINE,
                {"url": "https://duckduckgo.com/?q={}", "lang_param": False}
            )
            search_url = search_engine["url"].replace(
                "{lang}", self.parent_window.config.CURRENT_LANGUAGE
            ) if search_engine["lang_param"] else search_engine["url"]
            self.parent_window.current_tab().browser.setUrl(QUrl(search_url.format(url)))

    def toggle_bookmark(self):
        if self.parent_window.current_tab():
            url = self.parent_window.current_tab().browser.url().toString()
            title = self.parent_window.current_tab().get_display_title()
            
            if url:
                self.parent_window.toggle_bookmark(title, url)
                self.update_bookmark_state(url)

    def update_bookmark_state(self, url):
        is_bookmarked = any(url == bookmark["url"] for bookmark in self.parent_window.config.BOOKMARKS)
        self.bookmark_btn.setChecked(is_bookmarked)

    def update_bookmarks_menu(self):
        self.bookmarks_menu.clear()
        
        if not self.parent_window.config.BOOKMARKS:
            action = self.bookmarks_menu.addAction("No bookmarks")
            action.setEnabled(False)
            return
        
        for bookmark in self.parent_window.config.BOOKMARKS:
            action = self.bookmarks_menu.addAction(bookmark["title"])
            action.setData(bookmark["url"])
            action.triggered.connect(lambda _, u=bookmark["url"]: self.parent_window.load_bookmark(u))
        
        self.bookmarks_menu.addSeparator()
        manage_action = self.bookmarks_menu.addAction("Manage Bookmarks...")
        manage_action.triggered.connect(self.parent_window.show_bookmark_manager)
        
        clear_action = self.bookmarks_menu.addAction("Clear All")
        clear_action.triggered.connect(self.parent_window.clear_bookmarks)

    def toggle_theme(self):
        self.parent_window.toggle_theme()

    def new_private_tab(self):
        self.parent_window.new_tab(private_mode=True)

    def export_pdf(self):
        if self.parent_window.current_tab():
            PDFExporter.export_to_pdf(self.parent_window.current_tab().browser, self.parent_window)

    def show_history_manager(self):
        dialog = QDialog(self.parent_window)
        dialog.setWindowTitle("History Manager")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout()
        
        # Search and filter controls
        filter_layout = QHBoxLayout()
        
        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search history...")
        search_bar.textChanged.connect(self.filter_history)
        
        date_filter = QComboBox()
        date_filter.addItems(["All Time", "Today", "Last Week", "Last Month"])
        date_filter.currentIndexChanged.connect(self.filter_history_by_date)
        
        clear_filter_btn = QPushButton("Clear Filters")
        clear_filter_btn.clicked.connect(self.clear_history_filters)
        
        filter_layout.addWidget(search_bar)
        filter_layout.addWidget(QLabel("Filter by:"))
        filter_layout.addWidget(date_filter)
        filter_layout.addWidget(clear_filter_btn)
        
        layout.addLayout(filter_layout)
        
        # History table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)  # Added checkbox column
        self.history_table.setHorizontalHeaderLabels(["", "Date", "Title", "URL", "Actions"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setSortingEnabled(True)
        
        self.load_history_to_table()
        
        # Button group
        btn_group = QDialogButtonBox()
        
        open_btn = btn_group.addButton("Open Selected", QDialogButtonBox.ActionRole)
        open_btn.clicked.connect(self.open_selected_history_items)
        
        delete_btn = btn_group.addButton("Delete Selected", QDialogButtonBox.ActionRole)
        delete_btn.clicked.connect(self.delete_selected_history)
        
        clear_btn = btn_group.addButton("Clear All History", QDialogButtonBox.ActionRole)
        clear_btn.clicked.connect(self.clear_history_with_confirmation)
        
        export_btn = btn_group.addButton("Export to CSV", QDialogButtonBox.ActionRole)
        export_btn.clicked.connect(self.export_history)
        
        btn_group.addButton(QDialogButtonBox.Close)
        btn_group.rejected.connect(dialog.reject)
        
        layout.addWidget(self.history_table)
        layout.addWidget(btn_group)
        dialog.setLayout(layout)
        dialog.exec_()

    def load_history_to_table(self):
        history = self.parent_window.config.load_history(self.parent_window.config.CURRENT_PROFILE)
        self.history_table.setRowCount(len(history))
        
        for row, item in enumerate(history):
            # Checkbox column
            chk = QCheckBox()
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_widget.setLayout(chk_layout)
            
            # Date column
            date_item = QTableWidgetItem(item['time'])
            date_item.setData(Qt.UserRole, item['url'])  # Store URL for filtering
            
            # Title column
            title_item = QTableWidgetItem(item['title'])
            title_item.setToolTip(item['title'])
            
            # URL column
            url_item = QTableWidgetItem(item['url'])
            url_item.setToolTip(item['url'])
            
            # Action buttons
            action_widget = QWidget()
            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)
            
            open_btn = QToolButton()
            open_btn.setIcon(QIcon.fromTheme("window-new"))
            open_btn.setToolTip("Open in new tab")
            open_btn.clicked.connect(lambda _, url=item['url']: self.parent_window.new_tab(url))
            
            delete_btn = QToolButton()
            delete_btn.setIcon(QIcon.fromTheme("edit-delete"))
            delete_btn.setToolTip("Delete this entry")
            delete_btn.clicked.connect(lambda _, r=row: self.delete_history_item(r))
            
            action_layout.addWidget(open_btn)
            action_layout.addWidget(delete_btn)
            action_layout.addStretch()
            action_widget.setLayout(action_layout)
            
            self.history_table.setCellWidget(row, 0, chk_widget)
            self.history_table.setItem(row, 1, date_item)
            self.history_table.setItem(row, 2, title_item)
            self.history_table.setItem(row, 3, url_item)
            self.history_table.setCellWidget(row, 4, action_widget)
        
        self.history_table.resizeColumnsToContents()
        self.history_table.sortByColumn(1, Qt.DescendingOrder)

    def get_selected_history_rows(self):
        """Get indices of selected rows (checked or selected)"""
        selected = set()
        
        # Get checked rows
        for row in range(self.history_table.rowCount()):
            chk = self.history_table.cellWidget(row, 0).findChild(QCheckBox)
            if chk and chk.isChecked():
                selected.add(row)
        
        # Also include currently selected rows
        selected.update(index.row() for index in self.history_table.selectedIndexes())
        
        return sorted(selected)

    def open_selected_history_items(self):
        selected_rows = self.get_selected_history_rows()
        for row in selected_rows:
            url = self.history_table.item(row, 3).text()
            self.parent_window.new_tab(url)

    def delete_selected_history(self):
        selected_rows = self.get_selected_history_rows()
        if not selected_rows:
            return
            
        confirm = QMessageBox.question(
            self.parent_window,
            "Confirm Deletion",
            f"Delete {len(selected_rows)} selected items?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm == QMessageBox.Yes:
            if self.parent_window.config.delete_history_items(
                self.parent_window.config.CURRENT_PROFILE, 
                selected_rows
            ):
                self.load_history_to_table()

    def delete_history_item(self, row):
        if self.parent_window.config.delete_history_items(
            self.parent_window.config.CURRENT_PROFILE, 
            [row]
        ):
            self.load_history_to_table()

    def clear_history_with_confirmation(self):
        confirm = QMessageBox.question(
            self.parent_window,
            "Clear History",
            "Are you sure you want to delete ALL history?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            if self.parent_window.config.clear_history(self.parent_window.config.CURRENT_PROFILE):
                self.history_table.setRowCount(0)

    def clear_history_filters(self):
        """Clear all filters and show full history"""
        self.sender().parent().findChild(QLineEdit).clear()
        self.sender().parent().findChild(QComboBox).setCurrentIndex(0)
        for row in range(self.history_table.rowCount()):
            self.history_table.setRowHidden(row, False)

    def filter_history(self, text):
        for row in range(self.history_table.rowCount()):
            match = False
            for col in [1, 2, 3]:  # Check Date, Title, URL columns
                item = self.history_table.item(row, col)
                if text.lower() in item.text().lower():
                    match = True
                    break
            self.history_table.setRowHidden(row, not match)

    def filter_history_by_date(self, index):
        now = datetime.now()
        for row in range(self.history_table.rowCount()):
            date_str = self.history_table.item(row, 1).text()
            try:
                item_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
                
            show = True
            if index == 1:  # Today
                show = item_date.date() == now.date()
            elif index == 2:  # Last Week
                show = (now - item_date).days <= 7
            elif index == 3:  # Last Month
                show = (now - item_date).days <= 30
                
            self.history_table.setRowHidden(row, not show)

    def export_history(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self.parent_window,
            "Export History",
            "",
            "CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                history = self.parent_window.config.load_history(self.parent_window.config.CURRENT_PROFILE)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("Date,Title,URL\n")
                    for item in history:
                        f.write(f'"{item["time"]}","{item["title"]}","{item["url"]}"\n')
                QMessageBox.information(self.parent_window, "Success", "History exported successfully!")
            except Exception as e:
                ErrorHandler.handle("file", e, show_user=True)

    def show_app_launcher(self):
        self.parent_window.show_app_launcher()

class ProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Profile")
        self.setWindowIcon(QIcon.fromTheme("user-identity"))
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        
        self.profile_list = QListWidget()
        self.profile_list.itemDoubleClicked.connect(self.accept)
        
        self.new_profile_btn = QPushButton("New Profile")
        self.new_profile_btn.clicked.connect(self.create_profile)
        
        self.delete_profile_btn = QPushButton("Delete Profile")
        self.delete_profile_btn.clicked.connect(self.delete_profile)
        
        self.encrypt_checkbox = QCheckBox("Encrypt Profile")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_confirm = QLineEdit()
        self.password_confirm.setPlaceholderText("Confirm Password")
        self.password_confirm.setEchoMode(QLineEdit.Password)
        
        encrypt_layout = QVBoxLayout()
        encrypt_layout.addWidget(self.encrypt_checkbox)
        encrypt_layout.addWidget(QLabel("Password:"))
        encrypt_layout.addWidget(self.password_input)
        encrypt_layout.addWidget(QLabel("Confirm:"))
        encrypt_layout.addWidget(self.password_confirm)
        
        self.password_input.hide()
        self.password_confirm.hide()
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(QLabel("Select profile to use:"))
        layout.addWidget(self.profile_list)
        layout.addWidget(self.new_profile_btn)
        layout.addWidget(self.delete_profile_btn)
        layout.addLayout(encrypt_layout)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        self.load_profiles()
        
        self.encrypt_checkbox.stateChanged.connect(self.toggle_password_fields)

    def toggle_password_fields(self, state):
        self.password_input.setVisible(state)
        self.password_confirm.setVisible(state)

    def load_profiles(self):
        self.profile_list.clear()
        config = Config()
        
        for profile in config.get_available_profiles():
            item = QListWidgetItem(profile)
            
            meta_file = Path(f"profiles/{profile}/profile.meta")
            if meta_file.exists() and meta_file.read_bytes().startswith(b"ENCRYPTED:"):
                item.setIcon(QIcon.fromTheme("security-high"))
                item.setToolTip("Encrypted profile")
            
            self.profile_list.addItem(item)
        
        self.profile_list.setCurrentRow(0)

    def create_profile(self):
        name, ok = QInputDialog.getText(
            self, 
            "New Profile", 
            "Profile name:",
            text=f"profile_{len(self.profile_list) + 1}"
        )
        
        if ok and name:
            if name not in [self.profile_list.item(i).text() for i in range(self.profile_list.count())]:
                if self.encrypt_checkbox.isChecked():
                    password = self.password_input.text()
                    confirm = self.password_confirm.text()
                    
                    if password and password == confirm:
                        Config.create_encrypted_profile(name, password)
                        self.load_profiles()
                    else:
                        QMessageBox.warning(self, "Error", "Passwords don't match or are empty!")
                else:
                    profile_dir = Path(f"profiles/{name}")
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    
                    default_config = Config.load("default")
                    default_config.CURRENT_PROFILE = name
                    default_config.save()
                    
                    self.load_profiles()
            else:
                QMessageBox.warning(self, "Error", "A profile with this name already exists!")

    def delete_profile(self):
        current = self.profile_list.currentItem()
        if current and current.text() != "default":
            confirm = QMessageBox.question(
                self,
                "Delete Profile",
                f"Are you sure you want to delete '{current.text()}' and all its data?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:
                import shutil
                try:
                    shutil.rmtree(f"profiles/{current.text()}")
                    self.load_profiles()
                except Exception as e:
                    ErrorHandler.handle("file", e, show_user=True)

    def selected_profile(self):
        return self.profile_list.currentItem().text()

class PluginManager:
    def __init__(self, browser):
        self.browser = browser
        self.plugins = []
        self.plugin_dir = Path("plugins")
        self.load_plugins()

    def load_plugins(self):
        self.plugin_dir.mkdir(exist_ok=True)
        
        for plugin_file in self.plugin_dir.glob("*.py"):
            try:
                plugin_name = plugin_file.stem
                spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
                module = importlib.util.module_from_spec(spec)
                module.__dict__['browser'] = self.browser
                spec.loader.exec_module(module)
                
                if not hasattr(module, "activate"):
                    logger.warning(f"Plugin {plugin_name} missing activate() function")
                    continue
                    
                plugin_data = {
                    "name": plugin_name,
                    "module": module,
                    "activated": False,
                    "description": getattr(module, "__description__", "No description"),
                    "author": getattr(module, "__author__", "Unknown"),
                    "version": getattr(module, "__version__", "1.0")
                }
                
                self.plugins.append(plugin_data)
                logger.info(f"Loaded plugin: {plugin_name} v{plugin_data['version']}")
                
            except Exception as e:
                ErrorHandler.handle("plugin", e)
                logger.error(f"Failed to load plugin {plugin_file}: {str(e)}")

    def activate_plugins(self):
        for plugin in self.plugins:
            try:
                context = {
                    "browser": self.browser,
                    "logger": logging.getLogger(f"{APP_NAME}.Plugin.{plugin['name']}"),
                    "config": self.browser.config
                }
                
                exec("activate(browser)", 
                     {**plugin["module"].__dict__, **context}, 
                     context)
                
                plugin["activated"] = True
                logger.info(f"Activated plugin: {plugin['name']}")
                
            except Exception as e:
                plugin["activated"] = False
                ErrorHandler.handle("plugin", e)
                logger.error(f"Plugin {plugin['name']} activation failed: {str(e)}")

    def get_plugin_info(self):
        return [{
            "name": p["name"],
            "active": p["activated"],
            "description": p["description"],
            "author": p["author"],
            "version": p["version"]
        } for p in self.plugins]

    def toggle_plugin(self, plugin_name):
        for plugin in self.plugins:
            if plugin["name"] == plugin_name:
                try:
                    if plugin["activated"]:
                        if hasattr(plugin["module"], "deactivate"):
                            plugin["module"].deactivate(self.browser)
                        plugin["activated"] = False
                        logger.info(f"Deactivated plugin: {plugin_name}")
                    else:
                        plugin["module"].activate(self.browser)
                        plugin["activated"] = True
                        logger.info(f"Reactivated plugin: {plugin_name}")
                    return True
                except Exception as e:
                    ErrorHandler.handle("plugin", e)
                    return False
        return False

class MainWindow(QMainWindow):
    def __init__(self, config: Config = None):
        if not config:
            profile_dialog = ProfileDialog()
            if profile_dialog.exec_() == QDialog.Accepted:
                profile_name = profile_dialog.selected_profile()
                config = Config.load(profile_name)
                if not config:
                    sys.exit(1)
            else:
                sys.exit(0)
        
        super().__init__()
        self.config = config
        self.setup_window()
        self.setup_menus()
        self.setup_shortcuts()
        
        self.language_manager = LanguageManager(self.config)
        self.plugin_manager = PluginManager(self)
        self.plugin_manager.activate_plugins()
        
        # Built-in plugins
        self.translate_plugin = TranslatePlugin(self)
        self.ai_plugin = AISummaryPlugin(self)
        
        if self.config.SAVE_SESSION:
            self.load_session()
        
        self.statusBar().showMessage(f"{APP_NAME} v{VERSION} - {self.config.CURRENT_PROFILE} profile", 3000)

    def setup_window(self):
        self.setWindowTitle(f"{APP_NAME} - {self.config.CURRENT_PROFILE}")
        self.setWindowIcon(QIcon.fromTheme("web-browser"))
        self.resize(self.config.WINDOW_SIZE)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        central_widget.setLayout(main_layout)
        
        self.nav_bar = NavigationBar(self)
        main_layout.addWidget(self.nav_bar)
        
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)
        
        # Add app launcher to corner
        self.app_launcher = AppLauncher(self)
        self.tabs.setCornerWidget(self.app_launcher, Qt.TopLeftCorner)
        
        main_layout.addWidget(self.tabs)
        
        self.apply_theme()
        self.apply_background()
        self.new_tab()

    def apply_background(self):
        if self.config.BACKGROUND_IMAGE and Path(self.config.BACKGROUND_IMAGE).exists():
            style = f"""
            QMainWindow {{
                background-image: url({self.config.BACKGROUND_IMAGE});
                background-position: center;
                background-repeat: no-repeat;
                background-attachment: fixed;
                opacity: {self.config.BACKGROUND_OPACITY};
            }}
            {self.config.CUSTOM_CSS}
            """
            self.setStyleSheet(style)

    def setup_menus(self):
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_tab_action = QAction("New Tab", self)
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(self.new_tab)
        file_menu.addAction(new_tab_action)
        
        new_private_tab_action = QAction("New Private Tab", self)
        new_private_tab_action.setShortcut("Ctrl+Shift+N")
        new_private_tab_action.triggered.connect(lambda: self.new_tab(private_mode=True))
        file_menu.addAction(new_private_tab_action)
        
        close_tab_action = QAction("Close Tab", self)
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addAction(close_tab_action)
        
        file_menu.addSeparator()
        
        switch_profile_action = QAction("Switch Profile...", self)
        switch_profile_action.triggered.connect(self.switch_profile)
        file_menu.addAction(switch_profile_action)
        
        create_shortcut_action = QAction("Create Desktop Shortcut", self)
        create_shortcut_action.triggered.connect(self.create_desktop_shortcut)
        file_menu.addAction(create_shortcut_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        
        reading_mode_action = QAction("Reading Mode", self)
        reading_mode_action.setShortcut("Ctrl+Shift+R")
        reading_mode_action.triggered.connect(self.toggle_reading_mode)
        edit_menu.addAction(reading_mode_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        theme_action = QAction("Dark Theme", self)
        theme_action.setCheckable(True)
        theme_action.setChecked(self.config.DARK_THEME)
        theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(theme_action)
        
        customize_action = QAction("Customize Browser", self)
        customize_action.triggered.connect(self.show_settings)
        view_menu.addAction(customize_action)
        
        # Bookmarks menu
        bookmarks_menu = menubar.addMenu("Bookmarks")
        
        add_bookmark_action = QAction("Add Bookmark", self)
        add_bookmark_action.setShortcut("Ctrl+D")
        add_bookmark_action.triggered.connect(self.nav_bar.toggle_bookmark)
        bookmarks_menu.addAction(add_bookmark_action)
        
        bookmarks_menu.addSeparator()
        
        self.bookmarks_submenu = QMenu("My Bookmarks", self)
        bookmarks_menu.addMenu(self.bookmarks_submenu)
        self.update_bookmarks_menu()
        
        bookmarks_menu.addSeparator()
        
        bookmark_manager_action = QAction("Bookmark Manager", self)
        bookmark_manager_action.triggered.connect(self.show_bookmark_manager)
        bookmarks_menu.addAction(bookmark_manager_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        tools_menu.addAction(settings_action)
        
        history_action = QAction("History Manager", self)
        history_action.setShortcut("Ctrl+H")
        history_action.triggered.connect(self.nav_bar.show_history_manager)
        tools_menu.addAction(history_action)
        
        logs_action = QAction("Log Manager", self)
        logs_action.setShortcut("Ctrl+Shift+L")
        logs_action.triggered.connect(self.show_log_manager)
        tools_menu.addAction(logs_action)
        
        apps_action = QAction("Manage Quick Apps", self)
        apps_action.triggered.connect(self.manage_apps)
        tools_menu.addAction(apps_action)
        
        # Language menu
        lang_menu = menubar.addMenu("Language")
        for code, name in self.config.SUPPORTED_LANGUAGES.items():
            action = lang_menu.addAction(name)
            action.setData(code)
            action.triggered.connect(lambda _, c=code: self.change_language(c))
        
        # Plugins menu
        plugin_menu = menubar.addMenu("Plugins")
        
        manage_plugins_action = QAction("Plugin Manager", self)
        manage_plugins_action.triggered.connect(self.show_plugin_manager)
        plugin_menu.addAction(manage_plugins_action)
        
        reload_plugins_action = QAction("Reload Plugins", self)
        reload_plugins_action.triggered.connect(self.reload_plugins)
        plugin_menu.addAction(reload_plugins_action)

    def setup_shortcuts(self):
        shortcuts = {
            "Ctrl+T": self.new_tab,
            "Ctrl+N": self.new_tab,
            "Ctrl+W": lambda: self.close_tab(self.tabs.currentIndex()),
            "Ctrl+Tab": self.next_tab,
            "Ctrl+Shift+Tab": self.previous_tab,
            "Ctrl+1": lambda: self.tabs.setCurrentIndex(0),
            "Ctrl+2": lambda: self.tabs.setCurrentIndex(1),
            "Ctrl+3": lambda: self.tabs.setCurrentIndex(2),
            "Ctrl+4": lambda: self.tabs.setCurrentIndex(3),
            "Ctrl+5": lambda: self.tabs.setCurrentIndex(4),
            "Ctrl+6": lambda: self.tabs.setCurrentIndex(5),
            "Ctrl+7": lambda: self.tabs.setCurrentIndex(6),
            "Ctrl+8": lambda: self.tabs.setCurrentIndex(7),
            "Ctrl+9": lambda: self.tabs.setCurrentIndex(self.tabs.count()-1),
            "F5": self.reload_page,
            "Ctrl+F5": lambda: self.current_tab().browser.reloadAndBypassCache(),
            "Ctrl+L": lambda: self.nav_bar.url_bar.setFocus(),
            "Ctrl+K": lambda: self.nav_bar.url_bar.setFocus(),
            "F6": lambda: self.nav_bar.url_bar.setFocus(),
            "F11": self.toggle_fullscreen,
            "Ctrl+Plus": self.zoom_in,
            "Ctrl+-": self.zoom_out,
            "Ctrl+0": self.zoom_reset,
            "Alt+Left": self.navigate_back,
            "Alt+Right": self.navigate_forward,
            "Ctrl+H": self.nav_bar.show_history_manager,
            "Ctrl+J": self.show_downloads,
            "Ctrl+P": lambda: PDFExporter.export_to_pdf(self.current_tab().browser, self),
            "Ctrl+S": self.save_page,
            "Ctrl+O": self.open_file,
            "Ctrl+Shift+P": self.toggle_private_mode,
            "Ctrl+Shift+N": lambda: self.new_tab(private_mode=True),
            "Ctrl+Shift+R": self.toggle_reading_mode,
            "Ctrl+Shift+T": lambda: self.translate_plugin.translate_page(),
            "Ctrl+Shift+S": lambda: self.ai_plugin.summarize_page(),
            "Ctrl+B": lambda: self.nav_bar.bookmark_btn.click(),
            "Ctrl+D": lambda: self.nav_bar.bookmark_btn.click()
        }
        
        for seq, callback in shortcuts.items():
            action = QAction(self)
            action.setShortcut(QKeySequence(seq))
            action.triggered.connect(callback)
            self.addAction(action)

    def apply_theme(self):
        palette = QPalette()
        
        if self.config.DARK_THEME:
            palette.setColor(QPalette.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.HighlightedText, Qt.white)
            
            self.setStyleSheet("""
                QLineEdit {
                    background: #353535;
                    color: white;
                    border: 1px solid #555;
                    padding: 3px;
                    border-radius: 3px;
                }
                QTabBar::tab {
                    background: #353535;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px;
                }
                QTabBar::tab:selected {
                    background: #2a82da;
                }
                QToolButton:checked {
                    background: #2a82da;
                }
                QMenu {
                    background: #353535;
                    color: white;
                    border: 1px solid #555;
                }
                QMenu::item:selected {
                    background: #2a82da;
                }
            """)
        else:
            self.setStyleSheet("""
                QLineEdit {
                    background: white;
                    color: black;
                    border: 1px solid #ccc;
                    padding: 3px;
                    border-radius: 3px;
                }
                QTabBar::tab {
                    background: #f0f0f0;
                    color: black;
                    border: 1px solid #ccc;
                    padding: 5px;
                }
                QTabBar::tab:selected {
                    background: #2a82da;
                    color: white;
                }
                QToolButton:checked {
                    background: #2a82da;
                    color: white;
                }
            """)
        
        self.setPalette(palette)

    def new_tab(self, url: str = None, private_mode: bool = False, custom_title: str = None, pinned: bool = False):
        try:
            tab = WebTab(self, self.config, private_mode, custom_title, pinned)
            
            tab_title = custom_title if custom_title else "New Tab"
            if private_mode:
                tab_title = f"🔒 {tab_title}" if custom_title else "🔒 Private Tab"
            
            index = self.tabs.addTab(tab, tab_title)
            self.tabs.setCurrentIndex(index)
            
            tab.browser.titleChanged.connect(
                lambda title, idx=index: self.update_tab_title(idx))
            
            tab.browser.urlChanged.connect(
                lambda url: self.update_url_bar(url.toString()))
            
            tab.browser.urlChanged.connect(
                lambda url: self.nav_bar.update_bookmark_state(url.toString()))
            
            if private_mode:
                self.tabs.tabBar().setTabTextColor(index, QColor("#ff6b6b"))
            
            if pinned:
                self.tabs.tabBar().setTabButton(index, QTabBar.LeftSide, None)
                self.tabs.tabBar().setTabIcon(index, QIcon.fromTheme("pin"))
                self.tabs.setTabEnabled(index, False)
            
            if url:
                tab.browser.setUrl(QUrl(url))
            elif not custom_title and not pinned:
                tab.browser.setUrl(QUrl(self.config.HOME_PAGE))
            
            return tab
        except Exception as e:
            ErrorHandler.handle("ui", e, show_user=True)

    def close_tab(self, index: int):
        try:
            if self.tabs.count() <= 1:
                self.close()
            else:
                widget = self.tabs.widget(index)
                if widget:
                    widget.deleteLater()
                    self.tabs.removeTab(index)
        except Exception as e:
            ErrorHandler.handle("ui", e, show_user=True)

    def current_tab(self) -> Optional[WebTab]:
        return self.tabs.currentWidget()

    def update_url_bar(self, url: str):
        self.nav_bar.url_bar.setText(url)
        self.nav_bar.url_bar.setCursorPosition(0)
        self.nav_bar.update_bookmark_state(url)

    def update_tab_title(self, index: int):
        tab = self.tabs.widget(index)
        if tab:
            title = tab.get_display_title()
            prefix = "🔒 " if tab.private_mode else ""
            
            if len(title) > 15:
                title = title[:15] + "..."
            
            self.tabs.setTabText(index, prefix + title)

    def tab_changed(self, index: int):
        tab = self.tabs.widget(index)
        if tab:
            self.update_url_bar(tab.browser.url().toString())

    def show_tab_context_menu(self, pos):
        index = self.tabs.tabBar().tabAt(pos)
        if index >= 0:
            menu = QMenu()
            
            close_action = QAction("Close Tab", self)
            close_action.triggered.connect(lambda: self.close_tab(index))
            menu.addAction(close_action)
            
            rename_action = QAction("Rename Tab", self)
            rename_action.triggered.connect(lambda: self.rename_tab(index))
            menu.addAction(rename_action)
            
            tab = self.tabs.widget(index)
            if tab:
                pin_action = QAction("Pin Tab" if not tab.pinned else "Unpin Tab", self)
                pin_action.triggered.connect(tab.toggle_pinned)
                menu.addAction(pin_action)
                
                if tab.private_mode:
                    menu.addSeparator()
                    private_action = QAction("🔒 Private Tab", self)
                    private_action.setEnabled(False)
                    menu.addAction(private_action)
            
            menu.exec_(QCursor.pos())

    def rename_tab(self, index: int):
        tab = self.tabs.widget(index)
        if tab:
            current_title = tab.custom_title if tab.custom_title else tab.browser.title()
            
            new_title, ok = QInputDialog.getText(
                self,
                "Rename Tab",
                "New title:",
                text=current_title
            )
            
            if ok and new_title:
                tab.custom_title = new_title
                self.update_tab_title(index)

    def next_tab(self):
        current = self.tabs.currentIndex()
        new_index = current + 1 if current < self.tabs.count() - 1 else 0
        self.tabs.setCurrentIndex(new_index)

    def previous_tab(self):
        current = self.tabs.currentIndex()
        new_index = current - 1 if current > 0 else self.tabs.count() - 1
        self.tabs.setCurrentIndex(new_index)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def zoom_in(self):
        if self.current_tab():
            self.current_tab().browser.setZoomFactor(self.current_tab().browser.zoomFactor() + 0.1)

    def zoom_out(self):
        if self.current_tab():
            self.current_tab().browser.setZoomFactor(self.current_tab().browser.zoomFactor() - 0.1)

    def zoom_reset(self):
        if self.current_tab():
            self.current_tab().browser.setZoomFactor(1.0)

    def save_page(self):
        if self.current_tab():
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Page",
                "",
                "Web Page, Complete (*.html *.htm);;Web Page, HTML Only (*.html *.htm)"
            )
            if file_path:
                self.current_tab().browser.page().save(file_path)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open HTML File",
            "",
            "HTML Files (*.html *.htm);;All Files (*)"
        )
        if file_path:
            self.new_tab(QUrl.fromLocalFile(file_path).toString())

    def toggle_private_mode(self):
        try:
            self.config.PRIVATE_MODE = not self.config.PRIVATE_MODE
            self.statusBar().showMessage(
                f"Private Mode: {'ON' if self.config.PRIVATE_MODE else 'OFF'}", 
                2000
            )
            
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if tab:
                    current_url = tab.browser.url().toString()
                    custom_title = tab.custom_title
                    pinned = tab.pinned
                    self.close_tab(i)
                    self.new_tab(current_url, self.config.PRIVATE_MODE, custom_title, pinned)
        except Exception as e:
            ErrorHandler.handle("ui", e, show_user=True)

    def toggle_reading_mode(self):
        if self.current_tab():
            self.current_tab().toggle_reading_mode()

    def toggle_bookmark(self, title: str, url: str):
        try:
            # Check if bookmark already exists
            existing_index = next((i for i, b in enumerate(self.config.BOOKMARKS) if b["url"] == url), None)
            
            if existing_index is not None:
                # Bookmark exists, remove it
                self.config.BOOKMARKS.pop(existing_index)
                self.statusBar().showMessage("Bookmark removed", 2000)
            else:
                # Add new bookmark
                self.config.BOOKMARKS.append({
                    "title": title,
                    "url": url,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                self.statusBar().showMessage("Bookmark added", 2000)
            
            self.config.save_bookmarks(self.config.CURRENT_PROFILE)
            self.update_bookmarks_menu()
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)

    def update_bookmarks_menu(self):
        self.bookmarks_submenu.clear()
        self.nav_bar.update_bookmarks_menu()
        
        if not self.config.BOOKMARKS:
            action = self.bookmarks_submenu.addAction("No bookmarks")
            action.setEnabled(False)
            return
        
        for bookmark in self.config.BOOKMARKS:
            action = self.bookmarks_submenu.addAction(bookmark["title"])
            action.setData(bookmark["url"])
            action.triggered.connect(lambda _, u=bookmark["url"]: self.load_bookmark(u))
        
        self.bookmarks_submenu.addSeparator()
        manage_action = self.bookmarks_submenu.addAction("Manage Bookmarks...")
        manage_action.triggered.connect(self.show_bookmark_manager)
        
        clear_action = self.bookmarks_submenu.addAction("Clear All")
        clear_action.triggered.connect(self.clear_bookmarks)

    def load_bookmark(self, url: str):
        if self.current_tab():
            self.current_tab().browser.setUrl(QUrl(url))

    def clear_bookmarks(self):
        confirm = QMessageBox.question(
            self,
            "Clear Bookmarks",
            "Are you sure you want to delete ALL bookmarks?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            if self.config.clear_bookmarks():
                self.update_bookmarks_menu()
                self.statusBar().showMessage("All bookmarks cleared", 2000)

    def show_bookmark_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Bookmark Manager")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout()
        
        # Search bar
        search_layout = QHBoxLayout()
        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search bookmarks...")
        search_bar.textChanged.connect(self.filter_bookmarks)
        search_layout.addWidget(search_bar)
        
        clear_filter_btn = QPushButton("Clear Filters")
        clear_filter_btn.clicked.connect(lambda: search_bar.clear())
        search_layout.addWidget(clear_filter_btn)
        
        layout.addLayout(search_layout)
        
        # Bookmark table with checkboxes
        self.bookmark_table = QTableWidget()
        self.bookmark_table.setColumnCount(5)  # Added checkbox column
        self.bookmark_table.setHorizontalHeaderLabels(["", "Title", "URL", "Date Added", "Actions"])
        self.bookmark_table.horizontalHeader().setStretchLastSection(True)
        self.bookmark_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.bookmark_table.setEditTriggers(QTableWidget.DoubleClicked)
        self.bookmark_table.setSortingEnabled(True)
        
        self.load_bookmarks_to_table()
        
        # Button group
        btn_group = QDialogButtonBox()
        
        open_btn = btn_group.addButton("Open Selected", QDialogButtonBox.ActionRole)
        open_btn.clicked.connect(self.open_selected_bookmarks)
        
        add_btn = btn_group.addButton("Add Bookmark", QDialogButtonBox.ActionRole)
        add_btn.clicked.connect(self.add_bookmark_from_manager)
        
        remove_btn = btn_group.addButton("Remove Selected", QDialogButtonBox.ActionRole)
        remove_btn.clicked.connect(self.remove_selected_bookmarks)
        
        clear_btn = btn_group.addButton("Clear All", QDialogButtonBox.ActionRole)
        clear_btn.clicked.connect(self.clear_bookmarks_with_confirmation)
        
        btn_group.addButton(QDialogButtonBox.Save)
        btn_box.accepted.connect(lambda: self.save_bookmarks_from_table(dialog))
        btn_box.rejected.connect(dialog.reject)
        
        layout.addWidget(self.bookmark_table)
        layout.addWidget(btn_group)
        dialog.setLayout(layout)
        dialog.exec_()

    def load_bookmarks_to_table(self):
        self.bookmark_table.setRowCount(len(self.config.BOOKMARKS))
        
        for row, bookmark in enumerate(self.config.BOOKMARKS):
            # Checkbox column
            chk = QCheckBox()
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_widget.setLayout(chk_layout)
            
            # Title column (editable)
            title_item = QTableWidgetItem(bookmark["title"])
            
            # URL column (editable)
            url_item = QTableWidgetItem(bookmark["url"])
            
            # Date added
            date_item = QTableWidgetItem(bookmark.get("date", ""))
            
            # Action buttons
            action_widget = QWidget()
            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)
            
            open_btn = QToolButton()
            open_btn.setIcon(QIcon.fromTheme("window-new"))
            open_btn.setToolTip("Open in new tab")
            open_btn.clicked.connect(lambda _, u=bookmark["url"]: self.new_tab(u))
            
            action_layout.addWidget(open_btn)
            action_layout.addStretch()
            action_widget.setLayout(action_layout)
            
            self.bookmark_table.setCellWidget(row, 0, chk_widget)
            self.bookmark_table.setItem(row, 1, title_item)
            self.bookmark_table.setItem(row, 2, url_item)
            self.bookmark_table.setItem(row, 3, date_item)
            self.bookmark_table.setCellWidget(row, 4, action_widget)
        
        self.bookmark_table.resizeColumnsToContents()

    def get_selected_bookmark_rows(self):
        """Get indices of selected bookmark rows"""
        selected = set()
        
        # Get checked rows
        for row in range(self.bookmark_table.rowCount()):
            chk = self.bookmark_table.cellWidget(row, 0).findChild(QCheckBox)
            if chk and chk.isChecked():
                selected.add(row)
        
        # Also include currently selected rows
        selected.update(index.row() for index in self.bookmark_table.selectedIndexes())
        
        return sorted(selected, reverse=True)  # Reverse for safe deletion

    def open_selected_bookmarks(self):
        selected_rows = self.get_selected_bookmark_rows()
        for row in selected_rows:
            url = self.bookmark_table.item(row, 2).text()
            self.new_tab(url)

    def add_bookmark_from_manager(self):
        title, ok1 = QInputDialog.getText(self, "Add Bookmark", "Title:")
        if ok1 and title:
            url, ok2 = QInputDialog.getText(self, "Add Bookmark", "URL:", text="https://")
            if ok2 and url:
                self.config.BOOKMARKS.append({
                    "title": title,
                    "url": url,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                self.load_bookmarks_to_table()

    def remove_selected_bookmarks(self):
        selected_rows = self.get_selected_bookmark_rows()
        if not selected_rows:
            return
            
        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete {len(selected_rows)} selected bookmarks?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm == QMessageBox.Yes:
            if self.config.delete_bookmarks(selected_rows):
                self.load_bookmarks_to_table()
                self.update_bookmarks_menu()

    def clear_bookmarks_with_confirmation(self):
        confirm = QMessageBox.question(
            self,
            "Clear Bookmarks",
            "Are you sure you want to delete ALL bookmarks?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            if self.config.clear_bookmarks():
                self.bookmark_table.setRowCount(0)
                self.update_bookmarks_menu()

    def save_bookmarks_from_table(self, dialog):
        """Save bookmarks from the table back to config"""
        bookmarks = []
        for row in range(self.bookmark_table.rowCount()):
            title = self.bookmark_table.item(row, 1).text()
            url = self.bookmark_table.item(row, 2).text()
            date = self.bookmark_table.item(row, 3).text()
            if title and url:
                bookmarks.append({
                    "title": title,
                    "url": url,
                    "date": date if date else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        
        self.config.BOOKMARKS = bookmarks
        self.config.save_bookmarks(self.config.CURRENT_PROFILE)
        self.update_bookmarks_menu()
        dialog.accept()

    def filter_bookmarks(self, text):
        """Filter bookmarks based on search text"""
        for row in range(self.bookmark_table.rowCount()):
            match = False
            for col in [1, 2]:  # Search title and URL columns
                item = self.bookmark_table.item(row, col)
                if text.lower() in item.text().lower():
                    match = True
                    break
            self.bookmark_table.setRowHidden(row, not match)

    def add_to_history(self, url, title):
        history = self.config.load_history(self.config.CURRENT_PROFILE)
        
        # Check if this URL is already in history
        existing_entry = next((h for h in history if h["url"] == url), None)
        
        if existing_entry:
            # Update existing entry
            existing_entry["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            existing_entry["title"] = title
        else:
            # Add new entry
            history.insert(0, {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "url": url,
                "title": title
            })
        
        # Keep only last 100 items
        history = history[:100]
        self.config.save_history(self.config.CURRENT_PROFILE, history)

    def toggle_theme(self):
        self.config.DARK_THEME = not self.config.DARK_THEME
        self.apply_theme()
        self.statusBar().showMessage(
            f"Theme: {'Dark' if self.config.DARK_THEME else 'Light'}", 
            2000
        )

    def show_log_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Log Manager")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout()
        
        # Filter controls
        filter_layout = QHBoxLayout()
        
        level_combo = QComboBox()
        level_combo.addItems(["All", "INFO", "WARNING", "ERROR", "CRITICAL"])
        
        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search logs...")
        
        filter_layout.addWidget(QLabel("Level:"))
        filter_layout.addWidget(level_combo)
        filter_layout.addWidget(QLabel("Search:"))
        filter_layout.addWidget(search_bar)
        filter_layout.addStretch()
        
        layout.addLayout(filter_layout)
        
        # Log table
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["Timestamp", "Level", "Source", "Message"])
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log_table.setSortingEnabled(True)
        
        self.load_logs_to_table()
        
        # Connect filters
        search_bar.textChanged.connect(self.filter_logs)
        level_combo.currentIndexChanged.connect(self.filter_logs)
        
        # Button group
        btn_group = QDialogButtonBox()
        
        refresh_btn = btn_group.addButton("Refresh", QDialogButtonBox.ActionRole)
        refresh_btn.clicked.connect(self.load_logs_to_table)
        
        delete_btn = btn_group.addButton("Delete Selected", QDialogButtonBox.ActionRole)
        delete_btn.clicked.connect(self.delete_selected_logs)
        
        clear_btn = btn_group.addButton("Clear All Logs", QDialogButtonBox.ActionRole)
        clear_btn.clicked.connect(self.clear_logs_with_confirmation)
        
        export_btn = btn_group.addButton("Export to File", QDialogButtonBox.ActionRole)
        export_btn.clicked.connect(self.export_logs)
        
        btn_group.addButton(QDialogButtonBox.Close)
        btn_group.rejected.connect(dialog.reject)
        
        layout.addWidget(self.log_table)
        layout.addWidget(btn_group)
        dialog.setLayout(layout)
        dialog.exec_()

    def load_logs_to_table(self):
        try:
            with open("logs/gyarados.log", "r", encoding="utf-8") as f:
                logs = f.readlines()
            
            self.log_table.setRowCount(len(logs))
            
            for row, line in enumerate(logs):
                if not line.strip():
                    continue
                    
                # Parse log line (format: "2023-01-01 12:00:00 - LEVEL - message")
                parts = line.split(" - ", 3)
                if len(parts) < 4:
                    continue
                    
                timestamp = parts[0]
                level = parts[1]
                source = parts[2]
                message = parts[3].strip()
                
                # Timestamp column
                time_item = QTableWidgetItem(timestamp)
                
                # Level column with color coding
                level_item = QTableWidgetItem(level)
                if level == "ERROR":
                    level_item.setForeground(QColor(200, 0, 0))
                elif level == "WARNING":
                    level_item.setForeground(QColor(200, 100, 0))
                elif level == "CRITICAL":
                    level_item.setForeground(QColor(255, 0, 0))
                    level_item.setBackground(QColor(50, 0, 0))
                
                # Source column
                source_item = QTableWidgetItem(source)
                
                # Message column
                message_item = QTableWidgetItem(message)
                message_item.setToolTip(message)
                
                self.log_table.setItem(row, 0, time_item)
                self.log_table.setItem(row, 1, level_item)
                self.log_table.setItem(row, 2, source_item)
                self.log_table.setItem(row, 3, message_item)
            
            self.log_table.resizeColumnsToContents()
            self.log_table.sortByColumn(0, Qt.DescendingOrder)
            
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)

    def filter_logs(self):
        level_filter = self.sender().parent().findChild(QComboBox).currentText()
        text_filter = self.sender().parent().findChild(QLineEdit).text().lower()
        
        for row in range(self.log_table.rowCount()):
            level_match = (level_filter == "All" or 
                          self.log_table.item(row, 1).text() == level_filter)
            text_match = (text_filter in self.log_table.item(row, 0).text().lower() or
                         text_filter in self.log_table.item(row, 2).text().lower() or
                         text_filter in self.log_table.item(row, 3).text().lower())
            
            self.log_table.setRowHidden(row, not (level_match and text_match))

    def delete_selected_logs(self):
        selected_rows = set(index.row() for index in self.log_table.selectedIndexes())
        if not selected_rows:
            return
            
        try:
            with open("logs/gyarados.log", "r", encoding="utf-8") as f:
                all_logs = f.readlines()
            
            # Keep only non-selected logs
            new_logs = [log for i, log in enumerate(all_logs) 
                       if i not in selected_rows and log.strip()]
            
            with open("logs/gyarados.log", "w", encoding="utf-8") as f:
                f.writelines(new_logs)
            
            self.load_logs_to_table()
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)

    def clear_logs_with_confirmation(self):
        confirm = QMessageBox.question(
            self,
            "Clear Logs",
            "Are you sure you want to delete ALL logs?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            try:
                with open("logs/gyarados.log", "w", encoding="utf-8") as f:
                    f.write("")
                self.log_table.setRowCount(0)
            except Exception as e:
                ErrorHandler.handle("file", e, show_user=True)

    def export_logs(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Logs",
            "",
            "Log Files (*.log);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open("logs/gyarados.log", "r", encoding="utf-8") as src:
                    with open(file_path, "w", encoding="utf-8") as dest:
                        dest.writelines(src.readlines())
                QMessageBox.information(self, "Success", "Logs exported successfully!")
            except Exception as e:
                ErrorHandler.handle("file", e, show_user=True)

    def save_session(self):
        try:
            if not self.config.SAVE_SESSION:
                return
                
            session = {
                "tabs": [],
                "current_index": self.tabs.currentIndex(),
                "dark_theme": self.config.DARK_THEME
            }
            
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if tab:
                    session["tabs"].append({
                        "url": tab.browser.url().toString(),
                        "private": tab.private_mode,
                        "custom_title": tab.custom_title,
                        "pinned": tab.pinned
                    })
            
            settings = QSettings(APP_NAME, f"Browser/{self.config.CURRENT_PROFILE}")
            settings.setValue("session", json.dumps(session))
        except Exception as e:
            ErrorHandler.handle("file", e)

    def load_session(self):
        try:
            settings = QSettings(APP_NAME, f"Browser/{self.config.CURRENT_PROFILE}")
            session_data = settings.value("session")
            
            if session_data:
                session = json.loads(session_data)
                for tab_data in session["tabs"]:
                    self.new_tab(
                        tab_data["url"],
                        tab_data.get("private", False),
                        tab_data.get("custom_title"),
                        tab_data.get("pinned", False)
                    )
                
                if "current_index" in session:
                    self.tabs.setCurrentIndex(session["current_index"])
                
                if "dark_theme" in session and session["dark_theme"]:
                    self.config.DARK_THEME = True
                    self.apply_theme()
        except Exception as e:
            ErrorHandler.handle("file", e)

    def switch_profile(self):
        dialog = ProfileDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            profile_name = dialog.selected_profile()
            if profile_name != self.config.CURRENT_PROFILE:
                self.save_session()
                self.config.save()
                
                new_config = Config.load(profile_name)
                if new_config:
                    self.config = new_config
                    self.setWindowTitle(f"{APP_NAME} - {self.config.CURRENT_PROFILE}")
                    
                    for i in range(self.tabs.count()):
                        self.close_tab(0)
                    
                    self.apply_theme()
                    self.apply_background()
                    self.new_tab()
                    self.update_bookmarks_menu()
                    
                    if self.config.SAVE_SESSION:
                        self.load_session()

    def change_language(self, lang_code):
        if self.language_manager.set_language(lang_code):
            self.config.CURRENT_LANGUAGE = lang_code
            self.config.save()
            QMessageBox.information(self, "Info", "Language changed. Please restart the application for changes to take effect.")

    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.resize(600, 500)
        
        layout = QVBoxLayout()
        tab_widget = QTabWidget()
        
        # General Tab
        general_tab = QWidget()
        general_layout = QVBoxLayout()
        
        # Home page
        home_page_layout = QHBoxLayout()
        home_page_layout.addWidget(QLabel("Home Page:"))
        home_page_input = QLineEdit(self.config.HOME_PAGE)
        home_page_layout.addWidget(home_page_input)
        
        # Search engine
        search_engine_layout = QHBoxLayout()
        search_engine_layout.addWidget(QLabel("Default Search Engine:"))
        search_engine_combo = QComboBox()
        search_engine_combo.addItems(self.config.SEARCH_ENGINES.keys())
        search_engine_combo.setCurrentText(self.config.DEFAULT_SEARCH_ENGINE)
        search_engine_layout.addWidget(search_engine_combo)
        
        # Language
        language_layout = QHBoxLayout()
        language_layout.addWidget(QLabel("Interface Language:"))
        language_combo = QComboBox()
        for code, name in self.config.SUPPORTED_LANGUAGES.items():
            language_combo.addItem(name, code)
        language_combo.setCurrentText(self.config.SUPPORTED_LANGUAGES.get(self.config.CURRENT_LANGUAGE, "English"))
        language_layout.addWidget(language_combo)
        
        # Translation language
        translate_layout = QHBoxLayout()
        translate_layout.addWidget(QLabel("Default Translation Language:"))
        translate_combo = QComboBox()
        for code, name in LANGUAGES.items():
            translate_combo.addItem(f"{name} ({code})", code)
        translate_combo.setCurrentText(f"{LANGUAGES.get(self.config.TRANSLATE_TARGET_LANG, 'English')} ({self.config.TRANSLATE_TARGET_LANG})")
        translate_layout.addWidget(translate_combo)
        
        general_layout.addLayout(home_page_layout)
        general_layout.addLayout(search_engine_layout)
        general_layout.addLayout(language_layout)
        general_layout.addLayout(translate_layout)
        general_layout.addStretch()
        general_tab.setLayout(general_layout)
        
        # Privacy Tab
        privacy_tab = QWidget()
        privacy_layout = QVBoxLayout()
        
        adblock_check = QCheckBox("Enable Ad Blocker")
        adblock_check.setChecked(self.config.ADBLOCK_ENABLED)
        
        cookies_check = QCheckBox("Enable Cookies")
        cookies_check.setChecked(self.config.COOKIES_ENABLED)
        
        javascript_check = QCheckBox("Enable JavaScript")
        javascript_check.setChecked(self.config.JAVASCRIPT_ENABLED)
        
        webgl_check = QCheckBox("Enable WebGL")
        webgl_check.setChecked(self.config.WEBGL_ENABLED)
        
        save_session_check = QCheckBox("Save Session Between Launches")
        save_session_check.setChecked(self.config.SAVE_SESSION)
        
        privacy_layout.addWidget(adblock_check)
        privacy_layout.addWidget(cookies_check)
        privacy_layout.addWidget(javascript_check)
        privacy_layout.addWidget(webgl_check)
        privacy_layout.addWidget(save_session_check)
        privacy_layout.addStretch()
        privacy_tab.setLayout(privacy_layout)
        
        # Appearance Tab
        appearance_tab = QWidget()
        appearance_layout = QVBoxLayout()
        
        theme_check = QCheckBox("Dark Theme")
        theme_check.setChecked(self.config.DARK_THEME)
        
        # Background settings
        bg_path_edit = QLineEdit(self.config.BACKGROUND_IMAGE or "")
        bg_browse_btn = QPushButton("Browse...")
        bg_browse_btn.clicked.connect(lambda: self.browse_background(bg_path_edit))
        
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setRange(10, 100)
        opacity_slider.setValue(int(self.config.BACKGROUND_OPACITY * 100))
        opacity_label = QLabel(f"Opacity: {opacity_slider.value()}%")
        opacity_slider.valueChanged.connect(lambda v: opacity_label.setText(f"Opacity: {v}%"))
        
        css_edit = QTextEdit(self.config.CUSTOM_CSS)
        css_edit.setPlaceholderText("Custom CSS styles...")
        
        appearance_layout.addWidget(theme_check)
        appearance_layout.addWidget(QLabel("Background Image:"))
        appearance_layout.addWidget(bg_path_edit)
        appearance_layout.addWidget(bg_browse_btn)
        appearance_layout.addWidget(QLabel("Opacity:"))
        appearance_layout.addWidget(opacity_slider)
        appearance_layout.addWidget(opacity_label)
        appearance_layout.addWidget(QLabel("Custom CSS:"))
        appearance_layout.addWidget(css_edit)
        appearance_tab.setLayout(appearance_layout)
        
        tab_widget.addTab(general_tab, "General")
        tab_widget.addTab(privacy_tab, "Privacy")
        tab_widget.addTab(appearance_tab, "Appearance")
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        
        layout.addWidget(tab_widget)
        layout.addWidget(button_box)
        dialog.setLayout(layout)
        
        if dialog.exec_() == QDialog.Accepted:
            # General settings
            self.config.HOME_PAGE = home_page_input.text()
            self.config.DEFAULT_SEARCH_ENGINE = search_engine_combo.currentText()
            
            new_lang = language_combo.currentData()
            if new_lang != self.config.CURRENT_LANGUAGE:
                self.config.CURRENT_LANGUAGE = new_lang
                lang_changed = True
            else:
                lang_changed = False
            
            self.config.TRANSLATE_TARGET_LANG = translate_combo.currentData()
            
            # Privacy settings
            self.config.ADBLOCK_ENABLED = adblock_check.isChecked()
            self.config.COOKIES_ENABLED = cookies_check.isChecked()
            self.config.JAVASCRIPT_ENABLED = javascript_check.isChecked()
            self.config.WEBGL_ENABLED = webgl_check.isChecked()
            self.config.SAVE_SESSION = save_session_check.isChecked()
            
            # Appearance settings
            self.config.DARK_THEME = theme_check.isChecked()
            self.config.BACKGROUND_IMAGE = bg_path_edit.text()
            self.config.BACKGROUND_OPACITY = opacity_slider.value() / 100
            self.config.CUSTOM_CSS = css_edit.toPlainText()
            
            # Apply changes
            self.apply_theme()
            self.apply_background()
            
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if tab:
                    tab.setup_web_engine()
            
            if lang_changed:
                QMessageBox.information(self, "Info", "Language changed. Please restart the application for changes to take effect.")

    def browse_background(self, path_edit):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if filename:
            path_edit.setText(filename)

    def show_plugin_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Plugin Manager")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout()
        
        plugin_table = QTableWidget()
        plugin_table.setColumnCount(5)
        plugin_table.setHorizontalHeaderLabels(["Name", "Version", "Author", "Status", "Description"])
        plugin_table.horizontalHeader().setStretchLastSection(True)
        plugin_table.setSelectionBehavior(QTableWidget.SelectRows)
        plugin_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        plugins = self.plugin_manager.get_plugin_info()
        plugin_table.setRowCount(len(plugins))
        
        for row, plugin in enumerate(plugins):
            plugin_table.setItem(row, 0, QTableWidgetItem(plugin["name"]))
            plugin_table.setItem(row, 1, QTableWidgetItem(plugin["version"]))
            plugin_table.setItem(row, 2, QTableWidgetItem(plugin["author"]))
            
            status = QTableWidgetItem("Active" if plugin["active"] else "Inactive")
            status.setForeground(QColor("green") if plugin["active"] else QColor("red"))
            plugin_table.setItem(row, 3, status)
            
            plugin_table.setItem(row, 4, QTableWidgetItem(plugin["description"]))
        
        btn_group = QDialogButtonBox()
        
        toggle_btn = btn_group.addButton("Toggle Status", QDialogButtonBox.ActionRole)
        toggle_btn.clicked.connect(lambda: self.toggle_plugin(plugin_table))
        
        refresh_btn = btn_group.addButton("Refresh", QDialogButtonBox.ActionRole)
        refresh_btn.clicked.connect(lambda: self.refresh_plugin_list(plugin_table))
        
        btn_group.addButton(QDialogButtonBox.Close)
        btn_group.rejected.connect(dialog.reject)
        
        layout.addWidget(plugin_table)
        layout.addWidget(btn_group)
        dialog.setLayout(layout)
        dialog.exec_()

    def toggle_plugin(self, plugin_table):
        selected = plugin_table.currentRow()
        if selected >= 0:
            plugin_name = plugin_table.item(selected, 0).text()
            if self.plugin_manager.toggle_plugin(plugin_name):
                plugin = next(p for p in self.plugin_manager.plugins if p["name"] == plugin_name)
                status = QTableWidgetItem("Active" if plugin["activated"] else "Inactive")
                status.setForeground(QColor("green") if plugin["activated"] else QColor("red"))
                plugin_table.setItem(selected, 3, status)

    def refresh_plugin_list(self, plugin_table):
        self.plugin_manager = PluginManager(self)
        self.plugin_manager.activate_plugins()
        
        plugins = self.plugin_manager.get_plugin_info()
        plugin_table.setRowCount(len(plugins))
        
        for row, plugin in enumerate(plugins):
            plugin_table.setItem(row, 0, QTableWidgetItem(plugin["name"]))
            plugin_table.setItem(row, 1, QTableWidgetItem(plugin["version"]))
            plugin_table.setItem(row, 2, QTableWidgetItem(plugin["author"]))
            
            status = QTableWidgetItem("Active" if plugin["active"] else "Inactive")
            status.setForeground(QColor("green") if plugin["active"] else QColor("red"))
            plugin_table.setItem(row, 3, status)
            
            plugin_table.setItem(row, 4, QTableWidgetItem(plugin["description"]))

    def reload_plugins(self):
        self.plugin_manager = PluginManager(self)
        self.plugin_manager.activate_plugins()
        QMessageBox.information(self, "Info", "Plugins reloaded successfully!")

    def show_app_launcher(self):
        self.app_launcher.load_apps()
        corner = self.tabs.cornerWidget(Qt.TopLeftCorner)
        if corner and corner.isHidden():
            corner.show()
        else:
            corner.hide()

    def manage_apps(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage Quick Apps")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout()
        
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Name", "URL", "Icon"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.DoubleClicked)
        
        table.setRowCount(len(self.config.APPS))
        for row, app in enumerate(self.config.APPS):
            table.setItem(row, 0, QTableWidgetItem(app["name"]))
            table.setItem(row, 1, QTableWidgetItem(app["url"]))
            table.setItem(row, 2, QTableWidgetItem(app.get("icon", "web-browser")))
        
        btn_group = QDialogButtonBox()
        
        add_btn = btn_group.addButton("Add", QDialogButtonBox.ActionRole)
        add_btn.clicked.connect(lambda: self.add_app_from_manager(table))
        
        remove_btn = btn_group.addButton("Remove", QDialogButtonBox.ActionRole)
        remove_btn.clicked.connect(lambda: self.remove_app_from_manager(table))
        
        btn_group.addButton(QDialogButtonBox.Save)
        btn_box.accepted.connect(lambda: self.save_apps_from_manager(table, dialog))
        btn_box.rejected.connect(dialog.reject)
        
        layout.addWidget(table)
        layout.addWidget(btn_group)
        dialog.setLayout(layout)
        dialog.exec_()

    def add_app_from_manager(self, table):
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem("New App"))
        table.setItem(row, 1, QTableWidgetItem("https://"))
        table.setItem(row, 2, QTableWidgetItem("web-browser"))

    def remove_app_from_manager(self, table):
        selected = table.currentRow()
        if selected >= 0:
            table.removeRow(selected)

    def save_apps_from_manager(self, table, dialog):
        self.config.APPS = []
        for row in range(table.rowCount()):
            name = table.item(row, 0).text()
            url = table.item(row, 1).text()
            icon = table.item(row, 2).text()
            if name and url:
                self.config.APPS.append({"name": name, "url": url, "icon": icon})
        self.config.save_apps(self.config.CURRENT_PROFILE)
        self.app_launcher.load_apps()
        dialog.accept()

    def create_desktop_shortcut(self):
        app_path = sys.executable
        icon_path = os.path.abspath("icons/gyarados.png") if os.path.exists("icons/gyarados.png") else None
        
        if DesktopShortcut.create(APP_NAME, app_path, icon_path):
            QMessageBox.information(self, "Success", "Desktop shortcut created successfully!")
        else:
            QMessageBox.warning(self, "Error", "Could not create desktop shortcut!")

    def reload_page(self):
        if self.current_tab():
            self.current_tab().browser.reload()

    def navigate_back(self):
        if self.current_tab():
            self.current_tab().browser.back()

    def navigate_forward(self):
        if self.current_tab():
            self.current_tab().browser.forward()

    def show_downloads(self):
        QMessageBox.information(self, "Downloads", "Download manager will be implemented in a future version.")

    def closeEvent(self, event):
        try:
            self.save_session()
            self.config.save()
            event.accept()
        except Exception as e:
            ErrorHandler.handle("general", e, show_user=True)
            event.accept()

def main():
    try:
        logger.info(f"{APP_NAME} v{VERSION} starting")
        
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
        
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setApplicationVersion(VERSION)
        
        window = MainWindow()
        window.show()
        
        logger.info("Application started successfully")
        sys.exit(app.exec_())
        
    except Exception as e:
        ErrorHandler.handle("general", e, show_user=True)
        logger.critical(f"Application failed to start: {str(e)}")

if __name__ == "__main__":
    main()