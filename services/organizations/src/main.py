"""Student organizations: school-email verification and memberships."""

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable

import jwt
from flask import Flask, jsonify, request

from email_service import EmailDeliveryError, send_verification_email
from models import Membership, Organization, VerificationToken, db


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "sqlite:///organizations.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET"] = os.getenv("JWT_SECRET", "development-only-secret")
app.config["JWT_ISSUER"] = os.getenv("JWT_ISSUER", "bsa-auth")
app.config["SERVICE_URL"] = os.getenv("SERVICE_URL", "http://localhost:5004").rstrip(
    "/"
)
app.config["VERIFICATION_HOURS"] = int(
    os.getenv("ORGANIZATION_VERIFICATION_HOURS", "24")
)
db.init_app(app)


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def serialize_organization(organization: Organization) -> dict[str, Any]:
    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "email_domain": organization.email_domain,
    }


def serialize_membership(membership: Membership) -> dict[str, Any]:
    return {
        "id": membership.id,
        "organization_id": membership.organization_id,
        "school_email": membership.school_email,
        "is_verified": membership.is_verified,
    }


def school_email_domain(school_email: str) -> str | None:
    if "@" not in school_email or len(school_email) > 320:
        return None
    domain = school_email.rsplit("@", 1)[1]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        return None
    return domain


def send_membership_verification(
    user_id: str, organization: Organization, school_email: str
):
    existing = Membership.query.filter_by(
        user_id=user_id, organization_id=organization.id
    ).first()
    if existing and existing.is_verified:
        return error("You are already verified in this organization", 409)
    if Membership.query.filter_by(
        organization_id=organization.id, school_email=school_email
    ).filter(Membership.user_id != user_id).first():
        return error("That school email is already linked to another member", 409)

    membership = existing or Membership(
        user_id=user_id,
        organization_id=organization.id,
        school_email=school_email,
    )
    membership.school_email = school_email
    db.session.add(membership)
    db.session.flush()
    VerificationToken.query.filter_by(membership_id=membership.id).delete()
    raw_token = secrets.token_urlsafe(48)
    db.session.add(
        VerificationToken(
            token_hash=token_hash(raw_token),
            membership_id=membership.id,
            expires_at=now_utc()
            + timedelta(hours=app.config["VERIFICATION_HOURS"]),
        )
    )
    verification_url = f"{app.config['SERVICE_URL']}/verify/{raw_token}"
    try:
        send_verification_email(school_email, raw_token, verification_url)
    except EmailDeliveryError as exc:
        db.session.rollback()
        return error(str(exc), 503)
    db.session.commit()
    return jsonify({"message": "Verification email sent to the school address"}), 202


@app.post("/memberships")
@require_access_token
def add_membership_by_email(user_id: str):
    data = get_json()
    school_email = str(data.get("school_email", "")).strip().lower()
    domain = school_email_domain(school_email)
    if domain is None:
        return error("A valid school email is required")

    organization = Organization.query.filter_by(email_domain=domain).first()
    created = False
    if organization is None:
        organization = Organization(
            name=domain,
            slug=f"{domain.replace('.', '-')}-{token_hash(domain)[:8]}",
            email_domain=domain,
            created_by=user_id,
        )
        db.session.add(organization)
        db.session.flush()
        created = True
    result = send_membership_verification(user_id, organization, school_email)
    if created and isinstance(result, tuple) and len(result) == 2 and result[1] >= 400:
        db.session.rollback()
    if isinstance(result, tuple) and len(result) == 2 and result[1] == 202:
        return (
            jsonify(
                {
                    "message": "Verification email sent to the school address",
                    "organization": serialize_organization(organization),
                }
            ),
            202,
        )
    return result


@app.post("/organizations")
@require_access_token
def create_organization(user_id: str):
    data = get_json()
    name = str(data.get("name", "")).strip()
    slug = str(data.get("slug", "")).strip().lower()
    email_domain = str(data.get("email_domain", "")).strip().lower().lstrip("@")
    if not name or len(name) > 160:
        return error("Organization name is required")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        return error("Slug must contain lowercase letters, numbers, and hyphens")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", email_domain):
        return error("A valid school email domain is required")
    if Organization.query.filter(
        (Organization.slug == slug) | (Organization.email_domain == email_domain)
    ).first():
        return error("An organization with this slug or email domain already exists", 409)

    organization = Organization(
        name=name, slug=slug, email_domain=email_domain, created_by=user_id
    )
    db.session.add(organization)
    db.session.commit()
    return jsonify(serialize_organization(organization)), 201


