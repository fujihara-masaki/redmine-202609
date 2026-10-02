from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import AppError
from .exporter import ExportResult
from .fields import EXTENDED_CSV_COLUMNS

CSV_COLUMNS = [
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
JST_CSV_COLUMNS = ["created_on_jst", "updated_on_jst"]
FORMULA_PREFIX = re.compile(r"^[\t\r\n ]*[=+\-@]")


def csv_safe(value: Any) -> Any:
    if isinstance(value, str) and FORMULA_PREFIX.match(value):
        return "'" + value
    return value


def _csv_row(
    issue: dict[str, Any], include_jst_columns: bool, extended: bool = False
) -> dict[str, Any]:
    row = {
        "id": issue["id"],
        "subject": issue["subject"],
        "project_id": issue["project"]["id"],
        "project_name": issue["project"]["name"],
        "tracker_id": issue["tracker"]["id"],
        "tracker_name": issue["tracker"]["name"],
        "status_id": issue["status"]["id"],
        "status_name": issue["status"]["name"],
        "assigned_to_id": issue["assigned_to"]["id"],
        "assigned_to_name": issue["assigned_to"]["name"],
        "created_on": issue["created_on"],
        "updated_on": issue["updated_on"],
    }
    if include_jst_columns:
        row.update(
            created_on_jst=issue.get("created_on_jst"),
            updated_on_jst=issue.get("updated_on_jst"),
        )
    if extended:
        for field in ("priority", "author", "category", "fixed_version"):
            reference = issue.get(field)
            row[f"{field}_id"] = (
                reference.get("id") if isinstance(reference, dict) else None
            )
            row[f"{field}_name"] = (
                reference.get("name") if isinstance(reference, dict) else None
            )
        parent = issue.get("parent")
        row["parent_id"] = parent.get("id") if isinstance(parent, dict) else None
        for field in ("start_date", "due_date", "done_ratio", "estimated_hours"):
            row[field] = issue.get(field)
        private = issue.get("is_private")
        row["is_private"] = (
            "true" if private is True else "false" if private is False else None
        )
    return {key: csv_safe(value) for key, value in row.items()}


def _run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run-{timestamp}-{uuid.uuid4().hex}"


def write_outputs(result: ExportResult, output_dir: Path) -> tuple[Path, Path]:
    staging_dir: Path | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix=".pending-", dir=output_dir))
        staged_csv = staging_dir / "issues.csv"
        staged_json = staging_dir / "issues.json"

        include_jst_columns = (
            any(
                "created_on_jst" in issue or "updated_on_jst" in issue
                for issue in result.issues
            )
            or result.metadata.get("include_jst_columns") is True
        )
        columns = CSV_COLUMNS + (JST_CSV_COLUMNS if include_jst_columns else [])
        extended = result.metadata.get("field_profile") == "extended"
        if extended:
            columns += list(EXTENDED_CSV_COLUMNS)
        with staged_csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(
                _csv_row(issue, include_jst_columns, extended)
                for issue in result.issues
            )
        with staged_json.open("w", encoding="utf-8") as stream:
            json.dump(
                {"metadata": result.metadata, "issues": result.issues},
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")

        completed_dir = output_dir / _run_name()
        os.rename(staging_dir, completed_dir)
        staging_dir = None
        return completed_dir / "issues.csv", completed_dir / "issues.json"
    except AppError:
        raise
    except (OSError, TypeError, ValueError, KeyError, csv.Error) as exc:
        raise AppError(f"cannot publish export run: {type(exc).__name__}") from None
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
