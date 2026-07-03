from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Club, ClubClaim, Membership, SavedClub

bp = Blueprint("clubs", __name__)


@bp.route("/clubs")
@login_required
def browse():
    category = request.args.get("category", "all")
    search = request.args.get("search", "").strip()
    page = int(request.args.get("page", 0))
    per_page = current_app.config["CLUBS_PER_PAGE"]

    status = request.args.get("status", "all")
    sort = request.args.get("sort", "name")

    query = Club.query
    if category != "all":
        query = query.filter_by(category=category)
    if status == "claimed":
        query = query.filter(Club.officer_id.isnot(None))
    elif status == "unclaimed":
        query = query.filter(Club.officer_id.is_(None))
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(Club.name.ilike(like), Club.description.ilike(like)))

    total = query.count()
    if sort == "members":
        from sqlalchemy import func
        from models import Membership as M
        query = (query.outerjoin(M).group_by(Club.id)
                 .order_by(func.count(M.id).desc(), Club.name))
    else:
        query = query.order_by(Club.name)
    clubs_list = query.offset(page * per_page).limit(per_page).all()
    has_more = (page + 1) * per_page < total

    categories = ["all"] + [c[0] for c in db.session.query(Club.category).distinct().order_by(Club.category).all()]
    joined_ids = current_user.joined_club_ids
    saved_ids = current_user.saved_club_ids

    return render_template(
        "clubs.html",
        clubs=clubs_list,
        categories=categories,
        current_category=category,
        current_status=status,
        current_sort=sort,
        search_query=search,
        result_count=total,
        current_page=page,
        has_more=has_more,
        joined_ids=joined_ids,
        saved_ids=saved_ids,
    )


@bp.route("/club/<int:club_id>")
@login_required
def detail(club_id):
    club = Club.query.get_or_404(club_id)
    is_member = club.id in current_user.joined_club_ids
    is_saved = club.id in current_user.saved_club_ids
    is_officer = club.officer_id == current_user.id
    pending_claim = ClubClaim.query.filter_by(club_id=club.id, user_id=current_user.id, status="pending").first()
    similar = Club.query.filter(Club.category == club.category, Club.id != club.id).limit(4).all()

    return render_template(
        "club_detail.html",
        club=club,
        is_member=is_member,
        is_saved=is_saved,
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


def _toggle_bookmark(club_id, kind):
    club = Club.query.get_or_404(club_id)
    existing = SavedClub.query.filter_by(user_id=current_user.id, club_id=club.id, kind=kind).first()
    if existing:
        db.session.delete(existing)
        added = False
    else:
        db.session.add(SavedClub(user_id=current_user.id, club_id=club.id, kind=kind))
        added = True
    db.session.commit()
    return club, added


@bp.route("/club/<int:club_id>/save", methods=["POST"])
@login_required
def save(club_id):
    club, added = _toggle_bookmark(club_id, "saved")
    flash(f"Saved {club.name} to your list." if added else f"Removed {club.name} from your saved clubs.", "success" if added else "info")
    return redirect(request.form.get("next") or url_for("clubs.detail", club_id=club.id))


@bp.route("/club/<int:club_id>/hide", methods=["POST"])
@login_required
def hide(club_id):
    club, added = _toggle_bookmark(club_id, "hidden")
    if added:
        flash(f"Got it — we won't recommend {club.name} again.", "info")
    return redirect(request.form.get("next") or url_for("main.recommendations"))
