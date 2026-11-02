import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import requests
from conftest import FakeResponse, FakeSession, issue, page

from redmine_readonly import followup
from redmine_readonly.cli import run
from redmine_readonly.errors import AppError
from redmine_readonly.fields import EXTENDED_CSV_COLUMNS
from redmine_readonly.followup import evaluate, load_rules, select_inputs
from redmine_readonly.output import CSV_COLUMNS, JST_CSV_COLUMNS

EXAMPLE = Path(__file__).resolve().parents[1] / "followup-rules.example.toml"
AS_OF = date(2026, 10, 23)


@pytest.fixture
def rules():
    return load_rules(EXAMPLE)


def raw_issue(number=1, incident="軽障害", discovered="2026-07-25", status=1):
    row = issue(number)
    row["status"] = {"id": status, "name": "架空状態"}
    row["custom_fields"] = [
        {
            "id": 102,
            "name": "wrong name",
            "value": discovered,
            "secret": "DISCARD-CF-KEY",
        },
        {"id": 999, "value": {"secret": "DISCARD-UNSELECTED"}},
        {"id": 101, "name": "wrong name", "value": incident},
    ]
    row["description"] = "DISCARD-BODY"
    return row


def judge(rules, row=None, day=AS_OF):
    return evaluate(
        select_inputs(raw_issue() if row is None else row, rules), rules, day
    )


@pytest.mark.parametrize(
    "threshold,elapsed",
    [(90, 89), (90, 90), (90, 91), (180, 179), (180, 180), (180, 181), (90, 0)],
)
def test_exact_calendar_boundaries(rules, threshold, elapsed):
    discovered = AS_OF - timedelta(days=elapsed)
    result = judge(
        rules,
        raw_issue(
            incident="軽障害" if threshold == 90 else "重障害",
            discovered=discovered.isoformat(),
        ),
    )
    assert result == {
        "as_of": AS_OF.isoformat(),
        "threshold_days": threshold,
        "elapsed_days": elapsed,
        "threshold_date": (discovered + timedelta(days=threshold)).isoformat(),
        "target": elapsed >= threshold,
        "result": "target" if elapsed >= threshold else "not_target",
        "reason": "threshold_reached" if elapsed >= threshold else "below_threshold",
    }


@pytest.mark.parametrize(
    "discovered,as_of,elapsed,threshold_date",
    [
        ("2024-02-29", "2024-05-29", 90, "2024-05-29"),
        ("2025-12-31", "2026-03-31", 90, "2026-03-31"),
        ("2026-01-31", "2026-05-01", 90, "2026-05-01"),
    ],
)
def test_month_end_leap_day_and_year_boundary(
    rules, discovered, as_of, elapsed, threshold_date
):
    result = judge(rules, raw_issue(discovered=discovered), date.fromisoformat(as_of))
    assert result["elapsed_days"] == elapsed
    assert result["threshold_date"] == threshold_date
    assert result["target"] is True


@pytest.mark.parametrize("status", [None, False, True, 0, -1, "5", [], {}, 1.0])
def test_invalid_status_precedes_everything(rules, status):
    result = judge(rules, raw_issue(incident=None, discovered=None, status=status))
    assert result["target"] is None and result["reason"] == "invalid_status"


def test_missing_status_and_completed_priority(rules):
    row = raw_issue(status=5)
    del row["custom_fields"]
    assert judge(rules, row)["reason"] == "completed"
    assert judge(rules, row)["target"] is False
    assert judge(rules, row)["elapsed_days"] is None
    del row["status"]
    assert judge(rules, row)["reason"] == "invalid_status"
    assert judge(rules, raw_issue(status=999))["target"] is True


