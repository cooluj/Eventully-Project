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
     "description": "Learn the basics of ML with hands-on coding. Bring a laptop — we'll have starter notebooks ready. Beginners genuinely welcome; you'll train your first model before you leave.",
     "weekday": "Monday", "time": "18:00", "location": "CSE2 G001", "capacity": 60,
     "image_url": "https://images.unsplash.com/photo-1555255707-c07966088b7b?w=800"},
    {"club": "Active Minds at the University of Washington", "name": "Mental Health Awareness Fair",
     "description": "An afternoon of de-stress activities, therapy-dog visits, and resources from campus counseling. Free snacks while they last.",
     "weekday": "Tuesday", "time": "17:00", "location": "HUB 214", "capacity": 100,
     "image_url": "https://images.unsplash.com/photo-1544027993-37dbfe43562a?w=800"},
    {"club": "Women's Club Soccer at UW", "name": "Spring Championship Match",
     "description": "Come cheer on the team in the spring championship. Wear purple. Loud is encouraged.",
     "weekday": "Saturday", "time": "14:00", "location": "IMA Field 1", "capacity": 150,
     "image_url": "https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=800"},
    {"club": "DubHacks", "name": "Hack Night: Build Something Silly",
     "description": "No pitch decks, no prizes, no pressure — two hours to build the dumbest thing you can think of with people who love building. Demos at 9.",
     "weekday": "Thursday", "time": "19:00", "location": "CSE 403", "capacity": 80,
     "image_url": "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?w=800"},
    {"club": "Data Science Society at UW", "name": "Industry Panel: Breaking into Data",
     "description": "Analysts and data scientists from Seattle companies talk internships, portfolios, and what actually gets you hired. Q&A + networking after.",
     "weekday": "Wednesday", "time": "18:30", "location": "PAA A102", "capacity": 120,
     "image_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=800"},
    {"club": "Chess Club at UW", "name": "Casual Blitz Night",
     "description": "5+0 blitz, all ratings. Boards provided, bring nothing but hubris.",
     "weekday": "Friday", "time": "17:30", "location": "HUB 145", "capacity": 40,
     "image_url": "https://images.unsplash.com/photo-1529699211952-734e80c4d42b?w=800"},
    {"club": "Game Development Club", "name": "48-Hour Game Jam Kickoff",
     "description": "Theme reveal Friday night, demos Sunday. Artists, musicians, writers, and programmers all needed — teams form at the kickoff.",
     "weekday": "Friday", "time": "18:00", "location": "CSE2 271", "capacity": 70,
     "image_url": "https://images.unsplash.com/photo-1556438064-2d7646166914?w=800"},
    {"club": "Anime Nation at the University of Washington", "name": "Spring Showcase Screening",
     "description": "Member-voted lineup on the big lecture-hall screen. Snacks provided, cosplay encouraged, spoilers forbidden.",
     "weekday": "Wednesday", "time": "19:00", "location": "KNE 130", "capacity": 200,
     "image_url": "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=800"},
    {"club": "Dubshot Photography Club", "name": "Golden Hour Photo Walk",
     "description": "Sunset walk through the Quad and Rainier Vista. Any camera counts — phones included. We'll cover composition basics as we go.",
     "weekday": "Sunday", "time": "18:30", "location": "Meet at Drumheller Fountain", "capacity": 30,
     "image_url": "https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=800"},
    {"club": "Climbing Club at the University of Washington", "name": "Beginner Bouldering Session",
     "description": "First time on a wall? Perfect. Intro to technique and safety, then open climb. Rental shoes covered for members.",
     "weekday": "Tuesday", "time": "19:00", "location": "Crags Climbing Center (IMA)", "capacity": 25,
     "image_url": "https://images.unsplash.com/photo-1522163182402-834f871fd851?w=800"},
    {"club": "Debate Society at the University of Washington", "name": "Public Debate: This House Would...",
     "description": "Our monthly open-floor debate. Motion announced at the door; audience votes the winner. Heckling within reason.",
     "weekday": "Thursday", "time": "18:00", "location": "SAV 264", "capacity": 90,
     "image_url": "https://images.unsplash.com/photo-1475721027785-f74eccf877e2?w=800"},
    {"club": "Furmata A Cappella", "name": "Open Rehearsal + Auditions",
     "description": "Sit in on a full rehearsal, then stay to audition if you're feeling brave. All voice parts, no sheet-music experience needed.",
     "weekday": "Monday", "time": "19:30", "location": "Music Building 213", "capacity": 35,
     "image_url": "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=800"},
    {"club": "American Constitution Society", "name": "Pizza & Policy: Supreme Court Roundup",
     "description": "Law students break down this term's biggest cases in plain English. Free pizza, spicy takes.",
     "weekday": "Wednesday", "time": "17:00", "location": "William H. Gates Hall 133", "capacity": 60,
     "image_url": "https://images.unsplash.com/photo-1589994965851-a8f479c573a9?w=800"},
    {"club": "Awaaz at UW", "name": "Spring Culture Night",
     "description": "An evening of South Asian music, dance, and food. Performances from student groups across campus — bring friends.",
     "weekday": "Saturday", "time": "18:00", "location": "Meany Hall", "capacity": 250,
     "image_url": "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=800"},
    {"club": "Information Consulting Group", "name": "Case Interview Crash Course",
     "description": "Market sizing, frameworks, and a live mock case with feedback. Ideal prep if you're recruiting for consulting this fall.",
     "weekday": "Sunday", "time": "15:00", "location": "DEM 104", "capacity": 45,
     "image_url": "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=800"},
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

    # Demo account (publicly documented password — keep out of production)
    from flask import current_app
    if current_app.config["SEED_DEMO_ACCOUNT"] and not User.query.filter_by(email="demo@uw.edu").first():
        demo = User(email="demo@uw.edu", name="Demo Student", university="University of Washington")
        demo.set_password("demopass123")
        db.session.add(demo)
        db.session.commit()

    # Sample events so the Events page isn't empty on first run.
    # Idempotent per event: safe to re-run after adding new demo events.
    existing_events = {e.name for e in Event.query.with_entities(Event.name).all()}
    for e in DEMO_EVENTS:
        if e["name"] in existing_events:
            continue
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
