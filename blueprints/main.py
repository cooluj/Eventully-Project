from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from matching import MAJORS, smart_match_clubs
from utils import campus_now, event_sort_key, group_events_by_day, parse_page, split_upcoming, ttl_cached
from models import RSVP, Club, Event, Membership, UserPreference, load_attendee_previews

bp = Blueprint("main", __name__)

# Tiny in-process TTL cache for the anonymous landing page (its stats scan
# whole tables; single-worker deploy makes this safe and effective).
_landing_cache = {"at": 0.0, "data": None}
_LANDING_TTL = 600

# Per-user matcher results (user_id -> (timestamp, matches)).
_suggest_cache = {}
_SUGGEST_TTL = 600


def club_count():
    return ttl_cached("club-count", 600, lambda: Club.query.count())


def category_list():
    return ttl_cached(
        "club-categories", 600,
        lambda: [c[0] for c in db.session.query(Club.category).distinct().order_by(Club.category).all()],
    )


def matches_for(user):
    """Scored matches for a user, memoized for a few minutes: scoring all
    1,231 clubs in Python on every dashboard/recommendations load is the
    single most expensive thing the app does."""
    import time
    prefs = user.preferences
    if not prefs:
        return []
    key = (user.id, prefs.categories, prefs.major, prefs.time_commitment)
    cached = _suggest_cache.get(user.id)
    if cached and cached[0] == key and time.time() - cached[1] < _SUGGEST_TTL:
        return cached[2]
    matches = smart_match_clubs(
        Club.query.all(), prefs.category_list(), prefs.major, prefs.time_commitment
    )
    if len(_suggest_cache) > 500:
        _suggest_cache.clear()
    _suggest_cache[user.id] = (key, time.time(), matches)
    return matches


def rsvp_event_ids(user):
    return {row[0] for row in db.session.query(RSVP.event_id).filter_by(user_id=user.id).all()}


@bp.route("/healthz")
def healthz():
    # Deliberately touches no database: uptime pings keep the web dyno warm
    # without waking the (compute-metered) Postgres instance.
    return {"status": "ok"}, 200


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    import time
    if _landing_cache["data"] and time.time() - _landing_cache["at"] < _LANDING_TTL:
        stats, ticker_clubs = _landing_cache["data"]
    else:
        category_counts = (
            db.session.query(Club.category, func.count(Club.id))
            .group_by(Club.category)
            .order_by(func.count(Club.id).desc())
            .all()
        )
        public_events, _ = split_upcoming(
            Event.query.filter(Event.is_public.is_(True), Event.status != "cancelled").all()
        )
        stats = {
            "total_clubs": club_count(),
            "total_events": len(public_events),
            "categories": len(category_counts),
            "top_categories": dict(category_counts[:8]),
        }
        ticker_clubs = [
            c.name for c in Club.query.order_by(func.random()).limit(18).all()
        ]
        _landing_cache.update(at=time.time(), data=(stats, ticker_clubs))
    return render_template("landing.html", stats=stats, ticker_clubs=ticker_clubs)


@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        categories = request.form.getlist("categories")
        major = request.form.get("major", "")
        time_commitment = request.form.get("time_commitment", "")

        prefs = current_user.preferences
        if not prefs:
            prefs = UserPreference(user_id=current_user.id)
            db.session.add(prefs)
        prefs.categories = ",".join(categories)
        prefs.major = major
        prefs.time_commitment = time_commitment
        db.session.commit()

        return redirect(url_for("main.recommendations"))

    categories = category_list()
    prefs = current_user.preferences
    selected = set(prefs.category_list()) if prefs else set()
    return render_template(
        "onboarding.html",
        categories=categories,
        majors=MAJORS,
        selected_categories=selected,
        current_major=prefs.major if prefs else "",
        current_commitment=prefs.time_commitment if prefs else "",
    )


