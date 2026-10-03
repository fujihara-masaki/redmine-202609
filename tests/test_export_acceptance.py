import csv
import json
from pathlib import Path

import pytest
from conftest import FakeSession, issue, page

from redmine_readonly.cli import run

BASIC_COLUMNS = [
    "id",
    "subject",
    "project_id",
    "project_name",
    "tracker_id",
    "tracker_name",
    "status_id",
    "status_name",
    "assigned_to_id",
    "assigned_to_name",
    "created_on",
    "updated_on",
]
JST_COLUMNS = ["created_on_jst", "updated_on_jst"]
FIXED_TIME = "2026-03-01T00:00:00+00:00"
SNAPSHOT_NOTE = (
    "Count consistency was checked, but concurrent updates may prevent a "
    "transactional snapshot."
)


def _config(tmp_path: Path, *, page_size: int = 100) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        'base_url = "https://redmine.example.invalid/redmine"\n'
        f"page_size = {page_size}\n",
        encoding="utf-8",
    )
    return path


def _argv(config: Path, output: Path, *, fields=None, jst=False):
    argv = [
        "--config",
        str(config),
        "export",
        "--project",
        "42",
        "--output-dir",
        str(output),
    ]
    if fields is not None:
        argv.extend(["--fields", fields])
    if jst:
        argv.append("--include-jst-columns")
    return argv


def _run_cli(monkeypatch, config, output, responses, **options):
    session = FakeSession(responses)
    monkeypatch.setattr("requests.Session", lambda: session)
    monkeypatch.setattr("redmine_readonly.exporter._utc_now", lambda: FIXED_TIME)
    monkeypatch.setenv("REDMINE_API_KEY", "TEST-ONLY-KEY")
    assert run(_argv(config, output, **options)) == 0
    run_dir = next(output.glob("run-*"))
    return session, run_dir


def _basic_issue(number: int, *, assigned=True):
    item = issue(
        number, '=SUM(1,2)\n架空 "件名"' if number == 1 else "Issue 2", assigned
    )
    # These invalid extended values must remain completely irrelevant to basic.
    item.update(done_ratio="invalid", is_private="not-a-boolean")
    return item


