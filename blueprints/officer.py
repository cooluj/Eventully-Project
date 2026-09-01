from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Club, ClubRole, Event, User
from notifications import send_email
from utils import WEEKDAYS

bp = Blueprint("officer", __name__, url_prefix="/officer")


def _clean_website(raw):
    """Return a safe http(s) URL, "" when blank, or None when rejected.

    The value lands in an href, so anything other than http(s) (javascript:,
    data:, ...) is stored XSS waiting to happen."""
    url = raw.strip()
    if not url:
        return ""
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        return url
    if scheme:
        return None
    return "https://" + url


def _parse_capacity(raw, fallback):
    try:
        return max(1, min(int(raw), 100000))
    except (TypeError, ValueError):
        return fallback


def _clean_image_url(raw):
    """http(s) URL, "" when blank, None when rejected — image_url lands in a
    style attribute, so any other scheme is stored CSS/URL injection."""
    url = (raw or "").strip()
    if not url:
        return ""
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        return url
    return None


def _parse_event_schedule(form, fallback_event=None):
    """Read the schedule fields from an event form.

    Returns (fields, error): fields is a dict with weekday/time/starts_at/
    ends_at ready to assign. Weekly events keep starts_at NULL; one-time
    events also derive weekday/time so day filters and legacy displays work.
    Forms without a `schedule` field (legacy/tests) behave as weekly.
    """
    from datetime import datetime, timedelta

    schedule = form.get("schedule", "weekly")
    weekday = form.get("weekday") or (fallback_event.weekday if fallback_event else "Monday")
    if weekday not in WEEKDAYS:
        weekday = "Monday"
    time_raw = form.get("time") or (fallback_event.time if fallback_event else "18:00")
    try:
        hour, minute = (int(p) for p in time_raw.split(":")[:2])
        assert 0 <= hour < 24 and 0 <= minute < 60
    except (ValueError, AssertionError):
        return None, "That start time doesn't look right."
    time_str = f"{hour:02d}:{minute:02d}"

    if schedule != "once":
        return {"weekday": weekday, "time": time_str, "starts_at": None, "ends_at": None}, None

    try:
        day = datetime.strptime(form.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        return None, "Pick a date for a one-time event."
    starts_at = datetime(day.year, day.month, day.day, hour, minute)
    ends_at = None
    end_raw = (form.get("end_time") or "").strip()
    if end_raw:
        try:
            eh, em = (int(p) for p in end_raw.split(":")[:2])
            ends_at = datetime(day.year, day.month, day.day, eh, em)
            if ends_at <= starts_at:
                ends_at += timedelta(days=1)  # crosses midnight
        except ValueError:
            return None, "That end time doesn't look right."
    return {
        "weekday": starts_at.strftime("%A"),
        "time": time_str,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }, None


def owns_club(view):
    @wraps(view)
    def wrapped(club_id, *args, **kwargs):
        club = Club.query.get_or_404(club_id)
        if not club.can_manage(current_user):
            abort(403)
        if current_app.config["EMAIL_VERIFICATION_REQUIRED"] and not current_user.is_email_verified:
            flash("Verify your email before using officer tools.", "error")
            return redirect(url_for("auth.settings"))
        return view(club, *args, **kwargs)
    return wrapped


@bp.route("/")
@login_required
def dashboard():
    clubs = current_user.managed_clubs
    return render_template("officer_dashboard.html", clubs=clubs)


@bp.route("/club/<int:club_id>/edit", methods=["GET", "POST"])
@login_required
@owns_club
def edit_club(club):
    if request.method == "POST":
        website = _clean_website(request.form.get("website", ""))
        if website is None:
            flash("Website must be a normal http(s) link.", "error")
            return render_template("club_edit.html", club=club)
        club.description = request.form.get("description", "").strip()
        club.website = website
        club.instagram = request.form.get("instagram", "").strip().lstrip("@")
        club.contact_email = request.form.get("contact_email", "").strip()
        club.meeting_info = request.form.get("meeting_info", "").strip()
        club.dues = request.form.get("dues", "").strip()
        club.hours_per_week = request.form.get("hours_per_week", "").strip()
        from datetime import datetime
        club.updated_at = datetime.utcnow()
        db.session.commit()
        flash(f"{club.name}'s listing has been updated.", "success")
        return redirect(url_for("officer.dashboard"))
    return render_template("club_edit.html", club=club)


@bp.route("/club/<int:club_id>/events/new", methods=["GET", "POST"])
@login_required
@owns_club
def new_event(club):
    if request.method == "POST":
        schedule, schedule_error = _parse_event_schedule(request.form)
        image_url = _clean_image_url(request.form.get("image_url", ""))
        name = request.form.get("name", "").strip()
        if not name:
            flash("Give the event a name.", "error")
        elif schedule_error:
            flash(schedule_error, "error")
        elif image_url is None:
            flash("Image must be a normal http(s) link.", "error")
        else:
            event = Event(
                club_id=club.id,
                name=name,
                description=request.form.get("description", "").strip(),
                location=request.form.get("location", "").strip() or "TBD",
                image_url=image_url,
                capacity=_parse_capacity(request.form.get("capacity"), 50),
                is_public=bool(request.form.get("is_public")),
                created_by=current_user.id,
                **schedule,
            )
            db.session.add(event)
            db.session.commit()
            flash(f"{event.name} has been posted.", "success")
            return redirect(url_for("officer.dashboard"))
        return render_template("event_form.html", club=club, event=None, weekdays=WEEKDAYS)

    return render_template("event_form.html", club=club, event=None, weekdays=WEEKDAYS)


@bp.route("/event/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if not event.club.can_manage(current_user):
        abort(403)

    if request.method == "POST":
        schedule, schedule_error = _parse_event_schedule(request.form, fallback_event=event)
        image_url = _clean_image_url(request.form.get("image_url", ""))
        if schedule_error:
            flash(schedule_error, "error")
            return render_template("event_form.html", club=event.club, event=event, weekdays=WEEKDAYS)
        if image_url is None:
            flash("Image must be a normal http(s) link.", "error")
            return render_template("event_form.html", club=event.club, event=event, weekdays=WEEKDAYS)
        event.name = request.form.get("name", "").strip() or event.name
        event.description = request.form.get("description", "").strip()
        event.weekday = schedule["weekday"]
        event.time = schedule["time"]
        event.starts_at = schedule["starts_at"]
        event.ends_at = schedule["ends_at"]
        event.location = request.form.get("location", "").strip() or "TBD"
        event.image_url = image_url
        event.capacity = _parse_capacity(request.form.get("capacity"), event.capacity)
        event.is_public = bool(request.form.get("is_public"))
        db.session.commit()
        flash(f"{event.name} has been updated.", "success")
        return redirect(url_for("officer.dashboard"))

    return render_template("event_form.html", club=event.club, event=event, weekdays=WEEKDAYS)


@bp.route("/event/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    if not event.club.can_manage(current_user):
        abort(403)
    name = event.name
    db.session.delete(event)
    db.session.commit()
    flash(f"{name} has been removed.", "info")
    return redirect(url_for("officer.dashboard"))


@bp.route("/event/<int:event_id>/attendees")
@login_required
def attendees(event_id):
    event = Event.query.get_or_404(event_id)
    if not event.club.can_manage(current_user):
        abort(403)
    rsvps = sorted(event.rsvps, key=lambda r: r.created_at)
    return render_template("event_attendees.html", event=event, rsvps=rsvps)


@bp.route("/club/<int:club_id>/members")
@login_required
@owns_club
def members(club):
    member_rows = sorted(club.memberships, key=lambda m: m.joined_at)
    return render_template("club_members.html", club=club, memberships=member_rows)


@bp.route("/club/<int:club_id>/team", methods=["POST"])
@login_required
@owns_club
def add_team_member(club):
    email = request.form.get("email", "").strip().lower()
    role_name = request.form.get("role", "officer").strip().lower() or "officer"
    allowed_roles = {"officer", "events", "communications", "admin"}
    if role_name not in allowed_roles:
        role_name = "officer"

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("That user needs to create an Eventully account before you can add them.", "error")
        return redirect(url_for("officer.dashboard"))
    if club.officer_id == user.id:
        flash(f"{user.name} is already the club owner.", "info")
        return redirect(url_for("officer.dashboard"))

    existing = ClubRole.query.filter_by(club_id=club.id, user_id=user.id).first()
    if existing:
        existing.role = role_name
        flash(f"{user.name}'s role was updated.", "success")
    else:
        db.session.add(ClubRole(club_id=club.id, user_id=user.id, role=role_name, invited_by_id=current_user.id))
        flash(f"{user.name} can now help manage {club.name}.", "success")
    db.session.commit()

    send_email(
        user.email,
        f"You were added as an officer for {club.name}",
        f"Hi {user.name},\n\n{current_user.name} added you as {role_name} for {club.name} on Eventully.",
    )
    return redirect(url_for("officer.dashboard"))


@bp.route("/club/<int:club_id>/team/<int:role_id>/remove", methods=["POST"])
@login_required
@owns_club
def remove_team_member(club, role_id):
    if club.officer_id != current_user.id:
        abort(403)
    role = ClubRole.query.filter_by(id=role_id, club_id=club.id).first_or_404()
    name = role.user.name
    db.session.delete(role)
    db.session.commit()
    flash(f"{name} was removed from {club.name}'s officer team.", "info")
    return redirect(url_for("officer.dashboard"))