@pytest.mark.parametrize(
    "field,field_id", [("incident_type", 101), ("discovered_on", 102)]
)
@pytest.mark.parametrize(
    "case,state",
    [
        ("missing", "missing"),
        ("missing_value", "missing"),
        ("null", "null"),
        ("empty", "empty"),
        ("array", "multiple_values"),
        ("duplicate", "duplicate"),
        ("object", "unsupported"),
        ("boolean", "unsupported"),
        ("number", "unsupported"),
    ],
)
def test_input_states_do_not_save_arbitrary_values(rules, field, field_id, case, state):
    row = raw_issue()
    selected = next(cf for cf in row["custom_fields"] if cf["id"] == field_id)
    if case == "missing":
        row["custom_fields"].remove(selected)
    elif case == "missing_value":
        del selected["value"]
    elif case == "duplicate":
        row["custom_fields"].append({"id": field_id, "value": "DUPLICATE-DISCARD"})
    else:
        selected["value"] = {
            "null": None,
            "empty": "",
            "array": ["ARRAY-DISCARD"],
            "object": {"secret": "OBJECT-DISCARD"},
            "boolean": False,
            "number": 42,
        }[case]
    inputs = select_inputs(row, rules)
    assert inputs[field]["state"] == state
    assert evaluate(inputs, rules, AS_OF)["reason"] == f"{field}_{state}"
    serialized = json.dumps(inputs)
    for token in ("ARRAY-DISCARD", "OBJECT-DISCARD", "DUPLICATE-DISCARD", "DISCARD"):
        assert token not in serialized
    if case in ("null", "empty", "boolean", "number"):
        assert "value" in inputs[field]
    else:
        assert "value" not in inputs[field]


@pytest.mark.parametrize(
    "discovered",
    ["2026-02-30", "2026-2-01", "20260725", "2026-07-25T00:00:00Z", "not a date"],
)
def test_invalid_date_is_not_replaced(rules, discovered):
    assert (
        judge(rules, raw_issue(discovered=discovered))["reason"]
        == "discovered_on_invalid_date"
    )


def test_future_unknown_and_exact_match(rules):
    assert (
        judge(rules, raw_issue(discovered="2026-10-24"))["reason"]
        == "discovered_on_future"
    )
    for incident in ("その他", "軽障害 ", "軽"):
        result = judge(rules, raw_issue(incident=incident))
        assert result["target"] is None and result["reason"] == "unknown_incident_type"


@pytest.mark.parametrize(
    "days,discovered,as_of",
    [(90, "9999-12-30", date.max), (2**63 - 1, "0001-01-01", AS_OF)],
)
def test_date_overflow_is_per_row_but_completion_wins(rules, days, discovered, as_of):
    rules = replace(rules, threshold_days={"軽障害": days})
    row = raw_issue(discovered=discovered)
    result = judge(rules, row, as_of)
    assert result["reason"] == "date_out_of_range"
    assert result["target"] is None and result["threshold_date"] is None
    row["status"]["id"] = 5
    assert judge(rules, row, as_of)["reason"] == "completed"


@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-10-22T14:59:59+00:00", date(2026, 10, 22)),
        ("2026-10-22T15:00:00+00:00", date(2026, 10, 23)),
    ],
)
def test_jst_date_boundary(monkeypatch, instant, expected):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime.fromisoformat(instant).astimezone(tz)

    monkeypatch.setattr(followup, "datetime", Clock)
    assert followup.current_jst_date() == expected


@pytest.mark.parametrize(
    "old,new",
    [
        ("schema_version = 1", "schema_version = true"),
        ("schema_version = 1", "schema_version = 2"),
        ("schema_version = 1", "unknown_secret_key = 'SECRET'\nschema_version = 1"),
        ("schema_version = 1", ""),
        ("[fields]", "[fields]\nunknown = 'SECRET'"),
        ("incident_type_custom_field_id = 101", "incident_type_custom_field_id = true"),
        ("incident_type_custom_field_id = 101", "incident_type_custom_field_id = 102"),
        ("incident_type_custom_field_id = 101", "incident_type_custom_field_id = -1"),
        ("discovered_on_custom_field_id = 102", ""),
        ("discovered_on_custom_field_id = 102", "discovered_on_custom_field_id = 1.5"),
        ("[statuses]", "[statuses]\nsecret = 'SECRET'"),
        ("completed_ids = [5]", "completed_ids = []"),
        ("completed_ids = [5]", "completed_ids = [true]"),
        ("completed_ids = [5]", "completed_ids = [0]"),
        ("completed_ids = [5]", "completed_ids = 5"),
        ('"非影響" = 90', '"非影響" = true'),
        ('"非影響" = 90', '"非影響" = 0'),
        ('"非影響" = 90', '"非影響" = -1'),
        ('"非影響" = 90', '"非影響" = 1.5'),
        ('"非影響" = 90', '"" = 90'),
        ('"非影響" = 90', '" " = 90'),
        ('"非影響" = 90', '"非影響" = "SECRET"'),
    ],
)
def test_strict_rule_validation(tmp_path, old, new):
    path = tmp_path / "rules.toml"
    path.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )
    with pytest.raises(AppError) as exc:
        load_rules(path)
    assert "SECRET" not in str(exc.value) and "unknown_secret_key" not in str(exc.value)