def _expected_basic_issues(items, jst):
    expected = []
    for item in items:
        selected = {
            "id": item["id"],
            "subject": item["subject"],
            "project": {"id": 10, "name": "試験"},
            "tracker": {"id": 2, "name": "障害"},
            "status": {"id": 1, "name": "New"},
            "assigned_to": (
                {"id": 7, "name": "担当者"}
                if "assigned_to" in item
                else {"id": None, "name": None}
            ),
            "created_on": "2026-01-01T00:00:00Z",
            "updated_on": "2026-01-02T00:00:00Z",
        }
        if jst:
            selected.update(
                created_on_jst="2026-01-01 09:00:00 +09:00",
                updated_on_jst="2026-01-02 09:00:00 +09:00",
            )
        expected.append(selected)
    return expected


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("jst", [False, True])
@pytest.mark.parametrize("count", [0, 2])
def test_basic_cli_matches_frozen_base_contract(
    tmp_path, monkeypatch, explicit, jst, count
):
    """Compare every stable output field to constants derived from base 57848fd."""
    config = _config(tmp_path)
    output = tmp_path / "out"
    items = [_basic_issue(1), _basic_issue(2, assigned=False)][:count]
    _, run_dir = _run_cli(
        monkeypatch,
        config,
        output,
        [page(items, count)],
        fields="basic" if explicit else None,
        jst=jst,
    )

    csv_path = run_dir / "issues.csv"
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
        assert stream.encoding == "utf-8-sig"
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream))
    assert header == BASIC_COLUMNS + (JST_COLUMNS if jst else [])
    expected_rows = []
    for item in items:
        row = {
            "id": str(item["id"]),
            "subject": "'" + item["subject"]
            if item["subject"].startswith("=")
            else item["subject"],
            "project_id": "10",
            "project_name": "試験",
            "tracker_id": "2",
            "tracker_name": "障害",
            "status_id": "1",
            "status_name": "New",
            "assigned_to_id": "7" if "assigned_to" in item else "",
            "assigned_to_name": "担当者" if "assigned_to" in item else "",
            "created_on": "2026-01-01T00:00:00Z",
            "updated_on": "2026-01-02T00:00:00Z",
        }
        if jst:
            row.update(
                created_on_jst="2026-01-01 09:00:00 +09:00",
                updated_on_jst="2026-01-02 09:00:00 +09:00",
            )
        expected_rows.append(row)
    assert rows == expected_rows

    payload = json.loads((run_dir / "issues.json").read_text(encoding="utf-8"))
    expected_metadata = {
        "started_at": FIXED_TIME,
        "completed_at": FIXED_TIME,
        "conditions": {
            "project_id": "42",
            "status_id": "*",
            "subproject_id": "!*",
            "sort": "id:asc",
        },
        "issue_count": count,
        "pages": 1,
        "snapshot_note": SNAPSHOT_NOTE,
    }
    if jst:
        expected_metadata["include_jst_columns"] = True
    assert payload == {
        "metadata": expected_metadata,
        "issues": _expected_basic_issues(items, jst),
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "field_profile" not in serialized
    assert "extended_field_availability" not in serialized
    assert "done_ratio" not in serialized
    assert "is_private" not in serialized


def _extended_items():
    first = issue(1)
    first.update(
        priority={"id": 3, "name": "架空優先度", "unknown": "discard"},
        author=None,
        start_date="",
        done_ratio=0,
        estimated_hours=0.0,
        is_private=False,
        description="discarded body",
        custom_fields=[{"id": 99, "value": "discarded value"}],
    )
    second = issue(2)
    second.update(priority=None, author={"id": 4, "name": "架空作成者"})
    return [first, second]


@pytest.mark.parametrize("jst", [False, True])
def test_extended_cli_integration_and_request_equivalence(tmp_path, monkeypatch, jst):
    config = _config(tmp_path)
    items = _extended_items()
    basic_session, _ = _run_cli(
        monkeypatch, config, tmp_path / "basic", [page(items, 2)], jst=jst
    )
    extended_session, run_dir = _run_cli(
        monkeypatch,
        config,
        tmp_path / "extended",
        [page(items, 2)],
        fields="extended",
        jst=jst,
    )
    assert basic_session.calls == extended_session.calls
    assert len(extended_session.calls) == 1
    method, url, request = extended_session.calls[0]
    assert method == "GET" and url.endswith("/issues.json")
    assert "fields" not in request["params"]
    assert "field_profile" not in request["params"]

    with (run_dir / "issues.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows[0]) == (28 if jst else 26)
    assert rows[0]["done_ratio"] == "0"
    assert rows[0]["estimated_hours"] == "0.0"
    assert rows[0]["is_private"] == "false"
    assert rows[0]["start_date"] == ""
    assert rows[1]["done_ratio"] == ""

    payload = json.loads((run_dir / "issues.json").read_text(encoding="utf-8"))
    first, second = payload["issues"]
    assert first["author"] is None and second["priority"] is None
    assert first["done_ratio"] == 0 and first["estimated_hours"] == 0.0
    assert first["is_private"] is False and first["start_date"] == ""
    assert "description" not in first and "custom_fields" not in first
    assert first["created_on"] == "2026-01-01T00:00:00Z"
    if jst:
        assert rows[0]["created_on_jst"] == "2026-01-01 09:00:00 +09:00"
        assert first["created_on_jst"] == "2026-01-01 09:00:00 +09:00"
    else:
        assert "created_on_jst" not in first
    availability = payload["metadata"]["extended_field_availability"]
    assert availability["priority"] == {
        "missing_count": 0,
        "null_count": 1,
        "value_count": 1,
    }
    assert availability["author"] == {
        "missing_count": 0,
        "null_count": 1,
        "value_count": 1,
    }
    assert availability["done_ratio"] == {
        "missing_count": 1,
        "null_count": 0,
        "value_count": 1,
    }


def test_cli_invalid_extended_value_on_later_page_preserves_existing_run(
    tmp_path, monkeypatch, capsys
):
    config = _config(tmp_path, page_size=1)
    output = tmp_path / "out"
    existing = output / "run-existing"
    existing.mkdir(parents=True)
    marker = existing / "verified.txt"
    marker.write_text("unchanged", encoding="utf-8")
    invalid = issue(999_999)
    invalid.update(
        done_ratio="SECRET-INVALID-VALUE",
        description="SECRET BODY",
    )
    session = FakeSession([page([issue(1)], 2, 0), page([invalid], 2, 1)])
    monkeypatch.setattr("requests.Session", lambda: session)
    monkeypatch.setenv("REDMINE_API_KEY", "SECRET-API-KEY")

    assert run(_argv(config, output, fields="extended")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    combined = captured.out + captured.err
    for secret in (
        "SECRET-API-KEY",
        "SECRET-INVALID-VALUE",
        "999999",
        "SECRET BODY",
        "Traceback",
    ):
        assert secret not in combined
    assert "OK: exported" not in combined
    assert list(output.glob("run-*")) == [existing]
    assert list(output.glob(".pending-*")) == []
    assert marker.read_text(encoding="utf-8") == "unchanged"
