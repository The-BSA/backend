"""Email verification microservice."""

import hmac
import os

from flask import Flask, jsonify, request

from email_sender import EmailDeliveryError, send_verification_email


app = Flask(__name__)


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@app.post("/send-verification")
def send_verification():
    configured_token = os.getenv("EMAIL_SERVICE_TOKEN")
    request_token = request.headers.get("X-Internal-Token", "")
    if not configured_token:
        return error("EMAIL_SERVICE_TOKEN is not configured", 503)
    if not hmac.compare_digest(request_token, configured_token):
        return error("Invalid internal service token", 401)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("A JSON request body is required")
    email = data.get("email")
    token = data.get("token")
    verification_url = data.get("verification_url")
    if not isinstance(email, str) or not email.strip():
        return error("A recipient email is required")
    if not isinstance(token, str) or not token:
        return error("A verification token is required")
    if verification_url is not None and (
        not isinstance(verification_url, str) or not verification_url.startswith("http")
    ):
        return error("A valid verification URL is required")

    try:
        send_verification_email(email.strip(), token, verification_url)
    except EmailDeliveryError as exc:
        return error(str(exc), 503)
    return jsonify({"message": "Verification email accepted"}), 202


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5003")))
