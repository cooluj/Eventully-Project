from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Club, ClubClaim, Membership

bp = Blueprint("clubs", __name__)


@bp.route("/clubs")
@login_required
def browse():
    category = request.args.get("category", "all")
    search = request.args.get("search", "").strip()
    page = int(request.args.get("page", 0))
    per_page = current_app.config["CLUBS_PER_PAGE"]

    query = Club.query
    if category != "all":
        query = query.filter_by(category=category)
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(Club.name.ilike(like), Club.description.ilike(like)))

    total = query.count()
    clubs_list = query.order_by(Club.name).offset(page * per_page).limit(per_page).all()
    has_more = (page + 1) * per_page < total

    categories = ["all"] + [c[0] for c in db.session.query(Club.category).distinct().order_by(Club.category).all()]
    joined_ids = current_user.joined_club_ids

    return render_template(
        "clubs.html",
        clubs=clubs_list,
        categories=categories,
        current_category=category,
        search_query=search,
        result_count=total,
        current_page=page,
        has_more=has_more,
        joined_ids=joined_ids,
    )


@bp.route("/club/<int:club_id>")
@login_required
def detail(club_id):
    club = Club.query.get_or_404(club_id)
    is_member = club.id in current_user.joined_club_ids
    is_officer = club.officer_id == current_user.id
    pending_claim = ClubClaim.query.filter_by(club_id=club.id, user_id=current_user.id, status="pending").first()
    similar = Club.query.filter(Club.category == club.category, Club.id != club.id).limit(4).all()

    return render_template(
        "club_detail.html",
        club=club,
        is_member=is_member,
        is_officer=is_officer,
        pending_claim=pending_claim,
        similar_clubs=similar,
    )


@bp.route("/club/<int:club_id>/join", methods=["POST"])
@login_required
def join(club_id):
    club = Club.query.get_or_404(club_id)
    existing = Membership.query.filter_by(user_id=current_user.id, club_id=club.id).first()
    if not existing:
        db.session.add(Membership(user_id=current_user.id, club_id=club.id))
        db.session.commit()
        flash(f"You joined {club.name}!", "success")
    return redirect(url_for("clubs.detail", club_id=club.id))


@bp.route("/club/<int:club_id>/leave", methods=["POST"])
@login_required
def leave(club_id):
    club = Club.query.get_or_404(club_id)
    Membership.query.filter_by(user_id=current_user.id, club_id=club.id).delete()
    db.session.commit()
    flash(f"You left {club.name}.", "info")
    return redirect(url_for("clubs.detail", club_id=club.id))


@bp.route("/club/<int:club_id>/claim", methods=["GET", "POST"])
@login_required
def claim(club_id):
    club = Club.query.get_or_404(club_id)

    if club.is_claimed:
        flash("This club has already been claimed by an officer.", "error")
        return redirect(url_for("clubs.detail", club_id=club.id))

    existing = ClubClaim.query.filter_by(club_id=club.id, user_id=current_user.id, status="pending").first()
    if existing:
        flash("You already have a pending claim request for this club.", "info")
        return redirect(url_for("clubs.detail", club_id=club.id))

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            flash("Tell us a bit about your role in the club so we can verify your request.", "error")
            return render_template("claim_club.html", club=club)

        db.session.add(ClubClaim(club_id=club.id, user_id=current_user.id, message=message))
        db.session.commit()
        flash("Claim request submitted! We'll review it shortly.", "success")
        return redirect(url_for("clubs.detail", club_id=club.id))

    return render_template("claim_club.html", club=club)
