# Eventully — Club Discovery for UW

A web platform that helps University of Washington students discover clubs from a real, 1,231-organization directory, matched to their interests, major, and time commitment — and lets club officers claim and run their own listing.

---

## What's here

This is a full rebuild of the original class project into a real, deployable application:

- **Real accounts** — email + hashed password (Flask-Login + Werkzeug), not just an email field
- **Persistent database** (SQLite by default, swaps to Postgres by setting one env var) — nothing resets when the server restarts
- **Club officer claiming** — any user can request to claim an unclaimed club; a site admin reviews and approves the request before handing over the listing
- **Officer tools** — claimed clubs can edit their description, invite co-officers, post events, manage RSVPs, and message club members
- **Account recovery** — email verification and password reset links are supported through SMTP-backed transactional email
- **A polished product UI** — dark launch surfaces, app-style dashboards, event capacity bars, and split-pane club messaging
- **Production-ready config** — gunicorn, a Procfile, environment-based secrets, error pages

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
| `SEED_DEMO_ACCOUNT` | Seeds `demo@uw.edu`. **Set `false` in production** — its password is public. | `true` |
| `EMAIL_VERIFICATION_REQUIRED` | When `true`, blocks unverified users from club claims and officer tools. Configure SMTP first. | `false` |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_USE_TLS` | SMTP settings for verification, reset, claim, team, and message notification emails. | disabled |

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
2. **New → Blueprint**, connect the repo. Render provisions the web service + a free Postgres database, generates `SECRET_KEY`, and wires everything automatically.
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
