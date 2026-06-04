"""
msal_service.py — handles Microsoft login via MSAL.

Tries three strategies in order, stopping at the first success:
    1. Silent  — uses the cached token from a previous session
    2. Interactive — opens a browser pop-up
    3. Device code — fallback for machines with no browser; shows a code
       the user types at aka.ms/devicelogin (runs on a background thread
       so the UI stays responsive while polling)

Token cache is stored encrypted at <app_data>/data/auth/msal/token_cache.bin.
On Windows this uses DPAPI so only the current OS user can read it.

Callbacks are wired by the Orchestrator after construction:
    msal.on_login_complete(email, name, token)
    msal.on_device_code(payload)
    msal.error_login(error_str)
"""

import os
import msal
import requests
from msal_extensions import PersistedTokenCache, build_encrypted_persistence
from PyQt6.QtCore import QThread, pyqtSignal

from utils.file_utils import app_data_path
from utils.app_config_user import get


class LoginWorker(QThread):
    """
    Runs the device-code flow on a background thread.
    Emits twice: once when the code is ready (so the UI can show it),
    and again when the user completes auth.
    """
    finished = pyqtSignal(dict)

    def __init__(self, app, scopes: list):
        super().__init__()
        self.app    = app
        self.scopes = scopes

    def run(self):
        flow = self.app.initiate_device_flow(scopes=self.scopes)

        if "user_code" not in flow:
            self.finished.emit({"error": "Failed to create device flow"})
            return

        # Tell the UI to show the code while we wait
        self.finished.emit({
            "type":      "code",
            "user_code": flow["user_code"],
            "url":       flow["verification_uri"],
            "message":   flow["message"],
        })

        # Blocks this thread until the user completes auth or it times out
        result = self.app.acquire_token_by_device_flow(flow)
        self.finished.emit({"type": "result", "result": result})


class MSALService:

    SCOPES = [
        "User.Read",
        "Sites.Read.All",
        "Files.ReadWrite.All",
        "Mail.Send",
    ]

    def __init__(self, log):
        self.log = log

        # Wired by Orchestrator after construction
        self.on_login_complete = None
        self.on_device_code    = None
        self.error_login       = None

        self.token  = None
        self.worker = None  # keep a reference so the QThread isn't garbage collected

        client_id = get("CLIENT_ID")
        tenant_id = get("TENANT_ID")
        authority = f"https://login.microsoftonline.com/{tenant_id}"

        self.log.info("MSALService: Loading token cache")
        self.cache = self._load_cache()

        self.SCOPES = ["User.Read", "Sites.ReadWrite.All", "Files.ReadWrite", "Mail.Send"]

        self.log.info(f"MSALService: Building MSAL app")
        self.app = msal.PublicClientApplication(
            client_id, authority=authority, token_cache=self.cache
        )
        self.log.info("MSALService: Ready")

    def start_login(self):
        """Tries silent → interactive → device code, stops at first success."""
        self.log.section("MSAL LOGIN")
        accounts = self.app.get_accounts()

        # Try silent first (fastest — no user interaction if token is cached)
        if accounts:
            self.log.info(f"MSALService: Trying silent login | {accounts[0].get('username')}")
            result = self.app.acquire_token_silent(self.SCOPES, account=accounts[0])

            if result and "access_token" in result:
                self.log.info("MSALService: Silent login succeeded")
                self._handle_result(result)
                return

            self.log.info("MSALService: Silent login failed — token likely expired")

        # Try interactive (browser pop-up)
        self.log.info("MSALService: Trying interactive login")
        try:
            result = self.app.acquire_token_interactive(self.SCOPES)
        except Exception as e:
            self.log.warning(f"MSALService: Interactive login unavailable — {e}")
            result = None

        if result and "access_token" in result:
            self.log.info("MSALService: Interactive login succeeded")
            self._handle_result(result)
            return

        # Fall back to device code flow
        self.log.info("MSALService: Falling back to device code flow")
        self.worker = LoginWorker(self.app, self.SCOPES)
        self.worker.finished.connect(self._on_worker_payload)
        self.worker.start()

    def _on_worker_payload(self, payload: dict):
        """Handles both signal types from LoginWorker (code ready, or auth result)."""
        payload_type = payload.get("type")

        if payload_type == "code":
            self.log.info(f"MSALService: Device code ready | {payload.get('user_code')}")
            if self.on_device_code:
                self.on_device_code(payload)
            return

        if payload_type == "result":
            self.log.info("MSALService: Device code auth complete")
            self._handle_result(payload.get("result", {}))
            return

        self.log.error(f"MSALService: Unexpected worker payload | {payload}")
        if self.error_login:
            self.error_login("Unexpected authentication response")

    def _handle_result(self, result: dict):
        """On success, fetches the user profile and fires on_login_complete."""
        if "access_token" in result:
            self.token = result["access_token"]
            self.log.info("MSALService: Token acquired — fetching user profile")

            try:
                email, name = self._fetch_user_profile()
            except Exception as e:
                self.log.error(f"MSALService: Failed to fetch user profile — {e}", error=e)
                if self.error_login:
                    self.error_login(str(e))
                return

            self.log.event("Login complete", user=name, email=email)
            if self.on_login_complete:
                self.on_login_complete(email, name, self.token)

        else:
            error = (
                result.get("error_description")
                or result.get("error")
                or "Unknown MSAL error"
            )
            self.log.error(f"MSALService: Token acquisition failed — {error}")
            if self.error_login:
                self.error_login(error)

    def _fetch_user_profile(self) -> tuple[str, str]:
        """Calls Graph /me to get the user's email and display name."""
        self.log.info("MSALService: Calling Graph /me")
        response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {self.token}"},
        )

        if response.status_code == 200:
            data  = response.json()
            email = data.get("mail")
            name  = data.get("displayName")
            self.log.info(f"MSALService: Profile fetched | {name} ({email})")
            return email, name

        raise RuntimeError(
            f"MSALService: Graph /me returned HTTP {response.status_code}"
        )

    def _load_cache(self) -> PersistedTokenCache:
        """Loads (or creates) the encrypted token cache file."""
        cache_path = app_data_path() / "data" / "auth" / "msal" / "token_cache.bin"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.log.info(f"MSALService: Cache path — {cache_path}")
        persistence = build_encrypted_persistence(str(cache_path))
        return PersistedTokenCache(persistence)
