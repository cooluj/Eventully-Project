# Eventully — Club Discovery for UW

A web platform that helps University of Washington students discover clubs from a real, 1,231-organization directory, matched to their interests, major, and time commitment — and lets club officers claim and run their own listing.

---

## What's here

This is a full rebuild of the original class project into a real, deployable application:

- **Real accounts** — email + hashed password (Flask-Login + Werkzeug), not just an email field
- **Persistent database** (SQLite by default, swaps to Postgres by setting one env var) — nothing resets when the server restarts
- **Club officer claiming** — any user can request to claim an unclaimed club; a site admin reviews and approves the request before handing over the listing
- **Officer tools** — claimed clubs can edit their description and post real events; students RSVP with live capacity tracking
- **A from-scratch, distinctive UI** — a "campus directory" visual language (catalog stamps, ticket-stub event cards, a route-map hero) instead of a generic template look
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
│   ├── auth.py                 # register / login / logout
│   ├── main.py                 # landing, onboarding, recommendations, dashboard
│   ├── clubs.py                 # browse, detail, join/leave, claim
│   ├── events.py                 # browse, detail, RSVP
│   ├── officer.py                 # club editing, event CRUD (claimed-club owners only)
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

**Club officers:** register like any student → find their club in the directory → submit a claim request with proof of their role → a site admin approves it → they get an "Officer" nav link to edit the club's description and post/manage events.

**Admins:** anyone whose email is listed in `ADMIN_EMAILS` sees an Admin nav link and can approve or reject pending claims at `/admin/claims`.

## Configuration (environment variables)

Set these in `.env` locally, or in your host's dashboard when deploying:

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies. **Must** be a real random value in production. | dev placeholder |
| `DATABASE_URL` | Set to a Postgres URL to move off SQLite (recommended once you have real users — see below). | local SQLite file |
| `ADMIN_EMAILS` | Comma-separated emails allowed to approve club claims. | `demo@uw.edu` |
| `REQUIRE_EDU_EMAIL` | Set `false` to allow non-`.edu` signups (useful for demoing outside UW). | `true` |
| `FLASK_DEBUG` | Never `true` in production. | `true` locally |

## Deploying it for real

**On SQLite and hosting:** SQLite is a single file on disk. Most free/cheap hosts (Render, Railway, Fly.io) wipe the filesystem on every deploy or restart unless you attach persistent storage — so SQLite will lose data on those tiers eventually. For a portfolio piece with real users, the cleanest path is:

1. Deploy on **Render.com** (has a real free Postgres tier) — recommended.
2. Set `DATABASE_URL` to the Postgres URL Render gives you. The app already handles both SQLite and Postgres with no code changes.

### Steps on Render

1. Push this project to a GitHub repo.
2. In Render: **New → Web Service**, connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variables: `SECRET_KEY` (generate one), `ADMIN_EMAILS` (your email), `FLASK_DEBUG=false`.
6. **New → PostgreSQL** (free tier), copy its "Internal Connection String" into the web service's `DATABASE_URL` variable.
7. After the first deploy, open the Render shell for your service and run:
   ```bash
   flask --app app seed-db
   ```
   This loads all 1,231 clubs into the new database (safe to re-run — it skips clubs that already exist).
8. Your app is live at the `.onrender.com` URL Render gives you. Add a custom domain under the service's Settings if you want one.

Railway and Fly.io work the same way — Postgres add-on, set `DATABASE_URL`, deploy.

## Notes for future work

- **Email verification** isn't implemented — accounts are created immediately on registration. For a public launch, add a verification-link step so club claims are harder to fake.
- **Password reset** isn't implemented yet.
- **Officer claim proof** is currently just a free-text message reviewed by a human admin. At scale, verifying against a UW club registry export would remove the manual step.
- **Images** for events are just URLs right now — swapping in real upload storage (e.g. S3 or Cloudinary) would let officers upload photos directly.

---

**Data source:** `clubs_categorized.csv` — 1,231 real UW registered student organizations, auto-categorized into 18 groups by keyword matching.
