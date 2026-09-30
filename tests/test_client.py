import pytest
import requests
from conftest import FakeResponse, FakeSession

from redmine_readonly.client import RedmineClient
from redmine_readonly.errors import AppError


def test_check_returns_only_minimum_and_get_with_security_options(config):
    session = FakeSession(
        [
            FakeResponse(
                payload={"user": {"id": 3, "login": "alice", "mail": "secret@example"}}
            )
        ]
    )
    client = RedmineClient(config, "TOP-SECRET", session)
    assert client.current_user() == {"id": 3, "login": "alice"}
    method, url, options = session.calls[0]
    assert method == "GET"
    assert url == "https://redmine.example.invalid/redmine/users/current.json"
    assert options["allow_redirects"] is False
    assert options["verify"] is True
    assert options["timeout"] == (5.0, 30.0)
    assert session.headers["X-Redmine-API-Key"] == "TOP-SECRET"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(401, {}), "authentication failed"),
        (FakeResponse(403, {}), "permission denied"),
        (FakeResponse(404, {}), "not found"),
        (FakeResponse(500, {"secret": "LEAK"}), "HTTP 500"),
        (FakeResponse(302, {}), "redirect response refused"),
        (FakeResponse(200, "<html>LEAK</html>", "text/html"), "non-JSON"),
        (FakeResponse(200, json_error=ValueError("SECRET RESPONSE")), "malformed JSON"),
        (requests.ConnectTimeout("URL WITH SECRET"), "timed out"),
    ],
)
def test_safe_distinct_errors(config, response, message):
    client = RedmineClient(config, "TOP-SECRET", FakeSession([response]))
    with pytest.raises(AppError, match=message) as caught:
        client.current_user()
    rendered = str(caught.value)
    assert "TOP-SECRET" not in rendered
    assert "LEAK" not in rendered
    assert "SECRET RESPONSE" not in rendered
    assert "URL WITH SECRET" not in rendered


def test_no_api_key_is_rejected(config):
    with pytest.raises(AppError, match="API key"):
        RedmineClient(config, "  ", FakeSession([]))
