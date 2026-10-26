"""
sharepoint_service.py — thin wrapper around the Microsoft Graph SharePoint drive API.

Handles auth by attaching the Bearer token passed at construction. Callers
build the full Graph URL themselves and pass it in — this service just does
the actual HTTP call.

Scopes needed: Sites.ReadWrite.All, Files.ReadWrite
"""

import requests

_TIMEOUT = 30   # seconds — applied to every request


class SharePointService:

    def __init__(self, token: str):
        self.token = token

    def get(self, url: str) -> requests.Response:
        """Authenticated GET — used for downloading files and listing folder contents."""
        return requests.get(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=_TIMEOUT,
        )

    def put_file(self, url: str, data, content_type: str = "application/octet-stream", bypass_lock: bool = False) -> requests.Response:
        """
        Uploads content to a SharePoint drive item (creates or overwrites).
        URL should end in :/content per the Graph API convention.
        bypass_lock : bool
            When True, sends "Prefer: bypass-shared-lock" — Graph
            returns HTTP 423 when the item is checked out or has an
            active Office co-authoring session, and this header is the
            documented way to force the overwrite anyway. Only use this
            for files this app owns end-to-end (e.g. the Insightful
            tracker); leave False for hand-off files another person may
            legitimately have open.
        """
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  content_type,
        }
        if bypass_lock:
            headers["Prefer"] = "bypass-shared-lock"
            
        return requests.put(url, headers=headers, data=data, timeout=_TIMEOUT)

    def post_json(self, url: str, payload: dict) -> requests.Response:
        """POST a JSON payload — available for future use (list items, adaptive cards, etc.)."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }
        return requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
