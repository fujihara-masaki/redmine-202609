from pathlib import Path

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
