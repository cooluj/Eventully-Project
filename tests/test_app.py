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
    assert "Registration cancelled" in resp.get_data(as_text=True)
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
    assert "week-list" in html


def test_search_finds_clubs_and_events(client, app):
    with app.app_context():
        db.session.add(Event(club_id=1, name="Robot Rumble", location="HUB"))
        db.session.commit()
    register(client)
    html = client.get("/search?q=robot").get_data(as_text=True)
    assert "Robotics Club" in html
    assert "Robot Rumble" in html
    html = client.get("/search?q=zzzznope").get_data(as_text=True)
    assert "Nothing found" in html


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
    assert "Claimed clubs" in html
    assert "Revoke" in html
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


def _make_officer(app, email="student@uw.edu", club_id=1):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        db.session.get(Club, club_id).officer_id = user.id
        db.session.commit()


def test_club_website_rejects_script_schemes(client, app):
    register(client)
    _make_officer(app)

    resp = post(client, "/officer/club/1/edit", "/officer/club/1/edit",
                description="d", website="javascript:alert(1)", instagram="",
                contact_email="", meeting_info="", dues="", hours_per_week="")
    assert "Website must be a normal http(s) link" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Club, 1).website == ""

    post(client, "/officer/club/1/edit", "/officer/club/1/edit",
         description="d", website="uwrobotics.org", instagram="",
         contact_email="", meeting_info="", dues="", hours_per_week="")
    with app.app_context():
        assert db.session.get(Club, 1).website == "https://uwrobotics.org"


def test_event_capacity_bad_input_does_not_crash(client, app):
    register(client)
    _make_officer(app)

    resp = post(client, "/officer/club/1/events/new", "/officer/club/1/events/new",
                name="Garbage Capacity", description="", weekday="Monday",
                time="18:00", location="HUB", image_url="", capacity="lots", is_public="on")
    assert resp.status_code == 200
    with app.app_context():
        event = Event.query.filter_by(name="Garbage Capacity").first()
        assert event is not None
        assert event.capacity == 50


def test_resend_verification_rate_limited(client, app):
    import time
    from blueprints.auth import _attempts

    register(client)
    with app.app_context():
        user_id = User.query.filter_by(email="student@uw.edu").first().id
    _attempts[f"verify|{user_id}"] = [time.time()] * 3
    resp = post(client, "/resend-verification", "/settings")
    assert "requested several verification emails" in resp.get_data(as_text=True)


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
    assert "<h1>Messages</h1>" in html
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


# ---------- real event dates ----------
def test_one_time_event_lifecycle(client, app):
    """A dated event sorts by its date, shows on its calendar day, and sinks
    to Past once it's over."""
    from datetime import timedelta
    from utils import campus_now, split_upcoming

    with app.app_context():
        now = campus_now()
        future = Event(club_id=1, name="Career Fair Prep",
                       starts_at=now + timedelta(days=2),
                       ends_at=now + timedelta(days=2, hours=2),
                       weekday=(now + timedelta(days=2)).strftime("%A"),
                       time="17:00")
        past = Event(club_id=1, name="Old Social",
                     starts_at=now - timedelta(days=3),
                     weekday=(now - timedelta(days=3)).strftime("%A"),
                     time="17:00")
        weekly = Event(club_id=1, name="Weekly Standup", weekday="Monday", time="09:00")
        db.session.add_all([future, past, weekly])
        db.session.commit()

        upcoming, gone = split_upcoming(Event.query.all())
        assert {e.name for e in upcoming} == {"Career Fair Prep", "Weekly Standup"}
        assert [e.name for e in gone] == ["Old Social"]
        assert not weekly.is_past()
        assert weekly.next_occurrence() >= now

    register(client)
    html = client.get("/events").get_data(as_text=True)
    assert "Career Fair Prep" in html
    assert "Past events" in html and "Old Social" in html


