"""
sharepoint_service.py — thin wrapper around the Microsoft Graph SharePoint drive API.

Handles auth by attaching the Bearer token passed at construction. Callers
build the full Graph URL themselves and pass it in — this service just does
the actual HTTP call.

Scopes needed: Sites.Read.All, Files.ReadWrite.All
"""

import requests


class SharePointService:

    def __init__(self, token: str):
        self.token = token

    def get(self, url: str) -> requests.Response:
        """Authenticated GET — used for downloading files and listing folder contents."""
        return requests.get(url, headers={"Authorization": f"Bearer {self.token}"})

    def put_file(self, url: str, data, content_type: str = "application/octet-stream") -> requests.Response:
        """
        Uploads content to a SharePoint drive item (creates or overwrites).
        URL should end in :/content per the Graph API convention.
        """
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  content_type,
        }
        return requests.put(url, headers=headers, data=data)

    def post_json(self, url: str, payload: dict) -> requests.Response:
        """POST a JSON payload — available for future use (list items, adaptive cards, etc.)."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }
        return requests.post(url, headers=headers, json=payload)
