"""
file_utils.py — path helpers.

All app data lives under ~/Documents/Automations/<loc>/.
The loc env var identifies the environment (e.g. "PayrollProd") so
prod and dev data don't mix on the same machine.

Directory layout:
    <root>/data/
        logs/        — per-session log files
        archive/     — old logs and validation files, sorted by date
        validation/  — checker variance Excel exports
        auth/msal/   — encrypted MSAL token cache

resource_path() handles the dev vs PyInstaller bundle difference for
loading asset files (images, icons).
"""

import os
import sys
from pathlib import Path
from utils.app_config_user import get


def app_data_path() -> Path:
    """Returns (and creates) the root data folder: ~/Documents/Automations/<loc>/"""
    path = Path(get("installation_loc", "").replace("/app", ""))
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_path() -> Path:
    """Returns (and creates) <app_data>/data/logs/"""
    path = app_data_path() / "data" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_path() -> Path:
    """Returns (and creates) <app_data>/data/archive/"""
    path = app_data_path() / "data" / "archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validation_path() -> Path:
    """Returns (and creates) <app_data>/data/validation/"""
    path = app_data_path() / "data" / "validation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dbx_payroll_path() -> Path:
    """Returns (and creates) <app_data>/data/validation/"""
    path = app_data_path() / "data" / "tools" / "DBXtoSprout"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(relative_path: str) -> str:
    """
    Resolves an asset path that works in both dev and a PyInstaller bundle.
    In dev, assets are at the project root. In a bundle, they're under sys._MEIPASS.
    """
    base_path = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(base_path, relative_path)