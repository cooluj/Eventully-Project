"""Per-route query counts and render times against a realistic database.

    python scripts/perf_report.py            # seed a temp DB, print the table
    SHOW_SQL=/dashboard python scripts/perf_report.py

Seeds all 1,231 clubs plus 300 students, 60 claimed clubs, 220 events,
RSVPs, memberships, and messages into a throwaway SQLite file, then hits
every route as an anonymous visitor, a student, an officer, and an admin,
counting SQL statements per request. Use it before and after a change that
touches queries or templates; a jump in the q column is an N+1.
"""
import os
import random
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DB_PATH = os.path.join(tempfile.mkdtemp(prefix="eventully-perf-"), "perf.db")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{DB_PATH}", "AUTO_SEED": "false", "SEED_DEMO_ACCOUNT": "false",
    "ADMIN_EMAILS": "admin@uw.edu", "SECRET_KEY": "perf-secret", "FLASK_DEBUG": "false",
})

from sqlalchemy import event as sa_event  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import (Club, ClubMessage, ClubRole, Event, Membership, Notification, RSVP,  # noqa: E402
                    User, UserPreference)
from seed import seed_clubs  # noqa: E402
from utils import WEEKDAYS, campus_now  # noqa: E402


def seed(app):
    random.seed(7)
    with app.app_context():
        db.create_all()
        seed_clubs()
        clubs = Club.query.order_by(Club.id).all()
        pw = generate_password_hash("testpass123", method="pbkdf2:sha256")
        users = [User(email=f"student{i}@uw.edu", name=f"Student {i}", password_hash=pw) for i in range(1, 301)]
        fixtures = {k: User(email=f"{k}@uw.edu", name=k.title(), password_hash=pw) for k in ("student", "officer", "admin")}
        users += list(fixtures.values())
        db.session.add_all(users)
        db.session.commit()
        cats = sorted({c.category for c in clubs})
        for u in users:
            db.session.add(UserPreference(user_id=u.id, categories=",".join(random.sample(cats, 3)),
                                          major="Computer Science", time_commitment="medium"))
        claimed = random.sample(clubs, 60)
        for idx, club in enumerate(claimed):
            club.officer_id = users[idx].id
            club.claimed_at = club.updated_at = datetime.utcnow() - timedelta(days=random.randint(1, 60))
        claimed[0].officer_id = claimed[1].officer_id = fixtures["officer"].id
        for club in claimed[2:12]:
            db.session.add(ClubRole(club_id=club.id, user_id=random.choice(users).id))
        db.session.commit()
        now = campus_now()
        events = []
        for n in range(220):
            club = random.choice(claimed)
            kind = "weekly" if n < 120 else ("upcoming" if n < 190 else "past")
            ev = Event(club_id=club.id, name=f"Event {n}", description="Bring a friend. " * 8,
                       location="HUB 145", capacity=random.choice([20, 40, 60, 100, 300]),
                       is_public=random.random() < 0.8, created_by=club.officer_id)
            if kind == "weekly":
                ev.weekday, ev.time = random.choice(WEEKDAYS), random.choice(["17:00", "18:00", "19:00"])
            else:
                delta = random.randint(0, 30) if kind == "upcoming" else -random.randint(1, 60)
                start = (now + timedelta(days=delta)).replace(hour=18, minute=0, second=0, microsecond=0)
                ev.starts_at, ev.ends_at = start, start + timedelta(hours=2)
                ev.weekday, ev.time = start.strftime("%A"), "18:00"
            if n % 23 == 0:
                ev.status = "cancelled"
            events.append(ev)
        db.session.add_all(events)
        db.session.commit()
        for u in users:
            for club in set(random.sample(claimed, random.randint(2, 6))):
                db.session.add(Membership(user_id=u.id, club_id=club.id))
        # The student fixture belongs to the officer fixture's club so the
        # thread route measures as a member.
        if not any(m.club_id == claimed[0].id for m in fixtures["student"].memberships):
            db.session.add(Membership(user_id=fixtures["student"].id, club_id=claimed[0].id))
        db.session.commit()
        for ev in events:
            for u in random.sample(users, min(ev.capacity, random.randint(0, 40))):
                db.session.add(RSVP(event_id=ev.id, user_id=u.id))
        db.session.commit()
        for club in claimed[:30]:
            senders = [m.user_id for m in club.memberships] + [club.officer_id]
            for k in range(random.randint(15, 60)):
                db.session.add(ClubMessage(club_id=club.id, sender_id=random.choice(senders), body=f"Message {k}",
                                           created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 500))))
        for u in users:
            for k in range(random.randint(0, 10)):
                db.session.add(Notification(user_id=u.id, kind="event", title=f"Update {k}", link="/events",
                                            read_at=None if k % 2 else datetime.utcnow()))
        db.session.commit()
        busy = max((e for e in events if e.status == "active" and e.is_public), key=lambda e: e.attendee_count)
        return claimed[0].id, busy.id


def main():
    app = create_app()
    officer_club, busy_event = seed(app)
    counter = {"n": 0, "sql": []}
    with app.app_context():
        @sa_event.listens_for(db.engine, "before_cursor_execute")
        def _count(conn, cursor, statement, parameters, context, executemany):
            counter["n"] += 1
            counter["sql"].append(statement)

    token_re = re.compile(r'name="csrf_token" value="([^"]+)"')

    def client_for(email):
        c = app.test_client()
        if email:
            token = token_re.search(c.get("/login").get_data(as_text=True)).group(1)
            r = c.post("/login", data={"csrf_token": token, "email": email, "password": "testpass123"})
            assert r.status_code == 302, (email, r.status_code)
        return c

    routes = {
        None: ["/", "/events", "/clubs", "/clubs?sort=members", f"/club/{officer_club}", f"/event/{busy_event}",
               "/search?q=robot", "/about", "/help", "/login", "/claim", "/sitemap.xml"],
        "student@uw.edu": ["/dashboard", "/events", "/calendar", "/recommendations", "/notifications",
                           "/messages", f"/messages/club/{officer_club}", "/settings", f"/club/{officer_club}",
                           f"/event/{busy_event}", "/search?q=event"],
        "officer@uw.edu": ["/officer/", f"/officer/club/{officer_club}/edit", f"/officer/club/{officer_club}/members"],
        "admin@uw.edu": ["/admin/claims", "/admin/launch-readiness"],
    }
    print(f"{'role':8} {'path':40} {'st':>3} {'q':>4} {'ms':>7} {'KB':>4}")
    show = os.environ.get("SHOW_SQL", "")
    for who, paths in routes.items():
        c = client_for(who)
        for path in paths:
            times, sql = [], []
            for _ in range(5):
                counter["n"], counter["sql"] = 0, []
                t0 = time.perf_counter()
                r = c.get(path)
                times.append((time.perf_counter() - t0) * 1000)
                sql, queries, size, status = list(counter["sql"]), counter["n"], len(r.data), r.status_code
            print(f"{(who or 'anon').split('@')[0]:8} {path:40} {status:3} {queries:4} {statistics.median(times):7.1f} {size // 1024:4}")
            if show and any(o in path for o in show.split(",")):
                from collections import Counter
                for stmt, n in Counter(" ".join(x.split())[:160] for x in sql).most_common(10):
                    print(f"           {n:3}x {stmt}")


if __name__ == "__main__":
    main()
