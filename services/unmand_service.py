"""
unmand_service.py — client for the Unmand RPA platform.

After payroll files are uploaded to SharePoint, we hand off to Unmand to
run the actual payroll robot. The flow is:

    1. start_process() — POSTs to the webhook, gets back a taskGuid
    2. check_status()  — GETs the task status (user presses a button to poll)

Unmand uses a raw token as the Authorization header value, no "Bearer" prefix.
_TokenAuth handles that so requests stays consistent.
"""

import requests


class UnmandService:

    # Maps Unmand's task.status values to PAYROLL_STATUSES keys
    STATUS_MAP = {
        "SUCCESS":  "unmand_status_success",
        "ERROR":    "unmand_status_error",
        "FAILURE":  "unmand_status_error",
        "PENDING":  "unmand_status_pending_error",
        "QUEUED":   "unmand_status_pending_error",
        "RUNNING":  "unmand_status_pending_error",
    }

    _STATUS_ENDPOINT = "https://swarm.unmand.app/tasks/{task_guid}"

    def __init__(self, webhook_url: str, token: str):
        self.webhook_url = webhook_url
        self._auth       = _TokenAuth(token)

    def start_process(self, payload: dict) -> requests.Response:
        """
        Triggers the Unmand payroll robot.
        On success, response.json()["taskGuid"] is what you pass to check_status().
        """
        return requests.post(self.webhook_url, json=payload, auth=self._auth, timeout=30)

    def check_status(self, task_guid: str) -> str:
        """
        Polls the task status endpoint and returns a PAYROLL_STATUSES key.
        Raises UserWarning on a non-2xx response.
        """
        url      = self._STATUS_ENDPOINT.format(task_guid=task_guid)
        response = requests.get(url, auth=self._auth, timeout=30)

        if not str(response.status_code).startswith("2"):
            raise UserWarning(f"UnmandService: Status check failed — HTTP {response.status_code}")

        task_status = response.json().get("task", {}).get("status", "")
        return self.STATUS_MAP.get(task_status, "unmand_status_error")


class _TokenAuth(requests.auth.AuthBase):
    """
    Attaches the Unmand API token directly as the Authorization header value
    (no "Bearer" prefix — that's just how their API works).
    """

    def __init__(self, token: str):
        self._token = token

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = self._token
        return r
