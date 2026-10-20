import pytest
from django.db import OperationalError
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from accounts.models import User
from config.pagination import ResilientPageNumberPagination
from library.models import ImageSubmission
from library.serializers import SubmissionSerializer

pytestmark = pytest.mark.django_db
ROOT = "/api/moderation/workspace/administration/"


@pytest.fixture
def admin(client):
    actor = User.objects.create_superuser(username="page_admin", email="pages@example.test")
    client.force_authenticate(actor)
    return actor


def pending_images(count, uploaded_submission):
    data = uploaded_submission(canonical_answer="review target 0", source="manual")
    # This fixture supplies multipart JSON text; direct serializer calls take a list.
    data["accepted_synonyms"] = []
    serializer = SubmissionSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    image = serializer.save()
    ImageSubmission.objects.bulk_create(
        [
            ImageSubmission(
                canonical_answer=f"review target {index}",
                category=image.category,
                image_file=image.image_file.name,
                source="manual",
                license="CC0",
                attribution="Test",
            )
            for index in range(1, count)
        ]
    )


@pytest.mark.parametrize("operation", ["approve", "reject"])
@pytest.mark.parametrize("removed", [1, 2])
def test_review_recovers_last_pending_page(client, admin, uploaded_submission, operation, removed):
    pending_images(96 + removed, uploaded_submission)
    url = ROOT + "images/?status=pending&q=review%20target&sort=oldest&page=5"
    before = client.get(url).json()
    assert (before["page"], before["total_pages"], len(before["results"])) == (5, 5, removed)
    response = client.post(
        ROOT + "images/review/",
        {
            "operation": operation,
            "ids": [row["id"] for row in before["results"]],
        },
        format="json",
    )
    assert all(row["status"] == "success" for row in response.json()["results"])
    result = client.get(url)
    assert result.status_code == 200
    after = result.json()
    assert (after["page"], after["total_pages"], after["count"], after["page_size"]) == (
        4,
        4,
        96,
        24,
    )
    assert len(after["results"]) == 24 and after["next"] is None
    assert "status=pending" in after["previous"] and "sort=oldest" in after["previous"]
    assert all(row["status"] == "pending" for row in after["results"])


def test_valid_page_stays_and_empty_page_recovers(client, admin, uploaded_submission):
    pending_images(97, uploaded_submission)
    rows = client.get(ROOT + "images/?status=pending&page=3").json()["results"]
    client.post(
        ROOT + "images/review/", {"operation": "reject", "ids": [rows[0]["id"]]}, format="json"
    )
    assert client.get(ROOT + "images/?status=pending&page=3").json()["page"] == 3
    other = User.objects.create_superuser(
        username="other_page_admin", email="other-pages@example.test"
    )
    concurrent_client = APIClient()
    concurrent_client.force_authenticate(other)
    other_ids = list(ImageSubmission.objects.filter(status="pending").values_list("pk", flat=True))
    for offset in range(0, len(other_ids), 50):
        response = concurrent_client.post(
            ROOT + "images/review/",
            {"operation": "reject", "ids": other_ids[offset : offset + 50]},
            format="json",
        )
        assert response.status_code == 200
        assert all(row["status"] == "success" for row in response.json()["results"])
    empty = client.get(ROOT + "images/?status=pending&page=5").json()
    assert (empty["page"], empty["total_pages"], empty["count"]) == (1, 0, 0)
    assert empty["results"] == [] and empty["previous"] is None and empty["next"] is None


@pytest.mark.parametrize(
    "requested, expected",
    [("1", 1), ("2", 2), ("999", 2), ("last", 2), ("0", 1), ("-4", 1), ("wrong", 1), ("2.5", 1)],
)
def test_shared_paginator_clamps_with_one_count(requested, expected, django_assert_num_queries):
    User.objects.bulk_create(
        [User(username=f"page_user_{index}", email=f"p{index}@example.test") for index in range(25)]
    )
    pagination = ResilientPageNumberPagination()
    request = Request(APIRequestFactory().get("/?page=" + requested + "&q=kept"))
    with django_assert_num_queries(2):
        rows = pagination.paginate_queryset(User.objects.order_by("pk"), request)
        data = pagination.get_paginated_response([str(row.pk) for row in rows]).data
    assert data["page"] == expected and data["total_pages"] == 2 and data["page_size"] == 24
    assert "count" in data and "results" in data and "previous" in data and "next" in data


@pytest.mark.parametrize(
    "path",
    [
        ROOT + "images/",
        ROOT + "player-submissions/",
        ROOT + "imports/",
        ROOT + "audit/",
        ROOT + "players/",
        ROOT + "staff/",
        "/api/moderation/workspace/players/",
        "/api/moderation/workspace/reports/",
        "/api/moderation/workspace/appeals/",
        "/api/library/contributions/",
        "/api/library/catalog/",
        "/api/ranked/leaderboard/",
    ],
)
def test_list_endpoints_publish_page_metadata_and_recover_invalid_pages(client, admin, path):
    response = client.get(path, {"page": "999"})
    assert response.status_code == 200
    data = response.json()
    assert data["page_size"] == 24
    assert data["total_pages"] == (data["count"] + 23) // 24
    assert data["page"] == max(1, data["total_pages"])


def test_history_empty_page_recovers(client, user):
    response = client.get(f"/api/ranked/history/{user.username}/?page=9")
    assert response.status_code == 200
    assert response.json()["page"] == 1 and response.json()["total_pages"] == 0


def test_pagination_does_not_swallow_database_errors():
    class UnavailableQuerySet:
        ordered = True

        def count(self):
            raise OperationalError("Database unavailable")

    queryset = UnavailableQuerySet()
    with pytest.raises(OperationalError, match="Database unavailable"):
        ResilientPageNumberPagination().paginate_queryset(
            queryset, Request(APIRequestFactory().get("/?page=2"))
        )
