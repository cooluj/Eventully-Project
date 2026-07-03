"""End-to-end tests for every user flow, run against an in-memory database
with CSRF protection enabled (tokens are pulled from the rendered forms,
exactly like a browser would)."""
import re

import pytest

from app import create_app
from config import Config
from extensions import db
from models import Club, Event, Membership, RSVP, User


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    AUTO_SEED = False
    SEED_DEMO_ACCOUNT = False
    REQUIRE_EDU_EMAIL = True
    ADMIN_EMAILS = {"admin@uw.edu"}
    SECRET_KEY = "test-key"


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Club(name="Robotics Club", description="We build robots weekly.", category="Technology"),
            Club(name="Chess Society", description="Casual and competitive chess.", category="Games"),
            Club(name="Hiking Club", description="Weekend hikes around WA.", category="Sports & Recreation"),
        ])
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def get_token(client, path):
    html = client.get(path).get_data(as_text=True)
    match = TOKEN_RE.search(html)
    assert match, f"no CSRF token found on {path}"
    return match.group(1)


def register(client, email="student@uw.edu", name="Test Student", password="testpass123"):
    token = get_token(client, "/register")
    return client.post("/register", data={
        "csrf_token": token, "email": email, "name": name,
        "password": password, "confirm_password": password,
    }, follow_redirects=True)


def login(client, email, password="testpass123"):
    token = get_token(client, "/login")
    return client.post("/login", data={
        "csrf_token": token, "email": email, "password": password,
    }, follow_redirects=True)


def post(client, path, referer, **data):
    """POST with a CSRF token scraped from the referring page."""
    data["csrf_token"] = get_token(client, referer)
    return client.post(path, data=data, follow_redirects=True)


# ---------- auth ----------

def test_register_onboarding_recommendations(client):
    resp = register(client)
    assert "Welcome to Eventully" in resp.get_data(as_text=True)

    resp = post(client, "/onboarding", "/onboarding",
                categories="Technology", major="Computer Science", time_commitment="medium")
    html = resp.get_data(as_text=True)
    assert "Robotics Club" in html  # top match: category + major keywords


def test_register_rejects_non_edu_email(client):
    resp = register(client, email="someone@gmail.com")
    assert ".edu email" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert User.query.count() == 0


def test_login_wrong_password(client):
    register(client)
    client.get("/logout")
    resp = login(client, "student@uw.edu", password="wrongpass123")
    assert "Incorrect email or password" in resp.get_data(as_text=True)


