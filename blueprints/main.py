from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from matching import MAJORS, smart_match_clubs
from utils import WEEKDAY_ORDER, event_sort_key
from models import Club, Event, Membership, UserPreference

bp = Blueprint("main", __name__)


@bp.route("/healthz")
def healthz():
    # Deliberately touches no database: uptime pings keep the web dyno warm
    # without waking the (compute-metered) Postgres instance.
    return {"status": "ok"}, 200


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    category_counts = (
        db.session.query(Club.category, func.count(Club.id))
        .group_by(Club.category)
        .order_by(func.count(Club.id).desc())
        .all()
    )
    stats = {
        "total_clubs": Club.query.count(),
        "total_events": Event.query.count(),
        "categories": len(category_counts),
        "top_categories": dict(category_counts[:8]),
    }
    ticker_clubs = [
        c.name for c in Club.query.order_by(func.random()).limit(18).all()
    ]
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

    page = int(request.args.get("page", 0))
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

    # Events the user has RSVP'd to, soonest weekday first
    my_events = sorted(
        (r.event for r in current_user.rsvps),
        key=lambda e: (WEEKDAY_ORDER.get(e.weekday, 7), e.time),
    )

    # Events from the user's clubs they haven't RSVP'd to yet
    rsvp_ids = {r.event_id for r in current_user.rsvps}
    club_events = (
        sorted(
            Event.query.filter(Event.club_id.in_(user_club_ids), ~Event.id.in_(rsvp_ids)).all(),
            key=event_sort_key,
        )[:3]
    ) if user_club_ids else []

    featured_events = sorted(
        Event.query.filter(Event.is_public.is_(True), ~Event.id.in_(rsvp_ids)).all(),
        key=event_sort_key,
    )[:6]

    # A taste of the matcher: top 3 unjoined matches
    suggestions = []
    if current_user.preferences:
        all_matches = smart_match_clubs(
            Club.query.all(),
            current_user.preferences.category_list(),
            current_user.preferences.major,
            current_user.preferences.time_commitment,
        )
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
        stats=stats,
        has_preferences=current_user.preferences is not None,
    )


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
    from utils import WEEKDAYS
    user_club_ids = current_user.joined_club_ids
    events = sorted(
        Event.query.filter(db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids))).all(),
        key=event_sort_key,
    )
    by_day = {day: [] for day in WEEKDAYS}
    for event in events:
        by_day.setdefault(event.weekday, []).append(event)
    rsvp_ids = {r.event_id for r in current_user.rsvps}
    return render_template("calendar.html", by_day=by_day, weekdays=WEEKDAYS, rsvp_ids=rsvp_ids)


@bp.route("/search")
def search():
    q = request.args.get("q", "").strip()
    clubs, events = [], []
    if q:
        like = f"%{q}%"
        clubs = (Club.query.filter(db.or_(Club.name.ilike(like), Club.description.ilike(like)))
                 .order_by(Club.name).limit(24).all())
        user_club_ids = current_user.joined_club_ids if current_user.is_authenticated else set()
        events = sorted(
            Event.query
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
    return Response("User-agent: *\nAllow: /\nSitemap: " + url_for("main.sitemap", _external=True) + "\n",
                    mimetype="text/plain")


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