def test_officer_posts_one_time_event(client, app):
    from datetime import timedelta
    from utils import campus_now

    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.commit()
        target = (campus_now() + timedelta(days=5)).strftime("%Y-%m-%d")

    login(client, "owner@uw.edu")
    post(client, "/officer/club/1/events/new", "/officer/club/1/events/new",
         name="Robot Demo Day", schedule="once", date=target,
         time="15:30", end_time="17:00", location="CSE2 G001", capacity="80", is_public="on")
    with client.application.app_context():
        event = Event.query.filter_by(name="Robot Demo Day").one()
        assert event.starts_at is not None and event.starts_at.strftime("%H:%M") == "15:30"
        assert event.ends_at.strftime("%H:%M") == "17:00"
        assert not event.is_recurring
        assert event.weekday == event.starts_at.strftime("%A")


def test_calendar_links_carry_real_dates(app):
    from datetime import datetime
    from utils import build_calendar_link, build_ics

    with app.app_context():
        event = Event(club_id=1, name="Dated Event",
                      starts_at=datetime(2026, 10, 3, 15, 0),
                      ends_at=datetime(2026, 10, 3, 17, 0),
                      weekday="Saturday", time="15:00", location="HUB 145")
        db.session.add(event)
        db.session.commit()
        link = build_calendar_link(event)
        assert "dates=20261003T150000%2F20261003T170000" in link
        ics = build_ics(event)
        assert "DTSTART;TZID=America/Los_Angeles:20261003T150000" in ics
        assert "DTEND;TZID=America/Los_Angeles:20261003T170000" in ics
        assert "RRULE" not in ics

        weekly = Event(club_id=1, name="Weekly Thing", weekday="Monday", time="18:00")
        db.session.add(weekly)
        db.session.commit()
        assert "COUNT=26" in build_ics(weekly)
        assert "recur=RRULE" in build_calendar_link(weekly)


