"""Google Business Profile API adapter with no credential persistence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GoogleBusinessProfileIntegrationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class PublishedBusinessPost:
    post_id: str


@dataclass(frozen=True)
class BusinessProfileInspection:
    """Aggregate-only live GBP evidence; review text is never persisted."""

    location_id: str
    location_name: str | None
    website_uri: str | None
    primary_phone: str | None
    categories: tuple[str, ...]
    hours_present: bool
    service_area_present: bool
    open_state: str | None
    review_count: int | None
    average_rating: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "location_id": self.location_id,
            "location_name": self.location_name,
            "website_uri": self.website_uri,
            "primary_phone": self.primary_phone,
            "categories": list(self.categories),
            "hours_present": self.hours_present,
            "service_area_present": self.service_area_present,
            "open_state": self.open_state,
            "review_count": self.review_count,
            "average_rating": self.average_rating,
        }


class GoogleBusinessProfileAdapter:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    POST_URL = "https://mybusiness.googleapis.com/v4/{location}:localPosts"
    LOCATION_URL = "https://mybusinessbusinessinformation.googleapis.com/v1/{location}"
    REVIEWS_URL = "https://mybusiness.googleapis.com/v4/{account}/{location}/reviews"

    def __init__(self) -> None:
        self._client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        self._client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        self._refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
        if not self._client_id or not self._client_secret or not self._refresh_token:
            raise GoogleBusinessProfileIntegrationError("gbp_configuration_missing")
        self._cached_access_token: str | None = None

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
        ).encode()
        try:
            with urlopen(
                Request(self.TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"),
                timeout=15,
            ) as response:
                payload = json.loads(response.read().decode())
        except HTTPError as error:
            raise GoogleBusinessProfileIntegrationError("gbp_authorization_failed") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GoogleBusinessProfileIntegrationError("gbp_temporarily_unavailable", retryable=True) from error
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise GoogleBusinessProfileIntegrationError("gbp_authorization_failed")
        self._cached_access_token = token
        return token

    def publish_post(self, location_id: str, summary: str, call_to_action_url: str | None) -> PublishedBusinessPost:
        payload: dict[str, object] = {"languageCode": "en", "summary": summary, "topicType": "STANDARD"}
        if call_to_action_url:
            payload["callToAction"] = {"actionType": "LEARN_MORE", "url": call_to_action_url}
        request = Request(
            self.POST_URL.format(location=location_id),
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode())
        except HTTPError as error:
            if error.code in {401, 403}:
                raise GoogleBusinessProfileIntegrationError("gbp_authorization_failed") from error
            if error.code == 429 or error.code >= 500:
                raise GoogleBusinessProfileIntegrationError("gbp_temporarily_unavailable", retryable=True) from error
            raise GoogleBusinessProfileIntegrationError("gbp_publish_failed") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GoogleBusinessProfileIntegrationError("gbp_temporarily_unavailable", retryable=True) from error
        post_id = result.get("name") if isinstance(result, dict) else None
        if not isinstance(post_id, str) or not post_id:
            raise GoogleBusinessProfileIntegrationError("gbp_invalid_response", retryable=True)
        return PublishedBusinessPost(post_id=post_id)

    def _get_json(self, url: str) -> dict:
        request = Request(url, headers={"Authorization": f"Bearer {self._access_token()}"}, method="GET")
        try:
            with urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode())
        except HTTPError as error:
            if error.code in {401, 403}:
                raise GoogleBusinessProfileIntegrationError("gbp_authorization_failed") from error
            if error.code == 404:
                raise GoogleBusinessProfileIntegrationError("gbp_location_not_found") from error
            if error.code == 429 or error.code >= 500:
                raise GoogleBusinessProfileIntegrationError("gbp_temporarily_unavailable", retryable=True) from error
            raise GoogleBusinessProfileIntegrationError("gbp_inspection_failed") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GoogleBusinessProfileIntegrationError("gbp_temporarily_unavailable", retryable=True) from error
        if not isinstance(result, dict):
            raise GoogleBusinessProfileIntegrationError("gbp_invalid_response", retryable=True)
        return result

    def inspect_location(self, account_id: str, location_id: str) -> BusinessProfileInspection:
        """Read location facts and aggregate review metrics without storing review content."""
        location = location_id.strip()
        account = account_id.strip()
        if not account or not location:
            raise GoogleBusinessProfileIntegrationError("gbp_location_mapping_missing")
        read_mask = ",".join(
            (
                "name", "title", "phoneNumbers", "categories", "storefrontAddress",
                "websiteUri", "regularHours", "specialHours", "serviceArea", "openInfo",
                "metadata", "profile",
            )
        )
        location_payload = self._get_json(
            f"{self.LOCATION_URL.format(location=location)}?readMask={urlencode({'fields': read_mask})[7:]}"
        )
        reviews_payload = self._get_json(self.REVIEWS_URL.format(account=account, location=location))
        phone_numbers = location_payload.get("phoneNumbers") or {}
        categories_payload = location_payload.get("categories") or {}
        categories = []
        primary = categories_payload.get("primaryCategory")
        if isinstance(primary, dict) and primary.get("displayName"):
            categories.append(str(primary["displayName"]))
        for category in categories_payload.get("additionalCategories") or []:
            if isinstance(category, dict) and category.get("displayName"):
                categories.append(str(category["displayName"]))
        reviews = reviews_payload.get("reviews") or []
        rating = reviews_payload.get("averageRating")
        return BusinessProfileInspection(
            location_id=str(location_payload.get("name") or location),
            location_name=(location_payload.get("title") or {}).get("displayName") if isinstance(location_payload.get("title"), dict) else location_payload.get("title"),
            website_uri=location_payload.get("websiteUri"),
            primary_phone=phone_numbers.get("primaryPhone"),
            categories=tuple(dict.fromkeys(categories)),
            hours_present=bool(location_payload.get("regularHours")),
            service_area_present=bool(location_payload.get("serviceArea")),
            open_state=(location_payload.get("openInfo") or {}).get("status"),
            review_count=(int(reviews_payload["totalReviewCount"]) if reviews_payload.get("totalReviewCount") is not None else len(reviews) if isinstance(reviews, list) else None),
            average_rating=float(rating) if isinstance(rating, (int, float)) else None,
        )
