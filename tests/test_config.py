from pathlib import Path

import pytest

from redmine_readonly.config import Config, load_config
from redmine_readonly.errors import AppError


@pytest.mark.parametrize(
    "url",
    [
        "http://redmine.example.invalid",
        "https://user@redmine.example.invalid",
        "https://redmine.example.invalid?a=1",
        "https://redmine.example.invalid/#frag",
        "/relative",
    ],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(AppError):
        Config(url).validate()


def test_load_config_rejects_secret_or_unknown_key(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('base_url="https://redmine.example.invalid"\napi_key="secret"\n')
    with pytest.raises(AppError, match="unknown configuration keys") as caught:
        load_config(path)
    assert "secret" not in str(caught.value)


def test_subpath_is_valid():
    assert (
        Config("https://redmine.example.invalid/a/b")
        .validate()
        .base_url.endswith("/a/b")
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("base_url", 123, "base_url must be a string"),
        ("connect_timeout", "5", "connect_timeout must be a number"),
        ("connect_timeout", True, "connect_timeout must be a number"),
        ("read_timeout", False, "read_timeout must be a number"),
        ("read_timeout", float("inf"), "read_timeout must be finite"),
        ("page_size", 1.5, "page_size must be an integer"),
        ("page_size", True, "page_size must be an integer"),
        ("max_issues", "100", "max_issues must be an integer"),
        ("max_issues", False, "max_issues must be an integer"),
        ("max_pages", 2.0, "max_pages must be an integer"),
        ("max_pages", True, "max_pages must be an integer"),
        ("ca_bundle", 123, "ca_bundle must be a non-empty string"),
        ("ca_bundle", True, "ca_bundle must be a non-empty string"),
        ("ca_bundle", "  ", "ca_bundle must be a non-empty string"),
    ],
)
def test_validate_rejects_wrong_types_as_app_error(field, value, message):
    values = {"base_url": "https://redmine.example.invalid", field: value}
    with pytest.raises(AppError, match=message):
        Config(**values).validate()


@pytest.mark.parametrize(
    "toml_value",
    ["base_url=123", 'base_url="https://redmine.example.invalid"\npage_size=true'],
)
def test_load_config_type_errors_are_safe_app_errors(tmp_path: Path, toml_value):
    path = tmp_path / "config.toml"
    path.write_text(toml_value)
    with pytest.raises(AppError):
        load_config(path)
