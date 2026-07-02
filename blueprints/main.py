from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from matching import MAJORS, smart_match_clubs
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
    return render_template("onboarding.html", categories=categories, majors=MAJORS)


@bp.route("/recommendations")
@login_required
def recommendations():
    prefs = current_user.preferences
    if not prefs:
        return redirect(url_for("main.onboarding"))

    all_clubs = Club.query.all()
    all_matches = smart_match_clubs(all_clubs, prefs.category_list(), prefs.major, prefs.time_commitment)

    page = int(request.args.get("page", 0))
    per_page = current_app.config["MATCHES_PER_PAGE"]
    start, end = page * per_page, page * per_page + per_page
    matches = all_matches[start:end]
    has_more = end < len(all_matches)

    joined_ids = current_user.joined_club_ids
    return render_template(
        "recommendations.html",
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

    visible_events = (
        Event.query.filter(db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids)))
        .order_by(Event.weekday)
        .limit(6)
        .all()
    )

    stats = {
        "clubs_joined": len(user_clubs),
        "events_upcoming": Event.query.filter(
            db.or_(Event.is_public.is_(True), Event.club_id.in_(user_club_ids))
        ).count(),
        "total_available": Club.query.count(),
        "officer_of": len(current_user.officer_of),
    }

    return render_template(
        "dashboard.html", clubs=user_clubs[:6], events=visible_events, stats=stats
    )
