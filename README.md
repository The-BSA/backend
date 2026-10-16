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
