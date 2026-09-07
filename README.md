# JobTrail

Paste a link to any job. It reads your resume, tells you how well you actually
match that role, shows the gaps, and writes a tailored resume and cover letter
you edit before exporting.

**Runs for £0.** No paid APIs anywhere.

One React PWA, one FastAPI backend, one URL — phone, laptop and tablet, no native
builds. See [CLAUDE.md](CLAUDE.md) for the full spec and the reasoning behind the
architecture.

## How it works

1. **Upload your resume.** Text is extracted locally (pypdf / python-docx), falling
   back to the model reading the PDF natively only if it's a scan.
2. **Paste a job link.** The page is fetched and parsed — schema.org JSON-LD first,
   so most pastes cost no AI quota. Sites that block fetches (LinkedIn, Indeed) have
   a paste-the-text fallback.
3. **Get your match** — percentage, requirements met, and the gaps.
4. **Generate a resume and cover letter**, edit them in-app, export to PDF.

`History` keeps every job you've prepared documents for.

## Status

| Phase | State |
| --- | --- |
| 1 — Resume + paste-a-link | done |
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
| `GEMINI_API_KEY` | **Nothing AI works.** Free key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |

There are no other keys. There is no job-board API.

Check what's actually wired up:

```bash
curl localhost:8000/health                       # readiness flags
.venv/Scripts/python.exe -m app.tasks doctor     # connects to each service for real
```

## What it costs

Nothing. Gemini's free tier covers the AI; jobs come from links you paste, so there
is no job-board API to pay for; Render, Netlify and Cloudflare R2 free tiers cover
the rest.

The real constraint is **rate limit**, not money — the free tier allows single-digit
requests per minute. So the code parses pages itself before ever calling the model,
persists every AI result, and surfaces quota errors as "wait a minute" rather than
a failure.

## Security

Job descriptions are fetched from pages you paste links to, written by strangers,
then fed to an LLM. Two concerns dominate:

**SSRF.** The server fetches a URL you control. Private, loopback and link-local
addresses (cloud metadata at `169.254.169.254`) are refused, only http(s) is
allowed, and every redirect is re-validated — an open redirect to an internal
address is the standard bypass.

**Prompt injection** is the central concern, not a footnote:

- Adverts are wrapped in delimiters and labelled as data, never instructions. A
  posting that emits the closing delimiter to break out has it stripped.
- Adverts never enter the system prompt — only the user turn.
- Every call is constrained to a Pydantic schema, and the match percentage is
  clamped 0–100 server-side regardless of what comes back.
- No LLM output triggers a side effect. Generation writes a draft; you review and
  edit before anything is exported. Nothing is ever sent on your behalf.
- Your resume goes to the model because the feature requires it, and nowhere else.
  It is never logged in full.

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
and server-side defaults. **Every model call is stubbed**, so the suite never spends
money. Coverage includes the injection defenses and score clamping directly.

## Deploying

See **[DEPLOYMENT.md](DEPLOYMENT.md)**. Netlify for the frontend, Render for the API
and Postgres, Cloudflare R2 for uploaded resumes.

The API refuses to boot in production with a default `JWT_SECRET`, a wildcard or
non-HTTPS `CORS_ORIGINS`, or an http `APP_BASE_URL`. Anything that merely degrades
(no AI key, local media storage) is logged as `DEGRADED` and reported on `/health`.
