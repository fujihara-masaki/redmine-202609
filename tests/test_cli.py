from pathlib import Path

from conftest import FakeResponse, FakeSession

from redmine_readonly.cli import run


def test_cli_error_does_not_echo_key_or_config_secret(
    tmp_path: Path, monkeypatch, capsys
):
    config = tmp_path / "bad.toml"
    config.write_text('base_url="http://redmine.example.invalid/SECRET-IN-URL"\n')
    monkeypatch.setenv("REDMINE_API_KEY", "TOP-SECRET")
    assert run(["--config", str(config), "check"]) == 2
    captured = capsys.readouterr()
    assert "TOP-SECRET" not in captured.err
    assert "SECRET-IN-URL" not in captured.err


def test_missing_key_is_safe(tmp_path: Path, monkeypatch, capsys):
    config = tmp_path / "config.toml"
    config.write_text('base_url="https://redmine.example.invalid"\n')
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert run(["--config", str(config), "check"]) == 2
    assert "REDMINE_API_KEY" in capsys.readouterr().err


def test_invalid_config_type_is_reported_without_traceback(
    tmp_path: Path, monkeypatch, capsys
):
    config = tmp_path / "config.toml"
    config.write_text(
        'base_url="https://redmine.example.invalid"\nconnect_timeout="five"\n'
    )
    monkeypatch.setenv("REDMINE_API_KEY", "TEST-ONLY-KEY")

    assert run(["--config", str(config), "check"]) == 2

    captured = capsys.readouterr()
    assert "connect_timeout must be a number" in captured.err
    assert "Traceback" not in captured.err
    assert "TEST-ONLY-KEY" not in captured.err


def test_ca_bundle_os_error_is_reported_without_traceback(
    tmp_path: Path, monkeypatch, capsys
):
    secret_path = "/private/SECRET-CA-PATH/corporate.pem"
    config = tmp_path / "config.toml"
    config.write_text(
        f'base_url="https://redmine.example.invalid"\nca_bundle="{secret_path}"\n'
    )
    monkeypatch.setenv("REDMINE_API_KEY", "TEST-ONLY-KEY")

    def fail_get(*args, **kwargs):
        raise OSError(f"invalid CA path: {secret_path}")

    monkeypatch.setattr("requests.Session.get", fail_get)

    assert run(["--config", str(config), "check"]) == 2
    captured = capsys.readouterr()
    assert "CA bundle could not be accessed or loaded" in captured.err
    assert "Traceback" not in captured.err
    assert secret_path not in captured.err
    assert "TEST-ONLY-KEY" not in captured.err


def test_resolve_project_prints_only_minimum_fields(
    tmp_path: Path, monkeypatch, capsys
):
    config = tmp_path / "config.toml"
    config.write_text('base_url="https://redmine.example.invalid"\n')
    monkeypatch.setenv("REDMINE_API_KEY", "TEST-ONLY-KEY")
    session = FakeSession(
        [
            FakeResponse(
                payload={
                    "project": {
                        "id": 42,
                        "identifier": "sample-project",
                        "name": "Example Project",
                        "description": "must not be shown",
                    }
                }
            )
        ]
    )
    monkeypatch.setattr("requests.Session", lambda: session)

    assert (
        run(
            [
                "--config",
                str(config),
                "resolve-project",
                "--project",
                "sample-project",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == (
        "numeric_project_id: 42\nidentifier: sample-project\nname: Example Project\n"
    )
    assert "must not be shown" not in captured.out
    assert {call[0] for call in session.calls} == {"GET"}
