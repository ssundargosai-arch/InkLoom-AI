# Deployment guide

## Deployment status

This repository does not currently select or configure a hosting provider. It
contains no provider manifest, production frontend origin, backend origin, or
production database URL. Choose a provider and provision the required resources
before following the release steps below. Do not treat the default SQLite
database as production-persistent unless the selected host explicitly provides
a persistent disk and reliable backups.

## Recommended topology

- One FastAPI backend instance, with WebSocket support enabled.
- A managed PostgreSQL database with automated backups and persistent storage.
- A static frontend host serving `frontend/dist` and falling back to
  `index.html` for client-side routes.
- Frontend and API on HTTPS origins under the same site, for example
  `https://app.example.com` and `https://api.example.com`. The session cookie
  uses `SameSite=Strict`; unrelated sites can prevent browser authentication
  cookies from being sent.

WebSocket collaboration uses process-local state. Keep the backend to one
process/instance unless collaboration is redesigned to use shared state.

The default Vercel `*.vercel.app` and Render `*.onrender.com` hostnames are
different sites. Pointing `VITE_API_BASE_URL` directly at the Render hostname
from the default Vercel hostname is not a valid production authentication
setup with the current `SameSite=Strict` cookie. Use frontend and API
subdomains under the same registrable domain (for example, an already-owned
domain), or provide a verified same-origin proxy that supports both the API
and WebSocket upgrade route. Test the actual browser cookie and WebSocket
behavior before considering deployment complete. Do not weaken cookie policy
as a shortcut.

## Backend

Install the checked-in Python dependencies in the backend directory:

```sh
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure these values in the hosting provider's secret/environment settings.
Do not commit credentials or production `.env` files.

Required for a secured deployment:

- `DATABASE_URL`: persistent PostgreSQL SQLAlchemy URL, such as
  `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require`.
- `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`: set together to
  provision the initial Admin only when the database has no users. Use a unique
  password and remove or rotate the bootstrap secret after provisioning as
  appropriate for the host's operational model. Existing users are not reset.
- `CORS_ORIGINS`: comma-separated, exact trusted frontend origins, for example
  `https://app.example.com`.
- `AUTH_COOKIE_SECURE=true`: required when serving over HTTPS.
- `PASSWORD_RESET_BASE_URL`: the exact HTTPS frontend origin, for example
  `https://app.example.com`.
- `PORT`: use the port assigned by the hosting provider.

Optional settings should remain unset unless intentionally enabled and reviewed:

- LLM: `LLM_PROVIDER`, `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.
- Embeddings: `EMBEDDING_MODEL` (uses the configured compatible provider).
- External search: `FACT_CHECK_PROVIDER`, `FACT_CHECK_API_KEY`,
  `TRUSTED_SOURCE_DOMAINS`.
- SMTP invitations/recovery: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_STARTTLS`, `SMTP_USE_SSL`.
- Visual analysis: `OCR_ENABLED`, `BRAND_PALETTE`, `PALETTE_TOLERANCE`,
  `BRAND_ASSET_REFERENCE_PATHS`, `BRAND_ASSET_SIMILARITY_THRESHOLD`.
- Capacity limits: `MAX_CONTENT_LENGTH`, `MAX_UPLOAD_SIZE`,
  `MAX_SOURCE_UPLOAD_SIZE`, `MAX_SOURCE_LENGTH`, `MAX_IMAGE_PIXELS`,
  `MAX_RETRIEVAL_CHUNKS`.
- Operational/security tuning: `AUTH_SESSION_HOURS`,
  `FRESHNESS_CHECK_INTERVAL_SECONDS`, `RISK_WEIGHT_CRITICAL`,
  `RISK_WEIGHT_HIGH`, `RISK_WEIGHT_MEDIUM`, `RISK_WEIGHT_LOW`,
  `PUBLISH_RISK_MEDIUM_THRESHOLD`, `PUBLISH_RISK_HIGH_THRESHOLD`,
  `PUBLISH_RISK_CRITICAL_THRESHOLD`, `GEMINI_REQUEST_TIMEOUT_SECONDS`.

The app loads environment values from the process first and only fills missing
values from `backend/.env`. Production secrets should be injected by the host;
do not upload a developer `.env` file.

Start one backend process:

```sh
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

The health endpoint is `GET /api/health`. Startup runs `create_all` and
additive, idempotent migrations before the app serves traffic. Back up the
database before deploying a schema-changing release, and avoid concurrent
first-starts against an unmigrated database. The migrations are startup code,
not a separately reviewed migration CLI.

## Frontend

Set the backend's public HTTPS origin at build time. The API base URL is
embedded in the generated frontend bundle and is not a secret.

```sh
cd frontend
npm ci
VITE_API_BASE_URL=https://api.example.com VITE_MOCK_API=false npm run build
```

Publish the contents of `frontend/dist` on a static host configured to serve
`index.html` for application routes. Configure the backend `CORS_ORIGINS` with
that exact frontend origin. `VITE_MOCK_API` must remain `false`; mock mode
disables real authentication and role enforcement.

The current backend CORS configuration also allows the two built-in local
development origins (`http://localhost:5173` and
`http://127.0.0.1:5173`) in addition to configured origins. Review that trust
boundary for the selected production environment.

## Persistence, uploads, and operations

- PostgreSQL is supported through the installed `psycopg` driver. The default
  `sqlite:///./inkloom.db` is a local-development default, not a production
  persistence guarantee.
- Uploaded review files and approved visual assets are stored as private
  database BLOBs. Database backups, capacity, retention, and deletion policies
  therefore include upload data; the app does not provide encryption-at-rest
  guarantees or a retention policy.
- Configure HTTPS at the host/proxy and set `AUTH_COOKIE_SECURE=true`.
- Confirm the host forwards WebSocket upgrades and supports the single-process
  collaboration model.
- Configure SMTP if user invitations or password recovery are part of the demo.
- Configure trusted proxy/IP handling and edge rate limits where required by
  the deployment; forwarded client IP headers are not trusted by default.

## Release checks

Run before deployment:

```sh
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run test:utils
cd frontend && npm run build
git diff --check
```

After deployment, verify `https://api.example.com/api/health`, load the
frontend, sign in over HTTPS, submit one disposable analysis, and establish an
authorized review collaboration WebSocket. Confirm no secrets are present in
the frontend bundle or logs.

## Current limitation

The hosting provider, domain/origins, managed database, and deployment account
are not specified by this repository. Deployment cannot safely proceed until
those resources and authorized access are provided.
