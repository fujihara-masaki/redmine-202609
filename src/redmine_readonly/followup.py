"""Opt-in, local follow-up selection and calendar-day evaluation. No network IO."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .errors import AppError

JST = timezone(timedelta(hours=9))
MAX_VALUE_LENGTH = 4096
MAX_CUSTOM_FIELDS = 10_000
CSV_COLUMNS = (
    "incident_type",
    "discovered_on",
    "followup_as_of",
    "followup_threshold_days",
    "followup_elapsed_days",
    "followup_threshold_date",
    "followup_target",
    "followup_result",
    "followup_reason",
)
RESULT_LABELS = {"target": "対象", "not_target": "対象外", "indeterminate": "判定不能"}
REASONS = {
    "invalid_status": "ステータスIDが欠損または不正です",
    "completed": "現在のステータスが完了です",
    "unknown_incident_type": "障害区分の日数ルールが未設定です",
    "discovered_on_invalid_date": "発見日が有効なYYYY-MM-DDではありません",
    "discovered_on_future": "発見日が基準日より未来です",
    "date_out_of_range": "必要な日付演算が範囲外です",
    "threshold_reached": "設定日数以上が経過し、現在未完了です",
    "below_threshold": "現在未完了ですが設定日数に達していません",
}
for _field, _label in (("incident_type", "障害区分"), ("discovered_on", "発見日")):
    for _state, _description in {
        "missing": "項目または値がありません",
        "null": "nullです",
        "empty": "空文字です",
        "unsupported": "未対応の値型です",
        "multiple_values": "複数値です",
        "duplicate": "選択IDが重複しています",
    }.items():
        REASONS[f"{_field}_{_state}"] = f"{_label}：{_description}"


@dataclass(frozen=True)
class FollowupRules:
    incident_type_custom_field_id: int
    discovered_on_custom_field_id: int
    completed_ids: frozenset[int]
    threshold_days: Mapping[str, int]
    sha256: str


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _keys(value: Any, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise AppError("followup configuration has missing or unknown keys")


def load_rules(path: Path) -> FollowupRules:
    # Read exactly once: validation and provenance refer to the same bytes.
    try:
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise AppError(
            f"cannot read followup configuration: {type(exc).__name__}"
        ) from None
    _keys(data, {"schema_version", "fields", "statuses", "threshold_days"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise AppError("followup schema_version must be integer 1")
    fields = data["fields"]
    _keys(fields, {"incident_type_custom_field_id", "discovered_on_custom_field_id"})
    first, second = (
        fields["incident_type_custom_field_id"],
        fields["discovered_on_custom_field_id"],
    )
    if not _positive_int(first) or not _positive_int(second) or first == second:
        raise AppError("followup field IDs must be distinct positive integers")
    _keys(data["statuses"], {"completed_ids"})
    completed = data["statuses"]["completed_ids"]
    if (
        not isinstance(completed, list)
        or not completed
        or not all(map(_positive_int, completed))
    ):
        raise AppError(
            "followup completed_ids must be a non-empty positive integer array"
        )
    thresholds = data["threshold_days"]
    if (
        not isinstance(thresholds, dict)
        or not thresholds
        or any(
            not isinstance(key, str) or not key.strip() or not _positive_int(value)
            for key, value in thresholds.items()
        )
    ):
        raise AppError(
            "followup thresholds require non-empty names and positive integer days"
        )
    return FollowupRules(
        first,
        second,
        frozenset(completed),
        MappingProxyType(thresholds),
        hashlib.sha256(raw).hexdigest(),
    )


def parse_as_of(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise AppError("as-of must be an existing YYYY-MM-DD date")


def current_jst_date() -> date:
    return datetime.now(JST).date()


def prepare_followup(
    config: Path | None, as_of: str | None, status: str = "*"
) -> tuple[FollowupRules | None, date | None]:
    if config is None:
        if as_of is not None:
            raise AppError("as-of requires followup-config")
        return None, None
    if status != "*":
        raise AppError("followup requires status '*'")
    day = parse_as_of(as_of) if as_of is not None else current_jst_date()
    return load_rules(config), day


def _input_value(entry: dict[str, Any]) -> dict[str, Any]:
    if "value" not in entry:
        return {"state": "missing"}
    value = entry["value"]
    if value is None:
        return {"state": "null", "value": None}
    if isinstance(value, str):
        if len(value) > MAX_VALUE_LENGTH:
            raise AppError("selected followup value exceeds maximum length")
        return {"state": "empty" if value == "" else "value", "value": value}
    if isinstance(value, list):
        if len(value) > MAX_CUSTOM_FIELDS:
            raise AppError("selected followup array exceeds maximum length")
        return {"state": "multiple_values"}
    if type(value) in (int, float, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise AppError("selected followup scalar is not finite")
        return {"state": "unsupported", "value": value}
    return {"state": "unsupported"}


def select_inputs(issue: dict[str, Any], rules: FollowupRules) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    status = issue.get("status")
    status_id = status.get("id") if isinstance(status, dict) else None
    selected["status_id"] = (
        {"state": "value", "value": status_id}
        if _positive_int(status_id)
        else {"state": "invalid"}
    )
    fields = issue.get("custom_fields", [])
    if not isinstance(fields, list) or len(fields) > MAX_CUSTOM_FIELDS:
        raise AppError("custom_fields has an invalid structure or length")
    by_id = {
        rules.incident_type_custom_field_id: [],
        rules.discovered_on_custom_field_id: [],
    }
    for entry in fields:
        if not isinstance(entry, dict) or not _positive_int(entry.get("id")):
            raise AppError("custom_fields entry has an invalid structure")
        if entry["id"] in by_id:
            # Validate each selected scalar even if the ID later proves duplicate.
            by_id[entry["id"]].append(_input_value(entry))
    for name, field_id in (
        ("incident_type", rules.incident_type_custom_field_id),
        ("discovered_on", rules.discovered_on_custom_field_id),
    ):
        values = by_id[field_id]
        state = (
            {"state": "missing"}
            if not values
            else values[0]
            if len(values) == 1
            else {"state": "duplicate"}
        )
        selected[name] = {"custom_field_id": field_id, **state}
    return selected


def evaluate(
    inputs: dict[str, Any], rules: FollowupRules, as_of: date
) -> dict[str, Any]:
    """Pure, deterministic evaluation of selected inputs and validated rules."""
    result: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "threshold_days": None,
        "elapsed_days": None,
        "threshold_date": None,
    }

    def finish(target: bool | None, reason: str) -> dict[str, Any]:
        return {
            **result,
            "target": target,
            "result": "indeterminate"
            if target is None
            else "target"
            if target
            else "not_target",
            "reason": reason,
        }

    status = inputs["status_id"]
    if status["state"] != "value":
        return finish(None, "invalid_status")
    if status["value"] in rules.completed_ids:
        return finish(False, "completed")
    incident = inputs["incident_type"]
    if incident["state"] != "value":
        return finish(None, "incident_type_" + incident["state"])
    threshold = rules.threshold_days.get(incident["value"])
    if threshold is None:
        return finish(None, "unknown_incident_type")
    result["threshold_days"] = threshold
    discovered = inputs["discovered_on"]
    if discovered["state"] != "value":
        return finish(None, "discovered_on_" + discovered["state"])
    try:
        day = parse_as_of(discovered["value"])
    except AppError:
        return finish(None, "discovered_on_invalid_date")
    result["elapsed_days"] = (as_of - day).days
    if day > as_of:
        return finish(None, "discovered_on_future")
    try:
        result["threshold_date"] = (day + timedelta(days=threshold)).isoformat()
    except OverflowError:
        return finish(None, "date_out_of_range")
    target = result["elapsed_days"] >= threshold
    return finish(target, "threshold_reached" if target else "below_threshold")


def input_sha256(issues: list[dict[str, Any]]) -> str:
    snapshot = [
        {"issue_id": row["id"], "inputs": row["followup_inputs"]} for row in issues
    ]
    raw = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def apply_followup(
    issues: list[dict[str, Any]], rules: FollowupRules, as_of: date
) -> dict[str, Any]:
    counts = dict.fromkeys(RESULT_LABELS, 0)
    for row in issues:
        row["followup"] = evaluate(row["followup_inputs"], rules, as_of)
        counts[row["followup"]["result"]] += 1
    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "timezone": "JST fixed UTC+09:00; calendar dates, current status",
        "rules_sha256": rules.sha256,
        "input_sha256": input_sha256(issues),
        "counts": counts,
    }


def csv_values(issue: dict[str, Any]) -> dict[str, Any]:
    inputs, result = issue["followup_inputs"], issue["followup"]
    values = {
        name: inputs[name].get("value") for name in ("incident_type", "discovered_on")
    }
    # Unsupported scalar values remain visible in JSON only.
    for name in values:
        if inputs[name]["state"] == "unsupported":
            values[name] = None
    values.update(
        {
            "followup_" + name: result[name]
            for name in ("as_of", "threshold_days", "elapsed_days", "threshold_date")
        }
    )
    values.update(
        followup_target="〇" if result["target"] is True else "",
        followup_result=RESULT_LABELS[result["result"]],
        followup_reason=REASONS[result["reason"]],
    )
    return values
