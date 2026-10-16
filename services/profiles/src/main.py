"""Profiles service with public and organization-only profile fields."""

import hmac
import os
from functools import wraps
from typing import Any, Callable

import jwt
from flask import Flask, jsonify, request

from models import Profile, db
from organization_client import (
    OrganizationServiceError,
    shares_verified_organization,
)


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///profiles.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET"] = os.getenv("JWT_SECRET", "development-only-secret")
app.config["JWT_ISSUER"] = os.getenv("JWT_ISSUER", "bsa-auth")
db.init_app(app)


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def get_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_access_token(handler: Callable[..., Any]):
    @wraps(handler)
    def wrapped(*args: Any, **kwargs: Any):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
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
        return handler(str(claims["sub"]), *args, **kwargs)

    return wrapped


def profile_or_default(user_id: str) -> Profile:
    profile = Profile.query.filter_by(user_id=user_id).first()
    if profile is None:
        profile = Profile(user_id=user_id)
        db.session.add(profile)
        db.session.flush()
    return profile


def public_profile(profile: Profile) -> dict[str, Any]:
    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "public_bio": profile.public_bio,
        "avatar_url": profile.avatar_url,
    }


def organization_profile(profile: Profile) -> dict[str, Any]:
    return {
        **public_profile(profile),
        "organization_bio": profile.organization_bio,
        "program": profile.program,
        "graduation_year": profile.graduation_year,
    }


def validate_profile_data(data: dict[str, Any]) -> dict[str, Any] | None:
    fields = {
        "display_name": (str, 160),
        "public_bio": (str, 1000),
        "avatar_url": (str, 2048),
        "organization_bio": (str, 1000),
        "program": (str, 160),
    }
    validated: dict[str, Any] = {}
    for field, (value_type, max_length) in fields.items():
        if field in data:
            value = data[field]
            if not isinstance(value, value_type) or len(value) > max_length:
                return None
            validated[field] = value.strip()
    if "graduation_year" in data:
        year = data["graduation_year"]
        if year is not None and (
            not isinstance(year, int) or year < 1900 or year > 2200
        ):
            return None
        validated["graduation_year"] = year
    return validated


@app.put("/me/profile")
@require_access_token
def update_my_profile(user_id: str):
    updates = validate_profile_data(get_json())
    if updates is None:
        return error("Profile fields are invalid")
    profile = profile_or_default(user_id)
    for field, value in updates.items():
        setattr(profile, field, value)
    db.session.commit()
    return jsonify(organization_profile(profile))


@app.get("/profiles/<user_id>")
def get_public_profile(user_id: str):
    profile = Profile.query.filter_by(user_id=user_id).first()
    if profile is None:
        return error("Profile not found", 404)
    return jsonify(public_profile(profile))


@app.get("/profiles/<user_id>/organization")
@require_access_token
def get_organization_profile(viewer_id: str, user_id: str):
    profile = Profile.query.filter_by(user_id=user_id).first()
    if profile is None:
        return error("Profile not found", 404)
    if viewer_id != user_id:
        try:
            allowed = shares_verified_organization(viewer_id, user_id)
        except OrganizationServiceError as exc:
            return error(str(exc), 503)
        if not allowed:
            return error("A shared verified organization is required", 403)
    return jsonify(organization_profile(profile))


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5005")))
