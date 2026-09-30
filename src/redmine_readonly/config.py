from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

from .errors import AppError


@dataclass(frozen=True)
class Config:
    base_url: str
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    page_size: int = 100
    max_issues: int = 100_000
    max_pages: int = 2_000
    ca_bundle: str | None = None

    def validate(self) -> "Config":
        if not isinstance(self.base_url, str):
            raise AppError("base_url must be a string")
        for name, value in (
            ("connect_timeout", self.connect_timeout),
            ("read_timeout", self.read_timeout),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AppError(f"{name} must be a number")
            if not math.isfinite(value):
                raise AppError(f"{name} must be finite")
        for name, value in (
            ("page_size", self.page_size),
            ("max_issues", self.max_issues),
            ("max_pages", self.max_pages),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise AppError(f"{name} must be an integer")
        if self.ca_bundle is not None and (
            not isinstance(self.ca_bundle, str) or not self.ca_bundle.strip()
        ):
            raise AppError("ca_bundle must be a non-empty string or omitted")
        try:
            parsed = urlsplit(self.base_url)
        except (TypeError, ValueError):
            raise AppError("base_url is not a valid URL") from None
        if parsed.scheme != "https" or not parsed.netloc:
            raise AppError("base_url must be an absolute HTTPS URL")
        if parsed.username or parsed.password:
            raise AppError("base_url must not contain user information")
        if parsed.query or parsed.fragment:
            raise AppError("base_url must not contain a query or fragment")
        if any(value <= 0 for value in (self.connect_timeout, self.read_timeout)):
            raise AppError("timeouts must be greater than zero")
        if self.page_size <= 0 or self.max_issues <= 0 or self.max_pages <= 0:
            raise AppError(
                "page_size, max_issues, and max_pages must be greater than zero"
            )
        return self


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AppError(f"cannot read configuration: {type(exc).__name__}") from None
    allowed = {field.name for field in Config.__dataclass_fields__.values()}
    unknown = set(data) - allowed
    if unknown:
        raise AppError("unknown configuration keys: " + ", ".join(sorted(unknown)))
    try:
        return Config(**data).validate()
    except TypeError:
        raise AppError("configuration values have invalid names or types") from None