def test_rejected_image_url_scheme(client, app):
    with app.app_context():
        owner = User(email="owner2@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        db.session.get(Club, 2).officer_id = owner.id
        db.session.commit()

    login(client, "owner2@uw.edu")
    resp = post(client, "/officer/club/2/events/new", "/officer/club/2/events/new",
                name="Sneaky", schedule="weekly", weekday="Monday", time="18:00",
                image_url="javascript:alert(1)")
    assert "Image must be a normal http(s) link" in resp.get_data(as_text=True)
    with client.application.app_context():
        assert Event.query.filter_by(name="Sneaky").count() == 0


# ---------- hardening ----------
def test_reset_token_dies_after_password_change(client, app):
    register(client, email="resetme@uw.edu")
    client.get("/logout")
    with app.app_context():
        user = User.query.filter_by(email="resetme@uw.edu").one()
        token = make_email_token(user, "reset-password")
        # Simulate the reset completing (or any password change)
        user.set_password("newpass456")
        db.session.commit()
    resp = client.get(f"/reset-password/{token}", follow_redirects=True)
    assert "no longer valid" in resp.get_data(as_text=True)


def test_garbage_page_params_dont_crash(client):
    assert client.get("/clubs?page=abc").status_code == 200
    assert client.get("/clubs?page=-5").status_code == 200
    register(client)
    assert client.get("/recommendations?page=zzz", follow_redirects=True).status_code == 200


def test_officer_delete_account_with_posted_events(client, app):
    """Deleting an account that created events must not 500 (FK nulled)."""
    with app.app_context():
        owner = User(email="deleteme@uw.edu", name="Owner")
        owner.set_password("testpass123")
        db.session.add(owner)
        db.session.commit()
        club = db.session.get(Club, 1)
        club.officer_id = owner.id
        db.session.add(Event(club_id=1, name="Orphan Event", weekday="Monday",
                             time="18:00", created_by=owner.id))
        db.session.commit()

    login(client, "deleteme@uw.edu")
    resp = post(client, "/settings/delete", "/settings", password="testpass123")
    assert resp.status_code == 200
    with client.application.app_context():
        assert User.query.filter_by(email="deleteme@uw.edu").count() == 0
        assert Event.query.filter_by(name="Orphan Event").one().created_by is None


# ---------- retention layer (notifications, cancel, unread, feeds, tasks) ----------
def _make_officer_with_member(app):
    """Owner runs club 1; a member has joined it. Returns (owner_email, member_email)."""
    with app.app_context():
        owner = User(email="own3@uw.edu", name="Owner Three")
        owner.set_password("testpass123")
        member = User(email="mem3@uw.edu", name="Member Three")
        member.set_password("testpass123")
        db.session.add_all([owner, member])
        db.session.commit()
        db.session.get(Club, 1).officer_id = owner.id
        db.session.add(Membership(user_id=member.id, club_id=1))
        db.session.commit()


def test_new_event_notifies_members(client, app):
    from models import Notification
    _make_officer_with_member(app)
    login(client, "own3@uw.edu")
    post(client, "/officer/club/1/events/new", "/officer/club/1/events/new",
         name="Notified Event", schedule="weekly", weekday="Friday", time="18:00")
    client.get("/logout")

    with app.app_context():
        member = User.query.filter_by(email="mem3@uw.edu").one()
        notes = Notification.query.filter_by(user_id=member.id).all()
        assert any("Notified Event" in n.title for n in notes)

    # The bell badge renders for the member, and the page marks things read
    login(client, "mem3@uw.edu")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "nav-badge" in html
    html = client.get("/notifications").get_data(as_text=True)
    assert "Notified Event" in html
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'nav-bell has-unread' not in html


def test_cancel_event_notifies_attendees_and_blocks_rsvp(client, app):
    from models import Notification
    _make_officer_with_member(app)
    event_id = make_event(app)

    login(client, "mem3@uw.edu")
    post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    client.get("/logout")

    login(client, "own3@uw.edu")
    resp = post(client, f"/officer/event/{event_id}/cancel", "/officer/")
    assert "cancelled" in resp.get_data(as_text=True)
    client.get("/logout")

    with app.app_context():
        member = User.query.filter_by(email="mem3@uw.edu").one()
        assert Notification.query.filter_by(user_id=member.id, kind="cancelled").count() == 1
        assert db.session.get(Event, event_id).is_cancelled

    # Cancelled events leave the browse list and refuse new registrations
    login(client, "mem3@uw.edu")
    assert "Test Meetup" not in client.get("/events").get_data(as_text=True)
    html = client.get(f"/event/{event_id}").get_data(as_text=True)
    assert "cancelled" in html.lower()


def test_delete_requires_cancel_when_attendees_exist(client, app):
    _make_officer_with_member(app)
    event_id = make_event(app)
    login(client, "mem3@uw.edu")
    post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    client.get("/logout")

    login(client, "own3@uw.edu")
    resp = post(client, f"/officer/event/{event_id}/delete", "/officer/")
    assert "Cancel the event first" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Event, event_id) is not None


def test_unread_message_indicators(client, app):
    _make_officer_with_member(app)
    login(client, "own3@uw.edu")
    post(client, "/messages/club/1", "/messages/club/1", body="Meeting moved to HUB 250")
    client.get("/logout")

    login(client, "mem3@uw.edu")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Messages <span" in html  # nav badge on the Messages link
    html = client.get("/messages/").get_data(as_text=True)
    assert "unread" in html
    # Opening the thread clears it
    client.get("/messages/club/1")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Messages <span" not in html


def test_personal_ics_feed(client, app):
    event_id = make_event(app)
    register(client)
    post(client, f"/event/{event_id}/rsvp", f"/event/{event_id}")
    html = client.get("/calendar").get_data(as_text=True)
    assert "Copy calendar link" in html

    with app.app_context():
        token = User.query.filter_by(email="student@uw.edu").one().ics_token
        assert token

    resp = client.get(f"/me/calendar.ics?t={token}")
    assert resp.status_code == 200
    assert "Test Meetup" in resp.get_data(as_text=True)
    assert client.get("/me/calendar.ics?t=wrongtoken").status_code == 404
    assert client.get("/me/calendar.ics").status_code == 404


