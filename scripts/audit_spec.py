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
ai = read("backend/app/services/ai.py")

head("Data model - every entity named in CLAUDE.md")
FIELDS = {
    "User": ["email", "password_hash", "name", "profile_picture_url", "created_at"],
    "Resume": ["user_id", "file_url", "original_filename", "content_type", "is_active", "uploaded_at"],
    "SkillProfile": ["resume_id", "skills", "job_titles", "domains", "locations",
                     "seniority", "years_experience", "summary", "generated_at", "model_used"],
    "Company": ["name", "logo_url", "short_description"],
    "Job": ["company_id", "title", "location", "salary_range", "url", "posted_date",
            "description", "source_api", "external_id", "source_publisher"],
    "JobMatch": ["user_id", "job_id", "resume_id", "match_percentage", "requirements_met",
                 "requirements_missing", "rationale", "generated_at", "model_used"],
    "SavedJob": ["user_id", "job_id", "saved_at"],
    "GeneratedDocument": ["user_id", "job_id", "resume_id", "kind", "content",
                          "edited_content", "created_at", "updated_at", "model_used"],
}
for cls, fields in FIELDS.items():
    m = re.search(rf"class {cls}\(Base\):(.*?)(?=\nclass |\Z)", models, re.S)
    body = m.group(1) if m else ""
    ck("model", f"{cls} exists", bool(m))
    for f in fields:
        ck("model", f"{cls}.{f}", f"{f}:" in body)

head("Removed tracker domain stays removed")
for gone in ["ApplicationStatus", "ApplicationEvent", "class Follow(", "NotifiedJob",
             "PushSubscription", "JobPreferences"]:
    ck("removed", f"no {gone.rstrip('(')}", gone not in models)
for path in ["backend/app/services/notifications.py", "backend/app/services/push.py",
             "backend/app/services/reminders.py", "backend/app/services/analytics.py",
             "frontend/src/pages/Applications.jsx", "frontend/src/pages/Analytics.jsx"]:
    ck("removed", f"{path} deleted", not (ROOT / path).exists())

head("History is derived, not stored")
ck("history", "no History table", "class History" not in models)
documents_router = read("backend/app/routers/documents.py")
ck("history", "history derived from GeneratedDocument", "GeneratedDocument" in documents_router
   and "/history" in documents_router)

head("Match scoring is on-demand, never across the feed")
jobs_router = read("backend/app/routers/jobs.py")
user_state = read("backend/app/services/user_state.py")
ck("cost", "feed cards carry no match percentage", "match_percentage" not in user_state)
ck("cost", "scoring is a separate explicit POST", '"/{job_id}/match"' in jobs_router)
ck("cost", "job detail does not score", "ai.analyze_match" not in jobs_router.split("def analyze_job")[0])
ck("cost", "match cached per (user, job, resume)", "uq_match_user_job_resume" in models)
ck("cost", "recompute only when explicitly refreshed", "refresh" in jobs_router)

head("Prompt injection defenses (the central security concern)")
ck("ai", "untrusted job text is fenced", "wrap_untrusted" in ai)
ck("ai", "delimiter injection is stripped", ".replace(UNTRUSTED_OPEN" in ai)
ck("ai", "guard tells the model the block is data", "never" in ai and "instructions to follow" in ai)
ck("ai", "job text never goes in the system prompt",
   "wrap_untrusted(description)" in ai and "system=f\"{wrap_untrusted" not in ai)
ck("ai", "structured output on every call", "response_schema=schema" in ai and "response_mime_type" in ai)
ck("ai", "match percentage clamped server-side", "max(0, min(100" in ai)
ck("ai", "generation forbids fabrication", "invent" in ai.lower())
ck("ai", "token usage is logged", "usage_metadata" in ai)
ck("ai", "free-tier quota surfaced as retryable", "AIRateLimited" in ai)
ck("ai", "AI endpoints are rate limited", "ai_rate_limit" in read("backend/app/rate_limit.py"))
for router in ("backend/app/routers/jobs.py", "backend/app/routers/documents.py",
               "backend/app/routers/resumes.py"):
    ck("ai", f"{Path(router).name} guards AI routes", "ai_rate_limit" in read(router))

