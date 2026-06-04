"""
app_config.py — unified config reader supporting both install types.
For ADMIN install (Program Files):
   - Secrets (CLIENT_ID, TENANT_ID) → Windows Credential Manager
   - Everything else                → Windows Registry
For USER install (Documents):
   - All values → .env file next to the exe
In development, both fall back to .env / environment variables.
"""

import os
import sys
from pathlib import Path

try:
   import winreg
   _WINREG_AVAILABLE = True
except ImportError:
   _WINREG_AVAILABLE = False
try:
   import keyring
   _KEYRING_AVAILABLE = True
except ImportError:
   _KEYRING_AVAILABLE = False

from dotenv import load_dotenv, dotenv_values

# Registry paths (admin install only)
_REG_PATH        = r"SOFTWARE\Intogreat\PayrollAutomation"
_KEYRING_SERVICE = "PayrollAutomation"
_SECRET_KEYS     = {"CLIENT_ID", "TENANT_ID"}

# Load .env from the app directory first (user install), then from current dir (dev)
_APP_DIR = os.path.dirname(sys.executable) if hasattr(sys, 'frozen') else os.getcwd()
_ENV_PATH = os.path.join(_APP_DIR, ".env")

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
ENV_VALUES = dotenv_values(ENV_PATH)

if os.path.exists(_ENV_PATH):
   load_dotenv(_ENV_PATH)
else:
   load_dotenv()  # Fall back to current directory or system env vars

def is_env():
    value = ENV_VALUES.get("ENVT")
    return value is not None

def get(key: str, fallback: str = "") -> str:
    """
    Reads a config value in priority order:
        1. Windows Credential Manager  (secrets only — admin install)
        2. Windows Registry            (admin install)
        3. Environment variable / .env (all installs)
        4. fallback argument
    """
    # ── Secrets from Credential Manager (admin install) ───────────────
    if key in _SECRET_KEYS and _KEYRING_AVAILABLE:
        value = keyring.get_password(_KEYRING_SERVICE, key)
        if value:
            return value
    # ── Non-secrets from Registry (admin install) ──────────────────────
    if _WINREG_AVAILABLE:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_PATH) as reg:
                value, _ = winreg.QueryValueEx(reg, key)
                if value:
                    return value
        except (FileNotFoundError, OSError):
            pass
    # ── Environment variable / .env (user install + dev) ───────────────
    return os.getenv(key, fallback)

def is_configured() -> bool:
    """
    Returns True if either registry key exists (admin) or .env exists (user).
    Used by the app to detect a misconfigured or fresh machine.
    """
    # User install — check for .env
    if os.path.exists(_ENV_PATH):
        return True
    # Admin install — check for registry
    if _WINREG_AVAILABLE:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_PATH):
                return True
        except FileNotFoundError:
            pass
    return False