@bp.route("/recommendations")
@login_required
def recommendations():
    prefs = current_user.preferences
    if not prefs:
        return redirect(url_for("main.onboarding"))

    hidden = current_user.hidden_club_ids
    all_matches = [m for m in matches_for(current_user) if m["club"].id not in hidden]

    page = parse_page(request.args.get("page"))
    per_page = current_app.config["MATCHES_PER_PAGE"]
    start, end = page * per_page, page * per_page + per_page
    matches = all_matches[start:end]
    has_more = end < len(all_matches)

    joined_ids = current_user.joined_club_ids
    saved_ids = current_user.saved_club_ids
    return render_template(
        "recommendations.html",
        saved_ids=saved_ids,
        matches=matches,
        total_matches=len(all_matches),
        current_page=page,
        has_more=has_more,
        joined_ids=joined_ids,
    )


@bp.route("/dashboard")
@login_required
def dashboard():
    user_club_ids = current_user.joined_club_ids
    user_clubs = (
        Club.query.filter(Club.id.in_(user_club_ids)).order_by(Club.name).all()
        if user_club_ids else []
    )

    # Events the user has RSVP'd to, soonest first (past one-offs excluded)
    rsvp_ids = rsvp_event_ids(current_user)
    live = Event.query.filter(Event.status != "cancelled")
    my_events, _ = split_upcoming(
        live.filter(Event.id.in_(rsvp_ids)).all() if rsvp_ids else []
    )

    # Events from the user's clubs they haven't RSVP'd to yet
    club_events = (
        split_upcoming(
            live.filter(Event.club_id.in_(user_club_ids), ~Event.id.in_(rsvp_ids)).all()
        )[0][:3]
    ) if user_club_ids else []

    featured_events = split_upcoming(
        live.filter(Event.is_public.is_(True), ~Event.id.in_(rsvp_ids)).all()
    )[0][:6]
    load_attendee_previews(my_events[:6] + club_events + featured_events)

    # A taste of the matcher: top 3 unjoined matches (memoized per user).
    suggestions = [
        m for m in matches_for(current_user) if m["club"].id not in user_club_ids
    ][:3]

    saved = [s.club for s in current_user.saved_clubs if s.kind == "saved"]
    saved_ids = current_user.saved_club_ids

    starter_clubs = []
    if not user_clubs:
        starter_clubs = (
            Club.query.join(Event)
            .filter(Event.is_public.is_(True))
            .distinct()
            .order_by(Club.name)
            .limit(3)
            .all()
        )
        if len(starter_clubs) < 3:
            seen = {c.id for c in starter_clubs}
            starter_clubs.extend(
                c for c in Club.query.order_by(Club.name).limit(6).all()
                if c.id not in seen
            )
            starter_clubs = starter_clubs[:3]

    stats = {
        "clubs_joined": len(user_clubs),
        "events_rsvpd": len(my_events),
        "total_available": club_count(),
        "officer_of": len(current_user.managed_clubs),
    }

    return render_template(
        "dashboard.html",
        clubs=user_clubs[:6],
        saved_clubs=saved[:6],
        my_events=my_events[:6],
        club_events=club_events,
        featured_events=featured_events,
        suggestions=suggestions,
        starter_clubs=starter_clubs,
        saved_ids=saved_ids,
        rsvp_ids=rsvp_ids,
        stats=stats,
        has_preferences=current_user.preferences is not None,
    )


@bp.route("/notifications")
@login_required
def notifications():
    from datetime import datetime
    from models import Notification
    items = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    # Snapshot which were unread (for bolding), then mark everything read.
    # Detach the loaded rows first: commit() would expire them and the
    # template would re-fetch every notification one query at a time.
    unread_ids = {n.id for n in items if not n.is_read}
    for item in items:
        db.session.expunge(item)
    if unread_ids:
        Notification.query.filter_by(user_id=current_user.id, read_at=None).update(
            {"read_at": datetime.utcnow()}, synchronize_session=False
        )
        db.session.commit()
    return render_template("notifications.html", items=items, unread_ids=unread_ids)


@bp.route("/me/calendar.ics")
def my_calendar_feed():
    """Login-free personal feed (calendar apps can't log in); the token in
    the URL is the credential."""
    from flask import Response, abort
    from models import User
    from utils import build_ics_feed
    token = request.args.get("t", "")
    user = User.query.filter_by(ics_token=token).first() if token else None
    if not user:
        abort(404)
    events = [r.event for r in user.rsvps if not r.event.is_cancelled]
    feed = build_ics_feed(events, name=f"Eventully — {user.name.split(' ')[0]}'s events")
    return Response(feed, mimetype="text/calendar")


