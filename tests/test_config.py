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
