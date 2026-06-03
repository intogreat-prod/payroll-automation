"""
config_service.py — reads and writes the remote app config JSON.

The config lives on SharePoint and controls who can log in, folder paths,
Unmand webhook details, deminimis values, and Teams group IDs. It's fetched
right after login and cached in Orchestrator.state["config"] for the session.
Any change (new user, updated deminimis) gets written back immediately.

Env vars needed: SP_BASE_URL, config_loc
"""

import json
import os
import requests

from utils.app_config_user import get


class ConfigService:

    def __init__(self):
        base_url   = get("SP_BASE_URL", "")
        config_loc = get("config_loc", "")
        self.config_url = f"{base_url}{config_loc}"

    def get(self, token: str) -> requests.Response:
        """Downloads the config JSON. Raises on non-200."""
        headers  = {"Authorization": f"Bearer {token}"}
        response = requests.get(self.config_url, headers=headers)

        if response.status_code == 200:
            return response

        raise Exception(
            f"ConfigService: Failed to fetch config — HTTP {response.status_code}"
        )

    def update(self, config_data: dict, token: str) -> requests.Response:
        """
        Overwrites the remote config with the given dict (full replace, not patch).
        Last write wins — no conflict detection.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
        return requests.put(
            self.config_url,
            headers=headers,
            data=json.dumps(config_data, indent=4),
        )