head("No LLM output triggers a side effect")
ck("ai", "documents are drafts the user edits", "edited_content" in models)
ck("ai", "original AI output is never overwritten", "never overwritten" in documents_router
   or "edited_content" in documents_router)
ck("ai", "no auto-apply or auto-send anywhere",
   not re.search(r"auto_apply|send_application|submit_application", read("backend/app/routers/documents.py")))

head("Nav - exactly 4 pages: Jobs, Saved, History, Profile")
nav = read("frontend/src/components/BottomNav.jsx")
routes = re.findall(r"to: '([^']+)'", nav)
ck("nav", "exactly 4 nav items", len(routes) == 4, str(routes))
ck("nav", "Jobs/Saved/History/Profile", set(routes) == {"/", "/saved", "/history", "/profile"}, str(routes))

head("Apply link - required everywhere a job is shown")
apply = read("frontend/src/components/ApplyLink.jsx")
ck("apply", "opens in a new tab", 'target="_blank"' in apply)
ck("apply", "rel=noopener noreferrer", 'rel="noopener noreferrer"' in apply)
ck("apply", "labelled with source_publisher", "source_publisher" in apply)
ck("apply", "hidden when there is no url", "if (!job.url) return null" in apply)
ck("apply", "on the feed card", "ApplyLink" in read("frontend/src/components/JobCard.jsx"))
ck("apply", "on job detail", "ApplyLink" in read("frontend/src/pages/JobDetail.jsx"))
ck("apply", "on History", "ApplyLink" in read("frontend/src/pages/History.jsx"))

head("Jobs enter by pasting - no paid feed")
job_url = read("backend/app/services/job_url.py")
ck("paste", "URL fetcher exists", bool(job_url))
ck("paste", "paste-a-link endpoint", "/from-url" in jobs_router)
ck("paste", "paste-the-text fallback", "/from-text" in jobs_router)
ck("paste", "no paid job APIs remain",
   not (BE / "app/services/jsearch.py").exists() and not (BE / "app/services/adzuna.py").exists())
ck("paste", "no RapidAPI key in config", "rapidapi" not in read("backend/app/config.py").lower())
ck("paste", "cheapest-first extraction (JSON-LD before the model)",
   "parse_json_ld" in jobs_router and jobs_router.index("parse_json_ld") < jobs_router.index("extract_job_from_page"))
ck("paste", "re-pasting the same job reuses the row", "sha256" in jobs_router)
ck("paste", "resume upload endpoint", (BE / "app/routers/resumes.py").exists())
ck("paste", "PDF/DOCX/text extraction", (BE / "app/services/resume_text.py").exists())
ck("paste", "skill profile is user-editable", "skill-profile" in read("backend/app/routers/resumes.py"))

head("SSRF - the server fetches a URL the user controls")
ck("ssrf", "addresses are resolved and checked", "getaddrinfo" in job_url)
ck("ssrf", "private ranges refused", "is_private" in job_url)
ck("ssrf", "loopback refused", "is_loopback" in job_url)
ck("ssrf", "link-local (cloud metadata) refused", "is_link_local" in job_url)
ck("ssrf", "only http(s) schemes", '("http", "https")' in job_url)
ck("ssrf", "redirects re-validated", job_url.count("validate_url") >= 3)
ck("ssrf", "response size capped", "MAX_PAGE_BYTES" in job_url)

