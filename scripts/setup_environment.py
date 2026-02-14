#!/usr/bin/env python3
"""
Setup virtual environment for ChatGPT CLI skill
"""

import os
import subprocess
import sys
from pathlib import Path


def get_python_executable():
    """Get a compatible Python executable (3.13 preferred for nodriver compatibility)"""
    import shutil
    # Try python3.13 first (nodriver has issues with 3.14+)
    python313 = shutil.which("python3.13")
    if python313:
        return python313
    # Fall back to python3.12
    python312 = shutil.which("python3.12")
    if python312:
        return python312
    # Last resort: current Python
    return sys.executable


def setup_venv():
    """Create and setup virtual environment"""
    skill_dir = Path(__file__).parent.parent
    venv_dir = skill_dir / ".venv"
    requirements_file = skill_dir / "requirements.txt"

    # Create venv if it doesn't exist
    if not venv_dir.exists():
        python_exe = get_python_executable()
        print(f"Creating virtual environment at {venv_dir} using {python_exe}...")
        subprocess.run([python_exe, "-m", "venv", str(venv_dir)], check=True)

    # Determine pip path
    if os.name == 'nt':
        pip_path = venv_dir / "Scripts" / "pip.exe"
    else:
        pip_path = venv_dir / "bin" / "pip"

    # Upgrade pip
    print("Upgrading pip...")
    subprocess.run([str(pip_path), "install", "--upgrade", "pip"], check=True)

    # Install requirements
    if requirements_file.exists():
        print("Installing dependencies...")
        subprocess.run([str(pip_path), "install", "-r", str(requirements_file)], check=True)

    # Create data directories
    data_dir = skill_dir / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "screenshots").mkdir(exist_ok=True)
    (data_dir / "browser_profile").mkdir(exist_ok=True)

    print("Setup complete!")
    return 0


if __name__ == "__main__":
    sys.exit(setup_venv())
