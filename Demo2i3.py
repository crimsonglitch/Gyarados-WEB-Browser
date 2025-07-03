import os
import sys
import json
import logging
import importlib.util
import base64
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from logging.handlers import RotatingFileHandler
from googletrans import Translator
import openai

from PyQt5.QtCore import (QUrl, QSize, Qt, QSettings, QFile, QTextStream, 
                          QStandardPaths, QTimer, QObject, pyqtSignal)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QToolButton, QTabWidget, 
                            QMenu, QAction, QMessageBox, QInputDialog, 
                            QFileDialog, QLabel, QDialog, QListWidget, 
                            QListWidgetItem, QPushButton, QDialogButtonBox,
                            QTableWidget, QTableWidgetItem, QCheckBox,
                            QComboBox, QGroupBox)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo
from PyQt5.QtGui import QIcon, QKeySequence, QPalette, QColor, QCursor
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog

# Constants
APP_NAME = "GyaradosAI"
VERSION = "3.0.0"
DEFAULT_WINDOW_SIZE = QSize(1280, 720)

# Logging Setup
def setup_logging():
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.INFO)
    
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
        "ai": ("AI Error", "An error occurred with AI services.")
    }

    @classmethod
    def handle(cls, error_type: str, error: Exception, show_user: bool = False):
        error_title, error_msg = cls.ERROR_TYPES.get(error_type, cls.ERROR_TYPES["general"])
        logger.error(f"{error_type.upper()} - {str(error)}")
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
        }
    })
    DEFAULT_SEARCH_ENGINE: str = "DuckDuckGo"
    SUPPORTED_LANGUAGES: Dict[str, str] = field(default_factory=lambda: {
        "en": "English",
        "tr": "Türkçe",
        "es": "Español",
        "fr": "Français",
        "de": "Deutsch",
        "ja": "日本語",
        # Add more languages as needed
    })
    CURRENT_LANGUAGE: str = "en"
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    WINDOW_SIZE: QSize = DEFAULT_WINDOW_SIZE
    PRIVATE_MODE: bool = False
    ADBLOCK_ENABLED: bool = True
    ADBLOCK_LISTS: List[str] = field(default_factory=lambda: [
        "https://easylist.to/easylist/easylist.txt",
        "https://easylist.to/easylist/easyprivacy.txt"
    ])
    COOKIES_ENABLED: bool = True
    JAVASCRIPT_ENABLED: bool = True
    WEBGL_ENABLED: bool = False
    SAVE_SESSION: bool = True
    DARK_THEME: bool = False
    BOOKMARKS: List[Tuple[str, str]] = field(default_factory=list)
    CURRENT_PROFILE: str = "default"
    PROFILES: List[str] = field(default_factory=lambda: ["default"])
    PROFILE_ENCRYPTED: bool = False
    AUTO_SWITCH_PROFILES: Dict[str, str] = field(default_factory=dict)
    OPENAI_API_KEY: Optional[str] = None

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
            
        except Exception as e:
            ErrorHandler.handle("profile", e, show_user=True)
            return None

    def load_bookmarks(self, profile_name):
        try:
            bookmarks_file = Path(f"profiles/{profile_name}/bookmarks.json")
            if bookmarks_file.exists():
                with open(bookmarks_file, 'r', encoding='utf-8') as f:
                    self.BOOKMARKS = [tuple(item) for item in json.load(f)]
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

class AdBlocker(QWebEngineUrlRequestInterceptor):
    def __init__(self, rules=None):
        super().__init__()
        self.rules = rules or []

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        url = info.requestUrl().toString()
        if any(rule in url for rule in self.rules):
            info.block(True)

class PDFExporter:
    @staticmethod
    def export_to_pdf(browser, parent=None):
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        
        file_name, _ = QFileDialog.getSaveFileName(
            parent or browser,
            "Export as PDF",
            "",
            "PDF Files (*.pdf)"
        )
        
        if file_name:
            printer.setOutputFileName(file_name)
            print_dialog = QPrintDialog(printer, parent or browser)
            if print_dialog.exec_() == QPrintDialog.Accepted:
                browser.page().print(printer, lambda ok: 
                    QMessageBox.information(parent or browser, 
                    "Info", "PDF saved successfully!" if ok else "Failed to save PDF!"))