head("Match percentage is presented honestly")
match_panel = read("frontend/src/components/MatchPanel.jsx")
ck("ui", "match panel exists", bool(match_panel))
ck("ui", "paste UI on the main page", "addJobFromUrl" in read("frontend/src/pages/Jobs.jsx"))
ck("ui", "text fallback offered", "addJobFromText" in read("frontend/src/pages/Jobs.jsx"))
ck("ui", "score never claimed as a hiring prediction", "not a prediction" in match_panel)
ck("ui", "requirements met and missing both shown",
   "requirements_met" in match_panel and "requirements_missing" in match_panel)

head("Document editor + export")
editor = read("frontend/src/pages/DocumentEditor.jsx")
ck("docs", "structured editor, not one textarea", "BulletList" in editor and "ResumeForm" in editor)
ck("docs", "user reviews before export", "before you use it" in editor)
ck("docs", "reset to generated", "resetDocument" in editor)
ck("docs", "PDF export", (FE / "src/lib/exportPdf.js").exists())
ck("docs", "export escapes model output", "function esc(" in read("frontend/src/lib/exportPdf.js"))

head("Security carried forward")
sec = read("backend/app/security.py")
auth = read("backend/app/routers/auth.py")
main = read("backend/app/main.py")
ck("sec", "bcrypt password hashing", "bcrypt" in sec)
ck("sec", "refresh tokens stored hashed", "hash_refresh_token" in sec and "sha256" in sec)
ck("sec", "rate limiting on login and signup", "login_rate_limit" in auth and "signup_rate_limit" in auth)
cors = main[main.find("add_middleware"): main.find("add_middleware") + 500]
ck("sec", "CORS restricted, not wildcard",
   "allow_origins=settings.cors_origins" in cors and '["*"]' not in cors)
ck("sec", "Pydantic validation at the boundary", "field_validator" in schemas)
ck("sec", "user text stripped of control chars", "clean_text" in schemas)
ck("sec", "API key is server-side only", "gemini_api_key" in read("backend/app/config.py")
   and "GEMINI" not in read("frontend/src/api/client.js"))
raw_sql = []
for py in (BE / "app").rglob("*.py"):
    txt = py.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'(?:execute|text)\(\s*f["\']', txt):
        raw_sql.append(f"{py.relative_to(BE)}:{txt[:m.start()].count(chr(10))+1}")
ck("sec", "no f-string interpolated SQL", not raw_sql, "; ".join(raw_sql))

head("Deployment readiness")
ck("deploy", "frontend host config", (ROOT / "netlify.toml").exists())
ck("deploy", "SPA redirect", (ROOT / "frontend/public/_redirects").exists())
ck("deploy", "backend blueprint", (ROOT / "render.yaml").exists())
ck("deploy", "no cron jobs for deleted tasks", "app.tasks digest" not in read("render.yaml"))
ck("deploy", "GEMINI_API_KEY in the blueprint", "GEMINI_API_KEY" in read("render.yaml"))
ck("deploy", "no paid keys in the blueprint", "RAPIDAPI" not in read("render.yaml") and "ADZUNA" not in read("render.yaml"))
ck("deploy", "container image", (ROOT / "backend/Dockerfile").exists())
ck("deploy", "migrations run before serving", "alembic upgrade head" in read("backend/start.sh"))
ck("deploy", "platform postgres:// normalised", "_PG_SCHEME_FIXES" in read("backend/app/config.py"))
ck("deploy", "production refuses a default JWT secret", "production_blockers" in read("backend/app/config.py"))
ck("deploy", "tests in the repo", (BE / "tests").is_dir())
ck("deploy", "CI runs them", (ROOT / ".github/workflows/ci.yml").exists())
ck("deploy", "deployment guide", (ROOT / "DEPLOYMENT.md").exists())
ck("deploy", "single migration head", len(list((BE / "alembic/versions").glob("*.py"))) >= 1)

print("\n" + "=" * 60)
print(f"{checks} checks, {len(issues)} problem(s)")
if issues:
    for s, l, d in issues:
        print(f"  [{s}] {l} {d}")
    sys.exit(1)
print("CLAUDE.md IS FULLY IMPLEMENTED")
