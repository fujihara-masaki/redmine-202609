from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests

from .config import Config
from .errors import AppError

PROJECT_REFERENCE = re.compile(r"(?:[1-9][0-9]*|[a-z0-9][a-z0-9_-]*)\Z")


class RedmineClient:
    """Client exposing only the explicitly supported read-only GET endpoints."""

    def __init__(
        self, config: Config, api_key: str, session: requests.Session | None = None
    ):
        if not api_key.strip():
            raise AppError("API key is required")
        self.config = config.validate()
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "X-Redmine-API-Key": api_key,
                "User-Agent": "redmine-readonly-export/0.1",
            }
        )

    def _get_json(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + endpoint
        verify: bool | str = self.config.ca_bundle or True
        try:
            response = self._session.get(
                url,
                params=params,
                timeout=(self.config.connect_timeout, self.config.read_timeout),
                verify=verify,
                allow_redirects=False,
            )
        except requests.Timeout:
            raise AppError("request timed out") from None
        except requests.RequestException as exc:
            raise AppError(f"request failed: {type(exc).__name__}") from None
        except OSError:
            if self.config.ca_bundle is not None:
                raise AppError("CA bundle could not be accessed or loaded") from None
            raise AppError("request failed due to a local I/O error") from None
        if 300 <= response.status_code < 400:
            raise AppError(
                "redirect response refused; verify base_url and proxy settings"
            )
        status_messages = {
            401: "authentication failed (HTTP 401)",
            403: "permission denied (HTTP 403)",
            404: "Redmine API endpoint or project not found (HTTP 404)",
        }
        if response.status_code in status_messages:
            raise AppError(status_messages[response.status_code])
        if not 200 <= response.status_code < 300:
            raise AppError(f"Redmine API returned HTTP {response.status_code}")
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/json" not in content_type:
            raise AppError("Redmine API returned a non-JSON response")
        try:
            payload = response.json()
        except (requests.JSONDecodeError, ValueError):
            raise AppError("Redmine API returned malformed JSON") from None
        if not isinstance(payload, dict):
            raise AppError("Redmine API returned an unexpected JSON structure")
        return payload

    def current_user(self) -> dict[str, Any]:
        payload = self._get_json("/users/current.json")
        user = payload.get("user")
        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            raise AppError("current-user response has an unexpected structure")
        return {"id": user["id"], "login": user.get("login")}

    def issue_page(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._get_json("/issues.json", params)

    def project(self, project_reference: str) -> dict[str, Any]:
        """Resolve one numeric ID or Redmine identifier to minimal project data."""
        if not PROJECT_REFERENCE.fullmatch(project_reference):
            raise AppError("project must be a numeric ID or valid identifier")
        encoded_reference = quote(project_reference, safe="")
        payload = self._get_json(f"/projects/{encoded_reference}.json")
        project = payload.get("project")
        if (
            not isinstance(project, dict)
            or not isinstance(project.get("id"), int)
            or isinstance(project.get("id"), bool)
            or not isinstance(project.get("identifier"), str)
            or not isinstance(project.get("name"), str)
        ):
            raise AppError("project response has an unexpected structure")
        return {
            "id": project["id"],
            "identifier": project["identifier"],
            "name": project["name"],
        }
