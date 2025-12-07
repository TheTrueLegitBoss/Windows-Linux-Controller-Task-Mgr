# Task Manager GUI

A modern, feature-rich task manager application for Linux with a PyQt5-based graphical interface.

## Features

- **Real-time Process Monitoring**: View all running processes with RAM usage
- **Multi-selection**: Select and terminate multiple processes at once (Ctrl+click)
- **System Resource Display**: Monitor total, used, and available RAM
- **Right-click Context Menu**: Quick access to terminate processes
- **Three Color Themes**: Light, Dark, and Modern themes with persistent selection
- **Theme Customization**: Switch themes on-the-fly with centered dialog
- **Sudo Support**: One-click button to run with elevated privileges
- **Smooth Performance**: 500ms refresh rate with background data fetching
- **Persistent Selection**: Selected processes remain highlighted across updates
- **Theme Persistence**: Your preferred theme is saved and loaded on startup

## Installation

### Option 1: Using the Setup Script

```bash
cd /path/to/task_manager
python3 setup.py
```

### Option 2: Using pip with requirements.txt

```bash
cd /path/to/task_manager
pip install -r requirements.txt
```

### Option 3: Manual Installation

```bash
pip install psutil PyQt5 tabulate
```

## Usage

### Running the Task Manager

```bash
python3 task_manager_gui.py
```

Or with a dedicated terminal for better display:

```bash
gnome-terminal -- python3 task_manager_gui.py
```

### Features Guide

**Selecting Processes:**
- Single click: Select a single process
- Ctrl+click: Add/remove process to selection
- Shift+click: Select a range of processes

**Managing Processes:**
- Right-click on selected process(es) to see context menu
- Click "End Task" or "End X Tasks" to terminate
- Use "Run as Sudo" button for system processes that need elevated privileges

**Themes:**
- Click the "Theme" button to open theme selector
- Choose from Light, Dark, or Modern themes
- Your selection is automatically saved

**Memory Monitoring:**
- Top of window shows total, used, and available RAM
- Progress bar indicates memory usage percentage
- Color coding: Green (<50%), Orange (50-80%), Red (>80%)

## Requirements

- Python 3.6+
- Linux with X11 or Wayland display server
- psutil 5.9.0+
- PyQt5 5.15.0+
- tabulate 0.8.0+

## File Structure

```
task_manager/
├── task_manager_gui.py      # Main application
├── setup.py                 # Installation script
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Configuration

The application stores its configuration in `~/.task_manager_config.json`:

```json
{
  "theme": "light"
}
```

You can manually edit this file to change default settings.

## Troubleshooting

### Window not visible in VS Code terminal

If the window doesn't appear when running from VS Code's integrated terminal:
1. Run from a dedicated terminal instead
2. Or use: `gnome-terminal -- python3 task_manager_gui.py`

### Permission denied when terminating processes

Some system processes require elevated privileges. Use the "Run as Sudo" button to restart the application with admin rights.

### Missing dependencies

Make sure all packages are installed:
```bash
pip install psutil PyQt5 tabulate
```

## Keyboard Shortcuts

- **Ctrl+Click**: Multi-select processes
- **Shift+Click**: Select range of processes
- **Right-Click**: Open context menu

## License

This project is provided as-is for personal use.

## Support

For issues or feature requests, check the code comments or contact the developer.
