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
        event = Event(
            club_id=club.id,
            name=request.form.get("name", "").strip(),
            description=request.form.get("description", "").strip(),
            weekday=request.form.get("weekday", "Monday"),
            time=request.form.get("time", "18:00"),
            location=request.form.get("location", "").strip() or "TBD",
            image_url=request.form.get("image_url", "").strip(),
            capacity=_parse_capacity(request.form.get("capacity"), 50),
            is_public=bool(request.form.get("is_public")),
            created_by=current_user.id,
        )
        if not event.name:
            flash("Give the event a name.", "error")
            return render_template("event_form.html", club=club, event=None, weekdays=WEEKDAYS)
        db.session.add(event)
        db.session.commit()
        flash(f"{event.name} has been posted.", "success")
        return redirect(url_for("officer.dashboard"))

    return render_template("event_form.html", club=club, event=None, weekdays=WEEKDAYS)


@bp.route("/event/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if not event.club.can_manage(current_user):
        abort(403)

    if request.method == "POST":
        event.name = request.form.get("name", "").strip() or event.name
        event.description = request.form.get("description", "").strip()
        event.weekday = request.form.get("weekday", event.weekday)
        event.time = request.form.get("time", event.time)
        event.location = request.form.get("location", "").strip() or "TBD"
        event.image_url = request.form.get("image_url", "").strip()
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
