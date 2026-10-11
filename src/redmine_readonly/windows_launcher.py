"""Private, key-free preflight protocol for the Windows launcher.

Input/output JSON travels over helper-only pipes, never command-line arguments.
No request is sent here; Windows PAC evaluation happens in the PowerShell layer.
"""

from __future__ import annotations

import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests
from requests.utils import select_proxy

from .client import PROJECT_REFERENCE
from .config import load_config


def target_url(config_path: Path, command: str, project: str = "") -> str:
    base = load_config(config_path).base_url.rstrip("/")
    endpoints = {"check": "/users/current.json", "export": "/issues.json"}
    if command == "resolve-project":
        if not PROJECT_REFERENCE.fullmatch(project):
            raise ValueError("invalid project")
        endpoint = f"/projects/{quote(project, safe='')}.json"
    else:
        endpoint = endpoints[command]
    url = base + endpoint
    parsed = urlsplit(url)
    # Tighten only the launcher's preflight; do not change the existing API code.
    if (
        re.search(r"[\s\x00-\x1f\x7f]", url)
        or "\\" in url
        or not parsed.hostname
        or parsed.port == 0
    ):
        raise ValueError("invalid target")
    # Session.get prepares the request before merging its environment. Reuse
    # Requests' URL normalization (IDNA, host case, percent encoding) so that
    # NO_PROXY is checked against the same URL the existing client will use.
    prepared = requests.Request("GET", url).prepare().url
    if prepared is None:
        raise ValueError("invalid target")
    return prepared


def proxy_identity(value: str) -> tuple[str, str, int]:
    """Validate a conventional proxy URI and compare implicit/default ports."""
    if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f]", value):
        raise ValueError("invalid proxy")
    uri = urlsplit(value)
    if (
        uri.scheme not in ("http", "https")
        or not uri.hostname
        or uri.username is not None
        or uri.password is not None
        or "?" in value
        or "#" in value
        or "\\" in value
        or uri.path not in ("", "/")
        or uri.port == 0
        or uri.netloc.endswith(":")
    ):
        raise ValueError("invalid proxy")
    host = uri.hostname.lower()
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        host = host.encode("idna").decode("ascii")
        if len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.rstrip(".").split(".")
        ):
            raise ValueError("invalid proxy") from None
    return uri.scheme, host, uri.port or (443 if uri.scheme == "https" else 80)


def verify_selection(url: str, decision: str, proxy: str | None) -> None:
    # Same default Session and merge/select path used by RedmineClient.get.
    # This retains Requests' environment, NO_PROXY, registry and CA behavior.
    with requests.Session() as session:
        settings = session.merge_environment_settings(url, {}, None, None, None)
        selected = select_proxy(url, settings["proxies"])
    if decision == "DIRECT":
        if selected:
            raise ValueError("proxy conflict")
    elif decision == "PROXY" and proxy is not None:
        if not selected or proxy_identity(selected) != proxy_identity(proxy):
            raise ValueError("proxy conflict")
    else:
        raise ValueError("invalid decision")


def handle(message: dict) -> dict:
    root = Path(message["root"]).resolve()
    if (
        Path(sys.prefix).resolve() != root / ".venv"
        or Path(__file__).resolve()
        != root / "src" / "redmine_readonly" / "windows_launcher.py"
    ):
        raise ValueError("wrong installation")
    url = target_url(Path(message["config"]), message["command"], message["project"])
    if message["stage"] == "target":
        return {"url": url}
    if message["stage"] != "verify":
        raise ValueError("invalid stage")
    verify_selection(url, message["decision"], message.get("proxy"))
    return {"ok": True}


def main() -> None:
    try:
        result = handle(json.load(sys.stdin))
        print(json.dumps(result, ensure_ascii=True))
    except Exception:  # noqa: BLE001 - private boundary must never echo input
        print("ERROR: launcher preflight failed", file=sys.stderr)
        raise SystemExit(3) from None


if __name__ == "__main__":
    main()
