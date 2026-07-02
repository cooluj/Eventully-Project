from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Club, Event
from utils import WEEKDAYS

bp = Blueprint("officer", __name__, url_prefix="/officer")


def owns_club(view):
    @wraps(view)
    def wrapped(club_id, *args, **kwargs):
        club = Club.query.get_or_404(club_id)
        if club.officer_id != current_user.id:
            abort(403)
        return view(club, *args, **kwargs)
    return wrapped


@bp.route("/")
@login_required
def dashboard():
    clubs = list(current_user.officer_of)
    return render_template("officer_dashboard.html", clubs=clubs)


@bp.route("/club/<int:club_id>/edit", methods=["GET", "POST"])
@login_required
@owns_club
def edit_club(club):
    if request.method == "POST":
        club.description = request.form.get("description", "").strip()
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
            capacity=int(request.form.get("capacity") or 50),
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
    if event.club.officer_id != current_user.id:
        abort(403)

    if request.method == "POST":
        event.name = request.form.get("name", "").strip() or event.name
        event.description = request.form.get("description", "").strip()
        event.weekday = request.form.get("weekday", event.weekday)
        event.time = request.form.get("time", event.time)
        event.location = request.form.get("location", "").strip() or "TBD"
        event.image_url = request.form.get("image_url", "").strip()
        event.capacity = int(request.form.get("capacity") or event.capacity)
        event.is_public = bool(request.form.get("is_public"))
        db.session.commit()
        flash(f"{event.name} has been updated.", "success")
        return redirect(url_for("officer.dashboard"))

    return render_template("event_form.html", club=event.club, event=event, weekdays=WEEKDAYS)


@bp.route("/event/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.club.officer_id != current_user.id:
        abort(403)
    name = event.name
    db.session.delete(event)
    db.session.commit()
    flash(f"{name} has been removed.", "info")
    return redirect(url_for("officer.dashboard"))
