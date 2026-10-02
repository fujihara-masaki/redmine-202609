import pytest
from conftest import FakeResponse, FakeSession, issue, page

from redmine_readonly.client import RedmineClient
from redmine_readonly.config import Config
from redmine_readonly.errors import AppError
from redmine_readonly.exporter import fetch_issues, select_fields, to_jst


def client(config, responses):
    return RedmineClient(config, "test-key", FakeSession(responses))


@pytest.mark.parametrize("items", [[], [issue(1)]])
def test_zero_and_one_issue(config, items):
    result = fetch_issues(client(config, [page(items, len(items))]), "project")
    assert [item["id"] for item in result.issues] == [item["id"] for item in items]
    assert result.metadata["issue_count"] == len(items)


def test_multiple_pages_and_server_page_size_cap(config):
    api = client(
        config, [page([issue(1)], 3, 0), page([issue(2)], 3, 1), page([issue(3)], 3, 2)]
    )
    result = fetch_issues(api, "p", tracker_id=2, include_subprojects=True)
    assert [row["id"] for row in result.issues] == [1, 2, 3]
    offsets = [call[2]["params"]["offset"] for call in api._session.calls]
    assert offsets == [0, 1, 2]
    params = api._session.calls[0][2]["params"]
    assert params == {
        "project_id": "p",
        "status_id": "*",
        "subproject_id": "*",
        "sort": "id:asc",
        "tracker_id": 2,
        "limit": 2,
        "offset": 0,
    }


def test_full_issue_fields_are_discarded_during_page_processing(config):
    full_issue = issue(1)
    full_issue.update(
        {
            "description": "large unnecessary description" * 100,
            "custom_fields": [{"id": 99, "value": "not selected"}],
            "journals": [{"id": 123, "notes": "not selected"}],
        }
    )

    result = fetch_issues(client(config, [page([full_issue], 1)]), "p")

    assert result.issues == [
        {
            "id": 1,
            "subject": "Issue 1",
            "project": {"id": 10, "name": "試験"},
            "tracker": {"id": 2, "name": "障害"},
            "status": {"id": 1, "name": "New"},
            "assigned_to": {"id": 7, "name": "担当者"},
            "created_on": "2026-01-01T00:00:00Z",
            "updated_on": "2026-01-02T00:00:00Z",
        }
    ]


def test_default_excludes_subprojects_and_includes_all_statuses(config):
    api = client(config, [page([], 0)])
    fetch_issues(api, "p")
    params = api._session.calls[0][2]["params"]
    assert params["subproject_id"] == "!*"
    assert params["status_id"] == "*"


def test_explicit_status_filter(config):
    api = client(config, [page([], 0)])
    fetch_issues(api, "p", status_id="closed")
    assert api._session.calls[0][2]["params"]["status_id"] == "closed"


@pytest.mark.parametrize(
    ("project", "tracker", "status"),
    [("", None, "*"), ("p", 0, "*"), ("p", None, "")],
)
def test_invalid_filters_fail_before_request(config, project, tracker, status):
    api = client(config, [])
    with pytest.raises(AppError):
        fetch_issues(api, project, tracker_id=tracker, status_id=status)
    assert api._session.calls == []


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([page([issue(1)], 2, 0), page([issue(1)], 2, 1)], "duplicate"),
        ([page([issue(1)], 2, 0), page([issue(2)], 3, 1)], "count changed"),
        ([page([issue(1)], 2, 0), page([], 2, 1)], "empty page"),
        ([page([issue(1)], 2, 0), page([issue(2)], 2, 0)], "offset"),
        ([page([issue(1)], 2, 0), FakeResponse(500, {})], "HTTP 500"),
    ],
)
def test_incomplete_or_inconsistent_retrieval_fails(config, responses, message):
    with pytest.raises(AppError, match=message):
        fetch_issues(client(config, responses), "p")


def test_limits_are_failures():
    config = Config(
        "https://redmine.example.invalid", page_size=1, max_issues=1, max_pages=1
    )
    with pytest.raises(AppError, match="exceeds configured maximum"):
        fetch_issues(client(config, [page([], 2)]), "p")


def test_only_get_is_used(config):
    api = client(config, [page([], 0)])
    fetch_issues(api, "p")
    assert {call[0] for call in api._session.calls} == {"GET"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-01-01T00:00:00Z", "2026-01-01 09:00:00 +09:00"),
        ("2026-01-01T18:30:00+00:00", "2026-01-02 03:30:00 +09:00"),
        ("2026-01-01T12:00:00-05:00", "2026-01-02 02:00:00 +09:00"),
        (None, None),
    ],
)
def test_to_jst_handles_iso_offsets_and_none(raw, expected):
    assert to_jst(raw) == expected


@pytest.mark.parametrize("raw", ["not-a-date", "2026-01-01T00:00:00", 123])
def test_to_jst_rejects_invalid_or_ambiguous_values(raw):
    with pytest.raises(AppError, match="timestamp"):
        to_jst(raw)


def test_jst_columns_are_opt_in_and_raw_values_are_unchanged():
    raw_issue = issue(1)
    original_created = raw_issue["created_on"]
    original_updated = raw_issue["updated_on"]

    basic = select_fields(raw_issue)
    with_jst = select_fields(raw_issue, include_jst_columns=True)

    assert list(basic) == [
        "id",
        "subject",
        "project",
        "tracker",
        "status",
        "assigned_to",
        "created_on",
        "updated_on",
    ]
    assert "created_on_jst" not in basic
    assert with_jst["created_on"] == original_created
    assert with_jst["updated_on"] == original_updated
    assert with_jst["created_on_jst"] == "2026-01-01 09:00:00 +09:00"
    assert with_jst["updated_on_jst"] == "2026-01-02 09:00:00 +09:00"
    assert raw_issue["created_on"] == original_created
    assert raw_issue["updated_on"] == original_updated
