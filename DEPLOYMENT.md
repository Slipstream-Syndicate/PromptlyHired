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

# Web push keypair (VAPID)
cd backend && .venv/Scripts/python.exe -m app.tools.vapid
```

> Regenerating VAPID keys later invalidates every existing push subscription, so
> generate once and keep them.

---

## 2. Deploy the API to Render

1. Render → **New** → **Blueprint** → select your repo. It reads `render.yaml` and
   proposes a web service, a Postgres database, and two cron jobs.
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
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | from step 1 |
| `VAPID_SUBJECT` | `mailto:you@example.com` |

Set the same values on **both cron jobs** (they send the emails, so they need
`APP_BASE_URL` for the links).

The API **refuses to start** in production if `JWT_SECRET` is a default/short
value, if `CORS_ORIGINS` is missing, wildcarded, or non-HTTPS. That is deliberate —
a misconfigured deploy should fail immediately, not leak.

---

## 5. Email — required for notifications to actually work

Until `SMTP_HOST` is set, digests and reminders are **written to the log instead of
being sent**. Email is the baseline channel, so this is not optional if you want
notifications at all.

Any SMTP provider works. Free options include Resend, Brevo, Mailjet, or a Gmail
App Password. Set on the web service **and both cron jobs**:

| Key | Example |
| --- | --- |
| `SMTP_HOST` | `smtp.resend.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `resend` |
| `SMTP_PASSWORD` | your API key |
| `SMTP_FROM` | `JobTrail <no-reply@yourdomain.com>` |

Most providers require a verified sender domain before they will deliver to
arbitrary inboxes — do that in their dashboard.

Verify with:

```bash
curl https://<your-api>.onrender.com/health
# "email_notifications": true
```

---

## 6. Profile pictures — Cloudflare R2

`MEDIA_STORAGE=local` writes to the container filesystem, which Render **wipes on
every deploy**. Uploads would vanish. `render.yaml` already sets `MEDIA_STORAGE=s3`;
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

# Once SMTP is configured, prove delivery end to end:
python -m app.tasks doctor --email you@example.com
```

It round-trips a real object through R2, makes a real JSearch call, validates the
VAPID keypair, and reports any failure with the exact variable to fix.

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
  "email_notifications": true,
  "web_push": true,
  "durable_media_storage": true
}
```

Then, in a browser:

1. Open the Netlify URL, sign up, and confirm real listings load.
2. **Android/Chrome:** an install prompt appears → install → Profile → *Enable push
   notifications* → **Send test**.
3. **iPhone:** Safari → Share → **Add to Home Screen**, then open it from the home
   screen. Push only works from the installed app, on iOS 16.4+ — in a normal Safari
   tab the button correctly tells you to install first.
4. Hard-refresh on `/applications` — it must load, not 404. (That is the SPA
   redirect; if it 404s, `netlify.toml` was not picked up.)

---

## Free-tier gotchas

- **Render free web services sleep after ~15 minutes idle.** The first request
  afterwards takes 30–60s. Not a bug.
- **Render free Postgres expires after 30 days.** Back up or upgrade before then,
  or you lose the database.
- **JSearch free tier is ~200 calls/month.** The weekly digest costs one call per
  followed company (capped by `DIGEST_MAX_COMPANIES`, default 5). Keep the cron
  weekly — daily would exhaust the quota in about nine days.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Frontend loads, every request fails | `VITE_API_BASE_URL` unset or has a trailing slash. Check the browser console — the app logs this explicitly. |
| CORS errors in the console | `CORS_ORIGINS` on Render doesn't exactly match the Netlify origin (scheme included). |
| API won't boot, logs say `CONFIG ERROR` | Intentional. The message names the exact variable to fix. |
| `sqlalchemy.exc.NoSuchModuleError: postgres` | Shouldn't happen — `config.py` rewrites `postgres://`. If you see it, `DATABASE_URL` was overridden with something unusual. |
| Emails never arrive | `SMTP_HOST` unset (check `/health`), or the sender domain isn't verified with your provider. |
| Push works on Android, not iPhone | Expected unless the PWA was added to the home screen and iOS is 16.4+. |
| Profile pictures vanish after a deploy | `MEDIA_STORAGE` is not `s3`. See step 6. |
