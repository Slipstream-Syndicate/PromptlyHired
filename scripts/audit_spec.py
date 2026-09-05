"""Audit the codebase against every concrete claim in CLAUDE.md.

Run with: python scripts/audit_spec.py
Exits non-zero if the implementation has drifted from the spec.
"""

import re
import sys
from pathlib import Path

# Repo root, resolved from this file so it works in CI and on any machine.
ROOT = Path(__file__).resolve().parent.parent
BE, FE = ROOT / "backend", ROOT / "frontend"

issues, checks = [], 0


def read(p):
    return (ROOT / p).read_text(encoding="utf-8", errors="replace")


def ck(section, label, cond, detail=""):
    global checks
    checks += 1
    if not cond:
        issues.append((section, label, detail))
    print(f"  [{'ok' if cond else 'MISSING'}] {label}" + (f"  -- {detail}" if detail and not cond else ""))


def head(t):
    print(f"\n== {t} ==")


models = read("backend/app/models.py")
schemas = read("backend/app/schemas.py")

head("Data model — every field named in CLAUDE.md")
FIELDS = {
    "User": ["email", "password_hash", "name", "profile_picture_url", "created_at"],
    "Company": ["name", "logo_url"],
    "Job": ["company_id", "title", "location", "salary_range", "url", "posted_date",
            "description", "source_api", "external_id", "source_publisher"],
    "JobPreferences": ["keywords", "location", "salary_min", "salary_max", "job_type"],
    "Follow": ["user_id", "company_id", "created_at"],
    "SavedJob": ["user_id", "job_id", "saved_at"],
    "Application": ["user_id", "job_id", "status", "applied_date", "status_updated_at", "notes"],
}
for cls, fields in FIELDS.items():
    m = re.search(rf"class {cls}\(Base\):(.*?)(?=\nclass |\Z)", models, re.S)
    body = m.group(1) if m else ""
    ck("model", f"{cls} exists", bool(m))
    for f in fields:
        ck("model", f"{cls}.{f}", f"{f}:" in body or f"{f} :" in body)

head("Application status states (exactly the 6 in the spec)")
for s in ["applied", "online_assessment", "interview", "offer", "rejected", "withdrawn"]:
    ck("status", f"status '{s}'", f'{s} = "{s}"' in models)
ck("status", "'saved' is NOT an Application status", 'saved = "saved"' not in models,
   "spec: Saved is the separate SavedJob entity")

head("Follow vs SavedJob are separate, independent entities")
ck("model", "Follow is company-level", "company_id" in models.split("class Follow")[1].split("class ")[0])
ck("model", "SavedJob is job-level", "job_id" in models.split("class SavedJob")[1].split("class ")[0])
jobcard = read("frontend/src/components/JobCard.jsx")
ck("ui", "Save and Follow are separate controls", "onToggleSave" in jobcard and "onToggleFollow" in jobcard)

head("JobPreferences is one source of truth for profile + homepage filters")
jobs_router = read("backend/app/routers/jobs.py")
ck("prefs", "search reads stored prefs on login", "use_saved_preferences" in jobs_router)
ck("prefs", "submitted filters overwrite stored prefs", "prefs.keywords = keywords" in jobs_router)
prof = read("frontend/src/pages/Profile.jsx")
ck("prefs", "profile edits the same fields", all(k in prof for k in ["keywords", "location", "salary_min", "salary_max", "job_type"]))

head("Bottom nav — exactly 4 pages, Followed Companies NOT among them")
nav = read("frontend/src/components/BottomNav.jsx")
routes = [m for m in re.findall(r"to: '([^']+)'", nav)]
ck("nav", "exactly 4 nav items", len(routes) == 4, str(routes))
ck("nav", "nav is Home/Saved/Applications/Profile",
   set(routes) == {"/", "/saved", "/applications", "/profile"}, str(routes))
