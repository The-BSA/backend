"""Database models for public and organization-only profiles."""

from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class Profile(db.Model):
    """A profile keyed by the user ID owned by the auth service."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(160), nullable=False, default="")
    public_bio = db.Column(db.String(1000), nullable=False, default="")
    avatar_url = db.Column(db.String(2048), nullable=False, default="")
    organization_bio = db.Column(db.String(1000), nullable=False, default="")
    program = db.Column(db.String(160), nullable=False, default="")
    graduation_year = db.Column(db.Integer, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
