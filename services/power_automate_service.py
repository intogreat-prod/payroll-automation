"""
power_automate_service.py — triggers Power Automate HTTP flows.

Used in two places:
- Orchestrator._add_user()     → adds the new user to the Teams group via Entra
- utils/error_handler.py       → posts an error card to the Teams channel

Flow URLs come from config (never hardcoded here). The URL itself contains
the SAS token, so no Authorization header is needed.
"""

import json
import requests


class PowerAutomateService:

    def start(self, url: str, payload: dict, content_type: str = "application/json") -> requests.Response:
        """
        POSTs to a Power Automate HTTP trigger URL.
        202 Accepted means the flow was queued — not that it finished.
        """
        return requests.post(
            url,
            headers={"Content-Type": content_type},
            data=json.dumps(payload),
            timeout=10,
        )
