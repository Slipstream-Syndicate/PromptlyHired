# CLAUDE.md — JobTrail (working name)

## What this is
A job search + application tracker. Two core jobs:
1. Browse job listings, mark companies as favorites.
2. Track every job you've applied to and its current status.

Accessible from any device (phone, laptop, tablet) through one deployed web app — no separate native builds. Built as a PWA so it can be installed on a phone home screen and still get push notifications where the platform allows it.

---

## Architecture decision (why web app, not native apps)

The backend holds real persistent state (Postgres, not local JSON/localStorage). The frontend is deployed, not run locally. That means the same URL + same session works from any browser on any device — mobile, desktop, tablet — the moment it's live. No "port to iOS" / "port to Android" step needed for 90% of the functionality.

**Caveat: notifications are the one place this breaks down.** Browser tabs don't get push notifications unless the app is a PWA (installed, with a service worker). Even then:
- Android: web push works close to native.
- iOS: web push only fires if the user has "Added to Home Screen" — won't work in a normal open Safari tab, and needs iOS 16.4+.
- Desktop: fine as long as the browser process is around.

**Decision:** Build as an installable PWA from day one. Back notifications with email as the reliable fallback channel, web push as the enhancement — not the only channel. Don't block MVP on push notification plumbing.

**No native iOS/Android apps.** One React codebase, one deployment, one URL. Cross-platform coverage comes entirely from responsive design + PWA install, not separate builds. Native (React Native etc.) would triple maintenance surface (mobile app + web frontend + backend) and add app store review overhead for no meaningful gain on a solo/portfolio project.

**Cross-platform plan:**
1. Build as a responsive React web app — one set of components, CSS breakpoints handle mobile vs desktop layout. Not a separate mobile version.
2. Add PWA foundation from week one, not as a later bolt-on: `manifest.json` (name, icons, theme color) + service worker (asset caching, offline shell, push notification handling). Responsive breakpoints and the service worker need to be in place from the first commits — retrofitting this after the fact means redoing layout work.
3. Deploy once to one URL (Netlify/Vercel).

Per-device experience:
- **PC/laptop:** opens the URL, normal website, nothing extra needed.
- **Android:** opens URL in Chrome, gets an automatic "Install app" prompt (PWA), installs full-screen with an icon, gets push notifications.
- **iOS:** opens URL in Safari, user manually does Share → "Add to Home Screen." Same full-screen result. Push notifications only work after this install step, and only on iOS 16.4+ — this is a platform limitation, not something to build around.

Updates ship instantly to every device on push to the frontend — no app store review/waiting period.

---

## Tech stack

- **Frontend:** React + Vite, deployed on Netlify or Vercel. PWA manifest + service worker configured from the start.
- **Backend:** FastAPI (Python), deployed on Railway or Render.
- **Database:** Postgres.
- **Auth:** JWT, email/password only for MVP. No OAuth yet — not the hard part of this project, don't spend time here early.
- **Notifications:** Email digest (cron/scheduled job) as the baseline. Web push added later as enhancement, once core product works.
- **Job data source:** JSearch (via RapidAPI) — wraps Google for Jobs, which aggregates from LinkedIn, Indeed, Glassdoor, ZipRecruiter etc. Gives LinkedIn/Indeed-sourced listings legally, without scraping (scraping those sites directly violates ToS and gets IPs blocked). Free tier sufficient for MVP. Adzuna API as a backup/secondary source if JSearch coverage or rate limits fall short.

---

## Data model (draft)

**User**
- id, email, password_hash, name, profile_picture_url, created_at
- job_preferences → see JobPreferences below (same record drives both profile display and homepage auto-search)

**Company**
- id, name, logo_url (optional)

**Job**
- id, company_id (FK), title, location, salary_range, url, posted_date, description, source_api (which API the listing came from), external_id (source's own listing ID, for dedup), source_publisher (the board the listing actually lives on — LinkedIn, Indeed, Glassdoor, the company's own careers page)
- `url` is the **direct apply link** for the original posting, not an internal detail page. It is a required, load-bearing field: the app never hosts applications itself, so this link is the only route a user has to actually apply. A listing with no usable apply link is close to worthless to the user.
- `source_publisher` exists so the UI can name the destination before the user leaves ("Apply on LinkedIn") rather than sending them to an unlabelled external site.

**JobPreferences** (shared schema — same fields used for profile defaults AND homepage search filters)
- title/keywords, location, salary_min, salary_max, job_type (full-time/part-time/contract/remote)
- Stored once per user as their profile preferences. Homepage search filter UI reads/writes the exact same fields, so: on login, homepage auto-runs a search using these stored values; if the user changes filters on the homepage, that becomes their new saved preference (single source of truth, no drift between "what's in my profile" and "what I actually search with").

**Follow** (company-level — drives notifications only)
- id, user_id (FK), company_id (FK), created_at

**SavedJob** (job-level — shortlist, shows on Saved tab, no notification behavior)
- id, user_id (FK), job_id (FK), saved_at

**Application**
- id, user_id (FK), job_id (FK), status, applied_date, status_updated_at, notes

**Application status states** (toggle/click through once a job moves from Saved to actually applied):
- Applied
- Online Assessment
- Interview
- Offer
- Rejected
- Withdrawn

Note: "Saved" is no longer a status within Application — it's the separate SavedJob entity (shortlist, pre-application). A job moves from the Saved tab into the Applications tab (as a new Application record, status = Applied) once the user actually applies.

---

## Core UI structure (inspired by Indeed app screenshots)

