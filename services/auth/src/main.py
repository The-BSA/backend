"""Authentication microservice: credentials, JWTs, refresh, and revocation."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

import jwt
from flask import Flask, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from email_service import EmailDeliveryError, send_verification_email
from models import RefreshToken, User, VerificationToken, db


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///auth.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET"] = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
app.config["JWT_ISSUER"] = os.getenv("JWT_ISSUER", "bsa-auth")
app.config["ACCESS_TOKEN_MINUTES"] = int(
    os.getenv("ACCESS_TOKEN_MINUTES", "15")
)
app.config["REFRESH_TOKEN_DAYS"] = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))
db.init_app(app)


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user: User) -> str:
    issued_at = now_utc()
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "iat": issued_at,
        "exp": issued_at
        + timedelta(minutes=app.config["ACCESS_TOKEN_MINUTES"]),
        "iss": app.config["JWT_ISSUER"],
        "type": "access",
    }
    return jwt.encode(claims, app.config["JWT_SECRET"], algorithm="HS256")


def issue_refresh_token(user: User) -> str:
    raw_token = secrets.token_urlsafe(48)
    db.session.add(
        RefreshToken(
            token_hash=token_hash(raw_token),
            user_id=user.id,
            expires_at=now_utc()
            + timedelta(days=app.config["REFRESH_TOKEN_DAYS"]),
        )
    )
    return raw_token


def get_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_access_token(handler: Callable[..., Any]):
    @wraps(handler)
    def wrapped(*args: Any, **kwargs: Any):
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return error("A bearer access token is required", 401)
        try:
            claims = jwt.decode(
                token,
                app.config["JWT_SECRET"],
                algorithms=["HS256"],
                issuer=app.config["JWT_ISSUER"],
            )
        except jwt.InvalidTokenError:
            return error("Invalid or expired access token", 401)
        if claims.get("type") != "access" or not claims.get("sub"):
            return error("Invalid access token", 401)
        return handler(claims, *args, **kwargs)

    return wrapped


@app.post("/register")
@app.post("/signup")
def register():
    data = get_json()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    if "@" not in email or len(email) > 320:
        return error("A valid email is required")
    if not isinstance(password, str) or len(password) < 8:
        return error("Password must be at least 8 characters")
    if User.query.filter_by(email=email).first():
        return error("Email is already registered", 409)

    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.flush()
    verification_token = secrets.token_urlsafe(48)
    db.session.add(
        VerificationToken(
            token=verification_token,
            user_id=user.id,
            expires_at=now_utc() + timedelta(hours=24),
        )
    )
    try:
        send_verification_email(email, verification_token)
    except EmailDeliveryError as exc:
        db.session.rollback()
        return error(str(exc), 503)
    db.session.commit()
    return (
        jsonify(
            {
                "message": "Registration successful. Verify your email to continue.",
            }
        ),
        201,
    )


@app.get("/verify/<token>")
def verify(token: str):
    record = VerificationToken.query.filter_by(token=token).first()
    if not record or record.expires_at.replace(tzinfo=timezone.utc) < now_utc():
        return error("Invalid or expired verification token")
    user = db.session.get(User, record.user_id)
    if user is None:
        return error("Invalid verification token")
    user.is_verified = True
    db.session.delete(record)
    db.session.commit()
    return jsonify({"message": "Email verified successfully"})


@app.post("/login")
def login():
    data = get_json()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not isinstance(password, str) or not check_password_hash(
        user.password_hash, password
    ):
        return error("Invalid email or password", 401)
    if not user.is_verified:
        return error("Email must be verified before login", 403)

    refresh_token = issue_refresh_token(user)
    db.session.commit()
    return jsonify(
        {
            "access_token": create_access_token(user),
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": app.config["ACCESS_TOKEN_MINUTES"] * 60,
        }
    )


@app.post("/refresh")
def refresh():
    data = get_json()
    raw_token = data.get("refresh_token", "")
    if not isinstance(raw_token, str) or not raw_token:
        return error("A refresh token is required")
    record = RefreshToken.query.filter_by(token_hash=token_hash(raw_token)).first()
    if (
        not record
        or record.revoked_at is not None
        or record.expires_at.replace(tzinfo=timezone.utc) < now_utc()
    ):
        return error("Invalid or expired refresh token", 401)
    user = db.session.get(User, record.user_id)
    if user is None:
        return error("Invalid refresh token", 401)

    record.revoked_at = now_utc()
    new_refresh_token = issue_refresh_token(user)
    db.session.commit()
    return jsonify(
        {
            "access_token": create_access_token(user),
            "refresh_token": new_refresh_token,
            "token_type": "Bearer",
            "expires_in": app.config["ACCESS_TOKEN_MINUTES"] * 60,
        }
    )


@app.post("/logout")
def logout():
    data = get_json()
    raw_token = data.get("refresh_token", "")
    if not isinstance(raw_token, str) or not raw_token:
        return error("A refresh token is required")
    record = RefreshToken.query.filter_by(token_hash=token_hash(raw_token)).first()
    if record and record.revoked_at is None:
        record.revoked_at = now_utc()
        db.session.commit()
    return jsonify({"message": "Logout successful"})


@app.get("/introspect")
@require_access_token
def introspect(claims: dict[str, Any]):
    return jsonify({"active": True, "claims": claims})


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
