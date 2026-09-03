from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import RSVP, Club, Event, load_attendee_previews
from utils import (WEEKDAYS, build_calendar_link, build_ics, campus_now, group_events_by_day,
                   split_upcoming, ttl_cached, window_events)

bp = Blueprint("events", __name__)

# Timeline pages two weeks at a time: every weekly event lands exactly once
# per window, and the page stays readable when hundreds of clubs post.
WINDOW_DAYS = 14


def category_list():
    return ttl_cached(
        "club-categories", 600,
        lambda: [c[0] for c in db.session.query(Club.category).distinct().order_by(Club.category).all()],
    )


def _visible_events_query():
    query = Event.query.filter(Event.status != "cancelled")
    if not current_user.is_authenticated:
        return query.filter(Event.is_public.is_(True))
    user_club_ids = current_user.joined_club_ids
    return query.filter(db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids)))


def _can_view_event(event):
    if event.is_public:
        return True
    if not current_user.is_authenticated:
        return False
    return (
        event.club_id in current_user.joined_club_ids
        or event.club.can_manage(current_user)
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
    from datetime import datetime, timedelta

    category = request.args.get("category", "all")
    day = request.args.get("day", "all")
    scope = request.args.get("scope", "all")
    allowed_scopes = {"all", "public", "members", "rsvped"}
    if scope not in allowed_scopes:
        scope = "all"

    rsvp_ids = (
        {r.event_id for r in current_user.rsvps} if current_user.is_authenticated else set()
    )

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

    now = campus_now()
    today = now.date()
    try:
        window_start_day = datetime.strptime(request.args.get("from", ""), "%Y-%m-%d").date()
    except ValueError:
        window_start_day = today
    if window_start_day <= today:
        window_start_day = today
        window_start = now  # nothing earlier than right now on the first page
    else:
        window_start = datetime.combine(window_start_day, datetime.min.time())
    window_end = datetime.combine(window_start_day + timedelta(days=WINDOW_DAYS), datetime.min.time())

    upcoming, past = split_upcoming(query.all(), now)
    visible = window_events(upcoming, window_start, window_end)
    past = past[:12] if window_start_day == today else []
    load_attendee_previews(visible + past)
    day_groups = group_events_by_day(visible, now=now, start=window_start)

    later_exists = any(e.next_occurrence(window_start) >= window_end for e in upcoming)
    filters = {k: v for k, v in (("category", category), ("day", day), ("scope", scope)) if v != "all"}
    later_url = url_for("events.browse", **filters, **{"from": (window_start_day + timedelta(days=WINDOW_DAYS)).isoformat()}) if later_exists else None
    earlier_day = window_start_day - timedelta(days=WINDOW_DAYS)
    earlier_url = None
    if window_start_day > today:
        earlier_url = url_for("events.browse", **filters, **({"from": earlier_day.isoformat()} if earlier_day > today else {}))

    window_label = None
    if window_start_day > today:
        last = window_start_day + timedelta(days=WINDOW_DAYS - 1)
        window_label = f"{window_start_day.strftime('%b %d').replace(' 0', ' ')} – {last.strftime('%b %d').replace(' 0', ' ')}"

    return render_template(
        "events.html",
        events=visible,
        day_groups=day_groups,
        past_events=past,
        categories=["all"] + category_list(),
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
        later_url=later_url,
        earlier_url=earlier_url,
        window_label=window_label,
        total_upcoming=len(upcoming),
    )


@bp.route("/event/<int:event_id>")
def detail(event_id):
    event = _visible_event_or_404(event_id)
    is_rsvpd = current_user.is_authenticated and RSVP.query.filter_by(event_id=event.id, user_id=current_user.id).first() is not None
    load_attendee_previews([event])
    return render_template(
        "event_detail.html", event=event, is_rsvpd=is_rsvpd, calendar_link=build_calendar_link(event)
    )


@bp.route("/event/<int:event_id>/rsvp", methods=["POST"])
@login_required
def rsvp(event_id):
    event = _visible_event_or_404(event_id)
    if event.is_cancelled:
        flash("This event was cancelled.", "error")
        return redirect(url_for("events.detail", event_id=event.id))
    existing = RSVP.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash("Registration cancelled.", "info")
    else:
        # Row lock so two simultaneous registrations can't oversell the last
        # spot (no-op on SQLite, real on Postgres).
        db.session.query(Event).filter_by(id=event.id).with_for_update().first()
        count = db.session.query(RSVP).filter_by(event_id=event.id).count()
        if count >= (event.capacity or 0):
            db.session.rollback()
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
