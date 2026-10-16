"""HTTP client for the standalone email verification service."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmailDeliveryError(RuntimeError):
    """Raised when the email verification service cannot deliver a message."""


def send_verification_email(recipient: str, token: str, verification_url: str) -> None:
    service_url = os.getenv("EMAIL_SERVICE_URL", "http://localhost:5003").rstrip("/")
    payload = json.dumps(
        {
            "email": recipient,
            "token": token,
            "verification_url": verification_url,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    service_token = os.getenv("EMAIL_SERVICE_TOKEN")
    if service_token:
        headers["X-Internal-Token"] = service_token
    request = Request(
        f"{service_url}/send-verification",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 202:
                raise EmailDeliveryError("Email service rejected verification email")
    except HTTPError as exc:
        raise EmailDeliveryError("Email service rejected verification email") from exc
    except (OSError, URLError) as exc:
        raise EmailDeliveryError("Email service is unavailable") from exc
