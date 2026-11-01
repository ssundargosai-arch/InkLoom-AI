# InkLoom AI

InkLoom AI is a brand-governance workspace that reviews content against configured brand guidelines and approved evidence before publication. It combines deterministic checks with optional, explicitly configured AI services and keeps final decisions with human reviewers.

## Current capabilities

- Brand guideline management and review-specific guideline selection.
- Content analysis for terminology, tone, promotional claims, factual claims, and supported image checks.
- Approved evidence-source ingestion and review; pending or rejected sources are excluded from analysis.
- Claim-level `verified`, `contradicted`, and `unverified` advisory statuses with evidence excerpts when available.
- Optional OpenAI-compatible LLM analysis, embeddings, and consent-based external search; these providers are not required for local deterministic checks.
- Human review queue, comments, revisions, approval decisions, activity history, and analytics.
- Admin, Reviewer, and Contributor roles, invite-only account activation, session cookies, and password recovery when SMTP is configured.
- Explicit mock mode for UI development, visibly labeled and not suitable for a secured workspace.

## Run locally on macOS

Use two terminals. Python 3.9+ and Node.js 18+ are required.

### 1. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` and set a unique `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` (at least 12 characters). Keep `.env` private:

```bash
chmod 600 .env
uvicorn app.main:app --reload
```

The first Admin is created only when the configured database contains no users. Existing accounts are not reset or replaced. Local API documentation is at `http://localhost:8000/docs`.

For a separate local development database and interactive Admin setup, see `backend/README.md` and run `python run_local.py` from `backend` instead.

### 2. Start the frontend

In a second terminal:

```bash
cd frontend
npm ci
cp .env.example .env
npm run dev
```

Open `http://localhost:5173`. Use the same hostname (`localhost`) for the frontend and API during local development because authentication uses an HttpOnly cookie.

### 3. Run checks

Backend tests use an in-memory SQLite database:

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

Frontend helper tests use Node's built-in test runner and require no extra test dependency:

```bash
cd frontend
npm run test:utils
npm run build
```

## Important trust and security notes

- Findings are advisory; they are not legal advice, a complete accessibility audit, or proof that a factual claim is true or false.
- `verified` means a configured source matched the current heuristic. Review source scope, date, and context before publication.
- External search is optional and only runs when configured and explicitly requested. Search snippets are candidate evidence, not proof.
- Uploaded image checks use local visual heuristics; they do not constitute a trained visual brand-compliance model.
- Do not commit `.env` files, API keys, local database files, or real customer content.
- Mock mode disables real authentication and role enforcement and must not be used for a secured demo or production deployment.
- Before deployment, use HTTPS, set `AUTH_COOKIE_SECURE=true`, configure explicit trusted origins and secrets, and perform a deployment-specific security review.

For full configuration, role descriptions, endpoint details, and known limitations, read [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md).

For the single-origin Docker deployment on Render with persistent Neon
PostgreSQL, follow [`DEPLOYMENT.md`](DEPLOYMENT.md).
