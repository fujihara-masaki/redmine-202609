from __future__ import annotations

from typing import Any

import pytest

from redmine_readonly.config import Config


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        content_type: str = "application/json",
        json_error: Exception | None = None,
    ):
        self.status_code = status
        self._payload = payload
        self.headers = {"Content-Type": content_type}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, *args, **kwargs):  # pragma: no cover - fails loudly if introduced
        raise AssertionError("POST must never be called")


@pytest.fixture
def config():
    return Config(
        "https://redmine.example.invalid/redmine",
        page_size=2,
        max_issues=20,
        max_pages=10,
    )


def issue(number: int, subject: str | None = None, assigned=True):
    value = {
        "id": number,
        "subject": subject if subject is not None else f"Issue {number}",
        "project": {"id": 10, "name": "試験"},
        "tracker": {"id": 2, "name": "障害"},
        "status": {"id": 1, "name": "New"},
        "created_on": "2026-01-01T00:00:00Z",
        "updated_on": "2026-01-02T00:00:00Z",
    }
    if assigned:
        value["assigned_to"] = {"id": 7, "name": "担当者"}
    return value


def page(items, total, offset=0):
    return FakeResponse(
        payload={
            "issues": items,
            "total_count": total,
            "offset": offset,
            "limit": len(items),
        }
    )
