# JobTrail

Job search and application tracker. One React PWA, one FastAPI backend, one URL —
works on phone, laptop and tablet without separate native builds.

See [CLAUDE.md](CLAUDE.md) for the product spec and architecture decisions.

## Status — Phases 1, 2 and 3 complete, deployment-ready

| Phase 1 requirement | Where |
| --- | --- |
| Auth (signup/login) | `backend/app/routers/auth.py`, `frontend/src/pages/Login.jsx` |
| Homepage feed, search + filters | `backend/app/routers/jobs.py`, `frontend/src/pages/Home.jsx` |
| Auto-search on login from stored preferences | `GET /api/jobs/search?use_saved_preferences=true` |
| Followed-company listings pinned above general results | `SearchResponse.followed` |
| Save a job / Follow a company as independent actions | `routers/saved.py`, `routers/follows.py` |
| Outbound Apply link to the original posting, labelled with the source board | `frontend/src/components/ApplyLink.jsx` |
| Saved Jobs page | `frontend/src/pages/SavedJobs.jsx` |
| Applications page with status badge | `frontend/src/pages/Applications.jsx` |
| Followed Companies sub-page under Profile | `frontend/src/pages/FollowedCompanies.jsx` |
| Email notification for new jobs from followed companies | `backend/app/services/notifications.py` |

### Phase 2 — PWA + polish

| Phase 2 requirement | Where |
| --- | --- |
| Installable PWA (manifest, service worker, offline shell) | `frontend/vite.config.js`, `components/InstallPrompt.jsx` |
| Web push notifications | `backend/app/services/push.py`, `routers/push.py`, `frontend/public/push-sw.js` |
| Profile picture upload | `backend/app/services/storage.py`, `components/AvatarUpload.jsx` |
| Job preferences editing | `frontend/src/pages/Profile.jsx` (shipped in Phase 1) |
| Search/filter improvements | "Load more" cursor pagination in `pages/Home.jsx` |

**Web push reality check.** Push is layered on top of email, never instead of it.
Android/Chrome works normally. **iOS only delivers push to an installed PWA on 16.4+**
— in a plain Safari tab `PushManager` does not exist, so the Profile page detects that
and tells the user to Add to Home Screen instead of showing a dead button. A user with
no working subscription still receives the digest email.

Generate a VAPID keypair with `python -m app.tools.vapid` and paste it into
`backend/.env`. Regenerating invalidates every existing subscription.

**Profile pictures.** Uploads are re-encoded through Pillow rather than stored as
received — that verifies the bytes really are an image, strips EXIF and any embedded
payload, and bounds dimensions to 512px. `MEDIA_STORAGE=local` writes to
`backend/media` and is dev-only: **Render and Railway wipe the filesystem on every
redeploy.** Set `MEDIA_STORAGE=s3` with Cloudflare R2 credentials before deploying.

## Going live

Full walkthrough in **[DEPLOYMENT.md](DEPLOYMENT.md)**: Netlify for the frontend,
Render for the API + Postgres + the two cron jobs, Cloudflare R2 for uploads.

```bash
python -m app.tasks doctor    # verify every integration actually works
```

The API refuses to boot in production with a default `JWT_SECRET`, a wildcard or
non-HTTPS `CORS_ORIGINS`, or an http `APP_BASE_URL` — a misconfigured deploy fails
immediately rather than leaking. Anything that merely degrades (no SMTP, local
media storage) is logged as `DEGRADED` at startup and reported on `/health`.

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest        # needs the docker-compose Postgres running
python ../scripts/audit_spec.py           # checks the code against CLAUDE.md
```

Tests run against real Postgres, never SQLite — the schema uses native enums and
server-side defaults that SQLite would not exercise. CI runs both on every push.

## Running locally

### 1. Database

```bash
docker compose up -d          # Postgres 16 on localhost:5433
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

cp .env.example .env
# then set JWT_SECRET:  python -c "import secrets; print(secrets.token_urlsafe(64))"

.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

