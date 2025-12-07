#!/usr/bin/env python3
"""
Task Manager GUI - Display running processes with RAM usage
PyQt5-based GUI showing system memory and process information
"""

import sys
import os
import json
import psutil
import threading
import subprocess
import shutil
import ctypes
try:
    import pygame
    GAMEPAD_AVAILABLE = True
except ImportError:
    GAMEPAD_AVAILABLE = False
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLabel, QProgressBar, QHeaderView, QMenu, QMessageBox, QPushButton,
    QDialog, QRadioButton, QButtonGroup, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject, QPoint, QRect, QEvent
from PyQt5.QtGui import QFont, QColor, QBrush, QKeyEvent
from datetime import datetime

# Config file path
CONFIG_FILE = os.path.expanduser('~/.task_manager_config.json')


def load_theme():
    """Load saved theme from config file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # return saved theme if present
                if 'theme' in config:
                    return config.get('theme', 'light')
    except Exception as e:
        print(f"Error loading theme: {e}")
    # No saved theme -> detect system preference
    try:
        system_theme = detect_system_theme()
        if system_theme in ('dark', 'light'):
            return system_theme
    except Exception:
        pass
    return 'light'


def detect_system_theme():
    """Detect the system's theme preference and return 'dark' or 'light'.

    Attempts (in order):
    - GNOME `gsettings get org.gnome.desktop.interface color-scheme`
    - GNOME `gsettings get org.gnome.desktop.interface gtk-theme`
    - Environment hints (XDG_CURRENT_DESKTOP)
    Falls back to 'light'.
    """
    # Try GNOME color-scheme (GNOME 42+)
    try:
        out = subprocess.run([
            'gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'
        ], capture_output=True, text=True)
        if out.returncode == 0:
            val = out.stdout.strip().strip("'\" ")
            if 'dark' in val.lower():
                return 'dark'
            if 'light' in val.lower():
                return 'light'
    except Exception:
        pass

    # Try GTK theme name
    try:
        out = subprocess.run([
            'gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'
        ], capture_output=True, text=True)
        if out.returncode == 0:
            val = out.stdout.strip().strip("'\" ")
            if 'dark' in val.lower():
                return 'dark'
            # some themes include 'Light' or not; default to light
            return 'light'
    except Exception:
        pass

    # Fallback: check desktop env hints
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '') or os.environ.get('DESKTOP_SESSION', '')
    desktop = desktop.lower()
    if 'gnome' in desktop or 'unity' in desktop:
        # assume light unless GTK says dark
        return 'light'
    if 'kde' in desktop or 'plasma' in desktop:
        # KDE users often choose dark themes; attempt to read QT setting could be complex
        return 'light'

    return 'light'


def detect_gpu_info():
    """Detect GPU name and driver version.

    Tries (in order):
    - `nvidia-smi --query-gpu=name,driver_version`
    - `/proc/driver/nvidia/version`
    - `glxinfo` (OpenGL renderer/version)
    - `lspci -nnk` (VGA/3D controller and kernel driver)
    Returns a dict: { 'name': str, 'driver': str }
    """
    info = {'name': 'Unknown', 'driver': 'Unknown'}

    try:
        # NVIDIA users - nvidia-smi provides clear info (works on Windows and Linux if in PATH)
        if shutil.which('nvidia-smi'):
            out = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
                capture_output=True, text=True
            )
            if out.returncode == 0 and out.stdout.strip():
                line = out.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(',')]
                name = parts[0] if parts else 'NVIDIA GPU'
                driver = parts[1] if len(parts) > 1 else 'Unknown'
                return {'name': name, 'driver': driver}
    except Exception:
        pass

    # Windows-specific fallback via PowerShell WMI
    if os.name == 'nt':
        try:
            ps_cmd = [
                'powershell', '-NoProfile', '-Command',
                'Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,DriverVersion | '
                'ForEach-Object { "$($_.Name)|$($_.DriverVersion)" }'
            ]
            out = subprocess.run(ps_cmd, capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                line = out.stdout.strip().splitlines()[0]
                if '|' in line:
                    name, driver = [part.strip() or 'Unknown' for part in line.split('|', 1)]
                    return {'name': name, 'driver': driver}
        except Exception:
            pass

    try:
        # Check for /proc driver info (NVIDIA)
        if os.path.exists('/proc/driver/nvidia/version'):
            with open('/proc/driver/nvidia/version', 'r') as f:
                txt = f.read().strip()
                # Try to find a version-like token
                import re
                m = re.search(r"(\d+\.\d+(?:\.\d+)*)", txt)
                ver = m.group(1) if m else txt.splitlines()[0]
                return {'name': 'NVIDIA GPU', 'driver': ver}
    except Exception:
        pass

    try:
        # glxinfo (OpenGL renderer and version)
        if shutil.which('glxinfo'):
            out = subprocess.run(['glxinfo'], capture_output=True, text=True)
            if out.returncode == 0 and out.stdout:
                renderer = ''
                version = ''
                for line in out.stdout.splitlines():
                    if 'OpenGL renderer string' in line:
                        renderer = line.split(':', 1)[1].strip()
                    if 'OpenGL version string' in line:
                        version = line.split(':', 1)[1].strip()
                if renderer:
                    return {'name': renderer, 'driver': version or 'Unknown'}
    except Exception:
        pass

    try:
        # lspci fallback: try to find VGA/3D controller and kernel driver
        if shutil.which('lspci'):
            out = subprocess.run(['lspci', '-nnk'], capture_output=True, text=True)
            if out.returncode == 0 and out.stdout:
                lines = out.stdout.splitlines()
                for i, line in enumerate(lines):
                    low = line.lower()
                    if 'vga compatible controller' in low or '3d controller' in low or 'display controller' in low:
                        # device name after the first ':'
                        name = line.split(':', 1)[1].strip()
                        driver = 'Unknown'
                        for j in range(i + 1, min(i + 6, len(lines))):
                            if 'kernel driver in use:' in lines[j].lower():
                                driver = lines[j].split(':', 1)[1].strip()
                                break
                        return {'name': name, 'driver': driver}
    except Exception:
        pass

    return info


def detect_cpu_name():
    """Detect the installed CPU model name."""
    try:
        if os.name != 'nt' and os.path.exists('/proc/cpuinfo'):
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if 'model name' in line:
                        return line.split(':', 1)[1].strip()
    except Exception:
        pass

    try:
        import platform
        name = platform.processor() or platform.machine()
        if name:
            return name
    except Exception:
        pass

    return 'Unknown CPU'


def detect_os_name():
    """Detect the installed operating system name."""
    try:
        import platform
        system = platform.system() or 'Unknown OS'
        release = platform.release() or ''
        if release:
            return f"{system} {release}"
        return system
    except Exception:
        return 'Unknown OS'


def is_windows_admin() -> bool:
    """Return True if running with admin rights on Windows."""
    if os.name != 'nt':
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def save_theme(theme_name):
    """Save theme to config file"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['theme'] = theme_name
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving theme: {e}")