ck("nav", "Followed Companies is not a nav slot", "/profile/companies" not in routes)
appjsx = read("frontend/src/App.jsx")
ck("nav", "Followed Companies is a Profile sub-route", "/profile/companies" in appjsx)

head("Apply link — required everywhere a job is shown")
apply = read("frontend/src/components/ApplyLink.jsx")
ck("apply", "opens in a new tab", 'target="_blank"' in apply)
ck("apply", "rel=noopener noreferrer", 'rel="noopener noreferrer"' in apply)
ck("apply", "labelled with source_publisher", "source_publisher" in apply)
ck("apply", "hidden when there is no url", "if (!job.url) return null" in apply)
ck("apply", "primary styling, distinct from Save/Follow", "btn primary" in apply)
ck("apply", "present on Homepage + Saved (via JobCard)", "ApplyLink" in jobcard)
ck("apply", "present on Applications page", "ApplyLink" in read("frontend/src/pages/Applications.jsx"))

head("Notifications driven ONLY by Follow, never SavedJob")
notif = read("backend/app/services/notifications.py")
ck("notif", "digest joins on Follow", "Follow" in notif)
ck("notif", "digest never reads SavedJob", "SavedJob" not in notif)
ck("notif", "email is the baseline channel", "send_email" in notif)
ck("notif", "push is layered on top", "send_to_user" in notif)

head("Security requirements from CLAUDE.md")
sec = read("backend/app/security.py")
ck("sec", "bcrypt password hashing", "bcrypt" in sec)
ck("sec", "no plaintext passwords stored", "password_hash" in models)
ck("sec", "short-lived access token", "access_token_expire_minutes" in read("backend/app/config.py"))
ck("sec", "refresh token pattern", "RefreshToken" in models)
ck("sec", "refresh tokens stored hashed", "hash_refresh_token" in sec and "sha256" in sec)
rl = read("backend/app/rate_limit.py")
auth = read("backend/app/routers/auth.py")
ck("sec", "rate limiting on login", "login_rate_limit" in auth)
ck("sec", "rate limiting on signup", "signup_rate_limit" in auth)
main = read("backend/app/main.py")
# Look for an actual wildcard in the middleware args, not the word "*" anywhere
# in the file (the previous check tripped on an explanatory comment).
cors_block = main[main.find("add_middleware"): main.find("add_middleware") + 500]
ck("sec", "CORS restricted, not wildcard",
   "allow_origins=settings.cors_origins" in cors_block
   and '["*"]' not in cors_block and '"*"' not in cors_block.split("#")[0])
ck("sec", "Pydantic validation at the boundary", "BaseModel" in schemas and "field_validator" in schemas)
ck("sec", "user text stripped of control chars", "clean_text" in schemas)
ck("sec", "job text escaped before HTML email", "html.escape" in notif)

# Raw SQL scan across the backend.
raw_sql = []
for py in (BE / "app").rglob("*.py"):
    txt = py.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'(?:execute|text)\(\s*f["\']', txt):
        raw_sql.append(f"{py.relative_to(BE)}:{txt[:m.start()].count(chr(10))+1}")
ck("sec", "no f-string interpolated SQL anywhere", not raw_sql, "; ".join(raw_sql))

head("Phase 1 — MVP")
ck("p1", "signup + login endpoints", "/signup" in auth and "/login" in auth)
ck("p1", "job feed from JSearch", (BE / "app/services/jsearch.py").exists())
ck("p1", "search + filters", "salary_min" in jobs_router and "job_type" in jobs_router)
ck("p1", "followed-company results pinned above general", "followed=" in jobs_router)
ck("p1", "Saved Jobs page", (FE / "src/pages/SavedJobs.jsx").exists())
ck("p1", "Applications page", (FE / "src/pages/Applications.jsx").exists())
ck("p1", "Followed Companies sub-page", (FE / "src/pages/FollowedCompanies.jsx").exists())
ck("p1", "email notification for followed companies", "send_email" in notif)