class LanguageManager:
    def __init__(self, config):
        self.config = config
        self.translations = {}
        self.load_translations()
    
    def load_translations(self):
        lang_dir = Path("locales")
        lang_dir.mkdir(exist_ok=True)
        
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
        self.translator = Translator()
        self.target_lang = "en"
        self.setup_ui()
    
    def setup_ui(self):
        self.translate_action = QAction("Translate Page", self.browser)
        self.translate_action.setShortcut("Ctrl+Shift+T")
        self.translate_action.triggered.connect(self.translate_page)
        self.browser.addAction(self.translate_action)
        
        self.language_menu = QMenu("Translation Language", self.browser)
        for code, name in self.browser.config.SUPPORTED_LANGUAGES.items():
            action = self.language_menu.addAction(name)
            action.setData(code)
            action.triggered.connect(lambda _, c=code: setattr(self, 'target_lang', c))
        
        self.translate_action.setMenu(self.language_menu)
    
    def translate_page(self):
        self.browser.current_tab().browser.page().toPlainText(self.handle_page_text)
    
    def handle_page_text(self, text):
        try:
            translated = self.translator.translate(text[:5000], dest=self.target_lang).text
            self.show_translation(text, translated)
        except Exception as e:
            ErrorHandler.handle("plugin", e, show_user=True)
    
    def show_translation(self, original, translated):
        tab = self.browser.new_tab()
        tab.browser.setHtml(f"""
            <html>
                <head>
                    <title>Translation Result</title>
                    <style>
                        body {{ font-family: Arial; padding: 20px; }}
                        .section {{ margin-bottom: 30px; }}
                        h3 {{ color: #2a82da; }}
                        .original {{ color: #666; }}
                        .translated {{ color: #333; font-weight: bold; }}
                    </style>
                </head>
                <body>
                    <div class="section">
                        <h3>Original ({self.translator.detect(original).lang})</h3>
                        <div class="original">{original[:2000]}...</div>
                    </div>
                    <div class="section">
                        <h3>Translation ({self.target_lang})</h3>
                        <div class="translated">{translated}</div>
                    </div>
                </body>
            </html>
        """)

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
            QSettings().setValue("openai_api_key", key)
    
    def summarize_page(self):
        if not self.api_key:
            self.configure_api()
            if not self.api_key:
                return
        
        self.browser.current_tab().browser.page().toPlainText(self.handle_page_text)
    
    def handle_page_text(self, text):
        try:
            openai.api_key = self.api_key
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Summarize this content in 3-5 bullet points in the same language as the content."},
                    {"role": "user", "content": text[:6000]}  # Limit tokens
                ],
                temperature=0.5,
                max_tokens=500
            )
            
            summary = response.choices[0].message.content
            self.show_summary(summary)
        except Exception as e:
            ErrorHandler.handle("ai", e, show_user=True)
    
    def show_summary(self, summary):
        tab = self.browser.new_tab()
        tab.browser.setHtml(f"""
            <html>
                <head>
                    <title>Content Summary</title>
                    <style>
                        body {{ font-family: Arial; padding: 20px; }}
                        .summary {{ line-height: 1.6; white-space: pre-wrap; }}
                    </style>
                </head>
                <body>
                    <h2>AI Content Summary</h2>
                    <div class="summary">{summary}</div>
                </body>
            </html>
        """)