**Bottom nav — 4 pages** (kept at 4 to match Indeed's own nav density, avoid crowding):

1. **Homepage** — search bar + filters (title/keywords, location, salary, job type). On login, auto-runs a search using the user's stored JobPreferences. Results are ranked in two sections: **"New from companies you follow"** pinned at the top, then the rest of the general search results below. User can adjust filters beyond their defaults; changing filters updates their stored preferences (shared schema, see Data Model). Each listing has a **Save** toggle (heart icon), a **Follow company** action — independent state, not a combined toggle — and an **Apply** link.

   **Apply link (required on every listing, everywhere a job is shown).** Every job card must carry a clear, prominent outbound link to the original posting so the user can go and fill in the real application on the source site. This app tracks applications; it does not host them, so this link is the entire point of the browse flow — a listing the user cannot act on is dead weight. Requirements:
   - Opens in a new tab (`target="_blank"` with `rel="noopener noreferrer"`), so the user does not lose their place in the feed.
   - Labelled with the destination where known — "Apply on LinkedIn" / "Apply on Indeed" — using `source_publisher`, falling back to a generic "Apply" when the publisher is unknown.
   - Visually distinct from Save/Follow: it is the primary action on the card, not a third equal-weight toggle.
   - Present on the Homepage feed, the Saved Jobs page **and** the Applications page — after applying, the user still needs to get back to the posting to check status or re-read the description.
   - Degrades gracefully: if a listing arrives with no `url`, the button is disabled/hidden rather than rendering a dead link.

2. **Saved Jobs** — dedicated page. All jobs the user has saved but not yet applied to. Shortlist view.

3. **Applications** — dedicated page. Jobs the user has applied to, each with a clickable/toggleable status badge: Applied → OA → Interview → Offer / Rejected / Withdrawn.

4. **Profile** — name, email, profile picture, job preferences (same fields as homepage search filters), account settings. Includes a link to:
   - **Followed Companies** (sub-page, not bottom nav) — list of companies the user follows, with an unfollow option. Low-frequency page (set once, mostly just generates notifications afterward) so it lives one tap into Profile rather than taking a permanent nav slot.

**Notifications** — triggered only by companies the user has explicitly Followed (not by saved jobs). New listing from a followed company → email (MVP) / push (later), and also surfaces at the top of the homepage feed.

---

## Build phases

**Phase 1 — MVP**
- Auth (signup/login)
- Homepage: job listing feed from JSearch API, search + filters, auto-search on login using stored JobPreferences, followed-company listings ranked/pinned above general results
- Save a job (shortlist) and Follow a company (notifications) as separate, independent actions
- Outbound **Apply** link on every listing (Homepage, Saved, Applications), labelled with the source board where known — the only route from browsing to actually applying
- Saved Jobs page and Applications page (separate pages, both with status/shortlist views)
- Followed Companies sub-page (accessible from Profile)
- Email notification for new jobs from followed companies

**Phase 2 — PWA + polish**
- Installable PWA (manifest, service worker, offline shell)
- Web push notifications
- Profile page: profile picture upload, job preferences editing
- Search/filter improvements

**Phase 3 — Nice-to-haves**
- Additional job source integrations (e.g. Adzuna) for broader coverage
- Analytics on your own application funnel (e.g. response rate by company/status)
- Reminders (e.g. "no update in 2 weeks, follow up?")

---

## Security considerations

**Application security (relevant now, Phase 1):**
- Password hashing via bcrypt/argon2 — never store plaintext, never roll your own hashing.
- JWT with short expiry + refresh token pattern, not long-lived tokens.
- Parameterized queries / ORM (SQLAlchemy) only — no raw string-interpolated SQL, closes SQL injection.
- Input validation on every endpoint (Pydantic models in FastAPI handle this well) — reject malformed data at the API boundary, don't trust client-side validation alone.
- Rate limiting on auth endpoints (login/signup) to block brute-force attempts.
- CORS locked to your actual frontend domain, not wildcard `*`.
- HTTPS everywhere — Netlify/Vercel and Railway/Render give this by default, just don't disable it.
- Sanitize any user-generated text rendered back in the UI (job notes, preferences) to prevent stored XSS.

**Prompt injection (only relevant if/when an AI feature is added — no LLM-facing user input exists in the current scope):**
This app currently has no feature where user input gets passed to an LLM (no AI resume matching, no AI-generated cover letters, etc.). Prompt injection risk only applies the moment such a feature is added — flagging it here so it's designed in from the start rather than retrofitted:
- Never concatenate raw user input directly into a system prompt — treat all user-supplied text (job descriptions pulled from the API, user notes, preferences) as untrusted data, not instructions.
- If an AI feature is added later (e.g. AI job-match scoring, auto-generated application notes), keep user data in a clearly delimited/quoted block within the prompt, and instruct the model explicitly to treat that block as data, not commands.
- Don't let LLM output directly trigger side-effectful actions (e.g. auto-submitting an application, auto-emailing) without a human confirmation step in between — this is the same "explicit permission for side effects" pattern that should apply anywhere AI output could take an action on the user's behalf.
- If pulling job descriptions from JSearch/Adzuna and ever feeding them to an LLM (e.g. for summarization), remember that listing content is external, unvalidated text — same untrusted-input treatment applies.

---

## Open decisions (need input before building)

- App name (JobTrail is a placeholder).
- Profile picture storage: use an S3-compatible service (e.g. Cloudflare R2, free tier) rather than local disk on Render/Railway — local storage on most of these platforms doesn't persist across redeploys, so files get wiped. Lightweight either way since it's just one image per user, no resumes or other files.
