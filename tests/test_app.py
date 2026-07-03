"""End-to-end tests for every user flow, run against an in-memory database
with CSRF protection enabled (tokens are pulled from the rendered forms,
exactly like a browser would)."""
import re
import os

import pytest

os.environ["AUTO_SEED"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SEED_DEMO_ACCOUNT"] = "false"

from app import create_app
from config import Config
from extensions import db
from models import Club, ClubMessage, ClubRole, Event, Membership, RSVP, User
from notifications import make_email_token


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    AUTO_SEED = False
    SEED_DEMO_ACCOUNT = False
    REQUIRE_EDU_EMAIL = True
    ADMIN_EMAILS = {"admin@uw.edu"}
    SECRET_KEY = "test-key"
    EMAIL_VERIFICATION_REQUIRED = False
    MAIL_SERVER = ""


@pytest.fixture
def app():
    from blueprints.auth import _attempts
    _attempts.clear()
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


def test_register_rate_limited(client):
    import time
    from blueprints.auth import _attempts
    _attempts["register|127.0.0.1"] = [time.time()] * 50
    resp = register(client)
    assert "Too many signups" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert User.query.count() == 0


def test_canonical_host_redirect():
    class CanonicalConfig(TestConfig):
        CANONICAL_HOST = "eventully.org"

    capp = create_app(CanonicalConfig)
    cclient = capp.test_client()

    resp = cclient.get("/dashboard?tab=events", base_url="http://eventully.onrender.com")
    assert resp.status_code == 301
    assert resp.headers["Location"] == "https://eventully.org/dashboard?tab=events"

    # /healthz stays reachable on the host Render probes
    resp = cclient.get("/healthz", base_url="http://eventully.onrender.com")
    assert resp.status_code == 200

    # requests already on the canonical host pass through
    resp = cclient.get("/healthz", base_url="http://eventully.org")
    assert resp.status_code == 200


def test_login_wrong_password(client):
    register(client)
    client.get("/logout")
    resp = login(client, "student@uw.edu", password="wrongpass123")
    assert "Incorrect email or password" in resp.get_data(as_text=True)


def test_login_rejects_external_next_url(client):
    register(client)
    client.get("/logout")
    token = get_token(client, "/login?next=https://evil.example")
    resp = client.post("/login?next=https://evil.example", data={
        "csrf_token": token, "email": "student@uw.edu", "password": "testpass123",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/dashboard"


def test_email_verification_marks_account_verified(client, app):
    register(client)
    with app.app_context():
        user = User.query.filter_by(email="student@uw.edu").first()
        assert user.email_verified_at is None
        token = make_email_token(user, "verify-email")

    resp = client.get(f"/verify-email/{token}", follow_redirects=True)
    assert "Email verified" in resp.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(email="student@uw.edu").first().email_verified_at is not None


def test_password_reset_flow(client, app):
    register(client)
    client.get("/logout")
    with app.app_context():
        user = User.query.filter_by(email="student@uw.edu").first()
        token = make_email_token(user, "reset-password")

    resp = client.post(f"/reset-password/{token}", data={
        "csrf_token": get_token(client, f"/reset-password/{token}"),
        "password": "freshpass123",
        "confirm_password": "freshpass123",
    }, follow_redirects=True)
    assert "Password reset" in resp.get_data(as_text=True)

    resp = login(client, "student@uw.edu", password="freshpass123")
    assert "Welcome back" in resp.get_data(as_text=True)


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


def test_private_event_direct_routes_require_membership(client, app):
    event_id = make_event(app, public=False)
    register(client, email="outsider@uw.edu")

    assert client.get(f"/event/{event_id}").status_code == 403
    assert client.get(f"/event/{event_id}/calendar.ics").status_code == 403

    token = get_token(client, "/club/1")
    resp = client.post(f"/event/{event_id}/rsvp", data={"csrf_token": token})
    assert resp.status_code == 403
    with client.application.app_context():
        assert RSVP.query.count() == 0


def test_private_event_member_can_view_and_rsvp(client, app):
    event_id = make_event(app, public=False)
    register(client)
    post(client, "/club/1/join", "/club/1")
    resp = post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    assert "on the list" in resp.get_data(as_text=True)


def test_event_scope_tabs_filter_visible_events(client, app):
    with app.app_context():
        public = Event(club_id=1, name="Public Workshop", is_public=True)
        private = Event(club_id=1, name="Member Lab", is_public=False)
        db.session.add_all([public, private])
        db.session.commit()
        public_id = public.id

    register(client)
    post(client, "/club/1/join", "/club/1")
    post(client, f"/event/{public_id}/rsvp", f"/event/{public_id}")

    html = client.get("/events?scope=public").get_data(as_text=True)
    assert "Public Workshop" in html
    assert "Member Lab" not in html

    html = client.get("/events?scope=members").get_data(as_text=True)
    assert "Member Lab" in html
    assert "Public Workshop" not in html

    html = client.get("/events?scope=rsvped").get_data(as_text=True)
    assert "Public Workshop" in html
    assert "Member Lab" not in html


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


def test_owner_can_add_co_officer_who_can_manage_club(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        helper = User(email="helper@uw.edu", name="Helper")
        helper.set_password("testpass123")
        db.session.add_all([owner, helper])
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    login(client, "owner@uw.edu")
    resp = post(client, "/officer/club/1/team", "/officer/",
                email="helper@uw.edu", role="communications")
    assert "can now help manage Robotics Club" in resp.get_data(as_text=True)
    with app.app_context():
        assert ClubRole.query.count() == 1

    client.get("/logout")
    login(client, "helper@uw.edu")
    html = client.get("/officer/").get_data(as_text=True)
    assert "Robotics Club" in html
    resp = post(client, "/officer/club/1/edit", "/officer/club/1/edit",
                description="Updated by the helper.")
    assert "has been updated" in resp.get_data(as_text=True)


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

def test_forgot_password_request_accepts_existing_email(client):
    register(client)
    client.get("/logout")

    resp = post(client, "/forgot-password", "/forgot-password", email="student@uw.edu")
    assert "reset link is on the way" in resp.get_data(as_text=True)


def test_password_reset_bad_token(client):
    resp = client.get("/reset-password/not-a-real-token", follow_redirects=True)
    assert "reset link is invalid" in resp.get_data(as_text=True)


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


def test_admin_launch_readiness_lists_email_blocker(client):
    register(client, email="admin@uw.edu", name="Site Admin")
    html = client.get("/admin/launch-readiness").get_data(as_text=True)
    assert "Launch readiness" in html
    assert "Email delivery" in html
    assert "SMTP is incomplete" in html
    assert "Send test email" in html


def test_admin_launch_readiness_test_email_without_smtp(client):
    register(client, email="admin@uw.edu", name="Site Admin")
    resp = post(client, "/admin/launch-readiness/test-email", "/admin/launch-readiness")
    assert "Email delivery is not configured" in resp.get_data(as_text=True)


def test_remove_demo_events(client, app):
    from seed import DEMO_EVENTS

    register(client, email="admin@uw.edu", name="Site Admin")
    with app.app_context():
        event = Event(club_id=1, name=DEMO_EVENTS[0]["name"], capacity=10, is_public=True)
        db.session.add(event)
        db.session.commit()
        admin = User.query.filter_by(email="admin@uw.edu").first()
        db.session.add(RSVP(user_id=admin.id, event_id=event.id))
        db.session.commit()

    html = client.get("/admin/launch-readiness").get_data(as_text=True)
    assert "seeded sample event(s) are still live" in html

    resp = post(client, "/admin/launch-readiness/remove-demo-events", "/admin/launch-readiness")
    html = resp.get_data(as_text=True)
    assert "Removed 1 demo event(s)" in html
    assert "No seeded sample events remain" in html
    with app.app_context():
        assert Event.query.count() == 0
        assert RSVP.query.count() == 0


def test_demo_events_not_seeded_without_flag(app):
    from seed import seed_clubs

    with app.app_context():
        seed_clubs()
        assert Event.query.count() == 0


# ---------- club messages ----------

def test_member_and_officer_can_use_club_messages(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()

    register(client, email="member@uw.edu", name="Member Student")
    post(client, "/club/1/join", "/club/1")
    html = client.get("/messages/club/1").get_data(as_text=True)
    assert "Club messages" in html
    assert "Message Robotics Club" in html

    resp = post(client, "/messages/club/1", "/messages/club/1", body="Can I come to the next meeting?")
    html = resp.get_data(as_text=True)
    assert "Message sent" in html
    assert "Can I come to the next meeting?" in html
    with app.app_context():
        assert ClubMessage.query.count() == 1

    client.get("/logout")
    login(client, "owner@uw.edu")
    html = client.get("/messages/club/1").get_data(as_text=True)
    assert "Can I come to the next meeting?" in html
    resp = post(client, "/messages/club/1", "/messages/club/1", body="Yes, stop by at 6.")
    html = resp.get_data(as_text=True)
    assert "Yes, stop by at 6." in html
    assert "Officer" in html

    with app.app_context():
        message_id = ClubMessage.query.filter_by(body="Can I come to the next meeting?").first().id
    resp = post(client, f"/messages/message/{message_id}/delete", "/messages/club/1")
    html = resp.get_data(as_text=True)
    assert "Message removed" in html
    with app.app_context():
        assert ClubMessage.query.get(message_id).is_deleted


def test_non_member_cannot_read_club_messages(client, app):
    register(client, email="outsider@uw.edu")
    assert client.get("/messages/club/1").status_code == 403


def test_privacy_and_terms_pages_public(client):
    assert client.get("/privacy").status_code == 200
    assert "Privacy policy" in client.get("/privacy").get_data(as_text=True)
    assert client.get("/terms").status_code == 200
    assert "Terms of use" in client.get("/terms").get_data(as_text=True)
