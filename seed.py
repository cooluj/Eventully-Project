"""Seed the database with real UW clubs from clubs_categorized.csv, plus a
handful of demo events and a demo account so reviewers can explore the app
without registering."""
import csv
import os

from extensions import db
from models import Club, Event, User

CSV_PATH = os.path.join(os.path.dirname(__file__), "clubs_categorized.csv")

DEMO_EVENTS = [
    {"club": "Advanced Robotics at the University of Washington", "name": "Intro to Machine Learning Workshop",
     "description": "Learn the basics of ML with hands-on coding.", "weekday": "Monday", "time": "18:00",
     "location": "CSE 003", "capacity": 60,
     "image_url": "https://images.unsplash.com/photo-1555255707-c07966088b7b?w=800"},
    {"club": "Active Minds at the University of Washington", "name": "Mental Health Awareness Fair",
     "description": "Join us for activities and resources.", "weekday": "Tuesday", "time": "17:00",
     "location": "HUB 214", "capacity": 100,
     "image_url": "https://images.unsplash.com/photo-1544027993-37dbfe43562a?w=800"},
    {"club": "Women's Club Soccer at UW", "name": "Spring Championship Match",
     "description": "Come cheer on the team in the spring championship games.", "weekday": "Saturday",
     "time": "14:00", "location": "IMA Field", "capacity": 150,
     "image_url": "https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=800"},
]


def seed_clubs():
    """Insert clubs from the CSV that aren't already in the database. Returns count added."""
    existing_names = {c.name for c in Club.query.with_entities(Club.name).all()}
    added = 0

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Club"].strip()
            if not name or name in existing_names:
                continue
            db.session.add(Club(
                name=name,
                description=row.get("Description", "").strip(),
                category=row.get("Category", "General Interest").strip() or "General Interest",
            ))
            existing_names.add(name)
            added += 1

    db.session.commit()

    # Demo account
    if not User.query.filter_by(email="demo@uw.edu").first():
        demo = User(email="demo@uw.edu", name="Demo Student", university="University of Washington")
        demo.set_password("demopass123")
        db.session.add(demo)
        db.session.commit()

    # A few sample events so the Events page isn't empty on first run
    if Event.query.count() == 0:
        for e in DEMO_EVENTS:
            club = Club.query.filter_by(name=e["club"]).first()
            if not club:
                continue
            db.session.add(Event(
                club_id=club.id,
                name=e["name"],
                description=e["description"],
                weekday=e["weekday"],
                time=e["time"],
                location=e["location"],
                image_url=e["image_url"],
                capacity=e["capacity"],
                is_public=True,
            ))
        db.session.commit()

    return added
