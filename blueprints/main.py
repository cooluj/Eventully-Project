from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from matching import MAJORS, smart_match_clubs
from utils import campus_now, event_sort_key, group_events_by_day, parse_page, split_upcoming
from models import Club, Event, Membership, UserPreference

bp = Blueprint("main", __name__)

# Tiny in-process TTL cache for the anonymous landing page (its stats scan
# whole tables; single-worker deploy makes this safe and effective).
_landing_cache = {"at": 0.0, "data": None}
_LANDING_TTL = 600

# Per-user matcher results (user_id -> (timestamp, matches)).
_suggest_cache = {}


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
            "total_clubs": Club.query.count(),
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

    categories = [c[0] for c in db.session.query(Club.category).distinct().order_by(Club.category).all()]
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
    all_clubs = [c for c in Club.query.all() if c.id not in hidden]
    all_matches = smart_match_clubs(all_clubs, prefs.category_list(), prefs.major, prefs.time_commitment)

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
    memberships = Membership.query.filter_by(user_id=current_user.id).all()
    user_clubs = [m.club for m in memberships]
    user_club_ids = {c.id for c in user_clubs}

    # Events the user has RSVP'd to, soonest first (past one-offs excluded)
    my_events, _ = split_upcoming(
        r.event for r in current_user.rsvps if not r.event.is_cancelled
    )

    # Events from the user's clubs they haven't RSVP'd to yet
    rsvp_ids = {r.event_id for r in current_user.rsvps}
    live = Event.query.filter(Event.status != "cancelled")
    club_events = (
        split_upcoming(
            live.filter(Event.club_id.in_(user_club_ids), ~Event.id.in_(rsvp_ids)).all()
        )[0][:3]
    ) if user_club_ids else []

    featured_events = split_upcoming(
        live.filter(Event.is_public.is_(True), ~Event.id.in_(rsvp_ids)).all()
    )[0][:6]

    # A taste of the matcher: top 3 unjoined matches. Scoring all 1,231
    # clubs in Python on every dashboard load doesn't scale, so cache per
    # user for a few minutes.
    suggestions = []
    if current_user.preferences:
        import time
        cached = _suggest_cache.get(current_user.id)
        if cached and time.time() - cached[0] < 600:
            all_matches = cached[1]
        else:
            all_matches = smart_match_clubs(
                Club.query.all(),
                current_user.preferences.category_list(),
                current_user.preferences.major,
                current_user.preferences.time_commitment,
            )
            if len(_suggest_cache) > 500:
                _suggest_cache.clear()
            _suggest_cache[current_user.id] = (time.time(), all_matches)
        suggestions = [m for m in all_matches if m["club"].id not in user_club_ids][:3]

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
        "total_available": Club.query.count(),
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
    unread_ids = {n.id for n in items if not n.is_read}
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
        "total_clubs": Club.query.count(),
        "total_events": Event.query.count(),
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
    week = []
    for offset in range(7):
        day = (now + timedelta(days=offset)).date()
        todays = [e for e in upcoming if e.next_occurrence(now).date() == day]
        week.append((day, todays))
    rsvp_ids = {r.event_id for r in current_user.rsvps}
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
    joined_ids = current_user.joined_club_ids if current_user.is_authenticated else set()
    saved_ids = current_user.saved_club_ids if current_user.is_authenticated else set()
    return render_template("search.html", q=q, clubs=clubs, events=events,
                           joined_ids=joined_ids, saved_ids=saved_ids)


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
    return Response("\n".join(lines), mimetype="text/plain")


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
    return Response("\n".join(xml), mimetype="application/xml")