API on http://localhost:8000, interactive docs at http://localhost:8000/docs
(automatically disabled when `ENV=production`).

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev                   # http://localhost:5173
```

### Job listings without an API key

With `RAPIDAPI_KEY` unset the search endpoint serves a small set of sample listings
so the UI is fully usable offline; the response is tagged `"source": "sample"` and the
homepage shows a banner. Add a [JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)
key to `backend/.env` for live results.

### Email digest

```bash
cd backend
.venv/Scripts/python.exe -m app.tasks digest              # polls upstream, then emails
.venv/Scripts/python.exe -m app.tasks digest --dry-run    # emails from stored jobs, 0 API calls
```

Polls the job source for every followed company, stores new listings, and emails each
user the ones they have not been sent before. With `SMTP_HOST` unset the message is
logged instead of sent. On Railway/Render, run this as a scheduled job — **weekly**,
see the quota note below.

Use `--dry-run` while developing: it skips the upstream poll entirely and emails from
jobs already in the database, so it costs nothing and is repeatable.

### Phase 3 — nice-to-haves

| Phase 3 requirement | Where |
| --- | --- |
| Additional job source (Adzuna) | `backend/app/services/adzuna.py`, merged in `services/sources.py` |
| Funnel analytics (response rate by company/status) | `backend/app/services/analytics.py`, `frontend/src/pages/Analytics.jsx` |
| Follow-up reminders ("no update in 2 weeks") | `backend/app/services/reminders.py` |

**Analytics are built on real history, not a snapshot.** An `application_events` row
records every status transition, which is what lets the funnel answer "did this ever
reach interview" for something now marked rejected — the current status alone cannot.
History only exists from when this shipped, so pre-existing applications are counted
by current status.

```bash
.venv/Scripts/python.exe -m app.tasks reminders   # nudge stale applications, 0 API calls
```

An application is stale after `FOLLOW_UP_AFTER_DAYS` (default 14) with no status
change, and only if it is not already finished — offers and rejections are never
nagged about. `last_reminder_at` limits repeats to `REMINDER_REPEAT_DAYS` (default 7),
and any real status change resets the clock.

**Adzuna is optional.** With no `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` the feed runs on
JSearch alone. When enabled, both sources are queried concurrently and merged, with
cross-source duplicates dropped on normalised title + employer (the same vacancy
carries a different id in each aggregator, so id matching cannot catch it). If Adzuna
fails, JSearch results are still served. Adzuna's `salary_is_predicted` flag is
respected — estimated salaries are labelled `(est.)` rather than passed off as stated.

Pagination note: JSearch uses opaque cursors and Adzuna page numbers, which do not
compose, so Adzuna contributes to the first page only; "Load more" continues through
JSearch.

## API quota

The JSearch free plan is roughly 200 calls/month, and it is easy to blow through:

| Action | Upstream calls |
| --- | --- |
| One homepage search (new filters) | 1 |
| Same search again within the cache TTL | 0 |
| One digest run | 1 per followed company, capped at `DIGEST_MAX_COMPANIES` |
| `digest --dry-run` | 0 |
| `reminders` | 0 (reads stored data only) |
| Analytics / funnel page | 0 |

Three controls in `backend/.env`:

- `JSEARCH_CACHE_TTL_MINUTES` (default 15) — identical searches are served from
  memory. Building the UI means re-running the same search constantly; this makes
  that free.
- `DIGEST_MAX_COMPANIES` (default 5) — hard cap on calls per digest run.
- `JSEARCH_COUNTRY` (default `us`) — ISO code the search is scoped to. Set it to
  your market (`uk`, `de`, …) or results will skew American.

Run the digest **weekly, not daily**: 5 companies weekly is ~20 calls/month, while
daily would be ~150. Every upstream call is logged as
`JSearch upstream call #N`, so `grep` the log to see consumption.

## Data model notes

Two distinctions drive the whole design:

- **`Follow` (company) vs `SavedJob` (job)** — separate tables, independent actions.
  Following drives notifications; saving is a shortlist and notifies nothing.
- **`JobPreferences` is one row per user** backing both the profile fields and the
  homepage search filters. Submitting the filter form rewrites the stored preferences,
  so the two can never drift apart.

`Application` has no "Saved" status — a job becomes an `Application` (status `applied`)
only when the user actually applies, which also removes it from the shortlist.

Listings dedup on `(source_api, external_id)`; companies dedup on a normalised name so
one employer means one `Follow`. JSearch `search-v2` ids are ~400-character opaque
blobs, hence the wide `external_id` column.

The search endpoint paginates by opaque cursor, not page number: the response carries
`next_cursor`, which you pass back as `?cursor=…`.

## Security

- bcrypt password hashing; passwords over bcrypt's 72-byte limit are rejected, never
  silently truncated.
- 15-minute access JWTs; refresh tokens are opaque, stored only as SHA-256 hashes,
  and rotate on every use so a stolen token can be revoked.
- SQLAlchemy ORM throughout — no string-interpolated SQL.
- Pydantic validation on every endpoint; free text is length-capped and stripped of
  control characters.
- Rate limits on signup/login/refresh (in-process; move to Redis before running more
  than one instance).
- CORS restricted to configured origins, never `*`.
- Job listings are external untrusted text: HTML-escaped before going into emails, and
  escaped by React in the UI.
