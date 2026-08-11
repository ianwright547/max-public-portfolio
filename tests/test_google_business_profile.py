"""Google Business Profile stays approval-gated and client-bound."""

from fastapi.testclient import TestClient

from app.main import app
from app import google_business_profile_service
from app.routes import google_business_profile
from app import models
from app.database import SessionLocal
from sqlalchemy import select
from uuid import uuid4


def test_gbp_draft_requires_approval_and_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(google_business_profile, "require_provider_health", lambda *args, **kwargs: {})
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "")
    with TestClient(app) as client:
        created = client.post(
            "/clients", json={"business_name": "GBP Test", "service_start_date": "2026-08-13"}
        ).json()
        client_id = created["id"]
        connection = client.post(
            f"/clients/{client_id}/google-business-profile",
            json={"account_id": "accounts/1", "location_id": "locations/2", "location_name": "GBP Test"},
        )
        draft = client.post(
            f"/clients/{client_id}/google-business-profile/posts",
            json={"operation_key": "gbp-post-operation", "summary": "A truthful update for this business."},
        )
        repeat = client.post(
            f"/clients/{client_id}/google-business-profile/posts",
            json={"operation_key": "gbp-post-operation", "summary": "A truthful update for this business."},
        )
        blocked = client.post(f"/google-business-profile/posts/{draft.json()['id']}/publish")
        approved = client.post(
            f"/google-business-profile/posts/{draft.json()['id']}/approval",
            json={"approved_by": "Agency Owner"},
        )
        monkey = client.post(f"/google-business-profile/posts/{draft.json()['id']}/publish")

    assert connection.status_code == 201
    assert draft.status_code == 201
    assert repeat.json()["id"] == draft.json()["id"]
    assert blocked.status_code == 409
    assert approved.json()["status"] == "approved"
    assert monkey.status_code == 502
    with SessionLocal() as database:
        post_id = draft.json()["id"]
        events = list(
            database.scalars(
                select(models.AuditEvent).where(
                    models.AuditEvent.record_type == "google_business_profile_post",
                    models.AuditEvent.record_id == post_id,
                )
            )
        )
    assert {event.event_type for event in events} == {
        "gbp_post_approved",
        "gbp_post_publish_started",
        "gbp_post_publish_failed",
    }


def test_gbp_adapter_publishes_with_access_token(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh")
    responses = [b'{"access_token":"access"}', b'{"name":"locations/2/localPosts/3"}']

    class FakeResponse:
        def __init__(self, body: bytes):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return self.body

    def fake_urlopen(_request, timeout):
        assert timeout in {15, 20}
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(google_business_profile_service, "urlopen", fake_urlopen)
    result = google_business_profile_service.GoogleBusinessProfileAdapter().publish_post(
        "locations/2", "Truthful post", "https://example.com"
    )
    assert result.post_id == "locations/2/localPosts/3"


def test_gbp_publish_refuses_duplicate_in_flight_publication() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/clients", json={"business_name": f"GBP In Flight {uuid4().hex[:8]}", "service_start_date": "2026-08-13"}
        ).json()
        client_id = created["id"]
        account_id = f"accounts/{uuid4().hex[:8]}"
        location_id = f"locations/{uuid4().hex[:8]}"
        client.post(
            f"/clients/{client_id}/google-business-profile",
            json={"account_id": account_id, "location_id": location_id, "location_name": "GBP In Flight"},
        )
        draft = client.post(
            f"/clients/{client_id}/google-business-profile/posts",
            json={"operation_key": f"gbp-in-flight-{uuid4().hex[:8]}", "summary": "Approved update."},
        ).json()
        client.post(
            f"/google-business-profile/posts/{draft['id']}/approval",
            json={"approved_by": "Agency Owner"},
        )
        with SessionLocal() as database:
            post = database.get(models.GoogleBusinessProfilePost, draft["id"])
            post.status = "publishing"
            database.commit()
        blocked = client.post(f"/google-business-profile/posts/{draft['id']}/publish")

    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "GBP post publication is already in progress"


def test_gbp_adapter_inspects_location_and_aggregate_reviews_without_storing_text(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh")
    responses = [
        b'{"access_token":"access"}',
        b'{"name":"locations/2","title":"Example Auto","websiteUri":"https://example.com","phoneNumbers":{"primaryPhone":"555-0100"},"categories":{"primaryCategory":{"displayName":"Auto repair shop"}},"regularHours":{"periods":[{}]},"openInfo":{"status":"OPEN"}}',
        b'{"totalReviewCount":12,"averageRating":4.5,"reviews":[{"comment":"private text must not persist"}]}',
    ]

    class FakeResponse:
        def __init__(self, body: bytes):
            self.body = body
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return self.body

    monkeypatch.setattr(
        google_business_profile_service,
        "urlopen",
        lambda _request, timeout: FakeResponse(responses.pop(0)),
    )
    result = google_business_profile_service.GoogleBusinessProfileAdapter().inspect_location(
        "accounts/1", "locations/2"
    )

    assert result.location_name == "Example Auto"
    assert result.categories == ("Auto repair shop",)
    assert result.review_count == 12
    assert result.average_rating == 4.5
    assert "private text must not persist" not in str(result.as_dict())
