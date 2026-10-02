import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import issue

from redmine_readonly.errors import AppError
from redmine_readonly.exporter import ExportResult, select_fields
from redmine_readonly.output import write_outputs


def test_csv_and_json_handle_content_types_and_formula(tmp_path: Path):
    raw = issue(1, ' =SUM(1,2)\n日本語 "quoted"', assigned=False)
    selected = select_fields(raw)
    result = ExportResult(
        [selected], {"issue_count": 1, "conditions": {"status_id": "*"}}
    )
    csv_path, json_path = write_outputs(result, tmp_path)

    assert csv_path.parent == json_path.parent
    assert csv_path.parent.parent == tmp_path
    assert csv_path.parent.name.startswith("run-")
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not json_path.read_bytes().startswith(b"\xef\xbb\xbf")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["subject"] == '\' =SUM(1,2)\n日本語 "quoted"'
    assert row["assigned_to_id"] == ""

    payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
    assert payload["issues"][0]["subject"] == raw["subject"]
    assert payload["issues"][0]["assigned_to"] == {"id": None, "name": None}
    assert isinstance(payload["issues"][0]["id"], int)


def _result(number: int) -> ExportResult:
    return ExportResult(
        [select_fields(issue(number))],
        {"issue_count": 1, "conditions": {"project_id": f"project-{number}"}},
    )


def test_failure_between_files_leaves_no_completed_run(tmp_path: Path, monkeypatch):
    existing = tmp_path / "run-existing"
    existing.mkdir()
    marker = existing / "marker.txt"
    marker.write_text("keep")

    def fail_json(*args, **kwargs):
        raise OSError("simulated failure containing no real data")

    monkeypatch.setattr("redmine_readonly.output.json.dump", fail_json)
    with pytest.raises(AppError, match="cannot publish export run"):
        write_outputs(_result(1), tmp_path)

    assert marker.read_text() == "keep"
    assert list(tmp_path.glob("run-*")) == [existing]
    assert list(tmp_path.glob(".pending-*")) == []


def test_concurrent_runs_do_not_mix_files(tmp_path: Path):
    with ThreadPoolExecutor(max_workers=8) as executor:
        outputs = list(
            executor.map(
                lambda number: write_outputs(_result(number), tmp_path), range(16)
            )
        )

    run_dirs = {csv_path.parent for csv_path, json_path in outputs}
    assert len(run_dirs) == 16
    assert len(list(tmp_path.glob("run-*"))) == 16
    assert list(tmp_path.glob(".pending-*")) == []
    for number, (csv_path, json_path) in enumerate(outputs):
        assert csv_path.parent == json_path.parent
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            csv_id = int(next(csv.DictReader(stream))["id"])
        json_id = json.loads(json_path.read_text(encoding="utf-8"))["issues"][0]["id"]
        assert csv_id == json_id == number


def test_existing_legacy_outputs_are_not_overwritten(tmp_path: Path):
    old_csv = tmp_path / "issues.csv"
    old_json = tmp_path / "issues.json"
    old_csv.write_text("old csv")
    old_json.write_text("old json")

    csv_path, json_path = write_outputs(_result(42), tmp_path)

    assert old_csv.read_text() == "old csv"
    assert old_json.read_text() == "old json"
    assert csv_path.parent == json_path.parent
    assert csv_path.parent != tmp_path


def test_jst_columns_are_added_to_csv_and_json_only_when_requested(tmp_path: Path):
    selected = select_fields(issue(1), include_jst_columns=True)
    result = ExportResult([selected], {"issue_count": 1, "include_jst_columns": True})

    csv_path, json_path = write_outputs(result, tmp_path)

    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["created_on"] == "2026-01-01T00:00:00Z"
    assert row["created_on_jst"] == "2026-01-01 09:00:00 +09:00"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["issues"][0]["updated_on"] == "2026-01-02T00:00:00Z"
    assert payload["issues"][0]["updated_on_jst"] == "2026-01-02 09:00:00 +09:00"


def test_empty_jst_export_still_has_optional_csv_columns(tmp_path: Path):
    result = ExportResult([], {"issue_count": 0, "include_jst_columns": True})
    csv_path, _ = write_outputs(result, tmp_path)
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        columns = next(csv.reader(stream))
    assert columns[-2:] == ["created_on_jst", "updated_on_jst"]
