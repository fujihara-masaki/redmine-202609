import json
from pathlib import Path

import pytest
import requests

from redmine_readonly import windows_launcher as helper


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("preflight must not send HTTP")

    monkeypatch.setattr(requests.Session, "send", denied)


@pytest.mark.parametrize(
    ("command", "project", "endpoint"),
    [
        ("check", "", "/users/current.json"),
        ("export", "42", "/issues.json"),
        ("resolve-project", "sample-project", "/projects/sample-project.json"),
        ("resolve-project", "42", "/projects/42.json"),
    ],
)
def test_target_preserves_subpath(tmp_path, command, project, endpoint):
    config = tmp_path / "設定 (sample).toml"
    config.write_text('base_url="https://redmine.example.invalid/redmine/"\n')
    assert helper.target_url(config, command, project) == (
        "https://redmine.example.invalid/redmine" + endpoint
    )


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        (
            "https://REDMINE.example.invalid/redmine",
            "https://redmine.example.invalid/redmine/users/current.json",
        ),
        (
            "https://例.example.invalid/redmine",
            "https://xn--fsq.example.invalid/redmine/users/current.json",
        ),
        (
            "https://redmine.example.invalid/日本語",
            "https://redmine.example.invalid/%E6%97%A5%E6%9C%AC%E8%AA%9E/users/current.json",
        ),
    ],
)
def test_target_matches_requests_prepared_url(tmp_path, base, expected):
    config = tmp_path / "config.toml"
    config.write_text(f'base_url="{base}"', encoding="utf-8")
    assert helper.target_url(config, "check") == expected


@pytest.mark.parametrize(
    "project", ["../users", "a/b", "a?b", "a#b", "a%2fb", "a\n", "$(x)", ""]
)
def test_project_cannot_change_path(tmp_path, project):
    config = tmp_path / "config.toml"
    config.write_text('base_url="https://redmine.example.invalid"')
    with pytest.raises(ValueError):
        helper.target_url(config, "resolve-project", project)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "proxy.example.invalid:8080",
        "socks5://proxy.example.invalid:8080",
        "http://user:secret@proxy.example.invalid",
        "http://@proxy.example.invalid",
        "http://proxy.example.invalid/path",
        "http://proxy.example.invalid?",
        "http://proxy.example.invalid#",
        "http://proxy.example.invalid:0",
        "http://proxy.example.invalid:65536",
        "http://proxy.example.invalid:",
        "http://proxy.example.invalid\n",
        "http://proxy.example.invalid/%0d",
        "http://proxy.example.invalid\\",
        "http://bad_host.invalid",
        "http://proxy.example.invalid/a/..",
        "http:///",
        "http://proxy.example.invalid:abc",
    ],
)
def test_bad_proxy(value):
    with pytest.raises(ValueError):
        helper.proxy_identity(value)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("http://proxy.example.invalid", "http://PROXY.example.invalid:80/"),
        ("https://proxy.example.invalid", "https://proxy.example.invalid:443"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080/"),
        ("http://[::1]:8080", "http://[0:0:0:0:0:0:0:1]:8080/"),
    ],
)
def test_valid_proxy_identity(left, right):
    assert helper.proxy_identity(left) == helper.proxy_identity(right)


@pytest.fixture
def clean_proxy_environment(monkeypatch):
    for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        for key in (name, name.upper()):
            monkeypatch.delenv(key, raising=False)
    # Never consult the host's Windows registry in these isolated tests.
    monkeypatch.setattr(
        requests.utils, "getproxies", requests.compat.getproxies_environment
    )
    return monkeypatch


def test_proxy_selection_and_ca_preserved(clean_proxy_environment):
    m = clean_proxy_environment
    m.setenv("HTTPS_PROXY", "http://proxy.example.invalid:8080")
    m.setenv("ALL_PROXY", "http://other.example.invalid:8888")
    m.setenv("HTTP_PROXY", "http://other.example.invalid:8888")
    m.setenv("REQUESTS_CA_BUNDLE", "fictional-ca.pem")
    helper.verify_selection(
        "https://redmine.example.invalid", "PROXY", "http://proxy.example.invalid:8080/"
    )
    with requests.Session() as session:
        assert session.trust_env is True
        assert (
            session.merge_environment_settings(
                "https://redmine.example.invalid", {}, None, None, None
            )["verify"]
            == "fictional-ca.pem"
        )


