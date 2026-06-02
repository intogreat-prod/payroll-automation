"""
outlook_services.py — sends email via the Microsoft Graph sendMail API.

Sends from the signed-in user's mailbox, so recipients see it as coming
from whoever is logged in. Used in Orchestrator._add_user() to send
the welcome email to newly added users.

Scope needed: Mail.Send
"""

import json
import requests


class OutlookService:

    def send(self, url: str, payload: dict, token: str, content_type: str = "application/json") -> requests.Response:
        """
        POSTs to the Graph sendMail endpoint.
        Returns 202 Accepted when the email is queued for delivery.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  content_type,
        }
        return requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
