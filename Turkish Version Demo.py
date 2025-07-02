import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from PyQt5.QtCore import (QUrl, QSize, Qt, QSettings, QFile, QTextStream, 
                          QStandardPaths, QTimer)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QToolButton, QTabWidget, 
                            QMenu, QAction, QMessageBox, QInputDialog, 
                            QFileDialog, QLabel)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo
from PyQt5.QtGui import QIcon, QKeySequence, QPalette, QColor, QCursor

# Constants
APP_NAME = "Gyarados"
VERSION = "1.2.0"
DEFAULT_WINDOW_SIZE = QSize(1280, 720)

# Logging Setup
def setup_logging():
    """Configure application logging"""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.INFO)
    
    # File handler with rotation (5MB x 3 files)
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
    """Centralized error handling with user-friendly messages"""
    ERROR_TYPES = {
        "ui": ("Arayüz Hatası", "Arayüz işlemi sırasında bir sorun oluştu. Lütfen tekrar deneyin."),
        "file": ("Dosya Hatası", "Dosya işlemi sırasında hata oluştu. Yetkileri kontrol edin."),
        "network": ("Ağ Hatası", "Ağ bağlantısı kurulamadı. İnternetinizi kontrol edin."),
        "general": ("Hata", "Beklenmedik bir hata oluştu. Lütfen uygulamayı yeniden başlatın.")
    }

    @classmethod
    def handle(cls, error_type: str, error: Exception, show_user: bool = False):
        """Log and optionally show errors"""
        error_title, error_msg = cls.ERROR_TYPES.get(error_type, cls.ERROR_TYPES["general"])
        logger.error(f"{error_type.upper()} - {str(error)}")
        
        if show_user:
            QMessageBox.warning(None, error_title, error_msg)

@dataclass
class Config:
    """Application configuration with persistence"""
    HOME_PAGE: str = "https://duckduckgo.com"
    SEARCH_ENGINES: Dict[str, str] = field(default_factory=lambda: {
        "DuckDuckGo": "https://duckduckgo.com/?q={}",
        "Google": "https://www.google.com/search?q={}",
        "Bing": "https://www.bing.com/search?q={}",
        "Yandex": "https://yandex.com.tr/search/?text={}"
    })
    DEFAULT_SEARCH_ENGINE: str = "DuckDuckGo"
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

    @classmethod
    def load(cls) -> 'Config':
        """Load config from persistent storage"""
        settings = QSettings(APP_NAME, "Browser")
        config = cls()
        
        for field in cls.__dataclass_fields__:
            if settings.contains(field):
                value = settings.value(field)
                if field == "WINDOW_SIZE":
                    value = QSize(value)
                setattr(config, field, value)
        
        config.load_bookmarks()
        return config

    def save(self):
        """Save config to persistent storage"""
        settings = QSettings(APP_NAME, "Browser")
        for field in self.__dataclass_fields__:
            value = getattr(self, field)
            if isinstance(value, QSize):
                value = [value.width(), value.height()]
            settings.setValue(field, value)
        
        self.save_bookmarks()

    def load_bookmarks(self):
        """Load bookmarks from JSON file"""
        try:
            bookmarks_file = Path("data/bookmarks.json")
            if bookmarks_file.exists():
                with open(bookmarks_file, 'r', encoding='utf-8') as f:
                    self.BOOKMARKS = [tuple(item) for item in json.load(f)]
        except Exception as e:
            ErrorHandler.handle("file", e)
            self.BOOKMARKS = []

    def save_bookmarks(self):
        """Save bookmarks to JSON file safely"""
        try:
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            
            # Write to temp file first
            temp_file = data_dir / "bookmarks_temp.json"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.BOOKMARKS, f, ensure_ascii=False, indent=2)
            
            # Atomic rename
            bookmarks_file = data_dir / "bookmarks.json"
            if bookmarks_file.exists():
                bookmarks_file.unlink()
            temp_file.rename(bookmarks_file)
        except Exception as e:
            ErrorHandler.handle("file", e)

