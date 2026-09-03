# Eventully — Club Discovery for UW

A web platform that helps University of Washington students discover clubs from a real, 1,231-organization directory, matched to their interests, major, and time commitment — and lets club officers claim and run their own listing.

---

## What's here

This is a full rebuild of the original class project into a real, deployable application:

- **Real accounts** — email + hashed password (Flask-Login + Werkzeug), not just an email field
- **Real event dates** — one-time events with calendar dates and times, or weekly recurring ones; listings render as date-grouped timelines ("Today", "Tomorrow"), working Google Calendar / .ics buttons, and a personal calendar-subscription feed
- **Notifications** — in-app bell + unread badges; members hear about new events, cancellations, claim decisions, and team invites (email too when SMTP is configured)
- **Club officer claiming** — any user can request to claim an unclaimed club; admins get emailed, the claimant gets confirmations and a decision notification
- **Officer tools** — edit the listing, invite co-officers, post/cancel events (cancelling notifies attendees), manage RSVPs, and message club members with unread indicators
- **Scheduled jobs** — token-guarded `/tasks/reminders` (day-of event reminders) and `/tasks/digest` ("your clubs this week"), driven by a GitHub Actions schedule
- **A Luma-inspired design system** — light + dark themes, per-club tinted pages, timeline cards, installable PWA manifest, per-page OG cards, schema.org Event markup
- **Production-ready config** — gunicorn, a Procfile, environment-based secrets, error pages, CI running the test suite on every push

## Project structure

```
eventully/
├── app.py                  # App factory + entry point
├── config.py                # Env-driven configuration
├── extensions.py             # db / login_manager singletons
├── models.py                 # SQLAlchemy models
├── matching.py                # Club-matching scoring algorithm
├── seed.py                    # Loads clubs_categorized.csv + demo data
├── utils.py                   # Calendar link helper, weekday list
├── blueprints/
│   ├── auth.py                 # register / login / logout / verification / password reset
│   ├── main.py                 # landing, onboarding, recommendations, dashboard
│   ├── clubs.py                 # browse, detail, join/leave, claim
│   ├── events.py                 # browse, detail, RSVP
│   ├── messages.py              # member/officer club threads
│   ├── officer.py                 # club editing, team roles, event CRUD
│   └── admin.py                    # claim approvals (ADMIN_EMAILS only)
├── templates/                       # 19 Jinja templates
├── static/css/style.css              # Full design system
├── clubs_categorized.csv               # Source data (1,231 real UW clubs)
├── requirements.txt
├── Procfile                            # For gunicorn-based hosts
└── .env.example
```

## Running it locally

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Open .env and set SECRET_KEY to something random:
python3 -c "import secrets; print(secrets.token_hex(32))"

python3 app.py
```

Visit **http://127.0.0.1:5050**. On first run it creates `eventully.db` and loads all 1,231 clubs automatically. A demo account is seeded too:

- **Email:** `demo@uw.edu`
- **Password:** `demopass123`

That demo email is also the default site admin (see `ADMIN_EMAILS` below) — log in as it to review club-officer claim requests at `/admin/claims`.

## How the pieces fit together

**Students:** register → answer 3 onboarding questions → get a ranked, scored list of clubs → join clubs and RSVP to events → everything persists across visits.

**Club officers:** register like any student → verify email → find their club in the directory → submit a claim request with proof of their role → a site admin approves it → they can edit the listing, invite co-officers, message members, and post/manage events.

**Admins:** anyone whose email is listed in `ADMIN_EMAILS` sees an Admin nav link and can approve or reject pending claims at `/admin/claims`.

## Configuration (environment variables)

Set these in `.env` locally, or in your host's dashboard when deploying:

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies + CSRF tokens. **Must** be a real random value in production. | dev placeholder |
| `DATABASE_URL` | Set to a Postgres URL to move off SQLite (recommended once you have real users — see below). | local SQLite file |
| `ADMIN_EMAILS` | Comma-separated emails allowed to approve club claims. | `demo@uw.edu` |
| `REQUIRE_EDU_EMAIL` | Set `false` to allow non-`.edu` signups (useful for demoing outside UW). | `true` |
| `FLASK_DEBUG` | Never `true` in production. | `true` locally |
| `SECURE_COOKIES` | Set `true` in production (HTTPS) — marks session cookies Secure. | `false` |
| `AUTO_SEED` | Create tables + load the club directory on boot. Makes fresh deploys work with zero shell access. | `true` |
| `SEED_DEMO_ACCOUNT` | Seeds `demo@uw.edu` and the sample demo events. **Set `false` in production** — the password is public and the events are fictional. | `true` |
| `EMAIL_VERIFICATION_REQUIRED` | When `true`, blocks unverified users from club claims and officer tools. Configure SMTP first. | `false` |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_USE_TLS` | SMTP settings for verification, reset, claim, team, and message notification emails. | disabled |
| `TASKS_TOKEN` | Shared secret for the `/tasks/*` scheduled-job endpoints (digest + reminders). Generate with `python3 -c "import secrets; print(secrets.token_hex(24))"` and set the same value as a `TASKS_TOKEN` GitHub Actions secret so `scheduled-tasks.yml` can call them. Unset = the endpoints 404. | disabled |

### Production email

The app is wired for SMTP, but inbox delivery only works after you attach a provider in Render. A straightforward Resend setup is:

