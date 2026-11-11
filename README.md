# backend

## Services

### User service

The user service handles signup, email verification, and login. It runs on
port `5000` by default.

### Authentication service

The authentication service handles credentials, JWT access tokens, rotating
refresh tokens, token revocation, and token introspection. It runs on port
`5002` by default and stores its data in `auth.db` unless `DATABASE_URL` is
configured.

Set `JWT_SECRET` to a long, stable secret in deployed environments. The
authentication service calls the separate email verification service at
`EMAIL_SERVICE_URL` (default `http://localhost:5003`). Set
`EMAIL_SERVICE_TOKEN` to authenticate this internal call; this token is
required by the email verification service. Registration returns
an error instead of creating the account when the email service cannot accept
the message. The authentication service exposes:

- `POST /register` (also available as `POST /signup`) and
  `GET /verify/<token>` for credential registration.
- `POST /login` for access and refresh token issuance.
- `POST /refresh` for refresh-token rotation.
- `POST /logout` to revoke a refresh token.
- `GET /introspect` with an `Authorization: Bearer <access-token>` header.

### Student organizations service

The student organizations service runs on port `5004` and lets users belong to
multiple organizations after verifying a matching school email address. It
uses the auth service's JWT secret and issuer to identify users, but does not
store passwords or duplicate auth users.

Set `JWT_SECRET`, `JWT_ISSUER`, `EMAIL_SERVICE_URL`, `EMAIL_SERVICE_TOKEN`, and
`SERVICE_URL` in the service environment. Set `FRONTEND_URL` (default
`http://localhost`) so the verification email links to the site's
`/verify-organization/<token>` page, which calls `GET /verify/<token>`; leave it
empty to link straight to this service instead. Optionally set `CORS_ORIGINS`
(comma-separated; defaults to the local frontend) to choose which browser origins
may call `POST /memberships`, `GET /organizations`, `GET /verify/<token>` and
`GET /me/...`. Personal email providers such as gmail.com are rejected, because
they can't show that someone belongs to a school. It exposes:

- `POST /memberships` to add a school email. An organization is created
  automatically from the email domain when needed.
- `POST /organizations` to manually create an organization when custom
  metadata is needed.
- `GET /organizations` to list available organizations.
- `POST /organizations/<organization_id>/memberships` remains available for
  adding an email to a known organization.
- `GET /verify/<token>` to complete school-email verification.
- `GET /me/organizations` and `GET /me/memberships` to view the current user's
  verified organizations and membership records.
- `GET /organizations/<organization_id>/members` for verified members to list
  other verified members.

### Profiles service

The profiles service runs on port `5005`. Each user has one profile record
with public fields and organization-only fields. Public fields can be viewed
without membership; organization-only fields require the viewer and profile
owner to share a verified organization.

Set `JWT_SECRET`, `JWT_ISSUER`, `ORGANIZATION_SERVICE_URL`, and
`ORGANIZATION_SERVICE_TOKEN`. Set `PROFILES_SERVICE_TOKEN` to let trusted
services (the search service) list profiles. Optionally set `CORS_ORIGINS`
(comma-separated; defaults to the local frontend) to choose which browser
origins may call the read-only `/profiles/...` endpoints and `PUT /me/profile`. The service exposes:

- `PUT /me/profile` to create or update the authenticated user's profile.
- `GET /profiles/<user_id>` for public profile fields.
- `GET /profiles/<user_id>/organization` for organization-only fields.
- `GET /internal/profiles?limit=&offset=` returns full profiles (including
  organization-only fields) to trusted services. It requires the
  `X-Internal-Token` header to match `PROFILES_SERVICE_TOKEN`; callers must
  apply their own visibility rules.
- `GET /health` for health checks.

### Search service

The search service runs on port `5006`. It finds students by name or keyword
and applies the same visibility rules as the profiles service. It stores no
data of its own: it reads profiles from the profiles service and uses the
viewer's own access token to ask the organizations service which verified
organizations they share with each student.

Set `JWT_SECRET`, `JWT_ISSUER`, `PROFILES_SERVICE_URL` (default
`http://localhost:5005`), `PROFILES_SERVICE_TOKEN` (must match the profiles
service), `ORGANIZATION_SERVICE_URL` (default `http://localhost:5004`), and
optionally `CORS_ORIGINS` (comma-separated; defaults to the local frontend).

- `GET /search` searches students. Anonymous requests search public fields
  (display name and public bio). Requests with an `Authorization: Bearer
  <access-token>` header also see organization-only fields (organization bio,
  program, graduation year) for students who share a verified organization,
  and may filter on them. An invalid token is rejected with `401` rather than
  silently downgraded. Query parameters:
  - `q`: keywords; every word must match the name, bio, or (where visible)
    program or organization bio.
  - `program`, `graduation_year`, `organization_id`: filters on
    organization-only fields (login required; the viewer must belong to the
    organization).
  - `page` (default `1`) and `per_page` (default `12`, max `50`).

  The response contains `results`, paging fields (`page`, `per_page`, `total`,
  `total_pages`), `authenticated`, and `filters` (the organizations, programs,
  and graduation years the viewer can filter by). Profiles with no display
  name are not listed.
- `GET /health` for health checks.

### Email verification service

The email verification service owns SMTP delivery and runs on port `5003` by
default. Configure `SMTP_HOST`, `SMTP_FROM`, and optionally `SMTP_PORT`
(default `587`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS` (default
`true`), and `VERIFICATION_BASE_URL` (default
`http://localhost:5002/verify`). It exposes:

- `POST /send-verification`, called internally by the authentication service.
- `GET /health` for service health checks.

### Authorization service

The authorization service handles platform roles and permissions independently
from user identity. It runs on port `5001` by default and stores its data in
`authorization.db` unless `DATABASE_URL` is configured.

The service exposes these endpoints:

- `POST /roles` and `GET /roles` to manage roles.
- `POST /permissions` and `GET /permissions` to manage permissions.
- `POST /roles/<role_id>/permissions` to grant a permission to a role.
- `POST /subjects/<subject_id>/roles` to assign a role to a subject.
- `GET /subjects/<subject_id>/permissions` to list effective permissions.
- `POST /authorize` to check whether a subject may perform an action on a
  resource.

Subject IDs are opaque strings so the service can authorize users or other
platform principals without coupling its database to the user service.
