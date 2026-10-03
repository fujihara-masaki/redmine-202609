from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from .client import RedmineClient
from .errors import AppError
from .fields import EXTENDED_FIELDS, EXTENDED_NAME_MAX_LENGTH, FIELD_PROFILES


@dataclass(frozen=True)
class ExportResult:
    issues: list[dict[str, Any]]
    metadata: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fetch_issues(
    client: RedmineClient,
    project_id: str,
    tracker_id: int | None = None,
    include_subprojects: bool = False,
    status_id: str = "*",
    include_jst_columns: bool = False,
    field_profile: str = "basic",
) -> ExportResult:
    if field_profile not in FIELD_PROFILES:
        raise AppError("field profile must be 'basic' or 'extended'")
    if not project_id.strip():
        raise AppError("project must not be empty")
    if tracker_id is not None and tracker_id <= 0:
        raise AppError("tracker ID must be greater than zero")
    if not status_id.strip():
        raise AppError("status must not be empty")
    started_at = _utc_now()
    conditions: dict[str, Any] = {
        "project_id": project_id,
        "status_id": status_id,
        # Keep this explicit: omitting it can defer behavior to Redmine's
        # display_subprojects_issues setting in the target environment.
        "subproject_id": "*" if include_subprojects else "!*",
        "sort": "id:asc",
    }
    if tracker_id is not None:
        conditions["tracker_id"] = tracker_id

    selected_issues: list[dict[str, Any]] = []
    availability = {
        field: {"missing_count": 0, "null_count": 0, "value_count": 0}
        for field in EXTENDED_FIELDS
    }
    seen: set[int] = set()
    offset = 0
    expected_total: int | None = None
    pages = 0
    while True:
        if pages >= client.config.max_pages:
            raise AppError("maximum page count reached before export completed")
        params = {**conditions, "limit": client.config.page_size, "offset": offset}
        payload = client.issue_page(params)
        pages += 1
        page = payload.get("issues")
        total = payload.get("total_count")
        returned_offset = payload.get("offset")
        if (
            not isinstance(page, list)
            or not isinstance(total, int)
            or not isinstance(returned_offset, int)
        ):
            raise AppError("issue response has an unexpected pagination structure")
        if returned_offset != offset:
            raise AppError("server returned a non-progressing or unexpected offset")
        if expected_total is None:
            expected_total = total
            if total > client.config.max_issues:
                raise AppError("issue count exceeds configured maximum")
        elif total != expected_total:
            raise AppError(
                "issue count changed during retrieval; export was not written"
            )
        page_length = len(page)
        if not page and len(selected_issues) < total:
            raise AppError("server returned an empty page before retrieval completed")
        for issue in page:
            issue_id = issue.get("id") if isinstance(issue, dict) else None
            if not isinstance(issue_id, int):
                raise AppError("issue response contains an invalid issue ID")
            if issue_id in seen:
                raise AppError("duplicate issue ID detected; export was not written")
            seen.add(issue_id)
            selected = select_fields(
                issue, include_jst_columns, field_profile=field_profile
            )
            selected_issues.append(selected)
            if field_profile == "extended":
                for field in EXTENDED_FIELDS:
                    bucket = (
                        "missing_count"
                        if field not in issue
                        else ("null_count" if issue[field] is None else "value_count")
                    )
                    availability[field][bucket] += 1
            if len(selected_issues) > client.config.max_issues:
                raise AppError("maximum issue count reached before export completed")
        if page:
            del issue
        del page, payload
        if len(selected_issues) > total:
            raise AppError("server returned more issues than total_count")
        if len(selected_issues) == total:
            break
        if page_length == 0:
            raise AppError("pagination did not progress")
        next_offset = offset + page_length
        if next_offset <= offset:
            raise AppError("pagination did not progress")
        offset = next_offset

    metadata: dict[str, Any] = {
        "started_at": started_at,
        "completed_at": _utc_now(),
        "conditions": conditions,
        "issue_count": len(selected_issues),
        "pages": pages,
        "snapshot_note": "Count consistency was checked, but concurrent updates may prevent a transactional snapshot.",
    }
    if include_jst_columns:
        metadata["include_jst_columns"] = True
    if field_profile == "extended":
        metadata.update(
            field_profile="extended",
            export_schema="extended-v1",
            selected_extended_fields=list(EXTENDED_FIELDS),
            extended_field_availability=availability,
        )
    return ExportResult(selected_issues, metadata)


def _reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"id": None, "name": None}
    return {"id": value.get("id"), "name": value.get("name")}


JST = timezone(timedelta(hours=9))


def to_jst(value: Any) -> str | None:
    """Convert an aware ISO 8601 API timestamp to a stable JST display value."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise AppError("issue timestamp has an unexpected type")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AppError("issue timestamp is not valid ISO 8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AppError("issue timestamp must include a UTC offset")
    return parsed.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S +09:00")


def select_fields(
    issue: dict[str, Any],
    include_jst_columns: bool = False,
    *,
    field_profile: str = "basic",
) -> dict[str, Any]:
    if field_profile not in FIELD_PROFILES:
        raise AppError("field profile must be 'basic' or 'extended'")
    selected = {
        "id": issue.get("id"),
        "subject": issue.get("subject"),
        "project": _reference(issue.get("project")),
        "tracker": _reference(issue.get("tracker")),
        "status": _reference(issue.get("status")),
        "assigned_to": _reference(issue.get("assigned_to")),
        "created_on": issue.get("created_on"),
        "updated_on": issue.get("updated_on"),
    }
    if include_jst_columns:
        selected["created_on_jst"] = to_jst(selected["created_on"])
        selected["updated_on_jst"] = to_jst(selected["updated_on"])
    if field_profile == "extended":
        for field in EXTENDED_FIELDS:
            if field in issue:
                selected[field] = _extended_value(field, issue[field])
    return selected


def _invalid(field: str, reason: str) -> AppError:
    return AppError(f"extended field '{field}' {reason}")


def _positive_id(field: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(field, "has an invalid type")
    if value <= 0:
        raise _invalid(field, "has an invalid value")
    return value


def _extended_reference(
    field: str, value: Any, *, parent: bool = False
) -> dict[str, Any]:
    if not isinstance(value, dict) or "id" not in value:
        raise _invalid(field, "has an invalid structure")
    selected: dict[str, Any] = {"id": _positive_id(field, value["id"])}
    if not parent and "name" in value:
        name = value["name"]
        if name is not None and not isinstance(name, str):
            raise _invalid(field, "has an invalid name type")
        if isinstance(name, str) and len(name) > EXTENDED_NAME_MAX_LENGTH:
            raise _invalid(field, "name exceeds the maximum length")
        selected["name"] = name
    return selected


def _extended_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in {"priority", "author", "category", "fixed_version"}:
        return _extended_reference(field, value)
    if field == "parent":
        return _extended_reference(field, value, parent=True)
    if field in {"start_date", "due_date"}:
        if not isinstance(value, str):
            raise _invalid(field, "has an invalid type")
        if value:
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise _invalid(field, "has an invalid date") from None
            if parsed.isoformat() != value:
                raise _invalid(field, "has an invalid date")
        return value
    if field == "done_ratio":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(field, "has an invalid type")
        if not 0 <= value <= 100:
            raise _invalid(field, "is outside the allowed range")
        return value
    if field == "estimated_hours":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _invalid(field, "has an invalid type")
        if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
            raise _invalid(field, "has an invalid value")
        return value
    if field == "is_private":
        if not isinstance(value, bool):
            raise _invalid(field, "has an invalid type")
        return value
    raise _invalid(field, "is not allowed")
