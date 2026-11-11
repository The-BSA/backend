"""Search service: find students by name, bio, program, year, or organization.

Visibility follows the profiles service rules:
  * Anyone can search public fields (name, public bio, avatar).
  * A logged-in viewer additionally sees organization-only fields (organization
    bio, program, graduation year) for students who share a verified
    organization with them, and can filter on those fields.
"""

import math
import os
import secrets
from typing import Any

import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS

import clients
from clients import UpstreamError


app = Flask(__name__)
app.config["JWT_SECRET"] = os.getenv("JWT_SECRET", "development-only-secret")
app.config["JWT_ISSUER"] = os.getenv("JWT_ISSUER", "bsa-auth")
CORS(
    app,
    origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost,http://127.0.0.1,http://localhost:80,http://127.0.0.1:80",
        ).split(",")
        if origin.strip()
    ],
    allow_headers=["Authorization", "Content-Type"],
    methods=["GET", "OPTIONS"],
)

DEFAULT_PER_PAGE = 12
MAX_PER_PAGE = 50
MAX_QUERY_LENGTH = 100


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


class AuthError(Exception):
    pass


def viewer_from_request() -> tuple[str, str] | None:
    """Return (user_id, access_token) or None for an anonymous request.

    A token that is present but invalid raises AuthError, so clients with a
    stale token find out instead of silently receiving reduced results.
    """
    header = request.headers.get("Authorization", "")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("A bearer access token is required")
    try:
        claims = jwt.decode(
            token,
            app.config["JWT_SECRET"],
            algorithms=["HS256"],
            issuer=app.config["JWT_ISSUER"],
        )
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid or expired access token") from exc
    if claims.get("type") != "access" or not claims.get("sub"):
        raise AuthError("Invalid access token")
    return str(claims["sub"]), token


def public_view(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": profile["user_id"],
        "display_name": profile.get("display_name", ""),
        "public_bio": profile.get("public_bio", ""),
        "avatar_url": profile.get("avatar_url", ""),
        "program": profile.get("program", ""),
        "graduation_year": profile.get("graduation_year"),
        "organization_access": False,
    }


def organization_view(
    profile: dict[str, Any], shared_organization_ids: list[int]
) -> dict[str, Any]:
    return {
        **public_view(profile),
        "organization_access": True,
        "organization_bio": profile.get("organization_bio", ""),
        "shared_organization_ids": shared_organization_ids,
    }


def parse_int(name: str, minimum: int, maximum: int | None = None) -> int | None:
    raw = request.args.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is out of range")
    return value


def matches_query(terms: list[str], haystacks: list[str]) -> bool:
    """Every term must appear in at least one searchable field."""
    text = " ".join(haystacks).casefold()
    return all(term in text for term in terms)


@app.get("/search")
def search():
    try:
        viewer = viewer_from_request()
    except AuthError as exc:
        return error(str(exc), 401)

    query = request.args.get("q", "").strip()
    if len(query) > MAX_QUERY_LENGTH:
        return error(f"q must be at most {MAX_QUERY_LENGTH} characters")
    program_filter = request.args.get("program", "").strip().casefold()
    try:
        page = parse_int("page", 1) or 1
        per_page = parse_int("per_page", 1, MAX_PER_PAGE) or DEFAULT_PER_PAGE
        year_filter = parse_int("graduation_year", 1900, 2200)
        organization_filter = parse_int("organization_id", 1)
    except ValueError as exc:
        return error(str(exc))

    wants_org_filter = bool(
        program_filter or year_filter is not None or organization_filter is not None
    )
    if wants_org_filter and viewer is None:
        return error("Log in to filter by program, year, or organization", 401)

    try:
        profiles = clients.fetch_all_profiles()
        # user_id -> ids of the viewer's organizations that user belongs to
        shared: dict[str, list[int]] = {}
        viewer_organizations: list[dict[str, Any]] = []
        if viewer is not None:
            viewer_id, access_token = viewer
            viewer_organizations = clients.fetch_viewer_organizations(access_token)
            for organization in viewer_organizations:
                member_ids = clients.fetch_organization_member_ids(
                    access_token, organization["id"]
                )
                for member_id in member_ids:
                    shared.setdefault(member_id, []).append(organization["id"])
            shared.setdefault(viewer_id, [])
    except UpstreamError as exc:
        return error(str(exc), 503)

    viewer_org_ids = {organization["id"] for organization in viewer_organizations}
    if organization_filter is not None and organization_filter not in viewer_org_ids:
        return error("You are not a verified member of that organization", 403)

    terms = query.casefold().split()
    visible: list[dict[str, Any]] = []
    for profile in profiles:
        if not str(profile.get("display_name", "")).strip():
            continue  # blank profiles are noise in a people finder
        user_id = str(profile["user_id"])
        if viewer is not None and user_id in shared:
            visible.append(organization_view(profile, sorted(shared[user_id])))
        else:
            visible.append(public_view(profile))

    # Filter options come from everything the viewer can see, not just the
    # current results, so the dropdowns stay stable while filtering.
    programs = sorted(
        {r["program"] for r in visible if r["organization_access"] and r["program"]},
        key=str.casefold,
    )
    years = sorted(
        {
            r["graduation_year"]
            for r in visible
            if r["organization_access"] and r["graduation_year"] is not None
        }
    )

    results: list[dict[str, Any]] = []
    for result in visible:
        if wants_org_filter:
            if not result["organization_access"]:
                continue
            if program_filter and result["program"].casefold() != program_filter:
                continue
            if year_filter is not None and result["graduation_year"] != year_filter:
                continue
            if (
                organization_filter is not None
                and organization_filter not in result["shared_organization_ids"]
            ):
                continue
        if terms:
            searchable = [result["display_name"], result["public_bio"]]
            if result["organization_access"]:
                searchable += [result["program"], result["organization_bio"]]
            if not matches_query(terms, searchable):
                continue
        results.append(result)

    results.sort(key=lambda r: (r["display_name"].casefold(), r["user_id"]))
    total = len(results)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    return jsonify(
        {
            "results": results[start : start + per_page],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "authenticated": viewer is not None,
            "filters": {
                "organizations": [
                    {"id": o["id"], "name": o["name"]} for o in viewer_organizations
                ],
                "programs": programs,
                "graduation_years": years,
            },
        }
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5006")))
