"""
app_config.py — unified config reader for dev and production.

In production (packed .exe), all values come from the OS:
    - Secrets (CLIENT_ID, TENANT_ID) → Windows Credential Manager via keyring
    - Everything else                → Windows Registry under HKLM\SOFTWARE\Intogreat\FinanceSuite

In development, both fall back to .env / environment variables so the
workflow stays the same as before. You don't need to touch the registry
or Credential Manager on your dev machine.

Usage (replaces os.getenv everywhere):
    from utils.app_config_user import get
    client_id = get("CLIENT_ID")
    sp_url    = get("SP_BASE_URL")
"""

import os

try:
    import winreg
    _WINREG_AVAILABLE = True
except ImportError:
    # Non-Windows dev machine — fall straight through to .env
    _WINREG_AVAILABLE = False

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

from dotenv import dotenv_values
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
ENV_VALUES = dotenv_values(ENV_PATH)

# Registry path written by the Inno Setup installer
_REG_PATH = r"SOFTWARE\Intogreat\FinanceSuite"

# Keyring service name — matches what setup_helper.py writes
_KEYRING_SERVICE = "FinanceSuite"

# Keys that are treated as secrets and stored in Credential Manager.
# Everything else goes in the registry.
_SECRET_KEYS = {"CLIENT_ID", "TENANT_ID"}


def is_env():
    value = ENV_VALUES.get("ENVT")
    print("ENVT =", repr(value))
    print("ENV_PATH =", ENV_PATH)
    print("ENV_EXISTS =", ENV_PATH.exists())
    return value is not None

def get(key: str, fallback: str = "") -> str:
    """
    Reads a config value in priority order:
        1. Windows Credential Manager (secrets only)
        2. Windows Registry
        3. Environment variable / .env
        4. fallback argument
    """

    # ── Secrets from Credential Manager ───────────────────────────────
    if key in _SECRET_KEYS and _KEYRING_AVAILABLE:
        try:
            value = keyring.get_password(_KEYRING_SERVICE, key)
            if value:
                return value
        except Exception:
            pass

    # ── Non-secrets from Registry ─────────────────────────────────────
    if _WINREG_AVAILABLE:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_PATH) as reg:
                value, _ = winreg.QueryValueEx(reg, key)
                if value:
                    return value
        except (FileNotFoundError, OSError):
            pass

    # ── .env / environment first ──────────────────────────────────────
    value = ENV_VALUES.get(key)
    if value not in (None, ""):
        return value

    return fallback


def is_configured() -> bool:
    """
    Consider the app configured if:
      - required values exist in .env/env vars, OR
      - installer registry exists
    """

    required = ["CLIENT_ID", "TENANT_ID", "SP_BASE_URL"]

    if all(os.getenv(k) for k in required):
        return True

    if not _WINREG_AVAILABLE:
        return True

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REG_PATH):
            return True
    except FileNotFoundError:
        return False