def test_protected_pages_redirect_anonymous(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ---------- clubs ----------

def test_join_and_leave_club(client):
    register(client)
    resp = post(client, "/club/1/join", "/club/1")
    assert "You joined Robotics Club" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert Membership.query.count() == 1

    resp = post(client, "/club/1/leave", "/club/1")
    assert "You left Robotics Club" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert Membership.query.count() == 0


def test_club_search(client):
    register(client)
    html = client.get("/clubs?search=chess").get_data(as_text=True)
    assert "Chess Society" in html
    assert "Robotics Club" not in html


# ---------- events + RSVPs ----------

def make_event(app, club_id=1, capacity=50, public=True):
    with app.app_context():
        event = Event(club_id=club_id, name="Test Meetup", capacity=capacity, is_public=public)
        db.session.add(event)
        db.session.commit()
        return event.id


def test_rsvp_and_unrsvp(client, app):
    event_id = make_event(app)
    register(client)
    resp = post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    assert "on the list" in resp.get_data(as_text=True)
    resp = post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    assert "RSVP removed" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert RSVP.query.count() == 0


def test_rsvp_capacity_enforced(client, app):
    event_id = make_event(app, capacity=1)
    register(client, email="first@uw.edu")
    post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    client.get("/logout")

    register(client, email="second@uw.edu")
    resp = post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    assert "at capacity" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert RSVP.query.count() == 1


# ---------- claiming + officer + admin ----------

def test_full_claim_officer_lifecycle(client, app):
    register(client, email="officer@uw.edu")
    resp = post(client, "/club/1/claim", "/club/1/claim", message="I am the club president.")
    assert "Claim request submitted" in resp.get_data(as_text=True)
    client.get("/logout")

    register(client, email="admin@uw.edu", name="Site Admin")
    html = client.get("/admin/claims").get_data(as_text=True)
    assert "I am the club president." in html
    resp = post(client, "/admin/claims/1/approve", "/admin/claims")
    assert "is now the officer for Robotics Club" in resp.get_data(as_text=True)
    client.get("/logout")

    login(client, "officer@uw.edu")
    resp = post(client, "/officer/club/1/edit", "/officer/club/1/edit",
                description="A brand new description.")
    assert "has been updated" in resp.get_data(as_text=True)

    resp = post(client, "/officer/club/1/events/new", "/officer/club/1/events/new",
                name="Robot Demo Night", description="Live demos", weekday="Friday",
                time="18:00", location="CSE 001", capacity="30", is_public="on")
    assert "has been posted" in resp.get_data(as_text=True)

    with app.app_context():
        event_id = Event.query.filter_by(name="Robot Demo Night").first().id
    resp = post(client, f"/officer/event/{event_id}/edit", f"/officer/event/{event_id}/edit",
                name="Robot Demo Night v2", description="", weekday="Friday",
                time="19:00", location="CSE 002", capacity="30", is_public="on")
    assert "has been updated" in resp.get_data(as_text=True)

    resp = post(client, f"/officer/event/{event_id}/delete", "/officer/")
    assert "has been removed" in resp.get_data(as_text=True)
    with app.app_context():
        assert Event.query.count() == 0


def test_non_officer_cannot_edit_club(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        Club.query.get(1).officer_id = owner.id
        db.session.commit()

    register(client, email="rando@uw.edu")
    token = get_token(client, "/club/1")
    resp = client.post("/officer/club/1/edit", data={"csrf_token": token, "description": "hacked"})
    assert resp.status_code == 403


def test_non_admin_cannot_see_claims(client):
    register(client, email="rando@uw.edu")
    assert client.get("/admin/claims").status_code == 403


# ---------- CSRF ----------

def test_post_without_csrf_token_is_rejected(client):
    register(client)
    resp = client.post("/club/1/join", data={})
    assert resp.status_code == 302  # bounced by the CSRF handler, no membership created
    with client.application.app_context():
        assert Membership.query.count() == 0


# ---------- settings ----------

def test_settings_update_profile_and_password(client):
    register(client)
    resp = post(client, "/settings", "/settings", form="profile", name="Renamed Student")
    assert "Profile updated" in resp.get_data(as_text=True)

    resp = post(client, "/settings", "/settings", form="password",
                current_password="wrongpass", new_password="newpass12345",
                confirm_password="newpass12345")
    assert "current password is incorrect" in resp.get_data(as_text=True)

    resp = post(client, "/settings", "/settings", form="password",
                current_password="testpass123", new_password="newpass12345",
                confirm_password="newpass12345")
    assert "Password changed" in resp.get_data(as_text=True)

    client.get("/logout")
    resp = login(client, "student@uw.edu", password="newpass12345")
    assert "Welcome back, Renamed" in resp.get_data(as_text=True)


def test_onboarding_prefills_existing_preferences(client):
    register(client)
    post(client, "/onboarding", "/onboarding",
         categories="Technology", major="Computer Science", time_commitment="medium")
    html = client.get("/onboarding").get_data(as_text=True)
    assert 'value="Technology" checked' in html
    assert 'value="Computer Science" selected' in html
    assert 'value="medium" checked' in html


# ---------- about + ics ----------

def test_about_page(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert "Eventully" in resp.get_data(as_text=True)


def test_ics_download(client, app):
    event_id = make_event(app)
    register(client)
    resp = client.get(f"/event/{event_id}/calendar.ics")
    assert resp.status_code == 200
    assert resp.mimetype == "text/calendar"
    body = resp.get_data(as_text=True)
    assert "RRULE:FREQ=WEEKLY" in body
    assert "Test Meetup" in body


# ---------- attendees ----------

def test_officer_sees_attendees_others_403(client, app):
    event_id = make_event(app)
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    register(client, email="guest@uw.edu", name="Guest Student")
    post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    assert client.get(f"/officer/event/{event_id}/attendees").status_code == 403
    client.get("/logout")

    login(client, "owner@uw.edu")
    html = client.get(f"/officer/event/{event_id}/attendees").get_data(as_text=True)
    assert "Guest Student" in html
    assert "guest@uw.edu" in html


# ---------- club browse filters + officer listing fields ----------

def test_clubs_status_filter(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    register(client)
    html = client.get("/clubs?status=claimed").get_data(as_text=True)
    assert "Robotics Club" in html and "Chess Society" not in html
    html = client.get("/clubs?status=unclaimed").get_data(as_text=True)
    assert "Robotics Club" not in html and "Chess Society" in html


def test_officer_edits_listing_fields_shown_on_detail(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    login(client, "owner@uw.edu")
    post(client, "/officer/club/1/edit", "/officer/club/1/edit",
         description="We build robots.", meeting_info="Tuesdays 6pm, HUB 145",
         website="https://robots.uw.edu", instagram="@uwrobots",
         contact_email="robots@uw.edu")
    html = client.get("/club/1").get_data(as_text=True)
    assert "Tuesdays 6pm, HUB 145" in html
    assert "@uwrobots" in html  # handle stored without the @, rendered with it
    assert "robots@uw.edu" in html


# ---------- saved / hidden clubs ----------

def test_save_and_unsave_club(client):
    register(client)
    resp = post(client, "/club/1/save", "/club/1")
    assert "Saved Robotics Club" in resp.get_data(as_text=True)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Saved for later" in html and "Robotics Club" in html

    resp = post(client, "/club/1/save", "/club/1")
    assert "Removed Robotics Club" in resp.get_data(as_text=True)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Saved for later" not in html


def test_hidden_club_excluded_from_recommendations(client):
    register(client)
    post(client, "/onboarding", "/onboarding",
         categories="Technology", major="Computer Science", time_commitment="medium")
    html = client.get("/recommendations").get_data(as_text=True)
    assert "Robotics Club" in html

    post(client, "/club/1/hide", "/recommendations")
    html = client.get("/recommendations").get_data(as_text=True)
    assert "Robotics Club" not in html


# ---------- calendar / search / help ----------

def test_calendar_groups_by_weekday(client, app):
    with app.app_context():
        db.session.add(Event(club_id=1, name="Weds Workshop", weekday="Wednesday", time="18:00"))
        db.session.commit()
    register(client)
    html = client.get("/calendar").get_data(as_text=True)
    assert "Weds Workshop" in html
    assert "cal-grid" in html


def test_search_finds_clubs_and_events(client, app):
    with app.app_context():
        db.session.add(Event(club_id=1, name="Robot Rumble", location="HUB"))
        db.session.commit()
    register(client)
    html = client.get("/search?q=robot").get_data(as_text=True)
    assert "Robotics Club" in html
    assert "Robot Rumble" in html
    html = client.get("/search?q=zzzznope").get_data(as_text=True)
    assert "Nothing matched" in html


def test_help_page_public(client):
    resp = client.get("/help")
    assert resp.status_code == 200
    assert "How do club recommendations work?" in resp.get_data(as_text=True)


def test_officer_dues_hours_shown_on_card(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    login(client, "owner@uw.edu")
    post(client, "/officer/club/1/edit", "/officer/club/1/edit",
         description="We build robots.", dues="No dues", hours_per_week="3 hours/week")
    html = client.get("/club/1").get_data(as_text=True)
    assert "No dues" in html and "3 hours/week" in html
    assert "Last updated: today" in html


# ---------- public directory ----------

def test_directory_public_for_anonymous(client, app):
    event_id = make_event(app)
    assert client.get("/clubs").status_code == 200
    assert client.get("/club/1").status_code == 200
    assert client.get("/events").status_code == 200
    assert client.get(f"/event/{event_id}").status_code == 200
    html = client.get("/club/1").get_data(as_text=True)
    assert "Log in to join" in html


def test_private_event_hidden_from_anonymous(client, app):
    event_id = make_event(app, public=False)
    assert client.get(f"/event/{event_id}").status_code == 404
    html = client.get("/events").get_data(as_text=True)
    assert "Test Meetup" not in html


def test_sitemap_and_robots(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/club/1" in resp.get_data(as_text=True)
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Sitemap:" in resp.get_data(as_text=True)


# ---------- password reset ----------

def test_password_reset_flow(client, app):
    register(client)
    client.get("/logout")

    resp = post(client, "/forgot-password", "/forgot-password", email="student@uw.edu")
    assert "emailed a reset link" in resp.get_data(as_text=True)

    from itsdangerous import URLSafeTimedSerializer
    with app.app_context():
        user_id = User.query.filter_by(email="student@uw.edu").first().id
    token = URLSafeTimedSerializer(TestConfig.SECRET_KEY, salt="password-reset").dumps(user_id)

    resp = post(client, f"/reset-password/{token}", f"/reset-password/{token}",
                password="brandnewpass1", confirm_password="brandnewpass1")
    assert "Password updated" in resp.get_data(as_text=True)

    resp = login(client, "student@uw.edu", password="brandnewpass1")
    assert "Welcome back" in resp.get_data(as_text=True)


def test_password_reset_bad_token(client):
    resp = client.get("/reset-password/not-a-real-token", follow_redirects=True)
    assert "reset link" in resp.get_data(as_text=True) and "valid" in resp.get_data(as_text=True)


# ---------- rate limiting ----------

def test_login_rate_limited_after_failures(client):
    register(client)
    client.get("/logout")
    for _ in range(8):
        login(client, "student@uw.edu", password="wrongpassword")
    resp = login(client, "student@uw.edu", password="testpass123")  # correct, but locked
    assert "Too many failed attempts" in resp.get_data(as_text=True)


# ---------- account deletion ----------

def test_account_deletion_releases_officer_clubs(client, app):
    register(client, email="owner@uw.edu")
    with app.app_context():
        user = User.query.filter_by(email="owner@uw.edu").first()
        club = db.session.get(Club, 1)
        club.officer_id = user.id
        db.session.commit()

    resp = post(client, "/settings/delete", "/settings", password="wrongpass")
    assert "Incorrect password" in resp.get_data(as_text=True)

    resp = post(client, "/settings/delete", "/settings", password="testpass123")
    assert "account and data have been deleted" in resp.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(email="owner@uw.edu").first() is None
        assert db.session.get(Club, 1).officer_id is None


# ---------- officer member list + admin revoke ----------

def test_officer_member_list(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    register(client, email="member@uw.edu", name="Member Student")
    post(client, "/club/1/join", "/club/1")
    assert client.get("/officer/club/1/members").status_code == 403
    client.get("/logout")

    login(client, "owner@uw.edu")
    html = client.get("/officer/club/1/members").get_data(as_text=True)
    assert "Member Student" in html and "member@uw.edu" in html


def test_admin_revokes_officer(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        club = db.session.get(Club, 1)
        club.officer_id = owner.id
        db.session.commit()

    register(client, email="admin@uw.edu", name="Site Admin")
    html = client.get("/admin/claims").get_data(as_text=True)
    assert "Claimed clubs (1)" in html
    resp = post(client, "/admin/clubs/1/revoke", "/admin/claims")
    assert "no longer the officer" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Club, 1).officer_id is None
