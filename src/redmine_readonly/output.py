from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import uuid
from datetime import datetime, timezone

from .errors import AppError
from .exporter import ExportResult

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
FORMULA_PREFIX = re.compile(r"^[\t\r\n ]*[=+\-@]")


def csv_safe(value: Any) -> Any:
    if isinstance(value, str) and FORMULA_PREFIX.match(value):
        return "'" + value
    return value


def _csv_row(issue: dict[str, Any]) -> dict[str, Any]:
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
    return {key: csv_safe(value) for key, value in row.items()}


def _run_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run-{timestamp}-{uuid.uuid4().hex}"


def write_outputs(result: ExportResult, output_dir: Path) -> tuple[Path, Path]:
    staging_dir: Path | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix=".pending-", dir=output_dir))
        staged_csv = staging_dir / "issues.csv"
        staged_json = staging_dir / "issues.json"

        with staged_csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(_csv_row(issue) for issue in result.issues)
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
    except Exception as exc:
        raise AppError(f"cannot publish export run: {type(exc).__name__}") from None
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
