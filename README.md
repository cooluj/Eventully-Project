# Eventully — From Class Prototype to Live Campus Platform

**Live product:** https://eventully.org  
**Built by:** Ujjawal Agrawal

Eventully is a live platform for discovering and engaging with student organizations at the University of Washington. It turns a directory of **1,231 real UW clubs across 18 categories** into a product where students can discover organizations that fit them, join and save clubs, find events, RSVP, and message their communities — while officers can claim and manage their own presence.

What began as a class project became a much larger exercise in product ownership: redefining the problem, rebuilding the application, designing both student and officer workflows, implementing the system, testing edge cases, hardening it for production, and shipping it at **eventully.org**.

---

## Case study at a glance

**Problem:** Campus involvement is fragmented. Students have hundreds of organizations available to them, but knowing *what exists* is different from knowing *what fits*. Officers, meanwhile, need a reliable way to keep information current and turn discovery into actual participation.

**Users:** UW students looking for communities and club officers trying to manage them.

**My role:** Product strategy, UX research, interaction and visual design, full-stack development, information architecture, matching logic, testing, and deployment.

**Current state:** Live in production at [eventully.org](https://eventully.org).

**Production stack:** Python, Flask, SQLAlchemy, Jinja, JavaScript/CSS, PostgreSQL, Gunicorn, Render.

---

## Where it started

The earliest version of Eventully was a course project centered on a narrower problem: helping student organizations coordinate meetings and participation. I interviewed students and club officers, mapped scheduling and engagement workflows, prototyped the experience in Figma, and built an early implementation around availability, reminders, and participation.

That version was useful because it forced me to work through a real campus problem, but it also made something else obvious: scheduling is only one point in a much longer journey.

Before a student can attend an event, they have to find a club. Before an officer can improve participation, students have to know the organization exists. And if the product is going to mediate those relationships, it needs more than a polished prototype — it needs accounts, permissions, persistent data, trustworthy ownership, recovery flows, messaging, and all of the failure states that appear once real people can use it.

So I kept building after the class ended.

The first Java/MySQL prototype eventually became a broader production rebuild focused on **club discovery, engagement, and officer ownership**. The current application is written in Python/Flask with SQLAlchemy and a production PostgreSQL database.

---

## Reframing the problem

A directory of 1,231 clubs creates an interesting UX problem: the user often does not know what to search for.

Traditional search works well when someone already knows they want “Robotics Club” or “Chess Club.” It is less useful for the student whose actual question is:

> “I’m a CS student, I want something social but still related to tech, and I only have a few hours a week. What should I join?”

That changed the discovery flow from a simple searchable directory into a recommendation problem.

I designed onboarding around three pieces of intent:

1. **Interests / categories**
2. **Major**
3. **Desired time commitment**

The application then scores clubs against those preferences and gives the user understandable reasons for each recommendation.

I intentionally kept the matching logic interpretable. Category alignment receives the strongest weight, major-related keywords add additional relevance, and time-commitment language provides a smaller adjustment. Instead of returning a mysterious score alone, the interface can explain a match with reasons such as **“Technology club,” “Connects with Computer Science,”** or **“Fits your time commitment.”**

The current implementation roughly weights:

- category match: **55 points**
- major relevance: **up to 35 points**
- time-commitment fit: **10 points**

This is not meant to be a perfect model of human interests. It is a practical first system that produces useful, inspectable recommendations without pretending the algorithm knows more about the user than it does.

That tradeoff — useful enough to reduce a 1,231-item search space, but simple enough to understand and debug — was intentional.

---

## Designing both sides of the platform

Discovery only works if the information students find is useful and can stay current.

That created a second product problem: **who is allowed to manage a club?**

Giving every user edit access would make the directory unreliable. Manually maintaining 1,231 listings myself would not scale. Eventully therefore uses a claim-and-review model.

### Student flow

A student can:

**register → complete onboarding → receive recommendations → browse/search → save or join clubs → discover events → RSVP → view their dashboard/calendar → participate in club messaging**

Their memberships, saved clubs, preferences, and RSVPs persist across visits.

### Officer flow

A club officer starts as a normal user:

**register → verify identity/email → find the club → submit a claim with proof of role → wait for admin review → receive management access**

Once approved, an officer can:

- edit the club listing
- add co-officers with delegated roles
- create, edit, and remove events
- manage event capacity
- see attendees
- message members

### Admin flow

Admins review pending claims before control of a listing changes hands. That adds friction, but it is deliberate friction: ownership is a trust boundary, not just another button.

The product therefore has three overlapping permission models — student, officer, and administrator — rather than one universal account experience.

---

## Going beyond the happy path

The largest difference between the original prototype and the live product is not one headline feature. It is everything required for the product to continue working when the ideal flow stops being ideal.

Moving Eventully into production meant dealing with questions like:

- What happens when an event reaches capacity?
- Can someone access a private event by typing its URL directly?
- What happens when an officer adds a co-officer?
- Can a non-officer edit a club by manually posting to an endpoint?
- What happens when someone forgets their password?
- What if a club submits an unsafe URL such as a `javascript:` link?
- Should fictional demo events ever reach production?
- What happens when multiple campus users share the same public IP?
- How should the application behave behind Render's reverse proxy?
- What happens when an old deployment is accessed through the Render hostname instead of the canonical domain?

These are not separate from UX. They determine whether the interface can be trusted.

A few examples of changes that came out of production hardening:

- officer routes verify ownership or an approved co-officer role
- private events enforce membership on both the interface and direct routes
- event capacity is enforced server-side
- club URLs accept only safe HTTP(S) destinations
- registration and sensitive actions are rate-limited
- session cookies are hardened for production
- CSRF protection covers forms and state-changing actions
- demo accounts and fictional demo events are explicitly disabled in production
- canonical-host redirects keep the production product on `eventully.org`
- account verification and password reset can use transactional email

That work changed how I think about “finishing” a design. A screen can look resolved in Figma while the product behind it is still full of unanswered questions.

---

## What shipped

The current production application includes:

### Discovery
- 1,231 real UW student organizations
- 18 categories
- keyword search and category filtering
- personalized onboarding
- ranked club recommendations with human-readable reasons
- save, hide, join, and leave actions
- related-club discovery

### Events and engagement
- public and members-only events
- RSVP and un-RSVP flows
- capacity enforcement
- personal dashboard
- weekly calendar
- downloadable calendar events
- club messaging

### Officer tools
- club claiming
- admin approval workflow
- editable organization profiles
- co-officer roles
- event creation and management
- attendee views
- member communication

### Account and platform infrastructure
- persistent accounts and preferences
- password hashing
- email verification support
- password recovery
- role-based permissions
- production database
- health checks
- custom domain
- environment-based configuration
- automated tests

---

## Technical architecture

The application is organized around Flask blueprints so the major product areas remain separated as the system grows:

```
eventully/
├── app.py                    # App factory, middleware, error handling
├── config.py                 # Environment-driven configuration
├── extensions.py             # Database, login, CSRF extensions
├── models.py                 # SQLAlchemy data models
├── matching.py               # Recommendation scoring
├── seed.py                   # Loads the 1,231-club source dataset
├── notifications.py          # Transactional email helpers
├── utils.py                  # Calendar and shared helpers
├── blueprints/
│   ├── auth.py               # Registration, login, verification, recovery
│   ├── main.py               # Landing, onboarding, recommendations, dashboard
│   ├── clubs.py              # Browse, details, membership, claims
│   ├── events.py             # Events, RSVPs, calendar export
│   ├── messages.py           # Club conversations
│   ├── officer.py            # Officer editing, roles, event management
│   └── admin.py              # Claim review and launch tooling
├── templates/                # Server-rendered product UI
├── static/                   # Frontend styles and assets
├── clubs_categorized.csv     # UW organization dataset
├── tests/                    # End-to-end product tests
├── render.yaml               # Deployment configuration
└── requirements.txt
```

Local development uses SQLite for simplicity. Production uses PostgreSQL through `DATABASE_URL`, allowing the application code to remain environment-independent.

---

## Testing the product, not just the functions

I wanted the tests to represent real user behavior rather than only isolated helpers.

The end-to-end suite renders actual forms, extracts real CSRF tokens, submits requests like a browser, and checks the resulting application state.

Coverage includes:

- registration and login
- `.edu` account restrictions
- rate limiting
- email verification
- password reset
- onboarding and recommendations
- club search
- join/leave
- RSVP and capacity limits
- public vs. private event permissions
- club claim → admin approval → officer access
- co-officer permissions
- event creation/editing/deletion
- messaging permissions
- CSRF rejection
- profile/password settings
- canonical-domain behavior
- calendar export

The goal is not simply “tests pass.” The goal is to make it harder for a future change to quietly break a workflow a user depends on.

---

## What I learned

### 1. The product can outgrow the first problem statement

The original scheduling concept was not wasted work. It was the starting point that exposed a larger system around discovery, ownership, and participation.

Continuing after the class ended forced me to decide which parts of the original idea still mattered and which assumptions needed to change.

### 2. Designing permissions is designing UX

Officer claims, co-officer roles, private events, admin review, and message access all look like backend concerns until they fail. Then they become very visible user problems.

I learned to treat authorization rules as part of the interaction model, not an implementation detail added afterward.

### 3. Production exposes questions prototypes hide

A prototype can assume the database exists, the user has permission, the request succeeds, and the input is valid. A production product cannot.

The more I worked on Eventully, the less I thought of implementation as a translation of design and the more I saw it as another place where product decisions are made.

### 4. Explainable systems are easier to improve

The recommendation system is deliberately understandable. I can inspect why a club was ranked, change a weight, reproduce the result, and explain it to someone else.

That mattered more to me at this stage than making the matching system more sophisticated but less legible.

---

## Current limitations and next steps

Eventully is live, but I do not consider it finished.

Some areas I would improve next:

- **Officer verification:** claims are currently reviewed manually; a trusted UW registry integration would make verification more scalable.
- **Event media:** event images currently use URLs; direct object-storage uploads would be a better officer experience.
- **Recommendation quality:** the current matcher is deterministic and intentionally simple. With enough real usage data, I would evaluate where the ranking fails before increasing model complexity.
- **Participation feedback:** better aggregate engagement signals could help officers understand which events and communications are actually useful without exposing individual student behavior unnecessarily.
- **Operational maturity:** production monitoring and database migrations should become more formal as usage grows.

The point of listing these is not to make the product sound incomplete. It is the opposite: shipping it made the remaining tradeoffs concrete enough to prioritize.

---

## AI-assisted development

I used AI-assisted development tools during parts of Eventully's implementation, debugging, security review, and documentation work. I treated generated output as a starting point rather than an authority: I reviewed changes, tested behavior, corrected failures, and remained responsible for the product and technical decisions.

Several commits explicitly preserve AI co-authorship metadata where applicable.

---

# Developer reference

The sections below cover local setup and production configuration for anyone who wants to inspect or run the application.

## Local development

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"

python3 app.py
```

Visit **http://127.0.0.1:5050**.

On first run, the application creates a local SQLite database and loads all 1,231 clubs automatically.

When `SEED_DEMO_ACCOUNT=true`, local development also includes:

- **Email:** `demo@uw.edu`
- **Password:** `demopass123`

The demo account and fictional sample events are intentionally disabled in production.

---

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies and CSRF tokens. Use a random secret in production. | development placeholder |
| `DATABASE_URL` | Production database connection. | local SQLite |
| `ADMIN_EMAILS` | Emails allowed to review club claims. | `demo@uw.edu` |
| `REQUIRE_EDU_EMAIL` | Restricts registration to `.edu` addresses. | `true` |
| `FLASK_DEBUG` | Flask debug mode. Never enable in production. | `true` locally |
| `SECURE_COOKIES` | Adds Secure to session/remember cookies. | `false` locally |
| `AUTO_SEED` | Creates tables and loads the club directory on boot. | `true` |
| `SEED_DEMO_ACCOUNT` | Adds the documented demo account and sample events. | `true` locally |
| `EMAIL_VERIFICATION_REQUIRED` | Requires verification for officer tools/claims. | `false` |
| `CANONICAL_HOST` | Redirects alternate hosts to the production domain. | unset |
| `MAIL_*` | SMTP configuration for transactional email. | disabled |

---

## Production email

SMTP-backed email supports verification, password reset, club claims, team updates, and message notifications.

Example Resend configuration:

| Key | Value |
|---|---|
| `MAIL_SERVER` | `smtp.resend.com` |
| `MAIL_PORT` | `587` |
| `MAIL_USERNAME` | `resend` |
| `MAIL_PASSWORD` | Resend API key |
| `MAIL_FROM` | verified sender |
| `MAIL_USE_TLS` | `true` |

---

## Production deployment

Eventully is currently deployed at **https://eventully.org**.

The repository includes a `render.yaml` Blueprint. A reproducible deployment requires:

1. a Python web service
2. a PostgreSQL database
3. `SECRET_KEY`
4. `DATABASE_URL`
5. the appropriate admin and email environment variables
6. Gunicorn using:
   ```
   gunicorn --workers 1 --threads 8 --timeout 60 app:app
   ```
7. `/healthz` as the platform health check
8. `CANONICAL_HOST=eventully.org` for the production domain

The application can also run on another Python-compatible platform with PostgreSQL and the same environment variables.

---

## Security notes

- CSRF protection on state-changing forms
- PBKDF2-SHA256 password hashing
- HttpOnly and SameSite session cookies
- Secure cookies in production
- `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers
- role/ownership checks for officer routes
- explicit admin authorization
- private-event membership checks
- restricted club-message access
- HTTP(S)-only club website URLs
- rate limiting on sensitive flows

---

## Data

The source dataset in `clubs_categorized.csv` contains **1,231 University of Washington registered student organizations**, categorized into **18 groups** for browsing and recommendation.

---

If you are reviewing this repository as part of my work, the fastest way to understand Eventully is to use the live product first and then return here to see how the product decisions are represented in the implementation.