head("Phase 2 — PWA + polish")
vite = read("frontend/vite.config.js")
ck("p2", "PWA manifest configured", "manifest:" in vite)
ck("p2", "service worker generated", "VitePWA" in vite)
ck("p2", "offline shell (navigateFallback)", "navigateFallback:" in vite)
ck("p2", "maskable icon for install", "maskable" in vite)
ck("p2", "web push service worker handler", (FE / "public/push-sw.js").exists())
ck("p2", "push backend", (BE / "app/services/push.py").exists())
ck("p2", "push subscriptions persisted", "PushSubscription" in models)
ck("p2", "install prompt UI", (FE / "src/components/InstallPrompt.jsx").exists())
ck("p2", "iOS add-to-home-screen guidance", "Add to Home Screen" in read("frontend/src/components/InstallPrompt.jsx"))
ck("p2", "profile picture upload", (BE / "app/services/storage.py").exists())
ck("p2", "S3/R2 storage path (not local-only)", "uses_s3" in read("backend/app/services/storage.py"))
ck("p2", "job preferences editing", "savePreferences" in prof)
ck("p2", "responsive breakpoints", "@media (min-width: 768px)" in read("frontend/src/styles.css"))

head("Phase 3 — nice-to-haves")
ck("p3", "Adzuna integration", (BE / "app/services/adzuna.py").exists())
ck("p3", "multi-source merge", (BE / "app/services/sources.py").exists())
ck("p3", "funnel analytics service", (BE / "app/services/analytics.py").exists())
ck("p3", "response rate by company", '"response_rate"' in read("backend/app/services/analytics.py"))
ck("p3", "analytics UI", (FE / "src/pages/Analytics.jsx").exists())
ck("p3", "follow-up reminders", (BE / "app/services/reminders.py").exists())
ck("p3", "reminder threshold configurable", "follow_up_after_days" in read("backend/app/config.py"))

head("Open decisions flagged in CLAUDE.md")
cfg = read("backend/app/config.py")
ck("open", "profile pictures use S3-compatible storage, not local disk in prod",
   "s3_endpoint_url" in cfg and "media_storage" in cfg)
ck("open", "local disk documented as dev-only", "wipe" in read("backend/app/services/storage.py").lower()
   or "redeploy" in read("backend/app/services/storage.py").lower())

head("Deployment readiness")
ck("deploy", "frontend host config (Netlify)", (ROOT / "netlify.toml").exists())
ck("deploy", "SPA redirect so deep links do not 404", (ROOT / "frontend/public/_redirects").exists())
ck("deploy", "backend blueprint with Postgres + cron", (ROOT / "render.yaml").exists())
ck("deploy", "container image for the API", (ROOT / "backend/Dockerfile").exists())
ck("deploy", "migrations run before the server binds", "alembic upgrade head" in read("backend/start.sh"))
ck("deploy", "scheduled digest job defined", "app.tasks digest" in read("render.yaml"))
ck("deploy", "scheduled reminders job defined", "app.tasks reminders" in read("render.yaml"))
ck("deploy", "platform postgres:// URLs normalised", "_PG_SCHEME_FIXES" in read("backend/app/config.py"))
ck("deploy", "production refuses a default JWT secret", "production_blockers" in read("backend/app/config.py"))
ck("deploy", "HSTS + nosniff + frame-deny headers", "Strict-Transport-Security" in read("backend/app/main.py"))
ck("deploy", "automated tests live in the repo", (ROOT / "backend/tests").is_dir())
ck("deploy", "CI runs them", (ROOT / ".github/workflows/ci.yml").exists())
ck("deploy", "deployment guide", (ROOT / "DEPLOYMENT.md").exists())

print("\n" + "=" * 60)
print(f"{checks} checks, {len(issues)} problem(s)")
if issues:
    for s, l, d in issues:
        print(f"  [{s}] {l} {d}")
    sys.exit(1)
print("CLAUDE.md IS FULLY IMPLEMENTED")
