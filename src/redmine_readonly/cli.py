from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .client import RedmineClient
from .config import load_config
from .errors import AppError
from .exporter import fetch_issues
from .output import write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="redmine-readonly")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="TOML configuration path (must not contain API key)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate settings and authentication")
    resolve = commands.add_parser(
        "resolve-project", help="resolve a project identifier to its numeric ID"
    )
    resolve.add_argument(
        "--project", required=True, help="project numeric ID or identifier"
    )
    export = commands.add_parser("export", help="export issues as CSV and JSON")
    export.add_argument(
        "--project", required=True, help="explicit project ID or identifier"
    )
    export.add_argument(
        "--status",
        default="*",
        help="explicit Redmine status filter (default: * for all statuses)",
    )
    export.add_argument("--tracker", type=int, help="optional tracker ID")
    export.add_argument("--include-subprojects", action="store_true")
    export.add_argument(
        "--include-jst-columns",
        action="store_true",
        help="add JST display columns while retaining raw API timestamps",
    )
    export.add_argument("--output-dir", type=Path, required=True)
    return parser


def _api_key() -> str:
    key = os.environ.get("REDMINE_API_KEY")
    if key is None and sys.stdin.isatty():
        key = getpass.getpass("Redmine API key: ")
    if not key:
        raise AppError("set REDMINE_API_KEY or run interactively to enter the API key")
    return key


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = RedmineClient(load_config(args.config), _api_key())
        if args.command == "check":
            user = client.current_user()
            login = user.get("login")
            suffix = f", login={login}" if isinstance(login, str) else ""
            print(f"OK: authenticated (user_id={user['id']}{suffix})")
        elif args.command == "resolve-project":
            project = client.project(args.project)
            print(f"numeric_project_id: {project['id']}")
            print(f"identifier: {project['identifier']}")
            print(f"name: {project['name']}")
        else:
            result = fetch_issues(
                client,
                args.project,
                tracker_id=args.tracker,
                include_subprojects=args.include_subprojects,
                status_id=args.status,
                include_jst_columns=args.include_jst_columns,
            )
            csv_path, json_path = write_outputs(result, args.output_dir)
            print(f"OK: exported {len(result.issues)} issues")
            print(f"CSV: {csv_path}")
            print(f"JSON: {json_path}")
        return 0
    except AppError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