def test_task_endpoints_are_token_gated(client, app):
    # No token configured -> 404 even with a guess
    assert client.get("/tasks/reminders?token=guess").status_code == 404

    class TaskConfig(TestConfig):
        TASKS_TOKEN = "sekrit"

    tapp = create_app(TaskConfig)
    with tapp.app_context():
        db.create_all()
        club = Club(name="Cron Club", category="Technology")
        db.session.add(club)
        db.session.commit()
        user = User(email="cron@uw.edu", name="Cron User")
        user.set_password("testpass123")
        db.session.add(user)
        db.session.commit()
        db.session.add(Membership(user_id=user.id, club_id=club.id))
        event = Event(club_id=club.id, name="Cron Event", weekday="Monday", time="10:00")
        db.session.add(event)
        db.session.commit()
        db.session.add(RSVP(event_id=event.id, user_id=user.id))
        db.session.commit()

        tclient = tapp.test_client()
        assert tclient.get("/tasks/digest?token=wrong").status_code == 404
        resp = tclient.get("/tasks/digest?token=sekrit")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
        resp = tclient.get("/tasks/reminders?token=sekrit")
        assert resp.status_code == 200
        db.session.remove()
        db.drop_all()


def test_search_ranks_name_hits_first(client, app):
    with app.app_context():
        db.session.add(Club(name="Quantum Computing Club",
                            description="chess strategy discussions sometimes", category="Technology"))
        db.session.commit()
    html = client.get("/search?q=chess").get_data(as_text=True)
    # Name match (Chess Society) must appear before the description-only match
    assert html.index("Chess Society") < html.index("Quantum Computing Club")


# ---------- Performance & delivery ----------

def test_responses_are_compressed_when_asked(client):
    resp = client.get("/help", headers={"Accept-Encoding": "br"})
    assert resp.headers.get("Content-Encoding") == "br"
    assert "Accept-Encoding" in resp.headers.get("Vary", "")
    resp = client.get("/help", headers={"Accept-Encoding": "gzip"})
    assert resp.headers.get("Content-Encoding") == "gzip"
    plain = client.get("/help")
    assert plain.headers.get("Content-Encoding") is None
    assert "How do club recommendations work?" in plain.get_data(as_text=True)


def test_static_assets_are_versioned_and_immutable(client):
    html = client.get("/login").get_data(as_text=True)
    match = re.search(r'href="(/static/css/style\.css\?v=[0-9a-f]{10})"', html)
    assert match, "stylesheet link should carry a content hash"
    resp = client.get(match.group(1), headers={"Accept-Encoding": "gzip, deflate, br, zstd"})
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert resp.headers.get("Content-Encoding") == "br"
    unversioned = client.get("/static/css/style.css")
    assert unversioned.headers["Cache-Control"] == "public, max-age=3600"


def test_pages_are_private_and_revalidated(client):
    register(client)
    resp = client.get("/dashboard")
    assert resp.headers["Cache-Control"] == "private, no-cache"


def test_attendee_previews_batch_and_order(client, app):
    from models import load_attendee_previews
    with app.app_context():
        event = Event(club_id=1, name="Big Night", capacity=50)
        db.session.add(event)
        db.session.flush()
        people = []
        for i in range(7):
            u = User(email=f"p{i}@uw.edu", name=f"{chr(65 + i)} Person")
            u.set_password("testpass123")
            people.append(u)
        db.session.add_all(people)
        db.session.flush()
        from datetime import datetime, timedelta
        base = datetime(2026, 1, 1)
        for i, u in enumerate(people):
            db.session.add(RSVP(event_id=event.id, user_id=u.id, created_at=base + timedelta(minutes=i)))
        db.session.commit()
        event_id = event.id

    with app.app_context():
        events = Event.query.filter_by(id=event_id).all()
        load_attendee_previews(events, limit=5)
        names = [u.name for u in events[0].attendee_preview]
        assert names == ["A Person", "B Person", "C Person", "D Person", "E Person"]

    html = client.get(f"/event/{event_id}").get_data(as_text=True)
    assert "7 Going" in html
    assert "+2" in html  # 7 attendees, 5 shown


