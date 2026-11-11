"""HTTP clients for the services the search service depends on."""

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class UpstreamError(RuntimeError):
    """Raised when a backing service cannot answer a request."""


def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise UpstreamError(f"Upstream service returned {exc.code}") from exc
    except (OSError, URLError, ValueError, TypeError) as exc:
        raise UpstreamError("Upstream service is unavailable") from exc


def fetch_all_profiles() -> list[dict[str, Any]]:
    """Page through every profile held by the profiles service."""
    base = os.getenv("PROFILES_SERVICE_URL", "http://localhost:5005").rstrip("/")
    token = os.getenv("PROFILES_SERVICE_TOKEN", "bsa")
    headers = {"X-Internal-Token": token} if token else {}
    profiles: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = _get_json(
            f"{base}/internal/profiles?limit=500&offset={offset}", headers
        )
        batch = page.get("profiles", [])
        profiles.extend(batch)
        offset += len(batch)
        if not batch or offset >= int(page.get("total", 0)):
            return profiles


def fetch_viewer_organizations(access_token: str) -> list[dict[str, Any]]:
    """Organizations the viewer is verified in, using the viewer's own token."""
    base = os.getenv("ORGANIZATION_SERVICE_URL", "http://localhost:5004").rstrip("/")
    data = _get_json(
        f"{base}/me/organizations", {"Authorization": f"Bearer {access_token}"}
    )
    return data.get("organizations", [])


def fetch_organization_member_ids(
    access_token: str, organization_id: int
) -> set[str]:
    """Verified member user IDs; the organization service checks the viewer."""
    base = os.getenv("ORGANIZATION_SERVICE_URL", "http://localhost:5004").rstrip("/")
    data = _get_json(
        f"{base}/organizations/{organization_id}/members",
        {"Authorization": f"Bearer {access_token}"},
    )
    return {str(member["user_id"]) for member in data.get("members", [])}
