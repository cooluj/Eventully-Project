from datetime import datetime
from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Club, ClubClaim
from notifications import send_claim_decision_email

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_admin(current_app.config["ADMIN_EMAILS"]):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@bp.route("/claims")
@login_required
@admin_only
def claims():
    pending = ClubClaim.query.filter_by(status="pending").order_by(ClubClaim.created_at).all()
    recent = ClubClaim.query.filter(ClubClaim.status != "pending").order_by(ClubClaim.decided_at.desc()).limit(20).all()
    claimed_clubs = Club.query.filter(Club.officer_id.isnot(None)).order_by(Club.claimed_at.desc()).all()
    return render_template("admin_claims.html", pending=pending, recent=recent, claimed_clubs=claimed_clubs)


@bp.route("/claims/<int:claim_id>/approve", methods=["POST"])
@login_required
@admin_only
def approve(claim_id):
    claim = ClubClaim.query.get_or_404(claim_id)
    if claim.status != "pending":
        flash("That claim has already been decided.", "info")
        return redirect(url_for("admin.claims"))

    if claim.club.is_claimed:
        flash("This club was claimed by someone else in the meantime.", "error")
        claim.status = "rejected"
    else:
        claim.club.officer_id = claim.user_id
        claim.club.claimed_at = datetime.utcnow()
        claim.status = "approved"
        flash(f"{claim.requester.name} is now the officer for {claim.club.name}.", "success")

    claim.decision_note = request.form.get("decision_note", "").strip()
    claim.decided_by = current_user.id
    claim.decided_at = datetime.utcnow()
    db.session.commit()
    send_claim_decision_email(claim)
    return redirect(url_for("admin.claims"))


@bp.route("/claims/<int:claim_id>/reject", methods=["POST"])
@login_required
@admin_only
def reject(claim_id):
    claim = ClubClaim.query.get_or_404(claim_id)
    if claim.status == "pending":
        claim.status = "rejected"
        claim.decision_note = request.form.get("decision_note", "").strip()
        claim.decided_by = current_user.id
        claim.decided_at = datetime.utcnow()
        db.session.commit()
        send_claim_decision_email(claim)
        flash("Claim rejected.", "info")
    return redirect(url_for("admin.claims"))


@bp.route("/clubs/<int:club_id>/revoke", methods=["POST"])
@login_required
@admin_only
def revoke(club_id):
    club = Club.query.get_or_404(club_id)
    if club.officer_id is None:
        flash("That club has no officer.", "info")
    else:
        name = club.officer.name
        club.officer_id = None
        club.claimed_at = None
        db.session.commit()
        flash(f"{name} is no longer the officer of {club.name}. The listing is unclaimed again.", "success")
    return redirect(url_for("admin.claims"))
