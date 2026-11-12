"""
sharepoint_list_service.py — Microsoft Graph client for ONE SharePoint list.

Sits next to sharepoint_service.py (which handles drive files).  Same style:
the Bearer token is passed at construction, every call has a timeout, and the
raw requests.Response is returned so callers keep using utils.internet.ok().
The one exception is to_dataframe(), which returns a DataFrame and raises
on failure.

Scopes needed: Sites.ReadWrite.All

Usage
-----
    lists = SharePointListService(token, site_id, list_id)

    r  = lists.get("12")                          # one item
    r  = lists.create({"Title": "New", "Status": "Open"})
    r  = lists.update("12", {"Status": "Closed"}) # partial update
    df = lists.to_dataframe(filter_="fields/Status eq 'Open'")

site_id : Graph site id, e.g. "contoso.sharepoint.com,<siteGuid>,<webGuid>"
          (or "contoso.sharepoint.com:/sites/Payroll:")
list_id : list GUID or the list's display name

Field names
-----------
Graph uses each column's INTERNAL name (e.g. "Employee_x0020_ID" for a
column displayed as "Employee ID"), both when writing and in the DataFrame
columns.  Person / lookup / choice-multi columns come back as nested
dicts/lists and are left as-is.
"""

import time

import pandas as pd
import requests

_GRAPH    = "https://graph.microsoft.com/v1.0"
_TIMEOUT  = 30   # seconds — applied to every request
_RETRIES  = 3    # attempts on 429 / 503 (honours Retry-After)
_PAGE_MAX = 999  # Graph's max $top for list items


class SharePointListService:

    def __init__(self, token: str, site_id: str, list_id: str):
        self.token = token
        self.base  = f"{_GRAPH}/sites/{site_id}/lists/{list_id}"

    # ===================================================================
    # HTTP
    # ===================================================================

    def _request(self, method: str, url: str, *, params=None, json=None,
                 extra_headers=None) -> requests.Response:
        """Authenticated request with a small retry on throttling."""
        headers = {"Authorization": f"Bearer {self.token}"}
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(_RETRIES):
            response = requests.request(
                method, url, headers=headers, params=params,
                json=json, timeout=_TIMEOUT,
            )
            if response.status_code not in (429, 503) or attempt == _RETRIES - 1:
                return response
            try:
                wait = int(response.headers.get("Retry-After", 2 ** attempt))
            except ValueError:
                wait = 2 ** attempt
            time.sleep(min(wait, 30))
        return response  # unreachable; keeps linters quiet

    # ===================================================================
    # GET — one item
    # ===================================================================

    def get(self, item_id: str) -> requests.Response:
        """
        Fetch one item.  On success response.json()["fields"] holds the
        column values and response.json()["id"] the item id.
        """
        return self._request(
            "GET", f"{self.base}/items/{item_id}", params={"expand": "fields"}
        )

    # ===================================================================
    # CREATE
    # ===================================================================

    def create(self, fields: dict) -> requests.Response:
        """
        Create an item.  `fields` maps internal column name -> value.
        Returns 201 on success; response.json()["id"] is the new item id.
        """
        return self._request("POST", f"{self.base}/items", json={"fields": fields})

    # ===================================================================
    # UPDATE
    # ===================================================================

    def update(self, item_id: str, fields: dict) -> requests.Response:
        """
        Partial update: only the columns in `fields` change, others are
        untouched.  Returns 200 on success (body is the updated fields).
        """
        return self._request(
            "PATCH", f"{self.base}/items/{item_id}/fields", json=fields
        )

    # ===================================================================
    # LIST -> DATAFRAME
    # ===================================================================

    def to_dataframe(
        self,
        select:  list | None = None,
        filter_: str | None  = None,
        top:     int | None  = None,
    ) -> pd.DataFrame:
        """
        Read the list into a DataFrame (follows paging automatically).

        Parameters
        ----------
        select  : internal column names to return (default: all columns)
        filter_ : OData filter, e.g. "fields/Status eq 'Open'"
        top     : stop after this many items (default: all)

        Returns
        -------
        pd.DataFrame
            One row per item; an "id" column holds the item id (use it with
            get/update), followed by the item's fields.

        Raises
        ------
        UserWarning
            On any non-2xx response (same convention as UnmandService).
        """
        params = {"expand": "fields", "$top": min(top or _PAGE_MAX, _PAGE_MAX)}
        extra  = None
        if select:
            params["expand"] = f"fields($select={','.join(select)})"
        if filter_:
            params["$filter"] = filter_
            # Lets Graph filter on non-indexed columns instead of failing
            extra = {"Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"}

        rows = []
        url  = f"{self.base}/items"
        while url:
            response = self._request("GET", url, params=params, extra_headers=extra)
            if not 200 <= response.status_code < 300:
                raise UserWarning(
                    f"SharePointListService: List read failed — "
                    f"HTTP {response.status_code} @ {self.base}"
                )

            body = response.json()
            for item in body.get("value", []):
                rows.append({"id": item.get("id"), **item.get("fields", {})})

            if top and len(rows) >= top:
                rows = rows[:top]
                break

            url    = body.get("@odata.nextLink")
            params = None   # nextLink already carries the query string

        return pd.DataFrame(rows)