def load_hide_system_processes():
    """Load hide system processes setting from config file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('hide_system_processes', False)
    except Exception as e:
        print(f"Error loading hide_system_processes: {e}")
    return False


def save_hide_system_processes(hide_system: bool):
    """Save hide system processes setting to config file"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['hide_system_processes'] = hide_system
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving hide_system_processes: {e}")


def load_hide_inaccessible_processes():
    """Load hide inaccessible processes setting from config file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('hide_inaccessible_processes', False)
    except Exception as e:
        print(f"Error loading hide_inaccessible_processes: {e}")
    return False


def save_hide_inaccessible_processes(hide_inaccessible: bool):
    """Save hide inaccessible processes setting to config file"""
    try:
        config = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        config['hide_inaccessible_processes'] = hide_inaccessible
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving hide_inaccessible_processes: {e}")


class DataFetcher(QObject):
    """Worker thread to fetch system data without blocking UI"""
    data_ready = pyqtSignal(dict, list)
    
    def __init__(self):
        super().__init__()
        self.process_cache = {}
    
    def fetch_data(self):
        """Fetch memory and process data in background thread"""
        def _fetch():
            try:
                mem = psutil.virtual_memory()
                mem_info = {
                    'total': mem.total / (1024**3),
                    'used': mem.used / (1024**3),
                    'available': mem.available / (1024**3),
                    'percent': mem.percent
                }
                
                processes = []
                for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'username']):
                    try:
                        pinfo = proc.as_dict(attrs=['pid', 'name', 'memory_info', 'username'])
                        memory_mb = pinfo['memory_info'].rss / (1024**2)
                        disk_mb = 0.0
                        try:
                            io_counters = proc.io_counters()
                            disk_mb = (io_counters.read_bytes + io_counters.write_bytes) / (1024**2)
                        except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                            disk_mb = 0.0
                        processes.append({
                            'pid': pinfo['pid'],
                            'name': pinfo['name'][:50],
                            'username': pinfo.get('username') or 'unknown',
                            'memory_mb': memory_mb,
                            'memory_percent': proc.memory_percent(),
                            'disk_io_mb': disk_mb
                        })
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
                
                processes.sort(key=lambda x: x['memory_mb'], reverse=True)
                self.data_ready.emit(mem_info, processes[:100])  # Limit to top 100 processes
            except Exception as e:
                print(f"Error fetching data: {e}")
        
        # Run fetch in background thread to not block UI
        threading.Thread(target=_fetch, daemon=True).start()


class ThemeDialog(QDialog):
    """Dialog for selecting application theme"""
    def __init__(self, parent=None, current_theme='light'):
        super().__init__(parent)
        self.setWindowTitle('Select Theme')
        self.setFixedSize(300, 200)
        
        layout = QVBoxLayout()
        
        self.button_group = QButtonGroup()
        
        # Light theme
        light_radio = QRadioButton('Light Theme')
        light_radio.setChecked(current_theme == 'light')
        self.button_group.addButton(light_radio, 0)
        layout.addWidget(light_radio)
        
        # Dark theme
        dark_radio = QRadioButton('Dark Theme')
        dark_radio.setChecked(current_theme == 'dark')
        self.button_group.addButton(dark_radio, 1)
        layout.addWidget(dark_radio)
        
        # Modern theme
        modern_radio = QRadioButton('Modern Theme')
        modern_radio.setChecked(current_theme == 'modern')
        self.button_group.addButton(modern_radio, 2)
        layout.addWidget(modern_radio)

        # System default theme
        system_radio = QRadioButton('System Default')
        system_radio.setChecked(current_theme == 'system')
        self.button_group.addButton(system_radio, 3)
        layout.addWidget(system_radio)
        
        layout.addStretch()
        
        # OK button
        ok_button = QPushButton('Apply')
        ok_button.clicked.connect(self.accept)
        layout.addWidget(ok_button)
        
        self.setLayout(layout)
        
        # Center dialog on parent window
        if parent:
            self.center_on_parent(parent)
    
    def center_on_parent(self, parent):
        """Center dialog on parent window"""
        parent_geometry = parent.geometry()
        dialog_width = self.width()
        dialog_height = self.height()
        
        x = parent_geometry.x() + (parent_geometry.width() - dialog_width) // 2
        y = parent_geometry.y() + (parent_geometry.height() - dialog_height) // 2
        
        self.move(x, y)
    
    def get_theme(self):
        """Get selected theme"""
        themes = ['light', 'dark', 'modern', 'system']
        idx = self.button_group.checkedId()
        # Ensure index is in range
        if idx < 0 or idx >= len(themes):
            return 'light'
        return themes[idx]


class TaskManagerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data_fetcher = DataFetcher()
        self.current_theme = load_theme()  # Load saved theme
        
        # Track selected rows
        self.selected_pid = None
        
        # Initialize gamepad support early (before initUI)
        self.gamepad = None
        self.gamepad_name = None
        self.gamepad_button_states = {}
        self.gamepad_last_axis = {'x': 0, 'y': 0}
        self.gamepad_repeat_counter = 0
        self.gamepad_repeat_delay = 3  # Initial delay before repeat (in 100ms cycles)
        self.active_menu = None  # Track active context menu
        self.gamepad_focus_mode = 'table'  # Can be 'table', 'hide_system', or 'hide_inaccessible'
        if GAMEPAD_AVAILABLE:
            try:
                pygame.init()
                pygame.joystick.init()
                if pygame.joystick.get_count() > 0:
                    self.gamepad = pygame.joystick.Joystick(0)
                    self.gamepad.init()
                    self.gamepad_name = self.gamepad.get_name()
                    print(f"Gamepad connected: {self.gamepad_name}")
            except Exception as e:
                print(f"Gamepad initialization failed: {e}")
        
        # Initialize UI
        self.initUI()
        
        # Start gamepad timer after UI is ready
        if self.gamepad:
            self.gamepad_timer = QTimer()
            self.gamepad_timer.timeout.connect(self.process_gamepad_input)
            self.gamepad_timer.start(100)  # Poll gamepad every 100ms
        
        # Timer for auto-refresh - faster updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.request_data_update)
        self.timer.start(500)  # Update every 500ms for snappier feel
        
        # Request initial data
        self.request_data_update()
    
    def initUI(self):
        """Initialize the user interface"""
        self.setWindowTitle('Task Manager - System Monitor')
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        
        # Title
        title = QLabel('Task Manager - System Resource Monitor')
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        main_layout.addWidget(title)
        
        # System memory section
        memory_layout = QHBoxLayout()
        
        # Total RAM
        total_label = QLabel('Total RAM:')
        total_label.setStyleSheet("font-weight: bold;")
        self.total_ram_label = QLabel()
        memory_layout.addWidget(total_label)
        memory_layout.addWidget(self.total_ram_label)
        memory_layout.addSpacing(30)
        
        # Used RAM
        used_label = QLabel('Used RAM:')
        used_label.setStyleSheet("font-weight: bold;")
        self.used_ram_label = QLabel()
        memory_layout.addWidget(used_label)
        memory_layout.addWidget(self.used_ram_label)
        memory_layout.addSpacing(30)
        
        # Available RAM
        available_label = QLabel('Available RAM:')
        available_label.setStyleSheet("font-weight: bold;")
        self.available_ram_label = QLabel()
        memory_layout.addWidget(available_label)
        memory_layout.addWidget(self.available_ram_label)
        memory_layout.addStretch()
        
        main_layout.addLayout(memory_layout)
        
        # Memory progress bar
        bar_layout = QHBoxLayout()
        bar_label = QLabel('Memory Usage:')
        bar_label.setStyleSheet("font-weight: bold;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_label = QLabel()
        bar_layout.addWidget(bar_label)
        bar_layout.addWidget(self.progress_bar, 1)
        bar_layout.addWidget(self.progress_label)
        
        # Sudo button
        self.sudo_button = QPushButton('Run as Sudo')
        self.sudo_button.clicked.connect(self.run_with_sudo)
        self.sudo_button.setMaximumWidth(120)
        bar_layout.addWidget(self.sudo_button)
        
        # Theme button
        self.theme_button = QPushButton('Theme')
        self.theme_button.clicked.connect(self.open_theme_dialog)
        self.theme_button.setMaximumWidth(80)
        bar_layout.addWidget(self.theme_button)
        
        main_layout.addLayout(bar_layout)
        
        # Processes table
        table_title = QLabel('Running Processes (sorted by RAM usage)')
        table_title_font = QFont()
        table_title_font.setPointSize(12)
        table_title_font.setBold(True)
        table_title.setFont(table_title_font)
        main_layout.addWidget(table_title)
        
        # Create table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['PID', 'User', 'Process Name', 'RAM (MB)', 'RAM (%)', 'Disk I/O (MB)'])
        
        # Enable right-click context menu
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        # Configure table
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)  # Ctrl/Shift for multi-select
        self.table.verticalScrollBar().setSingleStep(3)  # Faster scrolling
        self.table.verticalScrollBar().setPageStep(10)
        self.table.setStyleSheet("""
            QTableWidget {
                alternate-background-color: #f0f0f0;
                background-color: #ffffff;
                gridline-color: #d0d0d0;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QScrollBar:vertical {
                width: 12px;
            }
            QScrollBar::handle:vertical {
                background: #888;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #555;
            }
        """)
        
        main_layout.addWidget(self.table)

        # System info area (directly below table) - GPU, checkbox, OS, CPU all in one row
        system_info_layout = QHBoxLayout()
        gpu_label = QLabel('GPU:')
        gpu_label.setStyleSheet("font-weight: bold;")
        self.gpu_name_label = QLabel('Detecting...')
        system_info_layout.addWidget(gpu_label)
        system_info_layout.addWidget(self.gpu_name_label)
        system_info_layout.addSpacing(20)
        driver_label = QLabel('Driver:')
        driver_label.setStyleSheet("font-weight: bold;")
        self.gpu_driver_label = QLabel('Detecting...')
        system_info_layout.addWidget(driver_label)
        system_info_layout.addWidget(self.gpu_driver_label)
        self.hide_system_checkbox = QCheckBox('Hide system processes')
        self.hide_system_checkbox.setChecked(load_hide_system_processes())
        self.hide_system_checkbox.stateChanged.connect(self.on_hide_system_changed)
        self.hide_system_checkbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.hide_system_checkbox.setMaximumWidth(170)
        self.hide_system_checkbox.setFixedHeight(self.gpu_driver_label.sizeHint().height())
        self.hide_system_checkbox.setContentsMargins(0, 0, 0, 0)
        system_info_layout.addSpacing(20)
        system_info_layout.addWidget(self.hide_system_checkbox, 0, Qt.AlignLeft)
        
        self.hide_inaccessible_checkbox = QCheckBox('Hide inaccessible processes')
        self.hide_inaccessible_checkbox.setChecked(load_hide_inaccessible_processes())
        self.hide_inaccessible_checkbox.stateChanged.connect(self.on_hide_inaccessible_changed)
        self.hide_inaccessible_checkbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.hide_inaccessible_checkbox.setMaximumWidth(200)
        self.hide_inaccessible_checkbox.setFixedHeight(self.gpu_driver_label.sizeHint().height())
        self.hide_inaccessible_checkbox.setContentsMargins(0, 0, 0, 0)
        system_info_layout.addSpacing(20)
        system_info_layout.addWidget(self.hide_inaccessible_checkbox, 0, Qt.AlignLeft)
        system_info_layout.addStretch()
        os_label_title = QLabel('OS:')
        os_label_title.setStyleSheet("font-weight: bold;")
        self.os_label = QLabel('Detecting...')
        system_info_layout.addWidget(os_label_title)
        system_info_layout.addWidget(self.os_label)
        system_info_layout.addSpacing(20)
        cpu_label_title = QLabel('CPU:')
        cpu_label_title.setStyleSheet("font-weight: bold;")
        self.cpu_label = QLabel('Detecting...')
        system_info_layout.addWidget(cpu_label_title)
        system_info_layout.addWidget(self.cpu_label)
        main_layout.addLayout(system_info_layout)

        # Status bar with controller label
        self.controller_label = QLabel('')
        self.statusBar().addPermanentWidget(self.controller_label)
        self.statusBar().showMessage('Loading...')
        
        central_widget.setLayout(main_layout)
        
        # Apply initial theme
        self.apply_theme(self.current_theme)

        # Detect and display GPU info
        try:
            gpu = detect_gpu_info()
            self.gpu_name_label.setText(gpu.get('name', 'Unknown'))
            self.gpu_driver_label.setText(gpu.get('driver', 'Unknown'))
        except Exception:
            self.gpu_name_label.setText('Unknown')
            self.gpu_driver_label.setText('Unknown')

        # Detect and display OS info
        try:
            os_name = detect_os_name()
            self.os_label.setText(f"OS: {os_name}")
        except Exception:
            self.os_label.setText('OS: Unknown')

        # Detect and display CPU info
        try:
            cpu_name = detect_cpu_name()
            self.cpu_label.setText(f"CPU: {cpu_name}")
        except Exception:
            self.cpu_label.setText('CPU: Unknown')
        
        # Display controller info
        if hasattr(self, 'gamepad_name') and self.gamepad_name:
            self.controller_label.setText(f"Controller: {self.gamepad_name}")
        else:
            self.controller_label.setText('')
        
        # Connect data fetcher signal
        self.data_fetcher.data_ready.connect(self.on_data_ready)
        
        # Connect table selection signal
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
    
    def run_with_sudo(self):
        """Restart the application with sudo privileges"""
        script_path = os.path.abspath(__file__)

        # Windows elevation path
        if os.name == 'nt':
            if is_windows_admin():
                QMessageBox.information(self, "Info", "Already running with Administrator privileges!")
                return
            try:
                self.sudo_button.setEnabled(False)
                ps_cmd = [
                    'powershell', '-NoProfile', '-Command',
                    f'Start-Process -FilePath "{sys.executable}" -ArgumentList "\"{script_path}\"" -Verb RunAs'
                ]
                subprocess.Popen(ps_cmd)
                self.statusBar().showMessage('Launched elevated instance; current window will remain open.')
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to request elevation: {str(e)}")
            finally:
                self.sudo_button.setEnabled(True)
            return

        # POSIX sudo path
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            QMessageBox.information(self, "Info", "Already running with sudo privileges!")
            return

        try:
            self.sudo_button.setEnabled(False)
            subprocess.Popen(['sudo', sys.executable, script_path])
            self.statusBar().showMessage('Sudo instance launched; current window will remain open.')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to run with sudo: {str(e)}")
        finally:
            self.sudo_button.setEnabled(True)

    def on_hide_system_changed(self, state):
        """Handle hide system processes checkbox state change"""
        save_hide_system_processes(self.hide_system_checkbox.isChecked())
        self.request_data_update()
    
    def on_hide_inaccessible_changed(self, state):
        """Handle hide inaccessible processes checkbox state change"""
        save_hide_inaccessible_processes(self.hide_inaccessible_checkbox.isChecked())
        self.request_data_update()
    
    @staticmethod
    def is_inaccessible_process(proc: dict) -> bool:
        """Check if process has an inaccessible executable path."""
        pid = proc.get('pid', -1)
        try:
            process = psutil.Process(pid)
            exe_path = process.exe()
            if not exe_path or not os.path.exists(exe_path):
                return True
            directory = os.path.dirname(exe_path)
            return not os.access(directory, os.R_OK)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True
        return False
    
    @staticmethod
    def is_system_process(proc: dict) -> bool:
        """Heuristic to detect system processes for filtering."""
        pid = proc.get('pid', -1)
        user = (proc.get('username') or '').lower()
        system_users = {
            'root',
            'system',
            'local system',
            'nt authority\\system',
            'nt authority\\localservice',
            'nt authority\\networkservice',
            'localservice',
            'networkservice'
        }
        if pid in (0, 1, 2):
            return True
        if user in system_users:
            return True
        return False
    
    def open_theme_dialog(self):
        """Open theme selection dialog"""
        dialog = ThemeDialog(self, self.current_theme)
        if dialog.exec_() == QDialog.Accepted:
            new_theme = dialog.get_theme()
            if new_theme != self.current_theme:
                self.current_theme = new_theme
                save_theme(new_theme)  # Save theme to config
                self.apply_theme(new_theme)
    
    def apply_theme(self, theme_name: str):
        """Apply the selected theme to the application"""
        # If the user selected the explicit 'system' option, resolve it now
        if theme_name == 'system':
            resolved = detect_system_theme()
            # Fall back to light if detection fails
            theme_name = resolved if resolved in ('dark', 'light') else 'light'

        if theme_name == 'light':
            self.apply_light_theme()
        elif theme_name == 'dark':
            self.apply_dark_theme()
        elif theme_name == 'modern':
            self.apply_modern_theme()
    
    def apply_light_theme(self):
        """Apply light theme"""
        stylesheet = """
            QMainWindow {
                background-color: #ffffff;
            }
            QTableWidget {
                alternate-background-color: #f0f0f0;
                background-color: #ffffff;
                gridline-color: #d0d0d0;
                color: #000000;
            }
            QTableWidget::item {
                color: #000000;
                background-color: #ffffff;
                padding: 2px;
            }
            QTableWidget::item:alternate {
                background-color: #f0f0f0;
            }
            QTableWidget::item:selected {
                background-color: #3daee9;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QLabel {
                color: #000000;
            }
            QCheckBox {
                color: #000000;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #7f8c8d;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #2c3e50;
            }
            QCheckBox[gamepadFocus="true"] {
                background-color: rgba(61, 174, 233, 0.3);
                border: 2px solid #3daee9;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton {
                background-color: #2c3e50;
                color: white;
                border: none;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #34495e;
            }
            QProgressBar {
                color: #000000;
            }
            QScrollBar:vertical {
                background-color: #f5f5f5;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #2c3e50;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #34495e;
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #d0d0d0;
            }
            QMenu::item:selected {
                background-color: #3daee9;
                color: #ffffff;
            }
            QMenu::item:hover {
                background-color: #3daee9;
                color: #ffffff;
            }
        """
        self.setStyleSheet(stylesheet)
    
    def apply_dark_theme(self):
        """Apply dark theme"""
        stylesheet = """
            QMainWindow {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QTableWidget {
                alternate-background-color: #2d2d2d;
                background-color: #252525;
                gridline-color: #3d3d3d;
                color: #ffffff;
            }
            QTableWidget::item {
                color: #ffffff;
                background-color: #252525;
                padding: 2px;
            }
            QTableWidget::item:alternate {
                background-color: #2d2d2d;
            }
            QTableWidget::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #0d47a1;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QLabel {
                color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #5d5d5d;
                background: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background: #0d47a1;
            }
            QCheckBox[gamepadFocus="true"] {
                background-color: rgba(255, 111, 0, 0.3);
                border: 2px solid #ff6f00;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton {
                background-color: #0d47a1;
                color: white;
                border: none;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
            QProgressBar {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QProgressBar::chunk {
                background-color: #1976d2;
            }
            QDialog {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QRadioButton {
                color: #ffffff;
            }
            QMessageBox {
                background-color: #1e1e1e;
            }
            QMessageBox QLabel {
                color: #ffffff;
            }
            QStatusBar {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QStatusBar QLabel {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #252525;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #0d47a1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #1565c0;
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
            }
            QMenu::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QMenu::item:hover {
                background-color: #ff6f00;
                color: #ffffff;
            }
        """
        self.setStyleSheet(stylesheet)
    
    def apply_modern_theme(self):
        """Apply modern theme"""
        stylesheet = """
            QMainWindow {
                background-color: #f5f5f5;
                color: #212121;
            }
            QTableWidget {
                alternate-background-color: #eeeeee;
                background-color: #ffffff;
                gridline-color: #e0e0e0;
                color: #212121;
            }
            QTableWidget::item {
                color: #212121;
                background-color: #ffffff;
                padding: 2px;
            }
            QTableWidget::item:alternate {
                background-color: #eeeeee;
            }
            QTableWidget::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #ff6f00;
                color: white;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
            QLabel {
                color: #212121;
            }
            QCheckBox {
                color: #212121;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #bdbdbd;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #ff6f00;
                border-color: #ff6f00;
            }
            QCheckBox[gamepadFocus="true"] {
                background-color: rgba(255, 111, 0, 0.3);
                border: 2px solid #ff6f00;
                border-radius: 3px;
                padding: 2px;
            }
            QPushButton {
                background-color: #ff6f00;
                color: white;
                border: none;
                padding: 6px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff8f00;
            }
            QProgressBar {
                background-color: #eeeeee;
                color: #212121;
                border-radius: 3px;
                border: 1px solid #e0e0e0;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 3px;
            }
            QDialog {
                background-color: #f5f5f5;
                color: #212121;
            }
            QRadioButton {
                color: #212121;
            }
            QScrollBar:vertical {
                background-color: #eeeeee;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #ff6f00;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #ff8f00;
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                border: none;
                background: none;
            }
            QMenu {
                background-color: #ffffff;
                color: #212121;
                border: 1px solid #e0e0e0;
            }
            QMenu::item:selected {
                background-color: #ff6f00;
                color: #ffffff;
            }
            QMenu::item:hover {
                background-color: #ff8f00;
                color: #ffffff;
            }
        """
        self.setStyleSheet(stylesheet)
    
    def on_selection_changed(self):
        """Track when rows are selected"""
        selected_items = self.table.selectedItems()
        if selected_items:
            # Get unique PIDs from selected rows
            pids = set()
            for item in selected_items:
                row = item.row()
                pid_item = self.table.item(row, 0)
                if pid_item:
                    try:
                        pids.add(int(pid_item.text()))
                    except ValueError:
                        pass
            self.selected_pid = pids if pids else None
        else:
            self.selected_pid = None
    
    def show_context_menu(self, position: QPoint):
        """Show right-click context menu"""
        row = self.table.rowAt(position.y())
        if row < 0:
            return
        
        # Get selected PIDs
        selected_items = self.table.selectedItems()
        if not selected_items:
            return
        
        selected_pids = {}
        for item in selected_items:
            row = item.row()
            pid_item = self.table.item(row, 0)
            name_item = self.table.item(row, 2)  # Process name is column 2 now
            if pid_item and name_item:
                try:
                    pid = int(pid_item.text())
                    name = name_item.text()
                    selected_pids[pid] = name
                except ValueError:
                    pass
        
        if not selected_pids:
            return
        
        # Create context menu
        menu = QMenu(self)
        count = len(selected_pids)
        if count == 1:
            name = list(selected_pids.values())[0]
            pid = list(selected_pids.keys())[0]
            kill_action = menu.addAction(f"End Task: {name}")
            open_location_action = menu.addAction("Open File Location")
            
            # Connect actions
            kill_action.triggered.connect(lambda: self.kill_processes(selected_pids))
            open_location_action.triggered.connect(lambda: self.open_file_location(pid))
        else:
            kill_action = menu.addAction(f"End {count} Tasks")
            open_location_action = menu.addAction(f"Open {count} File Locations")
            
            # Connect actions
            kill_action.triggered.connect(lambda: self.kill_processes(selected_pids))
            open_location_action.triggered.connect(lambda: self.open_multiple_file_locations(selected_pids))
        
        # Set first action as active for gamepad
        menu.setActiveAction(kill_action)
        
        # Track menu for gamepad navigation
        self.active_menu = menu
        self.active_menu_pids = selected_pids
        
        # Show menu (non-blocking for gamepad support)
        menu.popup(self.table.mapToGlobal(position))
        
        # Clear active menu when it closes
        menu.aboutToHide.connect(lambda: self.clear_active_menu())
    
    def clear_active_menu(self):
        """Clear the active menu reference"""
        self.active_menu = None
        self.active_menu_pids = None
    
    def open_file_location(self, pid: int):
        """Open the file location of a process"""
        try:
            proc = psutil.Process(pid)
            exe_path = proc.exe()
            if not exe_path or not os.path.exists(exe_path):
                QMessageBox.warning(self, "Error", "Cannot locate executable path for this process.")
                return
            
            directory = os.path.dirname(exe_path)
            
            # Cross-platform directory opening
            if os.name == 'nt':  # Windows
                subprocess.Popen(['explorer', '/select,', exe_path])
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(['open', '-R', exe_path])
            else:  # Linux
                # Suppress stderr to avoid net usershare errors and try multiple file managers
                try:
                    subprocess.Popen(['xdg-open', directory], stderr=subprocess.DEVNULL)
                except Exception:
                    # Fallback to common file managers
                    for fm in ['nautilus', 'dolphin', 'thunar', 'nemo', 'caja']:
                        if shutil.which(fm):
                            subprocess.Popen([fm, directory], stderr=subprocess.DEVNULL)
                            break
            
            self.statusBar().showMessage(f"Opened location: {directory}")
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Error", "Process no longer exists.")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Error", "Access denied. Cannot access process executable path.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open file location: {str(e)}")
    
    def open_multiple_file_locations(self, pids_dict: dict):
        """Open file locations for multiple processes"""
        opened = []
        failed = []
        access_denied = []
        unique_dirs = set()
        
        for pid, name in pids_dict.items():
            try:
                proc = psutil.Process(pid)
                exe_path = proc.exe()
                if not exe_path or not os.path.exists(exe_path):
                    failed.append(f"{name} (PID: {pid})")
                    continue
                
                directory = os.path.dirname(exe_path)
                
                # Skip if directory already opened
                if directory in unique_dirs:
                    continue
                unique_dirs.add(directory)
                
                # Cross-platform directory opening
                if os.name == 'nt':  # Windows
                    subprocess.Popen(['explorer', '/select,', exe_path])
                elif sys.platform == 'darwin':  # macOS
                    subprocess.Popen(['open', '-R', exe_path])
                else:  # Linux
                    try:
                        subprocess.Popen(['xdg-open', directory], stderr=subprocess.DEVNULL)
                    except Exception:
                        for fm in ['nautilus', 'dolphin', 'thunar', 'nemo', 'caja']:
                            if shutil.which(fm):
                                subprocess.Popen([fm, directory], stderr=subprocess.DEVNULL)
                                break
                
                opened.append(directory)
            except psutil.NoSuchProcess:
                failed.append(f"{name} (PID: {pid})")
            except psutil.AccessDenied:
                access_denied.append(f"{name} (PID: {pid})")
            except Exception as e:
                failed.append(f"{name} (PID: {pid}): {str(e)}")
        
        # Show status message
        if opened:
            self.statusBar().showMessage(f"Opened {len(opened)} location(s)")
        
        # Show warnings if there were issues
        if access_denied or failed:
            msg = ""
            if access_denied:
                msg += f"Access denied for:\n" + "\n".join(access_denied) + "\n\n"
            if failed:
                msg += f"Failed to open location for:\n" + "\n".join(failed)
            QMessageBox.warning(self, "Error", msg.strip())
    
    def kill_process(self, pid: int, process_name: str):
        """Kill a process by PID"""
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            self.statusBar().showMessage(f"Terminated process: {process_name} (PID: {pid})")
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Error", f"Process {process_name} (PID: {pid}) no longer exists")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Error", f"Access denied. Cannot terminate {process_name}.\nYou may need to run with sudo.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to terminate {process_name}: {str(e)}")
    
    def kill_processes(self, pids_dict: dict):
        """Kill multiple processes by PID"""
        failed = []
        access_denied = []
        terminated = []
        
        for pid, name in pids_dict.items():
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                terminated.append(f"{name} (PID: {pid})")
            except psutil.NoSuchProcess:
                pass  # Process already gone
            except psutil.AccessDenied:
                access_denied.append(f"{name} (PID: {pid})")
            except Exception as e:
                failed.append(f"{name} (PID: {pid}): {str(e)}")
        
        # Show status message
        if terminated:
            self.statusBar().showMessage(f"Terminated {len(terminated)} process(es)")
        
        # Show warnings if there were issues
        if access_denied or failed:
            msg = ""
            if access_denied:
                msg += f"Access denied for:\n" + "\n".join(access_denied) + "\n\nYou may need to run with sudo.\n\n"
            if failed:
                msg += f"Failed to terminate:\n" + "\n".join(failed)
            QMessageBox.warning(self, "Error", msg.strip())
    
    def process_gamepad_input(self):
        """Process gamepad input and convert to keyboard/mouse events"""
        if not self.gamepad:
            return
        
        try:
            pygame.event.pump()
            
            # Handle menu navigation if a menu is active
            if self.active_menu and self.active_menu.isVisible():
                print("Menu is active and visible")
                self.process_menu_navigation()
                return
            elif self.active_menu:
                print(f"Menu exists but not visible: {self.active_menu.isVisible()}")
            
            # D-pad / Left stick for navigation with continuous input
            hat = self.gamepad.get_hat(0) if self.gamepad.get_numhats() > 0 else (0, 0)
            axis_x = self.gamepad.get_axis(0) if self.gamepad.get_numaxes() > 0 else 0
            axis_y = self.gamepad.get_axis(1) if self.gamepad.get_numaxes() > 1 else 0
            
            # Check if axis moved significantly from last position
            # Invert axis_y: negative values mean up, positive means down
            current_y = hat[1] if hat[1] != 0 else (1 if axis_y < -0.5 else (-1 if axis_y > 0.5 else 0))
            current_x = hat[0] if hat[0] != 0 else (-1 if axis_x < -0.5 else (1 if axis_x > 0.5 else 0))
            
            # If direction changed or stopped, reset counter
            if current_y != self.gamepad_last_axis['y'] or current_x != self.gamepad_last_axis['x']:
                self.gamepad_repeat_counter = 0
                self.gamepad_last_axis['y'] = current_y
                self.gamepad_last_axis['x'] = current_x
            
            # Navigate if direction is held
            if current_y != 0 or current_x != 0:
                # Initial press or repeat after delay
                if self.gamepad_repeat_counter == 0 or self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                    if current_y > 0:
                        # Navigate up
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row > 0:
                                self.table.setCurrentCell(current_row - 1, 0)
                            else:
                                # At top of table, move to hide_inaccessible checkbox
                                self.gamepad_focus_mode = 'hide_inaccessible'
                                self.table.clearSelection()
                                self.hide_system_checkbox.setProperty('gamepadFocus', False)
                                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                                self.hide_inaccessible_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_inaccessible':
                            # Move to hide_system checkbox
                            self.gamepad_focus_mode = 'hide_system'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_system_checkbox.setProperty('gamepadFocus', True)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_system_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_system':
                            # Wrap around to last process
                            self.gamepad_focus_mode = 'table'
                            self.hide_system_checkbox.setProperty('gamepadFocus', False)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            last_row = self.table.rowCount() - 1
                            if last_row >= 0:
                                self.table.setCurrentCell(last_row, 0)
                                self.table.setFocus()
                    elif current_y < 0:
                        # Navigate down
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row < self.table.rowCount() - 1:
                                self.table.setCurrentCell(current_row + 1, 0)
                            else:
                                # At bottom of table, wrap to hide_system checkbox
                                self.gamepad_focus_mode = 'hide_system'
                                self.table.clearSelection()
                                self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                                self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                                self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                                self.hide_system_checkbox.setProperty('gamepadFocus', True)
                                self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                                self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                                self.hide_system_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_system':
                            # Move to hide_inaccessible checkbox
                            self.gamepad_focus_mode = 'hide_inaccessible'
                            self.hide_system_checkbox.setProperty('gamepadFocus', False)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.setFocus()
                        elif self.gamepad_focus_mode == 'hide_inaccessible':
                            # Wrap to first process
                            self.gamepad_focus_mode = 'table'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            if self.table.rowCount() > 0:
                                self.table.setCurrentCell(0, 0)
                                self.table.setFocus()
                    
                    # Handle left/right navigation for checkboxes
                    elif current_x > 0:
                        # Navigate right
                        if self.gamepad_focus_mode == 'hide_system':
                            self.gamepad_focus_mode = 'hide_inaccessible'
                            self.hide_system_checkbox.setProperty('gamepadFocus', False)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', True)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.setFocus()
                    elif current_x < 0:
                        # Navigate left
                        if self.gamepad_focus_mode == 'hide_inaccessible':
                            self.gamepad_focus_mode = 'hide_system'
                            self.hide_inaccessible_checkbox.setProperty('gamepadFocus', False)
                            self.hide_inaccessible_checkbox.style().unpolish(self.hide_inaccessible_checkbox)
                            self.hide_inaccessible_checkbox.style().polish(self.hide_inaccessible_checkbox)
                            self.hide_system_checkbox.setProperty('gamepadFocus', True)
                            self.hide_system_checkbox.style().unpolish(self.hide_system_checkbox)
                            self.hide_system_checkbox.style().polish(self.hide_system_checkbox)
                            self.hide_system_checkbox.setFocus()
                    
                    # Reset counter for continuous repeat
                    if self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                        self.gamepad_repeat_counter = self.gamepad_repeat_delay - 1  # Fast repeat
                
                self.gamepad_repeat_counter += 1
            
            # Button handling with state tracking
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                is_pressed = self.gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                # Only trigger on button press (not hold)
                if is_pressed and not was_pressed:
                    if button_id == 0:  # Button A - Open context menu or toggle checkbox
                        if self.gamepad_focus_mode == 'table':
                            current_row = self.table.currentRow()
                            if current_row >= 0:
                                rect = self.table.visualItemRect(self.table.item(current_row, 0))
                                self.show_context_menu(rect.center())
                        elif self.gamepad_focus_mode == 'hide_system':
                            self.hide_system_checkbox.setChecked(not self.hide_system_checkbox.isChecked())
                        elif self.gamepad_focus_mode == 'hide_inaccessible':
                            self.hide_inaccessible_checkbox.setChecked(not self.hide_inaccessible_checkbox.isChecked())
                    
                    elif button_id == 1:  # Button B - End task
                        selected_items = self.table.selectedItems()
                        if selected_items:
                            selected_pids = {}
                            for item in selected_items:
                                row = item.row()
                                pid_item = self.table.item(row, 0)
                                name_item = self.table.item(row, 2)
                                if pid_item and name_item:
                                    try:
                                        pid = int(pid_item.text())
                                        name = name_item.text()
                                        selected_pids[pid] = name
                                    except ValueError:
                                        pass
                            if selected_pids:
                                self.kill_processes(selected_pids)
                    
                    elif button_id == 4:  # L1 - Page up
                        current_row = self.table.currentRow()
                        new_row = max(0, current_row - 10)
                        self.table.setCurrentCell(new_row, 0)
                    
                    elif button_id == 5:  # R1 - Page down
                        current_row = self.table.currentRow()
                        new_row = min(self.table.rowCount() - 1, current_row + 10)
                        self.table.setCurrentCell(new_row, 0)
                
                self.gamepad_button_states[button_id] = is_pressed
            
        except Exception as e:
            print(f"Gamepad input error: {e}")
    
    def process_menu_navigation(self):
        """Handle gamepad navigation within context menus"""
        if not self.active_menu:
            return
        
        try:
            print("Processing menu navigation")
            # Get current direction
            hat = self.gamepad.get_hat(0) if self.gamepad.get_numhats() > 0 else (0, 0)
            axis_y = self.gamepad.get_axis(1) if self.gamepad.get_numaxes() > 1 else 0
            current_y = hat[1] if hat[1] != 0 else (1 if axis_y < -0.5 else (-1 if axis_y > 0.5 else 0))
            print(f"Menu nav - current_y: {current_y}, hat: {hat}, axis_y: {axis_y}")
            
            # Direction change detection
            if current_y != self.gamepad_last_axis['y']:
                self.gamepad_repeat_counter = 0
                self.gamepad_last_axis['y'] = current_y
            
            # Navigate menu items
            if current_y != 0:
                if self.gamepad_repeat_counter == 0 or self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                    actions = self.active_menu.actions()
                    current_action = self.active_menu.activeAction()
                    
                    if current_action:
                        current_index = actions.index(current_action)
                        if current_y > 0:  # Up
                            new_index = max(0, current_index - 1)
                        else:  # Down
                            new_index = min(len(actions) - 1, current_index + 1)
                        self.active_menu.setActiveAction(actions[new_index])
                    
                    if self.gamepad_repeat_counter >= self.gamepad_repeat_delay:
                        self.gamepad_repeat_counter = self.gamepad_repeat_delay - 1
                
                self.gamepad_repeat_counter += 1
            
            # Update button states for menu context
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                is_pressed = self.gamepad.get_button(button_id)
                was_pressed = self.gamepad_button_states.get(button_id, False)
                
                if is_pressed and not was_pressed:
                    if button_id == 0:  # Button A - Select menu item
                        current_action = self.active_menu.activeAction()
                        if current_action:
                            print(f"Triggering action: {current_action.text()}")
                            self.active_menu.close()
                            current_action.trigger()
                    elif button_id == 1:  # Button B - Close menu
                        print("Closing menu")
                        self.active_menu.close()
                
                self.gamepad_button_states[button_id] = is_pressed
            
            # Update button states
            for button_id in range(min(10, self.gamepad.get_numbuttons())):
                self.gamepad_button_states[button_id] = self.gamepad.get_button(button_id)
        
        except Exception as e:
            print(f"Menu navigation error: {e}")
    
    def request_data_update(self):
        """Request data update in worker thread"""
        self.data_fetcher.fetch_data()
    
    def on_data_ready(self, mem_info, processes):
        """Handle data received from worker thread"""
        # Save current scroll position
        scroll_value = self.table.verticalScrollBar().value()

        # Track total before filtering
        total_processes = len(processes)

        # Apply system-process filter if enabled
        if self.hide_system_checkbox.isChecked():
            processes = [p for p in processes if not self.is_system_process(p)]
        
        # Apply inaccessible-process filter if enabled
        if self.hide_inaccessible_checkbox.isChecked():
            processes = [p for p in processes if not self.is_inaccessible_process(p)]
        
        # Disable updates and selection signals during refresh
        self.table.setUpdatesEnabled(False)
        self.table.itemSelectionChanged.disconnect(self.on_selection_changed)
        self.table.setRowCount(0)  # Clear faster than individual updates
        
        # Update memory info - only if changed to reduce flickering
        self.total_ram_label.setText(f"{mem_info['total']:.2f} GB")
        self.used_ram_label.setText(f"{mem_info['used']:.2f} GB")
        self.available_ram_label.setText(f"{mem_info['available']:.2f} GB")
        
        # Update progress bar
        percent = int(mem_info['percent'])
        if self.progress_bar.value() != percent:
            self.progress_bar.setValue(percent)
        self.progress_label.setText(f"{mem_info['percent']:.1f}%")
        
        # Color code the progress bar - cache colors
        if mem_info['percent'] < 50:
            style = "QProgressBar::chunk { background-color: #27ae60; }"
        elif mem_info['percent'] < 80:
            style = "QProgressBar::chunk { background-color: #f39c12; }"
        else:
            style = "QProgressBar::chunk { background-color: #e74c3c; }"
        self.progress_bar.setStyleSheet(style)
        
        # Pre-allocate all rows at once for speed
        self.table.setRowCount(len(processes))
        
        # Color cache for performance
        color_high = QColor(255, 200, 0, 50)
        color_med = QColor(255, 200, 0, 30)
        color_none = QColor(255, 255, 255, 0)
        
        # Batch insert all items
        for row, proc in enumerate(processes):
            pid_item = QTableWidgetItem(str(proc['pid']))
            user_item = QTableWidgetItem(proc.get('username', 'unknown'))
            name_item = QTableWidgetItem(proc['name'])
            ram_item = QTableWidgetItem(f"{proc['memory_mb']:.2f}")
            percent_item = QTableWidgetItem(f"{proc['memory_percent']:.2f}")
            disk_item = QTableWidgetItem(f"{proc.get('disk_io_mb', 0.0):.2f}")
            
            # Set all items non-editable at once
            for item in [pid_item, user_item, name_item, ram_item, percent_item, disk_item]:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            user_item.setTextAlignment(Qt.AlignCenter)
            
            # Color code rows based on memory usage
            if proc['memory_percent'] > 10:
                color = color_high
            elif proc['memory_percent'] > 5:
                color = color_med
            else:
                color = color_none
            
            # Set items in table
            self.table.setItem(row, 0, pid_item)
            self.table.setItem(row, 1, user_item)
            self.table.setItem(row, 2, name_item)
            self.table.setItem(row, 3, ram_item)
            self.table.setItem(row, 4, percent_item)
            self.table.setItem(row, 5, disk_item)
            
            # Apply color
            for col in range(6):
                self.table.item(row, col).setBackground(color)
        
        # Re-enable updates
        self.table.setUpdatesEnabled(True)
        
        # Restore selections if they still exist (without scrolling to them)
        if self.selected_pid:
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                pid_item = self.table.item(row, 0)
                if pid_item:
                    try:
                        pid = int(pid_item.text())
                        if pid in self.selected_pid:
                            self.table.selectRow(row)
                    except ValueError:
                        pass
            self.table.blockSignals(False)
        
        # Restore scroll position
        self.table.verticalScrollBar().setValue(scroll_value)
        
        # Reconnect selection signal
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        
        # Update status bar with both counts
        current_time = datetime.now().strftime('%H:%M:%S')
        if self.hide_system_checkbox.isChecked() or self.hide_inaccessible_checkbox.isChecked():
            self.statusBar().showMessage(f'Ready - Last updated: {current_time} | Showing: {len(processes)} / Total Processes: {total_processes}')
        else:
            self.statusBar().showMessage(f'Ready - Last updated: {current_time} | Total Processes: {total_processes}')


def main():
    # Check if display is available
    if not os.environ.get('DISPLAY'):
        print("Warning: No display found. Setting DISPLAY to :0")
        os.environ['DISPLAY'] = ':0'
    
    try:
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"Failed to create QApplication: {e}")
        print("Trying with offscreen platform plugin...")
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        app = QApplication(sys.argv)
    
    window = TaskManagerGUI()
    window.showNormal()  # Use showNormal instead of show
    window.raise_()  # Bring window to front
    window.activateWindow()  # Ensure window is focused
    window.setWindowState(window.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
