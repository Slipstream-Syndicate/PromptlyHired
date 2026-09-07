# JobTrail

Reads your resume, works out your skillset, finds jobs that fit it, tells you how
well you actually match each one, and writes a tailored resume and cover letter
you edit before exporting.

One React PWA, one FastAPI backend, one URL — phone, laptop and tablet, no native
builds. See [CLAUDE.md](CLAUDE.md) for the full spec and the reasoning behind the
architecture.

## How it works

1. **Upload your resume.** Text is extracted locally (pypdf / python-docx), falling
   back to Claude reading the PDF natively only if it's a scan.
2. **Claude derives a skill profile** — skills, job titles, seniority, domains. You
   can edit it; extraction is a starting point, not an authority on your career.
3. **The feed searches automatically** from that profile. You never type keywords.
4. **Open a job** to get a match percentage, the requirements you meet, and the gaps.
5. **Generate a resume and cover letter**, edit them in-app, export to PDF.

`History` keeps every job you've prepared documents for.

## Status

| Phase | State |
| --- | --- |
| 1 — Resume-driven search | done |
| 2 — Match analysis | done |
| 3 — Document generation, editor, export | done |
| 4 — Polish (steering, templates, diff view) | partial: steering is wired end to end |

## Running locally

```bash
docker compose up -d                                          # Postgres on :5433

cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
cp .env.example .env                                          # then fill in the keys below
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload      # :8000

cd ../frontend
npm install && cp .env.example .env
npm run dev                                                    # :5173
```

### Keys you need

| Variable | Without it |
| --- | --- |
| `ANTHROPIC_API_KEY` | **Nothing AI works.** No skill profile, no matching, no generation — the endpoints return a clear 503. This is the product. |
| `RAPIDAPI_KEY` | The feed serves a handful of sample listings instead of real ones. |
| `ADZUNA_APP_ID` / `_KEY` | Optional second job source. JSearch alone still works. |

Check what's actually wired up:

```bash
curl localhost:8000/health                       # readiness flags
.venv/Scripts/python.exe -m app.tasks doctor     # connects to each service for real
```

## What the AI costs

Claude Opus 5 is $5/$25 per million tokens. Per action, roughly:

| Action | Cost | When |
| --- | --- | --- |
| Resume → skill profile | ~$0.05 | Once per upload |
| Match analysis | ~$0.03 | Only when you open a job card |
| Resume or cover letter | ~$0.08 | On request |

Three rules the code enforces, not just documents:

- **Nothing is scored until you open it.** Scoring a 20-result feed would cost ~20×
  the search itself, mostly on jobs nobody opens.
- **The resume is a cached prompt prefix.** It's identical across every call for a
  user; `usage.cache_read_input_tokens` is logged so a silently broken cache shows up.
- **Every AI result is persisted.** Recomputation is always user-initiated.

Every AI endpoint is rate limited (`AI_CALLS_PER_HOUR`, default 60). An unlimited
scoring endpoint is an unlimited bill.

## Security

Job descriptions come from a third-party aggregator and are written by strangers,
then fed to an LLM. That makes prompt injection the central concern, not a footnote:

- Adverts are wrapped in delimiters and labelled as data, never instructions. A
  posting that emits the closing delimiter to break out has it stripped.
- Adverts never enter the system prompt — only the user turn.
- Every call is constrained to a Pydantic schema, and the match percentage is
  clamped 0–100 server-side regardless of what comes back.
- No LLM output triggers a side effect. Generation writes a draft; you review and
  edit before anything is exported. Nothing is ever sent on your behalf.
- Your resume goes to Claude because the feature requires it, and nowhere else. It
  is never logged in full.

Carried over unchanged: bcrypt hashing, 15-minute access JWTs with rotating hashed
refresh tokens, SQLAlchemy ORM only, Pydantic validation at every boundary, auth
rate limiting, CORS locked to the real origin, HTTPS.

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest        # needs the docker-compose Postgres
python ../scripts/audit_spec.py           # checks the code against CLAUDE.md
```

Tests run against real Postgres, never SQLite — the schema uses native enums, JSONB
and server-side defaults. **Every Claude call is stubbed**, so the suite never spends
money. Coverage includes the injection defenses and score clamping directly.

## Deploying

See **[DEPLOYMENT.md](DEPLOYMENT.md)**. Netlify for the frontend, Render for the API
and Postgres, Cloudflare R2 for uploaded resumes.

The API refuses to boot in production with a default `JWT_SECRET`, a wildcard or
non-HTTPS `CORS_ORIGINS`, or an http `APP_BASE_URL`. Anything that merely degrades
(no AI key, local media storage) is logged as `DEGRADED` and reported on `/health`.