@bp.route("/about")
def about():
    stats = {
        "total_clubs": club_count(),
        "total_events": Event.query.filter(Event.status != "cancelled").count(),
    }
    return render_template("about.html", stats=stats)


@bp.route("/calendar")
@login_required
def calendar():
    from datetime import timedelta
    user_club_ids = current_user.joined_club_ids
    upcoming, _ = split_upcoming(
        Event.query.filter(Event.status != "cancelled")
        .filter(db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids))).all()
    )
    now = campus_now()
    # Today plus the next seven days: a weekly event whose slot already
    # passed today lands on the same weekday next week, which a plain
    # 7-day window would drop.
    by_day = {}
    for event in upcoming:
        by_day.setdefault(event.next_occurrence(now).date(), []).append(event)
    week = []
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        week.append((day, by_day.get(day, [])))
    rsvp_ids = rsvp_event_ids(current_user)
    # Mint the personal-feed token on first visit so the subscribe box works.
    if not current_user.ics_token:
        current_user.ensure_ics_token()
        db.session.commit()
    feed_url = url_for("main.my_calendar_feed", t=current_user.ics_token, _external=True)
    return render_template(
        "calendar.html", week=week, today=now.date(), rsvp_ids=rsvp_ids, feed_url=feed_url
    )


@bp.route("/search")
def search():
    from sqlalchemy import case
    q = request.args.get("q", "").strip()
    clubs, events = [], []
    if q:
        like = f"%{q}%"
        # Weighted relevance: a name hit beats a description hit, a claimed
        # (actively maintained) club beats a dormant listing.
        relevance = (
            case((Club.name.ilike(f"{q}%"), 4), else_=0)
            + case((Club.name.ilike(like), 2), else_=0)
            + case((Club.officer_id.isnot(None), 1), else_=0)
        )
        clubs = (Club.query.filter(db.or_(Club.name.ilike(like), Club.description.ilike(like)))
                 .order_by(relevance.desc(), Club.name).limit(24).all())
        user_club_ids = current_user.joined_club_ids if current_user.is_authenticated else set()
        events = sorted(
            Event.query
            .filter(Event.status != "cancelled")
            .filter(db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids)))
            .filter(db.or_(Event.name.ilike(like), Event.description.ilike(like), Event.location.ilike(like)))
            .limit(12).all(),
            key=event_sort_key,
        )
        load_attendee_previews(events)
    joined_ids = current_user.joined_club_ids if current_user.is_authenticated else set()
    saved_ids = current_user.saved_club_ids if current_user.is_authenticated else set()
    from flask import make_response
    response = make_response(render_template("search.html", q=q, clubs=clubs, events=events,
                                             joined_ids=joined_ids, saved_ids=saved_ids))
    # Reflected query text next to CSRF-bearing save forms: leave this one
    # page uncompressed so response size can't leak the token (BREACH).
    response.headers["Content-Encoding"] = "identity"
    return response


@bp.route("/help")
def help_page():
    return render_template("help.html")


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.route("/terms")
def terms():
    return render_template("terms.html")


@bp.route("/robots.txt")
def robots():
    from flask import Response
    lines = [
        "User-agent: *",
        "Disallow: /settings",
        "Disallow: /messages",
        "Disallow: /officer",
        "Disallow: /admin",
        "Disallow: /notifications",
        "Disallow: /me/",
        "Allow: /",
        "Sitemap: " + url_for("main.sitemap", _external=True),
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain",
                    headers={"Cache-Control": "public, max-age=3600"})


@bp.route("/sitemap.xml")
def sitemap():
    from flask import Response
    pages = [url_for("main.index", _external=True),
             url_for("main.about", _external=True),
             url_for("main.help_page", _external=True),
             url_for("clubs.browse", _external=True),
             url_for("events.browse", _external=True)]
    pages += [url_for("clubs.detail", club_id=c.id, _external=True)
              for c in Club.query.with_entities(Club.id).all()]
    pages += [url_for("events.detail", event_id=e.id, _external=True)
              for e in Event.query.filter_by(is_public=True).with_entities(Event.id).all()]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"<url><loc>{p}</loc></url>" for p in pages]
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})
