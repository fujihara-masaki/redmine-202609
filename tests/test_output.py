import csv
import json
from pathlib import Path

from redmine_readonly.exporter import ExportResult, select_fields
from redmine_readonly.output import write_outputs

from conftest import issue


def test_csv_and_json_handle_content_types_and_formula(tmp_path: Path):
    raw = issue(1, ' =SUM(1,2)\n日本語 "quoted"', assigned=False)
    selected = select_fields(raw)
    result = ExportResult(
        [selected], {"issue_count": 1, "conditions": {"status_id": "*"}}
    )
    csv_path, json_path = write_outputs(result, tmp_path)

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