class AdBlocker(QWebEngineUrlRequestInterceptor):
    """Block ads using filter lists"""
    def __init__(self, rules=None):
        super().__init__()
        self.rules = rules or []

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        url = info.requestUrl().toString()
        if any(rule in url for rule in self.rules):
            info.block(True)

class WebTab(QWidget):
    """Represents a single browser tab"""
    def __init__(self, parent=None, config: Config = None, private_mode=False, custom_title=None):
        super().__init__(parent)
        self.config = config or Config()
        self.private_mode = private_mode
        self.custom_title = custom_title
        self.browser = QWebEngineView()
        self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.setup_web_engine()
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.setLayout(layout)
        
        self.browser.setUrl(QUrl(self.config.HOME_PAGE))
        self.browser.urlChanged.connect(self.on_url_changed)
        
        if private_mode:
            self.setStyleSheet("background-color: #2d2d2d;")

    def setup_web_engine(self):
        """Configure web engine settings"""
        settings = self.browser.settings()
        
        # Privacy settings
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, self.config.JAVASCRIPT_ENABLED)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, self.config.WEBGL_ENABLED)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, False)
        
        # Performance settings
        settings.setAttribute(QWebEngineSettings.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        
        # Configure profile
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
        
        # Ad blocking
        if self.config.ADBLOCK_ENABLED:
            interceptor = AdBlocker(self.config.ADBLOCK_LISTS)
            profile.setUrlRequestInterceptor(interceptor)

    def on_url_changed(self, url):
        """Handle URL changes"""
        if hasattr(self.parent(), 'update_url_bar'):
            self.parent().update_url_bar(url.toString())

    def get_display_title(self):
        """Get the title to display in tab"""
        return self.custom_title if self.custom_title else self.browser.title()

class NavigationBar(QWidget):
    """Browser navigation toolbar"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setup_ui()

    def setup_ui(self):
        """Initialize UI components"""
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(5)
        
        # Navigation buttons
        self.back_btn = self.create_tool_btn("go-previous", self.navigate_back)
        self.forward_btn = self.create_tool_btn("go-next", self.navigate_forward)
        self.reload_btn = self.create_tool_btn("view-refresh", self.reload_page)
        self.home_btn = self.create_tool_btn("go-home", self.go_home)
        
        # Bookmarks
        self.bookmark_btn = self.create_tool_btn("bookmark-new", self.toggle_bookmark)
        self.bookmark_btn.setCheckable(True)
        self.bookmarks_menu = QMenu()
        self.bookmark_btn.setMenu(self.bookmarks_menu)
        self.bookmark_btn.setPopupMode(QToolButton.InstantPopup)
        
        # Theme toggle
        self.theme_btn = self.create_tool_btn("color-management", self.toggle_theme)
        
        # Private tab
        self.private_btn = self.create_tool_btn("security-high", self.new_private_tab)
        self.private_btn.setToolTip("Yeni gizli sekme (Ctrl+Shift+N)")
        
        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Arama yapın veya URL girin")
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        
        # Search button
        self.search_btn = self.create_tool_btn("system-search", self.navigate_to_url)
        
        # Assemble layout
        self.layout.addWidget(self.back_btn)
        self.layout.addWidget(self.forward_btn)
        self.layout.addWidget(self.reload_btn)
        self.layout.addWidget(self.home_btn)
        self.layout.addWidget(self.bookmark_btn)
        self.layout.addWidget(self.theme_btn)
        self.layout.addWidget(self.private_btn)
        self.layout.addWidget(self.url_bar, 1)
        self.layout.addWidget(self.search_btn)
        
        self.setLayout(self.layout)
        self.update_bookmarks_menu()

    def create_tool_btn(self, icon_name, callback):
        """Helper to create toolbar buttons"""
        btn = QToolButton()
        btn.setIcon(QIcon.fromTheme(icon_name))
        btn.clicked.connect(callback)
        btn.setStyleSheet("QToolButton { padding: 3px; border-radius: 3px; }")
        return btn

    def navigate_back(self):
        """Navigate back in history"""
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.back()

    def navigate_forward(self):
        """Navigate forward in history"""
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.forward()

    def reload_page(self):
        """Reload current page"""
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.reload()

    def go_home(self):
        """Navigate to home page"""
        if self.parent_window.current_tab():
            self.parent_window.current_tab().browser.setUrl(QUrl(self.parent_window.config.HOME_PAGE))

    def navigate_to_url(self):
        """Navigate to URL or search"""
        url = self.url_bar.text()
        if not self.parent_window.current_tab():
            return
            
        if '.' in url and ' ' not in url:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            self.parent_window.current_tab().browser.setUrl(QUrl(url))
        else:
            search_url = self.parent_window.config.SEARCH_ENGINES.get(
                self.parent_window.config.DEFAULT_SEARCH_ENGINE,
                "https://duckduckgo.com/?q={}"
            )
            self.parent_window.current_tab().browser.setUrl(QUrl(search_url.format(url)))

    def toggle_bookmark(self):
        """Add/remove current page from bookmarks"""
        if self.parent_window.current_tab():
            url = self.parent_window.current_tab().browser.url().toString()
            title = self.parent_window.current_tab().get_display_title()
            
            if url:
                self.parent_window.toggle_bookmark(title, url)
                self.update_bookmark_state(url)

    def update_bookmark_state(self, url):
        """Update bookmark button state"""
        is_bookmarked = any(url == bookmark[1] for bookmark in self.parent_window.config.BOOKMARKS)
        self.bookmark_btn.setChecked(is_bookmarked)

    def update_bookmarks_menu(self):
        """Refresh bookmarks menu"""
        self.bookmarks_menu.clear()
        
        if not self.parent_window.config.BOOKMARKS:
            action = self.bookmarks_menu.addAction("Yer imi yok")
            action.setEnabled(False)
            return
        
        for title, url in self.parent_window.config.BOOKMARKS:
            action = self.bookmarks_menu.addAction(title)
            action.setData(url)
            action.triggered.connect(lambda _, u=url: self.parent_window.load_bookmark(u))
        
        self.bookmarks_menu.addSeparator()
        clear_action = self.bookmarks_menu.addAction("Tümünü Temizle")
        clear_action.triggered.connect(self.parent_window.clear_bookmarks)

    def toggle_theme(self):
        """Toggle between light/dark theme"""
        self.parent_window.toggle_theme()

    def new_private_tab(self):
        """Open new private tab"""
        self.parent_window.new_tab(private_mode=True)

class MainWindow(QMainWindow):
    """Main application window"""
    def __init__(self, config: Config = None):
        super().__init__()
        self.config = config or Config.load()
        self.setup_window()
        self.setup_shortcuts()
        
        if self.config.SAVE_SESSION:
            self.load_session()
        
        # Show initial status
        self.statusBar().showMessage(f"{APP_NAME} v{VERSION} başlatıldı", 3000)

    def setup_window(self):
        """Initialize main window UI"""
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme("web-browser"))
        self.resize(self.config.WINDOW_SIZE)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        central_widget.setLayout(main_layout)
        
        # Navigation bar
        self.nav_bar = NavigationBar(self)
        main_layout.addWidget(self.nav_bar)
        
        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        
        # Tab context menu
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        
        # Tab double click to rename
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)
        
        main_layout.addWidget(self.tabs)
        
        # Apply theme
        self.apply_theme()
        
        # Create initial tab
        self.new_tab()

    def setup_shortcuts(self):
        """Configure keyboard shortcuts"""
        shortcuts = {
            "Ctrl+T": self.new_tab,
            "Ctrl+W": lambda: self.close_tab(self.tabs.currentIndex()),
            "Ctrl+Tab": self.next_tab,
            "Ctrl+Shift+Tab": self.previous_tab,
            "Ctrl+Shift+P": self.toggle_private_mode,
            "Ctrl+Shift+N": lambda: self.new_tab(private_mode=True)
        }
        
        for seq, callback in shortcuts.items():
            self.addAction(QKeySequence(seq), callback)

    def apply_theme(self):
        """Apply current theme settings"""
        palette = QPalette()
        
        if self.config.DARK_THEME:
            # Dark theme colors
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
            """)
        else:
            # Light theme (system defaults)
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
            """)
        
        self.setPalette(palette)

    def new_tab(self, url: str = None, private_mode: bool = False, custom_title: str = None):
        """Create new browser tab"""
        try:
            tab = WebTab(self, self.config, private_mode, custom_title)
            
            # Determine tab title
            if custom_title:
                tab_title = custom_title
            else:
                tab_title = "Yeni Sekme"
            
            if private_mode:
                tab_title = f"🔒 {tab_title}" if custom_title else "🔒 Gizli Sekme"
            
            # Add tab
            index = self.tabs.addTab(tab, tab_title)
            self.tabs.setCurrentIndex(index)
            
            # Connect signals
            tab.browser.titleChanged.connect(
                lambda title, idx=index: self.update_tab_title(idx))
            
            tab.browser.urlChanged.connect(
                lambda url: self.update_url_bar(url.toString()))
            
            tab.browser.urlChanged.connect(
                lambda url: self.nav_bar.update_bookmark_state(url.toString()))
            
            # Visual distinction for private tabs
            if private_mode:
                self.tabs.tabBar().setTabTextColor(index, QColor("#ff6b6b"))
            
            # Load URL if specified
            if url:
                tab.browser.setUrl(QUrl(url))
            elif not custom_title:  # Don't override home page for renamed tabs
                tab.browser.setUrl(QUrl(self.config.HOME_PAGE))
            
            return tab
        except Exception as e:
            ErrorHandler.handle("ui", e, show_user=True)

    def close_tab(self, index: int):
        """Close tab at specified index"""
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
        """Get currently active tab"""
        return self.tabs.currentWidget()

    def update_url_bar(self, url: str):
        """Update URL bar with current page URL"""
        self.nav_bar.url_bar.setText(url)
        self.nav_bar.url_bar.setCursorPosition(0)
        self.nav_bar.update_bookmark_state(url)

    def update_tab_title(self, index: int):
        """Update tab title based on page title or custom name"""
        tab = self.tabs.widget(index)
        if tab:
            title = tab.get_display_title()
            prefix = "🔒 " if tab.private_mode else ""
            
            if len(title) > 15:
                title = title[:15] + "..."
            
            self.tabs.setTabText(index, prefix + title)

    def tab_changed(self, index: int):
        """Handle tab switch events"""
        tab = self.tabs.widget(index)
        if tab:
            self.update_url_bar(tab.browser.url().toString())

    def show_tab_context_menu(self, pos):
        """Show context menu for tab"""
        index = self.tabs.tabBar().tabAt(pos)
        if index >= 0:
            menu = QMenu()
            
            # Close tab
            close_action = QAction("Sekmeyi Kapat", self)
            close_action.triggered.connect(lambda: self.close_tab(index))
            menu.addAction(close_action)
            
            # Rename tab
            rename_action = QAction("Sekmeyi Yeniden Adlandır", self)
            rename_action.triggered.connect(lambda: self.rename_tab(index))
            menu.addAction(rename_action)
            
            # Private tab indicator
            tab = self.tabs.widget(index)
            if tab and tab.private_mode:
                menu.addSeparator()
                private_action = QAction("🔒 Gizli Sekme", self)
                private_action.setEnabled(False)
                menu.addAction(private_action)
            
            menu.exec_(QCursor.pos())

    def rename_tab(self, index: int):
        """Rename specified tab"""
        tab = self.tabs.widget(index)
        if tab:
            current_title = tab.custom_title if tab.custom_title else tab.browser.title()
            
            new_title, ok = QInputDialog.getText(
                self,
                "Sekmeyi Yeniden Adlandır",
                "Yeni başlık:",
                text=current_title
            )
            
            if ok and new_title:
                tab.custom_title = new_title
                self.update_tab_title(index)

    def next_tab(self):
        """Switch to next tab"""
        current = self.tabs.currentIndex()
        new_index = current + 1 if current < self.tabs.count() - 1 else 0
        self.tabs.setCurrentIndex(new_index)

    def previous_tab(self):
        """Switch to previous tab"""
        current = self.tabs.currentIndex()
        new_index = current - 1 if current > 0 else self.tabs.count() - 1
        self.tabs.setCurrentIndex(new_index)

    def toggle_private_mode(self):
        """Toggle private browsing mode"""
        try:
            self.config.PRIVATE_MODE = not self.config.PRIVATE_MODE
            self.config.set_private_mode(self.config.PRIVATE_MODE)
            self.statusBar().showMessage(
                f"Gizli Mod: {'Açık' if self.config.PRIVATE_MODE else 'Kapalı'}", 
                2000
            )
            
            # Recreate all tabs with new privacy setting
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if tab:
                    current_url = tab.browser.url().toString()
                    custom_title = tab.custom_title
                    self.close_tab(i)
                    self.new_tab(current_url, self.config.PRIVATE_MODE, custom_title)
        except Exception as e:
            ErrorHandler.handle("ui", e, show_user=True)

    def toggle_bookmark(self, title: str, url: str):
        """Toggle bookmark for current page"""
        try:
            bookmark = (title, url)
            
            if bookmark in self.config.BOOKMARKS:
                self.config.BOOKMARKS.remove(bookmark)
                self.statusBar().showMessage("Yer imi kaldırıldı", 2000)
            else:
                self.config.BOOKMARKS.append(bookmark)
                self.statusBar().showMessage("Yer imi eklendi", 2000)
            
            # Persist changes
            self.config.save_bookmarks()
            self.nav_bar.update_bookmarks_menu()
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)

    def load_bookmark(self, url: str):
        """Load bookmarked URL in current tab"""
        if self.current_tab():
            self.current_tab().browser.setUrl(QUrl(url))

    def clear_bookmarks(self):
        """Remove all bookmarks"""
        try:
            self.config.BOOKMARKS.clear()
            self.config.save_bookmarks()
            self.nav_bar.update_bookmarks_menu()
            self.statusBar().showMessage("Tüm yer imleri temizlendi", 2000)
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)

    def toggle_theme(self):
        """Toggle between light/dark theme"""
        self.config.DARK_THEME = not self.config.DARK_THEME
        self.apply_theme()
        self.statusBar().showMessage(
            f"Tema: {'Koyu' if self.config.DARK_THEME else 'Açık'}", 
            2000
        )

    def save_session(self):
        """Save current session state"""
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
            
            settings = QSettings(APP_NAME, "Browser")
            settings.setValue("session", json.dumps(session))
        except Exception as e:
            ErrorHandler.handle("file", e)

    def load_session(self):
        """Load saved session state"""
        try:
            settings = QSettings(APP_NAME, "Browser")
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

    def closeEvent(self, event):
        """Handle window close event"""
        try:
            self.save_session()
            self.config.save()
            event.accept()
        except Exception as e:
            ErrorHandler.handle("general", e, show_user=True)
            event.accept()

def main():
    """Application entry point"""
    try:
        logger.info(f"{APP_NAME} v{VERSION} başlatılıyor")
        
        # High DPI support
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
        
        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setApplicationVersion(VERSION)
        
        # Load config
        try:
            config = Config.load()
            logger.info("Yapılandırma başarıyla yüklendi")
        except Exception as e:
            ErrorHandler.handle("file", e, show_user=True)
            config = Config()  # Fallback to defaults
        
        # Create and show main window
        window = MainWindow(config)
        window.show()
        
        logger.info("Uygulama başarıyla başlatıldı")
        sys.exit(app.exec_())
        
    except Exception as e:
        ErrorHandler.handle("general", e, show_user=True)
        logger.critical(f"Uygulama başlatılamadı: {str(e)}")

if __name__ == "__main__":
    main()