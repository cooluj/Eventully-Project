from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import RSVP, Club, Event
from utils import WEEKDAYS, build_calendar_link, build_ics, event_sort_key

bp = Blueprint("events", __name__)


def _visible_events_query():
    if not current_user.is_authenticated:
        return Event.query.filter(Event.is_public.is_(True))
    user_club_ids = current_user.joined_club_ids
    return Event.query.filter(db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids)))


def _can_view_event(event):
    if event.is_public:
        return True
    if not current_user.is_authenticated:
        return False
    return (
        event.club_id in current_user.joined_club_ids
        or event.club.officer_id == current_user.id
        or current_user.is_admin(current_app.config["ADMIN_EMAILS"])
    )


def _visible_event_or_404(event_id):
    event = Event.query.get_or_404(event_id)
    if not _can_view_event(event):
        # Hide existence from anonymous visitors; tell members-only to logged-in users
        abort(404 if not current_user.is_authenticated else 403)
    return event


@bp.route("/events")
def browse():
    category = request.args.get("category", "all")
    day = request.args.get("day", "all")
    scope = request.args.get("scope", "all")
    allowed_scopes = {"all", "public", "members", "rsvped"}
    if scope not in allowed_scopes:
        scope = "all"

    rsvp_ids = {r.event_id for r in current_user.rsvps} if current_user.is_authenticated else set()

    query = _visible_events_query()
    if scope == "public":
        query = query.filter(Event.is_public.is_(True))
    elif scope == "members":
        query = query.filter(Event.is_public.is_(False))
    elif scope == "rsvped":
        query = query.filter(Event.id.in_(rsvp_ids or {0}))

    if category != "all":
        query = query.join(Club).filter(Club.category == category)
    if day != "all":
        query = query.filter(Event.weekday == day)

    visible_events = sorted(query.all(), key=event_sort_key)
    categories = ["all"] + [c[0] for c in db.session.query(Club.category).distinct().order_by(Club.category).all()]

    return render_template(
        "events.html",
        events=visible_events,
        categories=categories,
        days=["all"] + WEEKDAYS,
        scopes=[
            ("all", "All"),
            ("public", "Public"),
            ("members", "Members only"),
            ("rsvped", "RSVPed"),
        ],
        current_scope=scope,
        current_category=category,
        current_day=day,
        rsvp_ids=rsvp_ids,
    )


@bp.route("/event/<int:event_id>")
def detail(event_id):
    event = _visible_event_or_404(event_id)
    is_rsvpd = current_user.is_authenticated and RSVP.query.filter_by(event_id=event.id, user_id=current_user.id).first() is not None
    return render_template(
        "event_detail.html", event=event, is_rsvpd=is_rsvpd, calendar_link=build_calendar_link(event)
    )


@bp.route("/event/<int:event_id>/rsvp", methods=["POST"])
@login_required
def rsvp(event_id):
    event = _visible_event_or_404(event_id)
    existing = RSVP.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash("RSVP removed.", "info")
    else:
        if event.attendee_count >= event.capacity:
            flash("This event is at capacity.", "error")
            return redirect(url_for("events.detail", event_id=event.id))
        db.session.add(RSVP(event_id=event.id, user_id=current_user.id))
        db.session.commit()
        flash(f"You're on the list for {event.name}!", "success")
    return redirect(url_for("events.detail", event_id=event.id))


@bp.route("/event/<int:event_id>/calendar.ics")
@login_required
def ics(event_id):
    event = _visible_event_or_404(event_id)
    return Response(
        build_ics(event),
        mimetype="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=eventully-{event.id}.ics"},
    )
