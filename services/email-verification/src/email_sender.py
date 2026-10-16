"""SMTP delivery for verification links."""

import os
import smtplib
import ssl
from email.message import EmailMessage


class EmailDeliveryError(RuntimeError):
    """Raised when SMTP cannot accept the verification email."""


def send_verification_email(
    recipient: str, token: str, verification_url: str | None = None
) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_from = os.getenv("SMTP_FROM")
    if not smtp_host or not smtp_from:
        raise EmailDeliveryError(
            "SMTP_HOST and SMTP_FROM must be configured"
        )

    verification_base_url = (
        verification_url
        or os.getenv("VERIFICATION_BASE_URL", "http://localhost:5002/verify")
    ).rstrip("/")
    verification_link = (
        verification_base_url
        if verification_url
        else f"{verification_base_url}/{token}"
    )
    message = EmailMessage()
    message["Subject"] = "Verify your BSA account"
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(
        "Verify your BSA account by opening this link:\n\n"
        f"{verification_link}\n\n"
        "This link expires in 24 hours."
    )

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if os.getenv("SMTP_USE_TLS", "true").lower() == "true":
                server.starttls(context=ssl.create_default_context())
            if username and password:
                server.login(username, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Unable to send verification email") from exc
