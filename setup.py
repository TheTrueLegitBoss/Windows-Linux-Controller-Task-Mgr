#!/usr/bin/env python3
"""
Setup script for Task Manager GUI
Installs all required dependencies
"""

import subprocess
import sys
import os


def run_command(command, description):
    """Run a shell command and report status"""
    print(f"\n{'='*60}")
    print(f"Installing: {description}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(command, shell=True, check=True)
        print(f"✓ {description} installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install {description}")
        print(f"Error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error while installing {description}")
        print(f"Error: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("Task Manager GUI - Setup Script")
    print("="*60)
    
    # List of dependencies
    dependencies = [
        ("pip install psutil", "psutil (Process and system utilities)"),
        ("pip install PyQt5", "PyQt5 (GUI framework)"),
        ("pip install PyQtWebEngine", "PyQtWebEngine (Embedded browser support)"),
        ("pip install tabulate", "tabulate (Table formatting)"),
        ("pip install pygame", "pygame (Gamepad support)"),
    ]
    
    success_count = 0
    failed_count = 0
    
    # Install each dependency
    for command, description in dependencies:
        if run_command(command, description):
            success_count += 1
        else:
            failed_count += 1
    
    # Summary
    print(f"\n{'='*60}")
    print("Installation Summary")
    print(f"{'='*60}")
    print(f"✓ Successfully installed: {success_count}")
    print(f"✗ Failed to install: {failed_count}")
    print(f"{'='*60}\n")
    
    if failed_count == 0:
        print("All dependencies installed successfully!")
        print("\nYou can now run the task manager with:")
        print("  python task_manager_gui.py")
        return 0
    else:
        print(f"Failed to install {failed_count} package(s)")
        print("Please install the missing packages manually")
        return 1


if __name__ == '__main__':
    sys.exit(main())
