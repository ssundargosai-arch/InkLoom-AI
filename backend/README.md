# InkLoom AI backend

FastAPI API for brand guidelines, approved evidence, content analysis, collaborative human review, activity history, and analytics. Local deterministic rules are the default. Optional OpenAI-compatible or Google Gemini chat models can add advisory findings when explicitly configured.

## Requirements and setup

Python 3.9+ is supported by this implementation.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Set BOOTSTRAP_ADMIN_EMAIL and a unique BOOTSTRAP_ADMIN_PASSWORD in .env before starting.
chmod 600 .env
uvicorn app.main:app --reload
```

### Start an isolated local workspace

To avoid using or changing an existing `inkloom.db`, start a separate development database and enter a local Admin credential interactively:

```bash
cd backend
.venv/bin/python run_local.py
```

The launcher prompts for an Admin email and a password twice; password input is hidden and neither value is written to a file or printed. It uses `inkloom-local-dev.db`, leaving the configured database untouched. Start the frontend separately with `cd frontend && npm run dev`; its default API URL is `http://localhost:8000`. Stop any other API already using port 8000 before starting this local instance. Use the Admin email/password entered at the prompts to sign in. SMTP invitations remain unavailable unless SMTP is separately configured.

Swagger UI is available at `http://localhost:8000/docs`, with OpenAPI JSON at `/openapi.json`. SQLite is created in the backend working directory by default. Configure its location using `DATABASE_URL`.

Authentication is enabled by default. On an empty user database, set `BOOTSTRAP_ADMIN_EMAIL` and a unique `BOOTSTRAP_ADMIN_PASSWORD` of at least 12 characters in `backend/.env`; the first account is created as an administrator at startup. The API loads this file by its path relative to the backend source, independent of the shell's current directory, without overriding environment variables already supplied by the process. Restrict the file to the owner (`chmod 600 .env`); do not commit it or reuse a development password. Bootstrap is intentionally create-only: if any user already exists, it will neither add another bootstrap administrator nor reset an existing account's password. For a database with existing users, sign in with an existing active Admin account. Admins invite accounts from **Admin dashboard → Invite user**; each recipient sets their own password through a single-use email link.

## Configuration