def test_empty_thresholds_invalid_toml_encoding_and_single_read(tmp_path, monkeypatch):
    raw = EXAMPLE.read_bytes()
    path = tmp_path / "rules.toml"
    for content in (
        raw.split(b"[threshold_days]")[0] + b"[threshold_days]\n",
        b"x =",
        b"\xff",
    ):
        path.write_bytes(content)
        with pytest.raises(AppError):
            load_rules(path)
    path.write_bytes(raw)
    original = Path.read_bytes
    calls = []

    def read_once(self):
        calls.append(self)
        content = original(self)
        self.write_bytes(b"invalid after read")
        return content

    monkeypatch.setattr(Path, "read_bytes", read_once)
    rules = load_rules(path)
    assert calls == [path]
    assert rules.sha256 == hashlib.sha256(raw).hexdigest()
    assert rules.threshold_days["軽障害"] == 90


def cli_setup(tmp_path, monkeypatch, responses):
    config = tmp_path / "config.toml"
    config.write_text(
        'base_url="https://redmine.example.invalid/redmine"\npage_size=2\n',
        encoding="utf-8",
    )
    output = tmp_path / "out"
    argv = [
        "--config",
        str(config),
        "export",
        "--project",
        "42",
        "--output-dir",
        str(output),
    ]
    session = FakeSession(responses)
    monkeypatch.setattr("requests.Session", lambda: session)
    monkeypatch.setenv("REDMINE_API_KEY", "TEST-ONLY-KEY")
    return argv, output, session


@pytest.mark.parametrize("encoding", ["ascii", "cp1252"])
def test_followup_summary_on_ascii_only_stdout(tmp_path, monkeypatch, encoding):
    items = [
        raw_issue(1, incident="minor"),
        raw_issue(2, incident="minor", status=5),
        raw_issue(3, incident="unknown"),
    ]
    argv, output, _ = cli_setup(tmp_path, monkeypatch, [page(items, 3)])
    rules_path = tmp_path / "rules.toml"
    rules_path.write_text(
        "schema_version = 1\n[fields]\n"
        "incident_type_custom_field_id = 101\n"
        "discovered_on_custom_field_id = 102\n"
        "[statuses]\ncompleted_ids = [5]\n"
        "[threshold_days]\nminor = 90\n",
        encoding="ascii",
    )
    argv += ["--followup-config", str(rules_path), "--as-of", "2026-10-23"]
    assert all(argument.isascii() for argument in argv)
    with (
        io.BytesIO() as buffer,
        io.TextIOWrapper(
            buffer, encoding=encoding, errors="strict", newline="\n"
        ) as stream,
    ):
        with monkeypatch.context() as context:
            context.setattr("sys.stdout", stream)
            code = run(argv)
        stream.flush()
        text = buffer.getvalue().decode(encoding)
    assert code == 0
    assert "Follow-up: target=1, not_target=1, indeterminate=1\n" in text
    run_dir = next(output.glob("run-*"))
    assert f"CSV: {run_dir / 'issues.csv'}\n" in text
    assert f"JSON: {run_dir / 'issues.json'}\n" in text
    assert (run_dir / "issues.csv").is_file()
    payload = json.loads((run_dir / "issues.json").read_text(encoding="utf-8"))
    assert len(payload["issues"]) == 3