@app.get("/organizations")
def list_organizations():
    return jsonify(
        {"organizations": [serialize_organization(org) for org in Organization.query]}
    )


@app.post("/organizations/<int:organization_id>/memberships")
@require_access_token
def add_membership(user_id: str, organization_id: int):
    organization = db.session.get(Organization, organization_id)
    if organization is None:
        return error("Organization not found", 404)
    data = get_json()
    school_email = str(data.get("school_email", "")).strip().lower()
    domain = school_email_domain(school_email)
    if domain is None:
        return error("A valid school email is required")
    if domain != organization.email_domain:
        return error("School email must use the organization's email domain", 422)
    return send_membership_verification(user_id, organization, school_email)


@app.get("/verify/<token>")
def verify_membership(token: str):
    record = VerificationToken.query.filter_by(token_hash=token_hash(token)).first()
    if not record or record.expires_at.replace(tzinfo=timezone.utc) < now_utc():
        return error("Invalid or expired organization verification token")
    membership = db.session.get(Membership, record.membership_id)
    if membership is None:
        return error("Invalid organization verification token")
    membership.is_verified = True
    membership.verified_at = now_utc()
    db.session.delete(record)
    db.session.commit()
    return jsonify({"message": "Organization membership verified"})


@app.get("/me/organizations")
@require_access_token
def my_organizations(user_id: str):
    memberships = Membership.query.filter_by(user_id=user_id, is_verified=True).all()
    organizations = [
        serialize_organization(db.session.get(Organization, membership.organization_id))
        for membership in memberships
    ]
    return jsonify({"organizations": organizations})


@app.get("/me/memberships")
@require_access_token
def my_memberships(user_id: str):
    memberships = Membership.query.filter_by(user_id=user_id).all()
    return jsonify(
        {"memberships": [serialize_membership(membership) for membership in memberships]}
    )


@app.get("/organizations/<int:organization_id>/members")
@require_access_token
def organization_members(user_id: str, organization_id: int):
    if db.session.get(Organization, organization_id) is None:
        return error("Organization not found", 404)
    verified = Membership.query.filter_by(
        user_id=user_id, organization_id=organization_id, is_verified=True
    ).first()
    if verified is None:
        return error("Verified organization membership is required", 403)
    members = Membership.query.filter_by(
        organization_id=organization_id, is_verified=True
    ).all()
    return jsonify(
        {
            "members": [
                {"user_id": member.user_id, "school_email": member.school_email}
                for member in members
            ]
        }
    )


@app.post("/internal/shared-membership")
def shared_membership():
    configured_token = os.getenv("ORGANIZATION_SERVICE_TOKEN")
    request_token = request.headers.get("X-Internal-Token", "")
    if not configured_token:
        return error("ORGANIZATION_SERVICE_TOKEN is not configured", 503)
    if not hmac.compare_digest(request_token, configured_token):
        return error("Invalid internal service token", 401)
    data = get_json()
    viewer_id = data.get("viewer_id")
    subject_id = data.get("subject_id")
    if not isinstance(viewer_id, str) or not isinstance(subject_id, str):
        return error("viewer_id and subject_id are required")
    if viewer_id == subject_id:
        return jsonify({"shared": True})
    viewer_orgs = db.session.query(Membership.organization_id).filter_by(
        user_id=viewer_id, is_verified=True
    )
    subject_orgs = db.session.query(Membership.organization_id).filter_by(
        user_id=subject_id, is_verified=True
    )
    shared = db.session.query(Membership.id).filter(
        Membership.organization_id.in_(viewer_orgs),
        Membership.organization_id.in_(subject_orgs),
        Membership.is_verified.is_(True),
    ).first() is not None
    return jsonify({"shared": shared})


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5004")))