@pytest.mark.parametrize(
    "no_proxy", ["*", "redmine.example.invalid", ".example.invalid"]
)
def test_no_proxy_conflict(clean_proxy_environment, no_proxy):
    m = clean_proxy_environment
    m.setenv("HTTPS_PROXY", "http://proxy.example.invalid:8080")
    m.setenv("NO_PROXY", no_proxy)
    with pytest.raises(ValueError):
        helper.verify_selection(
            "https://redmine.example.invalid",
            "PROXY",
            "http://proxy.example.invalid:8080",
        )


@pytest.mark.parametrize(
    "variable", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"]
)
def test_direct_conflict(clean_proxy_environment, variable):
    clean_proxy_environment.setenv(variable, "http://other.example.invalid:8080")
    with pytest.raises(ValueError):
        helper.verify_selection("https://redmine.example.invalid", "DIRECT", None)


def test_direct_and_windows_registry_selection(clean_proxy_environment, monkeypatch):
    helper.verify_selection("https://redmine.example.invalid", "DIRECT", None)
    monkeypatch.setattr(
        requests.utils,
        "getproxies",
        lambda: {"https": "http://registry.example.invalid:8080"},
    )
    with pytest.raises(ValueError):
        helper.verify_selection("https://redmine.example.invalid", "DIRECT", None)


def test_lowercase_selection_uses_requests_rules(clean_proxy_environment):
    m = clean_proxy_environment
    m.setenv("HTTPS_PROXY", "http://chosen.example.invalid:8080")
    m.setenv("https_proxy", "http://other.example.invalid:8080")
    # Windows environment names are case insensitive; on POSIX Requests gives
    # lowercase precedence. This test exercises the actual host's selection.
    import os

    selected = requests.utils.get_environ_proxies("https://redmine.example.invalid")[
        "https"
    ]
    if os.name == "nt":
        assert selected == "http://other.example.invalid:8080"
    with pytest.raises(ValueError):
        helper.verify_selection(
            "https://redmine.example.invalid",
            "PROXY",
            "http://chosen.example.invalid:8080",
        )


def test_main_masks_all_helper_errors(monkeypatch, capsys):
    import io

    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps({"secret": "FAKE-SECRET"}).encode())),
    )
    with pytest.raises(SystemExit) as exc:
        helper.main()
    assert exc.value.code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR: launcher preflight failed\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-32"])
def test_helper_accepts_dotnet_pipe_preamble(monkeypatch, capsys, encoding):
    import io

    message = {"fixture": "設定 (sample)"}
    payload = json.dumps(message, ensure_ascii=True).encode(encoding)
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(payload)))

    def handle(request):
        assert request == message
        return {"ok": True}

    monkeypatch.setattr(helper, "handle", handle)
    helper.main()
    captured = capsys.readouterr()
    assert captured.out == '{"ok": true}\n'
    assert captured.err == ""


def test_wrong_editable_installation(tmp_path):
    with pytest.raises(ValueError, match="wrong installation"):
        helper.handle({"root": str(tmp_path)})


def test_actual_helper_protocol(monkeypatch, tmp_path):
    root = Path(helper.__file__).resolve().parents[2]
    monkeypatch.setattr("sys.prefix", str(root / ".venv"))
    config = tmp_path / "config.toml"
    config.write_text('base_url="https://redmine.example.invalid"')
    request = {
        "root": str(root),
        "config": str(config),
        "command": "check",
        "project": "",
        "stage": "target",
    }
    assert helper.handle(request) == {
        "url": "https://redmine.example.invalid/users/current.json"
    }
    request.update(stage="bad")
    with pytest.raises(ValueError):
        helper.handle(request)