- `DATABASE_URL`: SQLAlchemy database URL; defaults to `sqlite:///./inkloom.db`.
- `CORS_ORIGINS`: comma-separated explicit frontend origins, loaded from `backend/.env` unless already set in the process environment. The two local Vite origins (`http://localhost:5173` and `http://127.0.0.1:5173`) are always included; configured origins are added to them. Credentialed requests are enabled, so wildcard origins are rejected.
- `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`: initial admin account for a new database; both are required together. Bootstrap will not add another admin once any account exists.
- `AUTH_COOKIE_SECURE`: set `true` when served over HTTPS (default `false` for local HTTP development).
- `AUTH_SESSION_HOURS`: absolute session lifetime in hours (default 12).
- Login protection: five failed attempts per email/IP pair, twenty per email, or thirty per IP in a rolling 15-minute window. Blocked requests return `429` with a `Retry-After` header. Failed-attempt identifiers are stored as SHA-256 fingerprints in the configured database. Forwarded IP headers are not trusted by default; configure trusted-proxy handling at the deployment edge before placing the API behind a proxy.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: configure outbound recovery email. Username/password must be configured together; host and sender are also required together. SMTP requires STARTTLS (`SMTP_STARTTLS=true`, default) or implicit TLS (`SMTP_USE_SSL=true`); plaintext transport is rejected.
- `PASSWORD_RESET_BASE_URL`: frontend origin used to build reset links (default `http://localhost:5173`). Configure the trusted HTTPS frontend origin in deployment; credentials, query strings, and fragments are not accepted.
- Invitation links use the same SMTP and frontend-origin settings as password recovery. They expire after 48 hours. Resending an invitation revokes previous outstanding links.
- `MAX_CONTENT_LENGTH`: maximum UTF-8 text body size in bytes (default 100,000).
- `MAX_UPLOAD_SIZE`: maximum image/PDF or visual-asset upload size in bytes (default 10 MiB).
- `MAX_SOURCE_UPLOAD_SIZE`: maximum source-document upload size in bytes (default 10 MiB).
- `MAX_SOURCE_LENGTH`: maximum extracted source text size in bytes (default 200,000).
- `MAX_IMAGE_PIXELS`: positive integer image dimension guard (default 40 million pixels).
- `OCR_ENABLED`: `true` to attempt OCR. `pytesseract` is installed from requirements, but the Tesseract executable must also be installed on the host (for example, `brew install tesseract` on macOS). OCR failures are reported in `image_analysis.limitations`.
- `BRAND_PALETTE`: optional comma-separated list of approved six-digit hex colours (with or without `#`). Leave empty until the actual brand palette is confirmed.
- `PALETTE_TOLERANCE`: integer approximate RGB distance threshold from 0 to 441 for the visual palette heuristic (default 36).
- `BRAND_ASSET_REFERENCE_PATHS`: optional comma-separated local paths to up to five actual approved PNG/JPEG/WEBP brand assets. There are no bundled reference assets; configure only existing approved files and restrict filesystem access appropriately.
- `BRAND_ASSET_SIMILARITY_THRESHOLD`: similarity percentage below which the backend emits an advisory that the upload may be a different asset variant (default 72).
- `LLM_PROVIDER`: `openai` (default) or `gemini`. The OpenAI path remains the existing OpenAI-compatible Chat Completions integration.
- `GEMINI_REQUEST_TIMEOUT_SECONDS`: Gemini request timeout in seconds (default 90, valid range 1–300). Connection establishment remains bounded to at most 8 seconds. One retry is made only after a transport timeout or connection error; non-transient HTTP/API errors are not retried. A retry can result in a second provider request if the first timed out after reaching Google.
- Gemini uses Google's native `POST /models/{model}:generateContent` endpoint with the `x-goog-api-key` header, `responseMimeType=application/json`, a JSON response schema, and a 1,200-token output cap. OpenAI-compatible Gemini Chat Completions are documented, but their feature coverage for this application's strict schema and output-limit fields is not explicit; the native adapter avoids assuming those mappings. Provider timeouts, errors, refusals, malformed or unsupported responses leave deterministic findings intact. Accepted model findings are marked `AI-generated suggestion (configured LLM)` and are advisory, not verified evidence or an approval decision. Leave chat credentials/model blank for local deterministic rules. The configured chat provider receives submitted content and guideline context; assess its data handling before enabling it.
- `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`: configure all three with `LLM_PROVIDER` to enable optional chat analysis. For OpenAI, use `https://api.openai.com/v1` and select a model that supports Chat Completions, strict JSON Schema output, and the request's output-token limit. For Gemini, use `https://generativelanguage.googleapis.com/v1beta`, a Gemini API key, and a model that supports `generateContent` structured JSON output. The current Google catalog and OpenAI-compatibility docs list `gemini-3.8-flash`; Google's pricing currently lists a free tier for this model, but free-tier access and quotas depend on the Google project and can change. Google may use free-tier content to improve its products; review its current [pricing](https://ai.google.dev/gemini-api/docs/pricing), [model catalog](https://ai.google.dev/gemini-api/docs/models), [API key guidance](https://ai.google.dev/gemini-api/docs/api-key), and [data terms](https://ai.google.dev/gemini-api/terms) before sending content.
- Gemini uses Google's native `POST /models/{model}:generateContent` endpoint with the `x-goog-api-key` header, `responseMimeType=application/json`, a JSON response schema, and a 1,200-token output cap. OpenAI-compatible Gemini Chat Completions are documented, but their feature coverage for this application's strict schema and output-limit fields is not explicit; the native adapter avoids assuming those mappings. Provider timeouts, errors, refusals, malformed or unsupported responses leave deterministic findings intact. Accepted model findings are marked `AI-generated suggestion (configured LLM)` and are advisory, not verified evidence or an approval decision. Leave chat credentials/model blank for local deterministic rules. The configured chat provider receives submitted content and guideline context; assess its data handling before enabling it.
- Consult OpenAI's current [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat) and [model catalog](https://developers.openai.com/api/docs/models) before selecting an OpenAI model; endpoint and parameter compatibility vary by model.
- `EMBEDDING_MODEL`: optional OpenAI-compatible `/embeddings` model name. Configure this with the OpenAI-compatible URL and key; it can be enabled without chat analysis. Gemini chat does not switch the embedding endpoint: lexical retrieval stays active when `LLM_PROVIDER=gemini`, even if an embedding model is configured. OpenAI embedding mode sends factual excerpts and selected approved-source chunks to the configured provider and caches source chunk embeddings in the application database.
- `MAX_RETRIEVAL_CHUNKS`: positive integer maximum source chunks considered per analysis (default 200). Text is split into overlapping 1,000-character chunks.
- `FRESHNESS_CHECK_INTERVAL_SECONDS`: interval for the persisted background freshness checker (default 86,400 seconds; minimum 60). The first check starts within 60 seconds of API startup. A database lease prevents multiple API workers from processing a scheduled or manual check concurrently.
- `RISK_WEIGHT_CRITICAL`, `RISK_WEIGHT_HIGH`, `RISK_WEIGHT_MEDIUM`, `RISK_WEIGHT_LOW`: deterministic base finding weights (defaults 30, 18, 8, and 3). Evidence status and confidence adjust the finding contribution; overlapping findings are grouped and only the highest contribution in each group is counted.
- `PUBLISH_RISK_MEDIUM_THRESHOLD`, `PUBLISH_RISK_HIGH_THRESHOLD`, `PUBLISH_RISK_CRITICAL_THRESHOLD`: increasing score thresholds from 0 to 100 (defaults 20, 45, and 70). Invalid threshold ordering prevents startup.
- `FACT_CHECK_PROVIDER`, `FACT_CHECK_API_KEY`, `TRUSTED_SOURCE_DOMAINS`: optional Brave Search integration. Set the provider to `brave`, configure its API key, and provide a comma-separated allowlist of bare DNS domains (no scheme, path, wildcard, or port). External lookup remains off unless the provider, key, and allowlist are present and the user explicitly opts in on the analysis page; only detected claim excerpts are sent. Search results outside the configured domains are discarded.

Visual analysis and visual-asset uploads accept PNG, JPEG, WEBP, and PDF. Each upload is limited by `MAX_UPLOAD_SIZE` (10 MiB by default); PDFs are limited to 100 pages, 20 inspected embedded images, 10 MiB per extracted image, and 50 MiB of cumulative extracted image data. Uploaded review files and approved-asset-library files are stored as private database BLOBs so authenticated reviewers can inspect the submitted original. Review attachment delivery is authenticated and uses a server-generated filename; filesystem paths are not exposed. Plan database capacity, encrypted backups, retention, and deletion policies accordingly. This MVP does not provide encryption-at-rest guarantees or a retention policy.

Factual verification compares detected numeric and promotional claims only with source documents explicitly approved by an Admin or Reviewer. New sources and legacy sources discovered during the additive startup migration are pending until reviewed; approval decisions retain the reviewer, timestamp, optional note, and decision history. Pending or rejected sources cannot be selected for analysis or retrieved as evidence. The optional external lookup uses Brave Search only after per-analysis user consent, sends extracted claim text (not the complete draft or image), and only accepts results whose host matches `TRUSTED_SOURCE_DOMAINS`. Provider results are stored as candidate citations with the review and never count as organisational proof. Claim comparison is conservative and deterministic: meaningful claim terms, detected values, polarity, and source validity are compared at sentence level. Similarity alone cannot mark a claim supported. Results remain advisory heuristics; every publication decision remains with a human reviewer. An external-provider failure leaves the claim unverified and does not block the regular analysis.

The optional embedding path requests embeddings from the configured OpenAI-compatible provider, caches source-chunk vectors in SQL, and ranks the bounded candidate set with cosine similarity in the application. This is not a dedicated vector database integration; for this single-workspace application's current bounded source set, it avoids an additional operational service while retaining the existing lexical fallback. Neither lexical nor semantic similarity alone establishes factual support.

Existing source records are migrated additively and marked pending; re-approve only after checking their provenance. Previously saved analyses remain historical snapshots and are not recalculated by this migration. Re-run any pre-migration analysis before relying on its claim status.

### Authentication and roles

- Sessions use opaque random tokens in `HttpOnly`, `SameSite=Strict` cookies; only SHA-256 token digests are stored in the database. Passwords are hashed with PBKDF2-HMAC-SHA256.
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, and `POST /api/auth/password` handle session and password operations.
- Admins can list members, invite accounts, resend pending invitations, and update account roles/status at `/api/auth/users`. Invitation creation and resend require SMTP configuration. Invited accounts remain inactive until a recipient accepts the 48-hour single-use link and sets a password of at least 12 characters; the database stores only the token digest. Invitation links and passwords are never returned by the API or written to application audit records/logs. Account creation, resend, acceptance, and updates create account audit events.
- `POST /api/auth/invitations/accept` accepts `{"token":"...","new_password":"..."}` and activates the account with the role selected by the Admin. Public self-registration is not implemented.
- **Admin** can manage users, guidelines and evidence sources, approve/reject evidence, analyze content, and manage reviews.
- **Reviewer** can read guidelines/sources, approve/reject evidence, analyze content, and manage review status, comments, and revisions.
- **Contributor** can read workspace materials, submit analyses, add public comments/revisions, and resubmit after changes are requested; only Admins and Reviewers can decide review status or create internal notes.
- **Visual assets:** Admins manage and approve assets; Contributors may submit assets for approval but cannot inspect pending/rejected assets or edit/approve any asset. Reviewers may inspect assets but cannot approve or edit them. Contributors can retrieve only active, approved, currently valid assets.
- Admins can assign or reassign a review to an active Reviewer. This deployment currently has a single workspace and no separate workspace-membership model.
- Review author/reviewer names are taken from the signed-in account, not trusted from client-supplied identity fields.
- Authenticated state-changing requests validate their `Origin`; WebSocket collaboration validates both session and origin. Use the same host name for frontend and API in local development, as configured by `CORS_ORIGINS`.

## API

All endpoints are under `/api`; FastAPI provides interactive schemas at `/docs`.

### Health and guidelines

- `GET /api/health` is public and reports service capabilities without secrets.
- `POST /api/auth/login` accepts `{"email":"...","password":"..."}` and sets the session cookie.
- `POST /api/auth/logout` revokes the current session; `GET /api/auth/me` returns the current account.
- `POST /api/auth/password` accepts `current_password` and a `new_password` of at least 12 characters, then rotates the session.
- `POST /api/auth/password/forgot` accepts `{"email":"..."}` and returns the same generic `202` response for existing and unknown accounts. Recovery requests are limited to three per address and ten per IP per hour; only hashed email/IP fingerprints are stored.
- `POST /api/auth/password/reset` accepts `{"token":"...","new_password":"..."}`. A reset token is stored only as a SHA-256 digest, expires after 20 minutes, is single-use, and revokes the account's active sessions.
- Admin-only `GET/POST /api/auth/users` lists or creates an invited account. `PATCH /api/auth/users/{user_id}` updates its `role` and `is_active`.
- `GET /api/guidelines` → guideline array. Three starter rules are inserted when the database is first initialized.
- `GET /api/guidelines?search=claims&category=Promotional%20Claims&active=true` → searchable/filterable guideline array; categories remain configurable and `GET /api/guidelines/categories` lists configured categories.
- Admin/Reviewer `GET /api/guidelines/diagnostics` returns deterministic, read-only suggestions for a narrow formal-versus-casual directive pattern and separately flags selected subjective wording for clarification. Category is only a grouping hint, scope is reported as unclear, and results require human review; this endpoint does not update guidelines. It does not interpret preferred terms as mandatory or assess arbitrary numeric, formatting, or date constraints.
- Admin `POST /api/guidelines` creates a guideline with examples, severity, terms, and active state. Admin `PATCH /api/guidelines/{guideline_id}` edits/deactivates/reactivates it; every create/edit/activation state is snapshotted. Admin `GET /api/guidelines/{guideline_id}/versions` inspects prior snapshots and editors. The legacy `DELETE` endpoint is retained but now deactivates instead of deleting the guideline.
- Admin/Reviewer `GET /api/guidelines/brand-voice` reads the optional organization configuration; Admin-only `PUT` updates it and `GET /api/guidelines/brand-voice/versions` lists Admin-authored snapshots. When configured, analysis flags exact prohibited expressions and may emit a narrow advisory for colloquial markers under formal/professional tones. Preferred expressions are not mandatory; audience/channel labels and arbitrary messaging principles are not interpreted as rules. Existing reviews are unchanged until explicitly reanalyzed.
- Guidelines include a configurable `review_interval_days` (default 180), last-reviewed actor/time, and a freshness state. Admin `POST /api/guidelines/{guideline_id}/review` records an explicit policy review without rewriting content versions.
- `GET /api/sources?search=pricing&approval_status=approved&active=true` → source records with approval history, provenance, validity, and lifecycle status.
- Admin `POST /api/sources` creates draft or pending evidence with title, description, source type, evidence content, optional guideline/URL, publication date (`source_date`), validity dates (`valid_from`, `valid_until`), and configurable `review_interval_days` (default 90). Legacy `expiry_date` remains accepted and returned as an alias for `valid_until`; legacy `source_date` is copied into `valid_from` when no explicit start date is supplied.
- Admin `PATCH /api/sources/{source_id}` edits or deactivates/reactivates evidence. Editing approved evidence or reactivating inactive evidence resets it to pending approval; changed or deactivated content invalidates saved embeddings.
- `GET /api/sources/{source_id}` inspects an evidence record; Admin `GET /api/sources/{source_id}/versions` inspects content and lifecycle snapshots with editors and timestamps.
- `POST /api/sources/upload` extracts UTF-8 TXT/Markdown or text-bearing PDF to draft or pending evidence (10 MiB and 100-page defaults).
- Admin/Reviewer `PATCH /api/sources/{source_id}/approval` accepts `{"status":"approved"|"rejected","note":"optional reviewer context"}` and records the decision. Reviewers retain the existing approval permission. Only approved, active, currently valid sources may support or contradict claims; expired approved sources can still be surfaced as expired evidence but never as current support.
- Admin/Reviewer `POST /api/sources/{source_id}/verify` records a freshness re-verification of active, approved, currently valid evidence. It does not change approval status and rejects inactive or out-of-window sources.
- Admin-only `DELETE /api/sources/{source_id}` → `204` and deactivates the source without deleting its content, versions, or approval history.
- Admin/Reviewer `GET /api/freshness` returns open alerts, recent run history, and recent resolved-alert history. Admin-only `POST /api/freshness/check` runs a check immediately; Admins and Reviewers can inspect active evidence and guideline alerts.
- Freshness checks detect expired and soon-to-expire active evidence, overdue evidence re-verification, and overdue active guideline reviews. Runs, failures, and alert resolution history are persisted. Scheduled checks run in the API process at the configured interval without blocking the event loop; manual checks do not approve evidence.
- `GET /api/visual-assets` → searchable/filterable visual asset records and lifecycle status. Contributor results include only active, approved, currently valid assets.
- `POST /api/visual-assets` accepts an image/PDF file plus name, category, description, restrictions, and optional validity dates. Admins and Contributors may submit; all uploads start pending.
- `GET /api/visual-assets/{asset_id}` and `GET /api/visual-assets/{asset_id}/file` return metadata or an authenticated preview. Contributors receive `404` for non-approved or invalid assets.
- Admin `PATCH /api/visual-assets/{asset_id}` updates asset metadata or deactivates/reactivates it; edits and reactivation require fresh approval. Admin `PUT /api/visual-assets/{asset_id}/file` replaces the file and resets approval.
- Admin `PATCH /api/visual-assets/{asset_id}/approval` accepts `{"status":"approved"|"rejected","note":"optional reason"}`; a rejection reason is required.

Example create body:

```json
{
  "name": "Preferred product terms",
  "category": "terminology",
  "description": "Use approved product naming.",
  "severity": "medium",
  "prohibited_terms": ["world class"],
  "preferred_terms": ["excellent"],
  "approved_sources": []
}
```

Approved guideline references accept `name`, optional `url`/`reference`, `source_date`, and `expiry_date` (ISO dates). Evidence-library records can be created as JSON text or uploaded with TXT/Markdown/PDF extraction.

### Analysis

`POST /api/analyze` accepts JSON or `multipart/form-data`. JSON fields: `content` (required), `content_type` (default `text`), `title`, `guideline_ids`, `source_ids`, `alt_text`, and optional `allow_external_verification` (default `false`). Multipart accepts the same fields plus an optional PNG/JPEG/WEBP image or PDF `file` and JSON-encoded ID arrays.

```json
{
  "content": "Our product guarantees 100% success for every customer.",
  "content_type": "text",
  "title": "Product campaign",
  "guideline_ids": [],
  "source_ids": [],
  "allow_external_verification": false
}
```

Factual and promotional claim findings include the exact `claim` text and its `claim_start`/`claim_end` offsets in the submitted draft when located, a detection `confidence`, canonical `evidence_status` (`supported`, `unsupported`, `conflicting`, `unverified`, or `expired_evidence`), and real `citations` with source identity and excerpt when relevant evidence is found. The legacy `verification_status` (`verified`, `contradicted`, `conflicting_evidence`, `unverified`, or `expired_evidence`) remains for existing clients. `verification_confidence` measures confidence in the deterministic classification; `evidence_strength` is a separate assessment of the evidence result and is zero for unverified or expired evidence. Explanations include the reason for the status, and suggestions remain advisory. No evidence or partial/irrelevant matches are not treated as proof or as evidence that the claim is false. External lookup is opt-in and reports provider/configuration status in `external_verification`.

The `200` response has a persisted review `id`/`review_id`, `overall_status`, `total_issues`, grouped `summary`, `findings` (also available as `issues`), `analyzed_at`, and optional `image_analysis`. Visual findings remain separate from factual evidence statuses and include a `visual_data` object with page, detected/expected values, detection method, estimated region, and source guideline where available. Original visual files are attached privately to the review; the review payload exposes an authenticated `visual_attachment.url` for the preview. Findings include `category`, `severity`, `title`, `explanation`/`message`, `matched_text`, `suggestion`, `source`/`guideline`, confidence, and pending review status. No-issue analyses are still recorded for human workflow.

Internal citations preserve the source publication date, validity window, approval and last-verification timestamps, source type, retrieval timestamp/method, and relevant excerpt. These fields are copied into the persisted analysis run and remain a historical snapshot if the source is later edited or deactivated.

The deterministic rules identify configured prohibited terms, selected promotional claim heuristics (guarantees, superlatives, savings, performance, comparisons, quantitative statements, and specific capabilities/outcomes), simple factual-looking excerpts, and basic accessibility signals. Claim findings retain source-text offsets; extraction is heuristic and can miss implicit claims or require reviewer interpretation. Source retrieval reports candidate excerpts, source dates, expiry dates, and relevance. Future-dated and expired source material cannot verify a current claim. Without `EMBEDDING_MODEL`, retrieval uses local BM25 lexical ranking. With it, source text is chunked and vectors are cached in SQLite/SQLAlchemy storage; each analysis embeds the factual excerpt and ranks cached chunks by cosine similarity. If embedding retrieval fails, analysis falls back to local BM25 retrieval and returns the failure in `provider_warnings`. If the LLM is explicitly configured, validated structured advisory findings are added to the local rules output; an LLM failure is also reported in `provider_warnings` while deterministic analysis continues. A successful response identifies the analysis and evidence retrieval modes. Candidate matches are never treated as proof or marked verified.

Example OpenAI-compatible semantic retrieval configuration (without enabling LLM analysis):

```dotenv
LLM_API_BASE_URL=https://your-approved-provider.example/v1
LLM_API_KEY=your-provider-key
LLM_PROVIDER=openai
EMBEDDING_MODEL=your-embedding-model
```

Review the embedding provider's retention and training policies before enabling this mode. Query excerpts and selected source chunks are sent to the provider. Cached vectors persist in the same database as the source library; changing the model creates a separate cache.

Example Gemini chat configuration:

```dotenv
LLM_PROVIDER=gemini
LLM_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta
LLM_API_KEY=your-gemini-api-key
LLM_MODEL=gemini-3.8-flash
```

Free-tier access is project-dependent and quotas/model availability can change. Google's current free-tier terms indicate that submitted content may be used to improve products. Do not send sensitive or confidential review content unless your data-handling requirements permit it.

Image analysis validates file extension, declared MIME type, signature/content, integrity, size, dimensions, and PDF page count. It reports dominant colours, aspect ratio/orientation, coarse edge density, transparency margins, and small source dimensions. Configured palette colors and HEX colors found in active visual guideline descriptions/examples are compared using approximate Euclidean RGB distance. Active, approved, date-valid logo/icon assets and any configured local references are compared using a coarse difference hash. If OCR is enabled and the host Tesseract binary is available, extracted text is checked against text rules and word-region colours are compared for a WCAG AA contrast estimate (4.5:1 normal text, 3:1 estimated large text). Contrast checks use the WCAG relative-luminance formula; OCR-region foreground/background and displayed text size remain estimates.

PDFs are inspected page-by-page for text and supported embedded raster images; page numbers are retained. The API explicitly reports pages that could not be visually assessed and per-file/page analysis limits. No PDF renderer is configured, so vector artwork, full page layout, text/background composition, typography, and logo placement are not rasterized or checked. Typography consistency, cropping, distortion, clear space, and semantic imagery checks are not reliable in this local pipeline. Missing image alt text is flagged when the submitter does not provide it; embedded PDF accessibility tags are not fully audited. No automated result certifies brand compliance or WCAG conformance. All findings are advisory and require human review. No external vision service or additional paid dependency is used.

### Review workflow

- `GET /api/reviews?offset=0&limit=20&status=pending` → paginated `{items,total,offset,limit}`.
- Contributors see only reviews they submitted in the queue, detail, comments, revision, activity, and visual-attachment APIs. Admins and Reviewers retain workspace review access.
- `GET /api/reviews/{review_id}` → review with findings, role-filtered comments, immutable revisions, analysis snapshots, assigned reviewers, and version-scoped approval progress.
- `GET /api/reviews/reviewers` (Admin) → active reviewers available for assignment.
- `PATCH /api/reviews/{review_id}/assignment` (Admin) with `{"reviewer_id":12}` or `{"reviewer_id":null}` → assign, reassign, or unassign; the action is recorded in activity.
- `PUT /api/reviews/{review_id}/assignments` (Admin) with `{"reviewers":[{"reviewer_id":12,"stage_number":1},{"reviewer_id":13,"stage_number":2}]}` → configure up to 20 active Reviewers across sequential approval stages. Only the active stage can record decisions; each reviewer can decide once per review.
- `POST /api/reviews/{review_id}/approval-decisions` (assigned Reviewer) with `{"decision":"approved","reason":"Optional context","acknowledge_warnings":false}` → record an approval, rejection, or change request for the current content version. Rejections/change requests require a reason; configured reviewers must approve before the review can become approved. New content revisions start a fresh approval round while preserving prior decisions.
- `POST /api/reviews/{review_id}/approval-bypass` (Admin) with `{"reason":"Documented exception justification","acknowledge_warnings":false}` → record one exceptional approval bypass. A reason is mandatory, existing warning acknowledgement remains enforced, and the initiating Admin and reason are retained with the review.
- `GET /api/reviews/{review_id}/revisions/compare?from_version_id=0&to_version_id={revision_id}` → compare immutable revision snapshots; version `0` is the original analysis submission when available.
- `GET /api/reviews/{review_id}/activity` → application events for submissions, assignments, comments, revisions, decisions, and warning acknowledgements. Internal-note events are hidden from Contributors.
- `PATCH /api/reviews/{review_id}/status` supports `draft`, `submitted`, legacy `pending`, `in_review`, `changes_requested`, `approved`, and `rejected`. Rejection and change requests require a reason; Contributors can resubmit only after changes are requested. Existing approval warning acknowledgement remains required when applicable.
- `POST /api/reviews/{review_id}/comments` with `{"comment":"Please verify the source.","is_internal":false,"parent_id":null}` → `201` comment. Reviewers/Admins may set `is_internal:true`; internal notes and their replies are never returned to Contributors.
- `POST /api/reviews/{review_id}/revisions` with `{"content":"Updated draft","title":"Revision 1"}` → `201` revision without re-analysis; retained for API compatibility.
- `POST /api/reviews/{review_id}/reanalyze` with `{"content":"Updated draft","title":"Revision 1"}` → persists a revision, reruns deterministic rules against approved local evidence, stores a new analysis snapshot, and resets review status to `pending`. Optional LLM and external-search providers are not called.
- `GET /api/reviews/{review_id}/publish-readiness` → explainable heuristic risk score, category breakdown, readiness state (`Ready`, `Ready with Warnings`, `Blocked`, or `Published`), stale-analysis and approval blockers, and evidence/guideline validity.
- `POST /api/reviews/{review_id}/publish` (Admin or authorized Reviewer) → creates one publication record for the current revision when review approval, required current-version reviewer decisions, current analysis, selected guideline status, and cited organisational evidence validity pass. Repeated requests for a published revision return the existing record.
- `POST /api/reviews/{review_id}/publish/override` (Admin) with `{"reason":"Documented exception justification"}` → publish despite eligible finding-risk or evidence-freshness blockers. A justification of at least 10 characters is required. Authentication, review access, review approval, required approval stages, current analysis, and active/approved selected guidelines cannot be overridden.
- `GET /api/reviews/{review_id}/publish-history` → permission-protected publication snapshots and publish-attempt/override audit events. Snapshots retain the revision ID, content hash, risk breakdown, warnings, approval stages, and any override reason.
- Publish records and audit events are initialized by an additive idempotent startup migration; a unique review/revision constraint prevents duplicate publication records. Reviewers must be assigned to a review to publish it when approval assignments are configured. Contributors may inspect readiness/history for their own reviews but cannot publish or override.

Risk values are deterministic heuristic estimates, not verified facts, legal advice, or a substitute for human review. They combine severity weights, evidence-status multipliers, confidence, guideline/visual indicators, and current evidence-freshness penalties. Critical unresolved findings and unsupported high/critical claims block normal publishing; stale analysis, incomplete approvals, and unavailable selected guidelines are non-overridable blockers. The gateway creates an internal publication record only; it does not transmit content to a CMS or external platform.

Lifecycle statuses include `draft`, `submitted`, legacy `pending`, `in_review`, `changes_requested`, `approved`, and `rejected`. Status changes require an authenticated role-authorized user; configured reviewer stages are enforced server-side. Admin bypass does not bypass authentication, role checks, or unresolved-warning acknowledgement.

Approval is blocked with `409` when unresolved critical findings, unsupported claims, or conflicting evidence remain unless the reviewer explicitly acknowledges the returned warnings. Send `{"status":"approved","acknowledge_warnings":true}` to proceed; acknowledgement is recorded in the review activity log with the actor and finding references. The earlier `acknowledge_conflicts` request field remains accepted for existing clients.

`WS /api/reviews/{review_id}/collaboration` validates the session, active account, and origin; Admins/Reviewers may connect, and Contributors may connect only to reviews they submitted. It provides process-local participant presence, typing, ephemeral shared draft text, and broadcasts public comments, status changes, assignments, decisions, bypasses, and revisions. Internal notes are never broadcast. Clients reconnect with backoff and REST endpoints remain available as fallback. Presence and broadcasts are in memory and are not shared across multiple workers/instances. The activity log is append-only through this API, but is not cryptographically immutable.

### Analytics

- `GET /api/analytics/summary` aggregates stored reviews/findings by status, category, severity, and guideline.
- `GET /api/analytics/guideline-blind-spots` returns frequency indicators for triggered guidelines. `ambiguity_score` is normalized trigger frequency only; it is explicitly not proof of ambiguity.

## Deliberate MVP boundaries

This backend does not implement MFA, centralized SSO/OAuth, encryption-at-rest guarantees, private model hosting, a dedicated vector database, live external fact-checking, Figma/Slack/Docs/CMS integrations, CMS publishing, distributed worker pools, Temporal workflows, or cryptographically tamper-proof audit storage. Password recovery and account invitations are available only when SMTP is configured. SMTP credentials and reset/invitation links are not logged by the application; the configured mail provider necessarily receives the recipient address and message. Protect the bootstrap credentials and database, deploy behind HTTPS with `AUTH_COOKIE_SECURE=true`, configure edge rate limiting and backups, and complete a security review before production use. Login throttling is database-backed and shared across API processes using the configured database; it is additional protection, not a substitute for edge controls. Embedding retrieval is a lightweight application-database cache and is bounded by `MAX_RETRIEVAL_CHUNKS`; it is not a managed vector store. Visual checks are local heuristics, not a trained visual brand-governance model. WebSocket collaboration is lightweight and single-process.

### Existing database upgrade

Startup migrations are additive and idempotent. `Base.metadata.create_all` creates newly registered tables, including guideline/source history, visual asset records, and private review-attachment storage, without dropping or replacing existing records. The review JSON-column migration checks existing tables and adds `review_approval_decisions.acknowledged_warning_ids` with a non-null empty-list JSON default and `review_visual_attachments.analysis_metadata` with a non-null empty-object JSON default when either is missing. Existing review decisions, assignments, and attachments are preserved. Existing review findings use their current JSON metadata column to retain visual details, so no existing finding schema is rewritten. Restart the API to run these migrations; back up the configured database first. BLOB storage grows with each submitted file and must be included in database backup, retention, and capacity planning.

## Tests

```bash
pytest
```

Tests use an in-memory SQLite database and do not change the development database.
