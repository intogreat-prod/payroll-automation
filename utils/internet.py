"""
internet.py — quick connectivity check.

Called once at startup to decide whether to show the login screen or the
no-internet screen. Uses HEAD instead of GET so there's no response body
to download — keeps it fast (~300ms).
"""

import requests


def internet_available(timeout: int = 3) -> bool:
    """Pings google.com and returns True if we get any response back."""
    try:
        requests.head("https://www.google.com", timeout=timeout)
        return True
    except Exception:
        return False
