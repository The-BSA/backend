"""Client for organization membership privacy checks."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OrganizationServiceError(RuntimeError):
    """Raised when the organization service cannot answer a privacy check."""


def shares_verified_organization(viewer_id: str, subject_id: str) -> bool:
    service_url = os.getenv(
        "ORGANIZATION_SERVICE_URL", "http://localhost:5004"
    ).rstrip("/")
    payload = json.dumps(
        {"viewer_id": viewer_id, "subject_id": subject_id}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    service_token = os.getenv("ORGANIZATION_SERVICE_TOKEN")
    if service_token:
        headers["X-Internal-Token"] = service_token
    request = Request(
        f"{service_url}/internal/shared-membership",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise OrganizationServiceError(
                    "Organization service rejected membership check"
                )
            result = json.loads(response.read())
    except HTTPError as exc:
        raise OrganizationServiceError(
            "Organization service rejected membership check"
        ) from exc
    except (OSError, URLError, ValueError, TypeError) as exc:
        raise OrganizationServiceError(
            "Organization service is unavailable"
        ) from exc
    return bool(result.get("shared"))
