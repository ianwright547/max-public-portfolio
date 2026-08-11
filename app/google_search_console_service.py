"""Replaceable, read-only Google Search Console adapter.

The adapter exchanges the agency refresh token only in memory and retrieves
aggregate metrics. It does not modify Search Console properties or websites.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class SearchConsoleIntegrationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class SearchConsoleMetrics:
    clicks: int
    impressions: int
    has_data: bool = True


@dataclass(frozen=True)
class SearchConsoleReport:
    metrics: SearchConsoleMetrics
    query_rows: tuple[dict[str, object], ...] = ()
    page_rows: tuple[dict[str, object], ...] = ()


class GoogleSearchConsoleAdapter:
    """Use the configured refresh token to read one verified property only."""

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    QUERY_URL = "https://www.googleapis.com/webmasters/v3/sites/{property_url}/searchAnalytics/query"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ) -> None:
        self._client_id = (client_id or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
        self._client_secret = (client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")).strip()
        self._refresh_token = (refresh_token or os.getenv("GOOGLE_REFRESH_TOKEN", "")).strip()
        if not self._client_id or not self._client_secret or not self._refresh_token:
            raise SearchConsoleIntegrationError("search_console_configuration_missing")
        self._cached_access_token: str | None = None

    @staticmethod
    def _token_error(error: HTTPError) -> SearchConsoleIntegrationError:
        if error.code in {400, 401, 403}:
            return SearchConsoleIntegrationError("search_console_authorization_failed")
        if error.code == 404:
            return SearchConsoleIntegrationError("search_console_property_not_found")
        if error.code == 429 or error.code >= 500:
            return SearchConsoleIntegrationError("search_console_temporarily_unavailable", retryable=True)
        return SearchConsoleIntegrationError("search_console_request_failed")

    @staticmethod
    def _query_error(error: HTTPError) -> SearchConsoleIntegrationError:
        if error.code == 403:
            return SearchConsoleIntegrationError("search_console_authorization_failed")
        if error.code == 404:
            return SearchConsoleIntegrationError("search_console_property_not_found")
        if error.code == 429 or error.code >= 500:
            return SearchConsoleIntegrationError("search_console_temporarily_unavailable", retryable=True)
        return SearchConsoleIntegrationError("search_console_request_invalid")

    def _access_token(self) -> str:
        if self._cached_access_token:
            return self._cached_access_token
        body = urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = Request(
            self.TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise self._token_error(error) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SearchConsoleIntegrationError("search_console_temporarily_unavailable", retryable=True) from error
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise SearchConsoleIntegrationError("search_console_authorization_failed")
        self._cached_access_token = token
        return token

    def read_metrics(self, property_url: str, start_date: str, end_date: str) -> SearchConsoleMetrics:
        request = Request(
            self.QUERY_URL.format(property_url=quote(property_url, safe="")),
            data=json.dumps({"startDate": start_date, "endDate": end_date}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise self._query_error(error) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SearchConsoleIntegrationError("search_console_temporarily_unavailable", retryable=True) from error
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not rows:
            return SearchConsoleMetrics(clicks=0, impressions=0, has_data=False)
        row = rows[0]
        try:
            return SearchConsoleMetrics(clicks=int(row.get("clicks", 0)), impressions=int(row.get("impressions", 0)))
        except (AttributeError, TypeError, ValueError) as error:
            raise SearchConsoleIntegrationError("search_console_invalid_response", retryable=True) from error

    @staticmethod
    def _rows(payload: object) -> tuple[dict[str, object], ...]:
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise SearchConsoleIntegrationError("search_console_invalid_response", retryable=True)
        normalized: list[dict[str, object]] = []
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            keys = row.get("keys")
            if not isinstance(keys, list) or not keys or not isinstance(keys[0], str):
                continue
            try:
                normalized.append(
                    {
                        "key": keys[0],
                        "clicks": int(row.get("clicks", 0)),
                        "impressions": int(row.get("impressions", 0)),
                        "ctr": float(row.get("ctr", 0.0)),
                        "position": float(row.get("position", 0.0)),
                    }
                )
            except (TypeError, ValueError):
                continue
        return tuple(normalized)

    def _read_dimension(
        self, property_url: str, start_date: str, end_date: str, dimension: str
    ) -> tuple[dict[str, object], ...]:
        request = Request(
            self.QUERY_URL.format(property_url=quote(property_url, safe="")),
            data=json.dumps(
                {
                    "startDate": start_date,
                    "endDate": end_date,
                    "dimensions": [dimension],
                    "rowLimit": 50,
                    "dataState": "final",
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise self._query_error(error) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SearchConsoleIntegrationError("search_console_temporarily_unavailable", retryable=True) from error
        return self._rows(payload)

    def read_report(self, property_url: str, start_date: str, end_date: str) -> SearchConsoleReport:
        metrics = self.read_metrics(property_url, start_date, end_date)
        if not metrics.has_data:
            return SearchConsoleReport(metrics=metrics)
        return SearchConsoleReport(
            metrics=metrics,
            query_rows=self._read_dimension(property_url, start_date, end_date, "query"),
            page_rows=self._read_dimension(property_url, start_date, end_date, "page"),
        )
