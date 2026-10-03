"""Fixed export profiles and their stable CSV representation."""

EXTENDED_FIELDS = (
    "priority",
    "author",
    "category",
    "fixed_version",
    "parent",
    "start_date",
    "due_date",
    "done_ratio",
    "estimated_hours",
    "is_private",
)

EXTENDED_CSV_COLUMNS = (
    "priority_id",
    "priority_name",
    "author_id",
    "author_name",
    "category_id",
    "category_name",
    "fixed_version_id",
    "fixed_version_name",
    "parent_id",
    "start_date",
    "due_date",
    "done_ratio",
    "estimated_hours",
    "is_private",
)

FIELD_PROFILES = ("basic", "extended")
EXTENDED_NAME_MAX_LENGTH = 4096