def test_timeline_pages_one_week_at_a_time(client, app):
    from datetime import timedelta
    from utils import campus_now
    now = campus_now()
    with app.app_context():
        soon = now + timedelta(days=3)
        later = now + timedelta(days=20)
        db.session.add(Event(club_id=1, name="Soon Social", starts_at=soon.replace(hour=18, minute=0), weekday=soon.strftime("%A"), time="18:00"))
        db.session.add(Event(club_id=1, name="Later Summit", starts_at=later.replace(hour=18, minute=0), weekday=later.strftime("%A"), time="18:00"))
        db.session.add(Event(club_id=2, name="Weekly Chess", weekday="Tuesday", time="19:00"))
        db.session.commit()

    first = client.get("/events").get_data(as_text=True)
    assert "Soon Social" in first
    assert "Later Summit" not in first
    assert "Weekly Chess" in first
    assert "Later →" in first

    later_from = (now + timedelta(days=14)).date().isoformat()
    second = client.get(f"/events?from={later_from}").get_data(as_text=True)
    assert "Later Summit" in second
    assert "Soon Social" not in second
    assert "Weekly Chess" in second  # weekly meetings recur into every window
    assert "← Earlier" in second
    assert "Past events" not in second

    # Garbage or past `from` values fall back to this week
    assert "Soon Social" in client.get("/events?from=nope").get_data(as_text=True)
    assert "Soon Social" in client.get("/events?from=2001-01-01").get_data(as_text=True)


def test_calendar_shows_every_weekly_event_once(client, app):
    from utils import WEEKDAYS
    with app.app_context():
        for day in WEEKDAYS:
            db.session.add(Event(club_id=1, name=f"{day} Standup", weekday=day, time="00:01"))
            db.session.add(Event(club_id=2, name=f"{day} Nightcap", weekday=day, time="23:59"))
        db.session.commit()
    register(client)
    html = client.get("/calendar").get_data(as_text=True)
    for day in WEEKDAYS:
        assert html.count(f"{day} Standup") == 1, day
        assert html.count(f"{day} Nightcap") == 1, day


def test_csp_nonce_covers_inline_scripts(client):
    resp = client.get("/login")
    csp = resp.headers["Content-Security-Policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    html = resp.get_data(as_text=True)
    assert f'<script nonce="{nonce}">' in html
    assert "onsubmit=" not in html
    assert "frame-ancestors 'none'" in csp


def test_search_page_is_never_compressed(client):
    resp = client.get("/search?q=robot", headers={"Accept-Encoding": "br, gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("Content-Encoding") is None
    assert "Robotics Club" in resp.get_data(as_text=True)


def test_officer_can_download_attendee_and_member_csv(client, app):
    with app.app_context():
        owner = User(email="owner@uw.edu", name="Owner")
        owner.set_password("testpass123")
        member = User(email="=cmd()|'/C calc'!A0@uw.edu", name="=HYPERLINK(\"x\")")
        member.set_password("testpass123")
        db.session.add_all([owner, member])
        db.session.flush()
        club = Club.query.get(1)
        club.officer_id = owner.id
        event = Event(club_id=1, name="Door List Night", capacity=10)
        db.session.add(event)
        db.session.flush()
        db.session.add(RSVP(event_id=event.id, user_id=member.id))
        db.session.add(Membership(user_id=member.id, club_id=1))
        db.session.commit()
        event_id = event.id

    login(client, "owner@uw.edu")
    resp = client.get(f"/officer/event/{event_id}/attendees.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert body.startswith("Name,Email,Registered")
    assert "'=HYPERLINK" in body  # formula-injection neutralized
    assert "'=cmd()" in body

    resp = client.get("/officer/club/1/members.csv")
    assert resp.status_code == 200
    assert "Name,Email,Joined" in resp.get_data(as_text=True)

    # A student who isn't an officer gets nothing
    client.get("/logout")
    register(client, email="nosy@uw.edu")
    assert client.get(f"/officer/event/{event_id}/attendees.csv").status_code == 403
    assert client.get("/officer/club/1/members.csv").status_code == 403


def test_register_honors_next_from_the_form(client):
    html = client.get("/register?next=/claim").get_data(as_text=True)
    assert 'name="next" value="/claim"' in html
    token = TOKEN_RE.search(html).group(1)
    resp = client.post("/register", data={
        "csrf_token": token, "email": "officer2@uw.edu", "name": "Off Two",
        "password": "testpass123", "confirm_password": "testpass123", "next": "/claim",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/claim")
