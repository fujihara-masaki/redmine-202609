# Repository guidance

- This repository is public. Never add actual server names, credentials, internal issue data, or real API responses.
- API application code must remain read-only: only explicitly implemented `GET` endpoints are allowed. Do not add a generic request/path command.
- Automated tests must mock HTTP and must not require an API key.
- Keep standard Redmine behavior separate from assumptions that need verification on the target installation.
- Run `python -m pytest` before committing.
