# Deploy InkLoom AI on Render and Neon

The application can run as one FastAPI web service: the Docker image builds
the React/Vite frontend, FastAPI serves its static files and client-side routes,
and `/api/*` plus the authenticated collaboration WebSocket stay on the same
HTTPS origin. This keeps the `SameSite=Strict`, `HttpOnly` session cookie
first-party without relaxing cookie or origin checks.

The repository does not create hosting resources or guarantee provider pricing.
Choose free plans only; provider plan names, quotas, and availability can
change. Do not enable paid add-ons or enter a paid commitment. Render's free
web services may sleep when idle, and their local filesystems are ephemeral.
User uploads are stored in the database; use Neon PostgreSQL rather than local
SQLite for persistent deployment.

## What the image does

- The first Docker stage runs `npm ci` and `npm run build`.
- The second stage installs `backend/requirements.txt`, copies the built
  frontend to `backend/app/static`, and runs one Uvicorn process.
- Uvicorn binds to `0.0.0.0` and uses Render's injected `PORT` (fallback
  `10000` for local Docker use).
- FastAPI serves frontend assets and SPA routes. Unknown `/api`, health,
  documentation, and missing asset paths remain 404s; API and WebSocket routes
  are not rewritten to the SPA.
- `AUTH_COOKIE_SECURE=true` enables secure cookies behind Render HTTPS.
- Configured `CORS_ORIGINS` is an exact allowlist. When set, local development
  origins are not added. Leave it empty only for local development.

## 1. Create a Neon PostgreSQL database

1. Sign in to Neon and create a project using its free option. Select a region
   close to the Render service.
2. Create or use the project's default database and role.
3. In the Neon dashboard, open **Connect** and copy a PostgreSQL connection
   string. Keep it private; do not paste it in chat, source code, or a
   committed `.env` file.
4. Confirm the connection string includes `sslmode=require`. InkLoom converts
   `postgres://` and `postgresql://` schemes to the installed `psycopg` SQLAlchemy
   driver; PostgreSQL query options such as `sslmode=require` are passed through.
5. Keep the connection string available for the Render secret setting in the
   next section. Never use a local SQLite URL for a hosted deployment.

The startup path creates missing tables and applies the repository's existing
additive, idempotent schema updates. It does not drop tables or reset data.
Back up existing databases before deploying schema changes. The first Render
startup must be allowed to complete its migration before another instance or
deployment is started.

## 2. Create the Render web service

1. In Render, choose **New → Web Service**, connect the personal repository
   `ssundargosai-arch/InkLoom-AI`, and select branch `round3-development`.
2. Choose **Docker** as the runtime and the free instance option. Set the
   Docker build context to the repository root and use the root `Dockerfile`.
   Do not set a separate build or start command; the Dockerfile builds and
   starts the application.
3. Do not add a persistent disk: application uploads are stored in PostgreSQL,
   while generated/static files are part of the image.
4. Add the environment variables below in Render's environment settings. Enter
   secret values directly in Render; do not place them in source files or share
   them in chat.
5. If the service settings show a health-check path, set it to
   `/api/health`.
6. Create the service and wait until the first deployment is healthy. Copy its
   HTTPS URL, such as `https://<service-name>.onrender.com`. Use that exact
   origin (scheme and hostname, no trailing slash) for both origin settings.

### Required Render environment variables

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | The private Neon connection string, with `sslmode=require`. |
| `BOOTSTRAP_ADMIN_EMAIL` | The initial administrator's email address. |
| `BOOTSTRAP_ADMIN_PASSWORD` | A new, unique password of at least 12 characters. Store it as a secret. |
| `AUTH_COOKIE_SECURE` | `true` |
| `CORS_ORIGINS` | The exact Render HTTPS origin, e.g. `https://<service-name>.onrender.com`. |
| `PASSWORD_RESET_BASE_URL` | The same exact Render HTTPS origin. |

Render supplies `PORT`; do not hardcode a port. The frontend is built with
`VITE_API_BASE_URL` empty and `VITE_MOCK_API=false`, so production API requests
and WebSocket connections use the service's own origin. Do not set
`VITE_API_BASE_URL` to another host for this deployment.

Optional model, external search, OCR, and SMTP settings are not required for
the application to run. Configure only providers you intentionally use, with
their credentials entered as Render secrets. If SMTP is not configured, email
invitation and password recovery features remain unavailable.

## 3. Bootstrap the first Admin securely

On startup, the app creates the configured Admin only if the database has no
users. It does not create or reset an account when any user already exists.
After Render reports the service healthy:

1. Open `https://<service-name>.onrender.com/api/health` and confirm
   `"status": "ok"`.
2. Open the Render service URL, sign in with the bootstrap Admin email and
   password, and verify the Admin role.
3. Remove `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` from Render
   after confirming the account. Removing them prevents accidental bootstrap
   attempts on later startups; the existing account is unchanged.
4. If the deployment fails before account creation, review service logs and
   Neon connectivity before retrying. Do not reset a database with existing
   data.

## Local Docker check

From the repository root:

```sh
docker build -t inkloom-ai .
docker run --rm -p 10000:10000 \
  -e PORT=10000 \
  -e DATABASE_URL='sqlite:////tmp/inkloom-local.db' \
  -e AUTH_COOKIE_SECURE=false \
  -e CORS_ORIGINS=http://localhost:10000 \
  -e BOOTSTRAP_ADMIN_EMAIL=admin@example.test \
  -e BOOTSTRAP_ADMIN_PASSWORD='replace-with-a-unique-local-password' \
  -e PASSWORD_RESET_BASE_URL=http://localhost:10000 \
  inkloom-ai
```

Use only disposable local credentials and data for this check. The mounted
SQLite database is ephemeral; do not use this command's database setting for
production. The local Docker check does not configure HTTPS or verify
production cookie behavior.

## Release and live checks

Run before deployment:

```sh
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run test:utils
cd frontend && npm run build
git diff --check
docker build -t inkloom-ai .
```

After deployment, verify:

1. The Render HTTPS URL loads the frontend, including a direct refresh on a
   nested route such as `/reviews`.
2. `/api/health` returns `200` and `{"status":"ok", ...}`.
3. Sign-in sets an `HttpOnly`, `Secure`, `SameSite=Strict` session cookie;
   login and logout both work over HTTPS.
4. Admin, Reviewer, and Contributor API permissions remain enforced.
5. Guideline, Brand Voice, evidence-source, analysis, review, and analytics
   workflows respond successfully.
6. An authorized review collaboration WebSocket connects through the same
   host. Collaboration presence is process-local; keep one service instance
   and one Uvicorn worker.
7. Restart the service and confirm PostgreSQL data remains. Do not test this
   by deleting or resetting the production database.

## Operational limitations

- This repository can prepare and test the deployment image, but an account
  owner must create Neon and Render resources and authorize repository access.
- Free hosting quotas, cold starts, sleeping, and provider availability are
  controlled by the providers and may change.
- Existing startup schema updates are application code rather than a separate
  migration CLI. Review them and back up any populated production database
  before release.
- WebSocket collaboration uses process-local state and requires a single
  backend process/instance for consistent presence.
- Uploads are stored as private database BLOBs; the application does not
  provide a retention policy or encryption-at-rest guarantee.
- Real external LLM, email, and search behavior requires separately configured
  providers and credentials. Rule-based analysis is available without them.
- OCR remains disabled by default. The image includes the Python OCR adapter
  but not the system Tesseract executable; enabling `OCR_ENABLED` requires
  extending the image with Tesseract.
