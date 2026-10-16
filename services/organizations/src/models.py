"""Database models for student organizations and memberships."""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class Organization(db.Model):
    """An organization identified by its school email domain."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email_domain = db.Column(db.String(255), nullable=False, index=True)
    created_by = db.Column(db.String(128), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Membership(db.Model):
    """A user's verified or pending membership in an organization."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(128), nullable=False, index=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organization.id"), nullable=False
    )
    school_email = db.Column(db.String(320), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "organization_id", name="unique_user_organization"
        ),
        db.UniqueConstraint(
            "organization_id", "school_email", name="unique_org_school_email"
        ),
    )


class VerificationToken(db.Model):
    """Single-use token for verifying an organization email membership."""

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey("membership.id"), nullable=False
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
