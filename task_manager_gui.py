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
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLabel, QProgressBar, QHeaderView, QMenu, QMessageBox, QPushButton,
    QDialog, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject, QPoint, QRect
from PyQt5.QtGui import QFont, QColor, QBrush
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
        # NVIDIA users - nvidia-smi provides clear info
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
                for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                    try:
                        pinfo = proc.as_dict(attrs=['pid', 'name', 'memory_info'])
                        memory_mb = pinfo['memory_info'].rss / (1024**2)
                        processes.append({
                            'pid': pinfo['pid'],
                            'name': pinfo['name'][:50],
                            'memory_mb': memory_mb,
                            'memory_percent': proc.memory_percent()
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
        self.initUI()
        
        # Track selected rows
        self.selected_pid = None
        
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
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['PID', 'Process Name', 'RAM (MB)', 'RAM (%)'])
        
        # Enable right-click context menu
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        # Configure table
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
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
        
        # GPU info area (bottom of GUI, above status bar)
        gpu_layout = QHBoxLayout()
        gpu_label = QLabel('GPU:')
        gpu_label.setStyleSheet("font-weight: bold;")
        self.gpu_name_label = QLabel('Detecting...')
        gpu_layout.addWidget(gpu_label)
        gpu_layout.addWidget(self.gpu_name_label)
        gpu_layout.addSpacing(20)
        driver_label = QLabel('Driver:')
        driver_label.setStyleSheet("font-weight: bold;")
        self.gpu_driver_label = QLabel('Detecting...')
        gpu_layout.addWidget(driver_label)
        gpu_layout.addWidget(self.gpu_driver_label)
        gpu_layout.addStretch()
        main_layout.addLayout(gpu_layout)

        # Status bar
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
        
        # Connect data fetcher signal
        self.data_fetcher.data_ready.connect(self.on_data_ready)
        
        # Connect table selection signal
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
    
    def run_with_sudo(self):
        """Restart the application with sudo privileges"""
        # Check if already running with sudo
        if os.geteuid() == 0:
            QMessageBox.information(self, "Info", "Already running with sudo privileges!")
            return
        
        try:
            # Get the script path
            script_path = os.path.abspath(__file__)
            # Restart with sudo
            subprocess.Popen(['sudo', sys.executable, script_path])
            # Close current instance
            self.close()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to run with sudo: {str(e)}")
    
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
            name_item = self.table.item(row, 1)
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
            kill_action = menu.addAction(f"End Task: {name}")
        else:
            kill_action = menu.addAction(f"End {count} Tasks")
        
        # Execute menu
        action = menu.exec_(self.table.mapToGlobal(position))
        
        if action == kill_action:
            self.kill_processes(selected_pids)
    
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
    
    def request_data_update(self):
        """Request data update in worker thread"""
        self.data_fetcher.fetch_data()
    
    def on_data_ready(self, mem_info, processes):
        """Handle data received from worker thread"""
        # Save current scroll position
        scroll_value = self.table.verticalScrollBar().value()
        
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
            name_item = QTableWidgetItem(proc['name'])
            ram_item = QTableWidgetItem(f"{proc['memory_mb']:.2f}")
            percent_item = QTableWidgetItem(f"{proc['memory_percent']:.2f}")
            
            # Set all items non-editable at once
            for item in [pid_item, name_item, ram_item, percent_item]:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            
            # Color code rows based on memory usage
            if proc['memory_percent'] > 10:
                color = color_high
            elif proc['memory_percent'] > 5:
                color = color_med
            else:
                color = color_none
            
            # Set items in table
            self.table.setItem(row, 0, pid_item)
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, ram_item)
            self.table.setItem(row, 3, percent_item)
            
            # Apply color
            for col in range(4):
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
        
        # Update status bar
        current_time = datetime.now().strftime('%H:%M:%S')
        self.statusBar().showMessage(f'Ready - Last updated: {current_time} | Total Processes: {len(processes)}')


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
