from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

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


def _atomic_write(
    path: Path,
    writer: Any,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding=encoding, newline=newline, dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            writer(stream)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary:
            temporary.unlink(missing_ok=True)
        raise AppError(f"cannot write export file: {type(exc).__name__}") from None


def write_outputs(result: ExportResult, output_dir: Path) -> tuple[Path, Path]:
    csv_path, json_path = output_dir / "issues.csv", output_dir / "issues.json"

    def write_csv(stream: Any) -> None:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(_csv_row(issue) for issue in result.issues)

    def write_json(stream: Any) -> None:
        json.dump(
            {"metadata": result.metadata, "issues": result.issues},
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")

    _atomic_write(csv_path, write_csv, encoding="utf-8-sig", newline="")
    _atomic_write(json_path, write_json)
    return csv_path, json_path