class WebTab(QWidget):
    def __init__(self, parent=None, config: Config = None, private_mode=False, custom_title=None):
        super().__init__(parent)
        self.config = config or Config()
        self.private_mode = private_mode
        self.custom_title = custom_title
        self.reading_mode = False
        self.browser = QWebEngineView()
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.setup_web_engine()
        self.setup_actions()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.setLayout(layout)
        
        self.browser.setUrl(QUrl(self.config.HOME_PAGE))
        self.browser.urlChanged.connect(self.on_url_changed)
        
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

    def setup_actions(self):
        self.reading_mode_action = QAction("Reading Mode", self)
        self.reading_mode_action.setShortcut("Ctrl+Shift+R")
        self.reading_mode_action.triggered.connect(self.toggle_reading_mode)
        self.addAction(self.reading_mode_action)

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
            new_tab = self.parent().new_tab(private_mode=self.private_mode)
            new_tab.browser.setHtml(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Reading Mode: {self.browser.title()}</title>
                    <style>
                        body {{ margin: 0; padding: 0; background-color: {'#1e1e1e' if self.config.DARK_THEME else '#f9f9f9'}; }}
                        #reader-content {{ width: 100%; height: 100%; padding: 20px; box-sizing: border-box; }}
                    </style>
                </head>
                <body>
                    <div id="reader-content">{content}</div>
                </body>
                </html>
            """)
            
            if self.parent().tabs.count() > 1:
                QTimer.singleShot(0, lambda: self.parent().close_tab(
                    self.parent().tabs.indexOf(self)
                ))
        
        self.browser.page().runJavaScript(js, process_content)

    def exit_reading_mode(self):
        self.browser.reload()

    def on_url_changed(self, url):
        if hasattr(self.parent(), 'update_url_bar'):
            self.parent().update_url_bar(url.toString())

    def get_display_title(self):
        return self.custom_title if self.custom_title else self.browser.title()

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
        
        self.setLayout(self.layout)
        self.update_bookmarks_menu()

    def create_tool_btn(self, icon_name, callback):
        btn = QToolButton()
        btn.setIcon(QIcon.fromTheme(icon_name))
        btn.clicked.connect(callback)
        btn.setStyleSheet("QToolButton { padding: 3px; border-radius: 3px; }")
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
        is_bookmarked = any(url == bookmark[1] for bookmark in self.parent_window.config.BOOKMARKS)
        self.bookmark_btn.setChecked(is_bookmarked)

    def update_bookmarks_menu(self):
        self.bookmarks_menu.clear()
        
        if not self.parent_window.config.BOOKMARKS:
            action = self.bookmarks_menu.addAction("No bookmarks")
            action.setEnabled(False)
            return
        
        for title, url in self.parent_window.config.BOOKMARKS:
            action = self.bookmarks_menu.addAction(title)
            action.setData(url)
            action.triggered.connect(lambda _, u=url: self.parent_window.load_bookmark(u))
        
        self.bookmarks_menu.addSeparator()
        clear_action = self.bookmarks_menu.addAction("Clear All")
        clear_action.triggered.connect(self.parent_window.clear_bookmarks)

    def toggle_theme(self):
        self.parent_window.toggle_theme()

    def new_private_tab(self):
        self.parent_window.new_tab(private_mode=True)

    def export_pdf(self):
        if self.parent_window.current_tab():
            PDFExporter.export_to_pdf(self.parent_window.current_tab().browser, self.parent_window)

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
        
        # Activate built-in plugins
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
        
        main_layout.addWidget(self.tabs)
        
        self.apply_theme()
        self.new_tab()

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
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        tools_menu.addAction(settings_action)
        
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
            "Ctrl+W": lambda: self.close_tab(self.tabs.currentIndex()),
            "Ctrl+Tab": self.next_tab,
            "Ctrl+Shift+Tab": self.previous_tab,
            "Ctrl+Shift+P": self.toggle_private_mode,
            "Ctrl+Shift+N": lambda: self.new_tab(private_mode=True),
            "Ctrl+Shift+R": self.toggle_reading_mode,
            "Ctrl+Shift+T": lambda: self.translate_plugin.translate_page(),
            "Ctrl+Shift+S": lambda: self.ai_plugin.summarize_page(),
            "Ctrl+B": lambda: self.nav_bar.bookmark_btn.click(),
            "Ctrl+D": lambda: self.nav_bar.bookmark_btn.click()
        }
        
        for seq, callback in shortcuts.items():
            self.addAction(QKeySequence(seq), callback)

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
                }
                QTabBar::tab:selected {
                    background: #2a82da;
                }
                QToolButton:checked {
                    background: #2a82da;
                }
            """)
        else:
            self.setPalette(QApplication.style().standardPalette())
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

    def new_tab(self, url: str = None, private_mode: bool = False, custom_title: str = None):
        try:
            tab = WebTab(self, self.config, private_mode, custom_title)
            
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
            
            if url:
                tab.browser.setUrl(QUrl(url))
            elif not custom_title:
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
            if tab and tab.private_mode:
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
                    self.close_tab(i)
                    self.new_tab(current_url, self.config.PRIVATE_MODE, custom_title)
        except Exception as e:
            ErrorHandler.handle("ui", e, show_user=True)

    def toggle_reading_mode(self):
        if self.current_tab():
            self.current_tab().toggle_reading_mode()

    def toggle_bookmark(self, title: str, url: str):
        try:
            bookmark = (title, url)
            
            if bookmark in self.config.BOOKMARKS:
                self.config.BOOKMARKS.remove(bookmark)
                self.statusBar().showMessage("Bookmark removed", 2000)
            else:
                self.config.BOOKMARKS.append(bookmark)
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
        
        for title, url in self.config.BOOKMARKS:
            action = self.bookmarks_submenu.addAction(title)
            action.setData(url)
            action.triggered.connect(lambda _, u=url: self.load_bookmark(u))

    def load_bookmark(self, url: str):
        if self.current_tab():
            self.current_tab().browser.setUrl(QUrl(url))

    def clear_bookmarks(self):
        try:
            self.config.BOOKMARKS.clear()
            self.config.save_bookmarks(self.config.CURRENT_PROFILE)
            self.update_bookmarks_menu()
            self.statusBar().showMessage("All bookmarks cleared", 2000)
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)

    def toggle_theme(self):
        self.config.DARK_THEME = not self.config.DARK_THEME
        self.apply_theme()
        self.statusBar().showMessage(
            f"Theme: {'Dark' if self.config.DARK_THEME else 'Light'}", 
            2000
        )

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
                        "custom_title": tab.custom_title
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
                        tab_data.get("custom_title")
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
        dialog.resize(500, 400)
        
        layout = QVBoxLayout()
        
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
        
        # Privacy
        privacy_group = QGroupBox("Privacy Settings")
        privacy_layout = QVBoxLayout()
        
        adblock_check = QCheckBox("Ad Blocker")
        adblock_check.setChecked(self.config.ADBLOCK_ENABLED)
        
        cookies_check = QCheckBox("Enable Cookies")
        cookies_check.setChecked(self.config.COOKIES_ENABLED)
        
        javascript_check = QCheckBox("Enable JavaScript")
        javascript_check.setChecked(self.config.JAVASCRIPT_ENABLED)
        
        webgl_check = QCheckBox("Enable WebGL")
        webgl_check.setChecked(self.config.WEBGL_ENABLED)
        
        privacy_layout.addWidget(adblock_check)
        privacy_layout.addWidget(cookies_check)
        privacy_layout.addWidget(javascript_check)
        privacy_layout.addWidget(webgl_check)
        privacy_group.setLayout(privacy_layout)
        
        # Session
        session_group = QGroupBox("Session Settings")
        session_layout = QVBoxLayout()
        
        save_session_check = QCheckBox("Save Session")
        save_session_check.setChecked(self.config.SAVE_SESSION)
        
        session_layout.addWidget(save_session_check)
        session_group.setLayout(session_layout)
        
        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        
        layout.addLayout(home_page_layout)
        layout.addLayout(search_engine_layout)
        layout.addWidget(privacy_group)
        layout.addWidget(session_group)
        layout.addWidget(button_box)
        dialog.setLayout(layout)
        
        if dialog.exec_() == QDialog.Accepted:
            self.config.HOME_PAGE = home_page_input.text()
            self.config.DEFAULT_SEARCH_ENGINE = search_engine_combo.currentText()
            self.config.ADBLOCK_ENABLED = adblock_check.isChecked()
            self.config.COOKIES_ENABLED = cookies_check.isChecked()
            self.config.JAVASCRIPT_ENABLED = javascript_check.isChecked()
            self.config.WEBGL_ENABLED = webgl_check.isChecked()
            self.config.SAVE_SESSION = save_session_check.isChecked()
            
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if tab:
                    tab.setup_web_engine()

    def show_plugin_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Plugin Manager")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout()
        
        plugin_table = QTableWidget()
        plugin_table.setColumnCount(5)
        plugin_table.setHorizontalHeaderLabels([
            "Name", "Version", "Author", "Status", "Description"
        ])
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
        
        btn_box = QDialogButtonBox()
        toggle_btn = btn_box.addButton("Toggle Status", QDialogButtonBox.ActionRole)
        toggle_btn.clicked.connect(lambda: self.toggle_plugin(plugin_table))
        
        refresh_btn = btn_box.addButton("Refresh", QDialogButtonBox.ActionRole)
        refresh_btn.clicked.connect(lambda: self.refresh_plugin_list(plugin_table))
        
        btn_box.addButton(QDialogButtonBox.Close)
        btn_box.rejected.connect(dialog.reject)
        
        layout.addWidget(plugin_table)
        layout.addWidget(btn_box)
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