# Deploying JobTrail

Frontend on **Netlify**, API + Postgres + scheduled jobs on **Render**. Both have
free tiers that cover this app. Total time: about 30 minutes, most of it waiting
for builds.

Work through this in order — later steps need values produced by earlier ones.

---

## 0. Push the repo to GitHub

Netlify and Render both deploy from a Git remote.

```bash
git add -A
git commit -m "JobTrail"
git branch -M main
git remote add origin https://github.com/<you>/jobtrail.git
git push -u origin main
```

`.gitignore` already excludes `backend/.env`, `frontend/.env`, `node_modules/`,
`.venv/` and `backend/media/`. **Never commit a `.env` file** — every secret below
belongs in the host's environment variable UI.

---

## 1. Generate your secrets

Run these locally and keep the output somewhere safe; you'll paste them in later.

```bash
# JWT signing key
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

You also need an **Anthropic API key** from
[console.anthropic.com](https://console.anthropic.com). Without it there is no
skill extraction, no matching and no document generation — the whole product.

---

## 2. Deploy the API to Render

1. Render → **New** → **Blueprint** → select your repo. It reads `render.yaml` and
   proposes a web service and a Postgres database.
2. Click **Apply**. The database and `JWT_SECRET` are created automatically.
3. The first deploy will **fail its health check** — that is expected, because
   `CORS_ORIGINS` and `APP_BASE_URL` are not set yet. Continue to step 3, then
   come back and set them.

`start.sh` runs `alembic upgrade head` before binding the port, so a deploy either
comes up with the correct schema or fails loudly. You never migrate by hand.

---

## 3. Deploy the frontend to Netlify

1. Netlify → **Add new site** → **Import an existing project** → your repo.
2. Netlify reads `netlify.toml`, so build settings are already correct
   (base `frontend`, publish `dist`).
3. Under **Site configuration → Environment variables**, add:

   | Key | Value |
   | --- | --- |
   | `VITE_API_BASE_URL` | `https://<your-render-service>.onrender.com` — no trailing slash |

4. Deploy. Note your site URL, e.g. `https://jobtrail.netlify.app`.

> `VITE_*` variables are baked in at **build** time, not read at runtime. Changing
> this value requires a redeploy, not just a page refresh.

---

## 4. Point the API at the frontend

Back in Render → your web service → **Environment**:

| Key | Value |
| --- | --- |
| `CORS_ORIGINS` | `https://jobtrail.netlify.app` |
| `APP_BASE_URL` | `https://jobtrail.netlify.app` |
| `JOB_COUNTRY` | `uk` (or `us`, `de`, …) |
| `RAPIDAPI_KEY` | your JSearch key |
| `ANTHROPIC_API_KEY` | your Anthropic key |

The API **refuses to start** in production if `JWT_SECRET` is a default/short
value, if `CORS_ORIGINS` is missing, wildcarded, or non-HTTPS. That is deliberate —
a misconfigured deploy should fail immediately, not leak.

---

## 5. Set a spending expectation

Claude Opus 5 costs $5/$25 per million tokens. In practice: ~$0.05 per resume
upload, ~$0.03 per job match, ~$0.08 per generated document. A session where
someone opens ten jobs and generates twice runs about **50 cents**.

That is fine for personal use and expensive as a free public product. Before
sharing the URL widely, either keep it private or add a per-user cap — the
`AI_CALLS_PER_HOUR` limit (default 60) is a blunt backstop, not a budget.

Watch real usage in the Anthropic console, and check the API logs for
`Claude match-analysis: input=... cached_read=...`. If `cached_read` is 0 across
repeated calls, prompt caching has broken and every match is paying full price
for the same resume tokens.

---

## 6. Resumes and profile pictures — Cloudflare R2

`MEDIA_STORAGE=local` writes to the container filesystem, which Render **wipes on
every deploy** — users' uploaded resumes would vanish. `render.yaml` already sets `MEDIA_STORAGE=s3`;
supply the bucket:

1. Cloudflare dashboard → **R2** → create a bucket, e.g. `jobtrail-media`.
2. Enable public access (or attach a custom domain) and copy the public base URL.
3. **Manage R2 API Tokens** → create a token with Object Read & Write.
4. Set on the Render web service:

| Key | Value |
| --- | --- |
| `S3_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `S3_BUCKET` | `jobtrail-media` |
| `S3_ACCESS_KEY_ID` | from the token |
| `S3_SECRET_ACCESS_KEY` | from the token |
| `S3_PUBLIC_BASE_URL` | your bucket's public URL |

---

## 7. Optional extras

**Adzuna** (second job source) — free key from
[developer.adzuna.com](https://developer.adzuna.com/). Set `ADZUNA_APP_ID` and
`ADZUNA_APP_KEY`. Leave blank and the feed runs on JSearch alone.

**Redis** (`REDIS_URL`) — only needed if you scale past one instance/worker.
Without it, auth rate limiting is per-process, so N workers means N× the limit.

---

## 8. Verify the live deployment

The fastest check is the built-in doctor, which actually connects to every
service rather than just reading your environment variables. On Render, open the
service **Shell** tab and run:

```bash
python -m app.tasks doctor

```

It round-trips a real object through R2, makes a real JSearch call, makes a real
(tiny) Claude call, and reports any failure with the exact variable to fix.

You can also check from anywhere with:

```bash
curl https://<your-api>.onrender.com/health
```

Every flag should be `true` for the features you configured:

```json
{
  "status": "ok",
  "env": "production",
  "live_job_listings": true,
  "ai_features": true,
  "durable_media_storage": true
}
```

Then, in a browser:

1. Open the Netlify URL and sign up.
2. Upload a resume on **Profile** and confirm a skill profile appears.
3. Return to **Jobs** — the feed should populate with no keywords typed.
4. Open a job, hit **Analyse my match**, then generate a document and export it.
5. Hard-refresh on `/history` — it must load, not 404. (That is the SPA redirect;
   if it 404s, `netlify.toml` was not picked up.)

---

## Free-tier gotchas

- **Render free web services sleep after ~15 minutes idle.** The first request
  afterwards takes 30–60s. Not a bug.
- **Render free Postgres expires after 30 days.** Back up or upgrade before then,
  or you lose the database.
- **JSearch free tier is ~200 calls/month.** One feed search is one call; identical
  searches within `JSEARCH_CACHE_TTL_MINUTES` are free.
- **Anthropic is billed per token, with no free tier.** See step 5.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Frontend loads, every request fails | `VITE_API_BASE_URL` unset or has a trailing slash. Check the browser console — the app logs this explicitly. |
| CORS errors in the console | `CORS_ORIGINS` on Render doesn't exactly match the Netlify origin (scheme included). |
| API won't boot, logs say `CONFIG ERROR` | Intentional. The message names the exact variable to fix. |
| `sqlalchemy.exc.NoSuchModuleError: postgres` | Shouldn't happen — `config.py` rewrites `postgres://`. If you see it, `DATABASE_URL` was overridden with something unusual. |
| No skill profile after upload | `ANTHROPIC_API_KEY` unset or invalid — check `/health` and run the doctor. |
| Match/generate return 503 | Same cause: no Anthropic key configured on the API service. |
| Resumes vanish after a deploy | `MEDIA_STORAGE` is not `s3`. See step 6. |