| Render key | Value |
| --- | --- |
| `MAIL_SERVER` | `smtp.resend.com` |
| `MAIL_PORT` | `587` |
| `MAIL_USERNAME` | `resend` |
| `MAIL_PASSWORD` | your Resend API key |
| `MAIL_FROM` | `Eventully <hello@your-verified-domain>` |
| `MAIL_USE_TLS` | `true` |

After saving those values, open `/admin/launch-readiness` as an admin and click **Send test email**. Only turn `EMAIL_VERIFICATION_REQUIRED=true` after the test email reaches your inbox.

### Custom domain

1. Buy the domain (Cloudflare Registrar sells at cost and its DNS handles the apex-CNAME problem; Porkbun/Namecheap also work).
2. In Render: service → **Settings → Custom Domains** → add the domain (and `www.` if you want it). Render shows the DNS records to add and provisions TLS automatically once they resolve.
3. In Resend: **Domains → Add Domain**, then add the SPF/DKIM records it lists at your DNS provider and hit Verify. Set `MAIL_FROM` to `Eventully <hello@yourdomain>`.
4. Set `CANONICAL_HOST` (e.g. `eventully.org`) in Render — every other host (like the `.onrender.com` URL) then 301s to it. `/healthz` is exempt so Render's health checks keep passing.

### Hosting plan

Production runs on Render's **Starter** instance ($7/mo — always on, no cold starts) with a paid **basic-256mb Postgres** (~$6/mo — daily backups, no free-tier expiry). Free-tier warnings from earlier iterations no longer apply; the old keep-warm Action has been retired. For uptime *alerts*, point a free UptimeRobot monitor at `/healthz`.

> History lesson (August 2026): the original free Postgres was auto-deleted at its 30-day limit and took the launch data with it. Free databases are fine for demos, never for a live site.

### Scheduled jobs (reminders + digest)

`/.github/workflows/scheduled-tasks.yml` calls the app daily (8am PT, day-of event reminders) and Sundays (9am PT, weekly digest). To enable: set `TASKS_TOKEN` on the Render service **and** add the same value as a repository Actions secret named `TASKS_TOKEN`. Users can opt out of the digest in Settings.

## Performance

Pages render server-side and are measured, not guessed. `scripts/perf_report.py`
seeds a throwaway database at production scale (all 1,231 clubs, 300 students,
220 events, thousands of RSVPs) and prints SQL statements and render time per
route for an anonymous visitor, a student, an officer, and an admin:

```bash
python scripts/perf_report.py
SHOW_SQL=/dashboard python scripts/perf_report.py   # the repeated statements behind one route
```

Run it before and after anything that touches queries or templates; a jump in
the `q` column is an N+1. Current numbers sit between 0 and 14 queries per
page. The things that keep it there:

- Many-to-one relationships every template touches (`event.club`, `rsvp.user`,
  `message.sender`, `club.officer`, ...) load with a JOIN.
- `load_attendee_previews()` fetches the face stacks for any number of events in
  one window-function query.
- The club matcher (all 1,231 clubs scored in Python) is memoized per user; the
  club count and category list are TTL-cached; the landing page is cached for
  ten minutes.
- Responses are Brotli/gzip compressed; static assets carry a content hash and a
  one-year immutable cache header; pages are `private, no-cache`.
- The events timeline pages one week at a time.

## Security

- All forms are CSRF-protected (Flask-WTF); passwords are hashed with PBKDF2-SHA256.
- Session/remember cookies are HttpOnly + SameSite=Lax, and Secure when `SECURE_COOKIES=true`.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) on every response.
- Officer routes verify club ownership or approved co-officer roles; admin routes verify against `ADMIN_EMAILS`.
- Club messages are limited to members, officers, and admins. Senders, officers, and admins can remove messages from normal views.

## Tests

```bash
.venv/bin/python -m pytest tests/
```

The end-to-end suite covers registration, login, email verification, password reset, onboarding + matching, join/leave, RSVP + capacity limits, the full claim → approve → officer lifecycle, co-officer access, messages, permission walls, and CSRF rejection.

## Deploying it for real (one click)

The repo includes a **`render.yaml` Blueprint**. On [Render.com](https://render.com):

1. Push this repo to GitHub.
2. **New → Blueprint**, connect the repo. Render provisions the Starter web service and generates `SECRET_KEY`. Create a **paid** Postgres instance separately and set `DATABASE_URL` to its internal connection string (free Render databases self-delete after 30 days).
3. When prompted, set `ADMIN_EMAILS` to **your** email — that's who approves club claims.
4. Configure SMTP env vars if you want verification/reset/notification email to send instead of logging.
5. First boot auto-creates tables and loads all 1,231 clubs (`AUTO_SEED`). Your app is live at the `.onrender.com` URL; add a custom domain in Settings if you want one.

Railway and Fly.io also work: add a Postgres add-on, set `DATABASE_URL` and the env vars above, start command `gunicorn --workers 1 --threads 8 --timeout 60 app:app`.

## Notes for future work

- **Officer claim proof** is currently human-reviewed free text plus admin notes. At scale, verifying against a UW club registry export would remove the manual step.
- **Images** for events are just URLs right now — swapping in real upload storage (e.g. S3 or Cloudinary) would let officers upload photos directly.
- **Email sending** requires SMTP environment variables. Without them, email bodies are logged for development.

---

**Data source:** `clubs_categorized.csv` — 1,231 real UW registered student organizations, auto-categorized into 18 groups by keyword matching.