@pytest.mark.parametrize("escape", [r"\ud800", r"\udfff"])
def test_surrogate_input_hash_failure_is_safe_and_preserves_runs(
    tmp_path, monkeypatch, capsys, escape
):
    # Decode the same escaped scalar that a JSON HTTP response can contain.
    selected_value = json.loads('"PRIVATE_SELECTED' + escape + '"')
    argv, output, _ = cli_setup(
        tmp_path, monkeypatch, [page([raw_issue(incident=selected_value)], 1)]
    )
    existing = output / "run-existing"
    existing.mkdir(parents=True)
    marker = existing / "marker"
    marker.write_text("keep", encoding="ascii")
    assert run(argv + ["--followup-config", str(EXAMPLE)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR: cannot encode followup inputs as UTF-8\n"
    assert list(output.iterdir()) == [existing]
    assert marker.read_text(encoding="ascii") == "keep"


@pytest.mark.parametrize(
    "options",
    [
        ["--as-of", "2026-10-23"],
        ["--followup-config", "MISSING"],
        ["--followup-config", str(EXAMPLE), "--as-of", "2026-02-30"],
        ["--followup-config", str(EXAMPLE), "--as-of", "20261023"],
        ["--followup-config", str(EXAMPLE), "--status", "open"],
        ["--followup-config", str(EXAMPLE), "--status", "5"],
    ],
)
def test_cli_misuse_stops_before_auth_and_http(tmp_path, monkeypatch, options):
    argv, output, session = cli_setup(tmp_path, monkeypatch, [])
    monkeypatch.setattr(
        "redmine_readonly.cli._api_key", lambda: pytest.fail("must not request a key")
    )
    assert run(argv + options) == 2
    assert session.calls == [] and not output.exists()


def test_invalid_rule_contents_before_auth(tmp_path, monkeypatch):
    argv, output, session = cli_setup(tmp_path, monkeypatch, [])
    rules_path = tmp_path / "bad.toml"
    rules_path.write_text("schema_version=true")
    monkeypatch.setattr(
        "redmine_readonly.cli._api_key", lambda: pytest.fail("must not request a key")
    )
    assert run(argv + ["--followup-config", str(rules_path)]) == 2
    assert session.calls == [] and not output.exists()


@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("jst", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_full_export_all_rows_columns_hashes_counts_and_get_only(
    tmp_path, monkeypatch, capsys, extended, jst, empty
):
    items = [
        raw_issue(1),
        raw_issue(2, status=5, discovered=None),
        raw_issue(3, incident="その他"),
        raw_issue(4, discovered="2026-10-23"),
    ]
    if empty:
        items = []
    responses = [page(items[:2], len(items))]
    if items:
        responses.append(page(items[2:], len(items), 2))
    argv, output, session = cli_setup(tmp_path, monkeypatch, responses)
    options = ["--followup-config", str(EXAMPLE), "--as-of", AS_OF.isoformat()]
    if extended:
        options += ["--fields", "extended"]
    if jst:
        options += ["--include-jst-columns"]
    assert run(argv + options) == 0
    run_dir = next(output.glob("run-*"))
    payload = json.loads((run_dir / "issues.json").read_text(encoding="utf-8"))
    with (run_dir / "issues.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == CSV_COLUMNS + (JST_CSV_COLUMNS if jst else []) + (
            list(EXTENDED_CSV_COLUMNS) if extended else []
        ) + list(followup.CSV_COLUMNS)
    assert (run_dir / "issues.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    meta = payload["metadata"]["followup"]
    assert meta["counts"] == (
        {"target": 0, "not_target": 0, "indeterminate": 0}
        if empty
        else {"target": 1, "not_target": 2, "indeterminate": 1}
    )
    assert (
        sum(meta["counts"].values())
        == payload["metadata"]["issue_count"]
        == len(rows)
        == len(payload["issues"])
    )
    assert meta["rules_sha256"] == hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
    snapshot = [
        {"issue_id": row["id"], "inputs": row["followup_inputs"]}
        for row in payload["issues"]
    ]
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert meta["input_sha256"] == hashlib.sha256(canonical).hexdigest()
    if items:
        assert [row["followup_target"] for row in rows] == ["〇", "", "", ""]
        assert [row["followup_result"] for row in rows] == [
            "対象",
            "対象外",
            "判定不能",
            "対象外",
        ]
        assert rows[3]["followup_elapsed_days"] == "0"
    for csv_row, json_row in zip(rows, payload["issues"], strict=True):
        assert (
            csv_row["followup_reason"]
            == followup.REASONS[json_row["followup"]["reason"]]
        )
        assert csv_row["followup_as_of"] == json_row["followup"]["as_of"]
    serialized = json.dumps(payload)
    assert (
        "DISCARD" not in serialized
        and "custom_fields" not in serialized
        and "description" not in serialized
    )
    for method, url, request in session.calls:
        assert (
            method == "GET"
            and url == "https://redmine.example.invalid/redmine/issues.json"
        )
        assert request["params"] == {
            "project_id": "42",
            "status_id": "*",
            "subproject_id": "!*",
            "sort": "id:asc",
            "limit": 2,
            "offset": request["params"]["offset"],
        }
    assert [call[2]["params"]["offset"] for call in session.calls] == (
        [0] if empty else [0, 2]
    )
    assert f"indeterminate={0 if empty else 1}" in capsys.readouterr().out


def test_default_as_of_is_captured_once_and_reproducible(tmp_path, monkeypatch):
    days = iter([AS_OF, AS_OF + timedelta(days=1)])
    calls = []

    def clock():
        calls.append(True)
        return next(days)

    monkeypatch.setattr(followup, "current_jst_date", clock)
    items = [raw_issue(1), raw_issue(2)]
    argv, output, _ = cli_setup(
        tmp_path, monkeypatch, [page(items[:1], 2), page(items[1:], 2, 1)]
    )
    assert run(argv + ["--followup-config", str(EXAMPLE)]) == 0
    first = json.loads(
        next(output.glob("run-*/issues.json")).read_text(encoding="utf-8")
    )
    assert calls == [True]
    assert {row["followup"]["as_of"] for row in first["issues"]} == {AS_OF.isoformat()}
    argv, output2, _ = cli_setup(tmp_path, monkeypatch, [page(items, 2)])
    argv[argv.index(str(output2))] = str(tmp_path / "second")
    assert (
        run(argv + ["--followup-config", str(EXAMPLE), "--as-of", AS_OF.isoformat()])
        == 0
    )
    second = json.loads(
        next((tmp_path / "second").glob("run-*/issues.json")).read_text(
            encoding="utf-8"
        )
    )
    assert first["issues"] == second["issues"]
    assert first["metadata"]["followup"] == second["metadata"]["followup"]


@pytest.mark.parametrize(
    "value", [' =SUM(1,2)\n架空 "区分"', "@formula", "-1", "+formula"]
)
def test_followup_csv_uses_string_protection(tmp_path, monkeypatch, value):
    argv, output, _ = cli_setup(
        tmp_path, monkeypatch, [page([raw_issue(incident=value)], 1)]
    )
    assert (
        run(argv + ["--followup-config", str(EXAMPLE), "--as-of", AS_OF.isoformat()])
        == 0
    )
    with next(output.glob("run-*/issues.csv")).open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        assert next(csv.DictReader(stream))["incident_type"] == "'" + value
    payload = json.loads(
        next(output.glob("run-*/issues.json")).read_text(encoding="utf-8")
    )
    assert payload["issues"][0]["followup_inputs"]["incident_type"]["value"] == value


@pytest.mark.parametrize(
    "failure",
    ["length", "structure", "timeout", "json", "paging", "csv_write", "json_write"],
)
def test_whole_export_failures_never_publish(tmp_path, monkeypatch, capsys, failure):
    bad = raw_issue(2)
    if failure == "length":
        bad["custom_fields"][0]["value"] = "SECRET" * 1000
    elif failure == "structure":
        bad["custom_fields"] = {"secret": "SECRET"}
    response = page([bad], 2, 1)
    if failure == "timeout":
        response = requests.Timeout("SECRET")
    elif failure == "json":
        response = FakeResponse(json_error=ValueError("SECRET"))
    elif failure == "paging":
        response = page([bad], 3, 1)
    argv, output, _ = cli_setup(
        tmp_path, monkeypatch, [page([raw_issue()], 2), response]
    )
    existing = output / "run-existing"
    existing.mkdir(parents=True)
    (existing / "marker").write_text("keep")
    if failure.endswith("write"):
        original = Path.open

        def open_file(self, *args, **kwargs):
            if (
                self.name == ("issues.csv" if failure == "csv_write" else "issues.json")
                and args
                and args[0] == "w"
            ):
                raise OSError("SECRET")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_file)
    assert run(argv + ["--followup-config", str(EXAMPLE)]) == 2
    assert list(output.iterdir()) == [existing]
    assert (existing / "marker").read_text() == "keep"
    captured = capsys.readouterr()
    assert (
        captured.out == ""
        and "SECRET" not in captured.err
        and "Traceback" not in captured.err
    )


def test_rule_file_ignore_policy():
    import subprocess

    root = EXAMPLE.parent
    for name in ("followup-rules.toml", "followup.local.toml"):
        assert (
            subprocess.run(["git", "check-ignore", "-q", name], cwd=root).returncode
            == 0
        )
    assert (
        subprocess.run(["git", "check-ignore", "-q", EXAMPLE.name], cwd=root).returncode
        == 1
    )


@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("jst", [False, True])
def test_opt_in_keeps_requests_and_other_filters_unchanged(
    tmp_path, monkeypatch, extended, jst
):
    item = raw_issue()
    argv, output, regular = cli_setup(tmp_path, monkeypatch, [page([item], 1)])
    options = ["--include-subprojects", "--tracker", "2"]
    if extended:
        options += ["--fields", "extended"]
    if jst:
        options += ["--include-jst-columns"]
    assert run(argv + options) == 0
    regular_payload = json.loads(
        next(output.glob("run-*/issues.json")).read_text(encoding="utf-8")
    )
    assert "followup" not in regular_payload["metadata"]
    assert "followup_inputs" not in regular_payload["issues"][0]
    followup_session = FakeSession([page([item], 1)])
    monkeypatch.setattr("requests.Session", lambda: followup_session)
    assert run(argv + options + ["--followup-config", str(EXAMPLE)]) == 0
    assert regular.calls == followup_session.calls
    assert regular.calls[0][2]["params"]["subproject_id"] == "*"
    assert regular.calls[0][2]["params"]["tracker_id"] == 2


def test_no_followup_ignores_invalid_custom_fields_and_retains_status_filter(
    tmp_path, monkeypatch
):
    item = raw_issue()
    item["custom_fields"] = {"malformed": "must be ignored without opt-in"}
    argv, output, session = cli_setup(tmp_path, monkeypatch, [page([item], 1)])
    assert run(argv + ["--status", "open"]) == 0
    assert session.calls[0][2]["params"]["status_id"] == "open"
    payload = json.loads(
        next(output.glob("run-*/issues.json")).read_text(encoding="utf-8")
    )
    assert (
        "followup" not in payload["metadata"]
        and "custom_fields" not in payload["issues"][0]
    )


@pytest.mark.parametrize(
    "malformation", ["array_length", "fields_length", "entry", "nonfinite"]
)
def test_safety_failures_are_not_business_indeterminates(rules, malformation):
    row = raw_issue(status=5)
    if malformation == "array_length":
        row["custom_fields"][0]["value"] = [None] * (followup.MAX_CUSTOM_FIELDS + 1)
    elif malformation == "fields_length":
        row["custom_fields"] = [{"id": 999}] * (followup.MAX_CUSTOM_FIELDS + 1)
    elif malformation == "entry":
        row["custom_fields"] = [False]
    else:
        row["custom_fields"][0]["value"] = float("inf")
    with pytest.raises(AppError):
        select_inputs(row, rules)


def test_missing_null_and_empty_are_distinguishable_in_saved_json(
    tmp_path, monkeypatch
):
    items = [raw_issue(1), raw_issue(2, discovered=None), raw_issue(3, discovered="")]
    items[0]["custom_fields"] = [
        cf for cf in items[0]["custom_fields"] if cf["id"] != 102
    ]
    argv, output, _ = cli_setup(
        tmp_path, monkeypatch, [page(items[:2], 3), page(items[2:], 3, 2)]
    )
    assert run(argv + ["--followup-config", str(EXAMPLE)]) == 0
    payload = json.loads(
        next(output.glob("run-*/issues.json")).read_text(encoding="utf-8")
    )
    inputs = [row["followup_inputs"]["discovered_on"] for row in payload["issues"]]
    assert inputs == [
        {"custom_field_id": 102, "state": "missing"},
        {"custom_field_id": 102, "state": "null", "value": None},
        {"custom_field_id": 102, "state": "empty", "value": ""},
    ]
