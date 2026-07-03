from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import Club, ClubMessage
from notifications import send_new_message_email

bp = Blueprint("messages", __name__, url_prefix="/messages")


def _can_access_club_messages(club):
    return (
        club.id in current_user.joined_club_ids
        or club.can_manage(current_user)
        or current_user.is_admin(current_app.config["ADMIN_EMAILS"])
    )


def _message_clubs():
    club_ids = current_user.joined_club_ids | current_user.managed_club_ids
    if current_user.is_admin(current_app.config["ADMIN_EMAILS"]):
        club_ids |= {club.id for club in Club.query.filter(Club.officer_id.isnot(None)).limit(30).all()}
    if not club_ids:
        return []

    clubs = Club.query.filter(Club.id.in_(club_ids)).all()
    latest_messages = (
        ClubMessage.query
        .filter(ClubMessage.club_id.in_(club_ids))
        .order_by(ClubMessage.created_at.desc())
        .all()
    )
    latest_by_club = {}
    counts_by_club = {club.id: 0 for club in clubs}
    for message in latest_messages:
        latest_by_club.setdefault(message.club_id, message)
        counts_by_club[message.club_id] = counts_by_club.get(message.club_id, 0) + 1

    def sort_key(club):
        latest = latest_by_club.get(club.id)
        return (latest.created_at if latest else datetime.min, club.name.lower())

    clubs.sort(key=sort_key, reverse=True)
    return [
        {
            "club": club,
            "latest": latest_by_club.get(club.id),
            "message_count": counts_by_club.get(club.id, 0),
            "is_officer": club.can_manage(current_user),
            "is_member": club.id in current_user.joined_club_ids,
        }
        for club in clubs
    ]


@bp.route("/")
@login_required
def inbox():
    conversations = _message_clubs()
    if conversations:
        return redirect(url_for("messages.thread", club_id=conversations[0]["club"].id))
    return render_template(
        "messages.html",
        conversations=[],
        selected_club=None,
        thread_messages=[],
    )


@bp.route("/club/<int:club_id>", methods=["GET", "POST"])
@login_required
def thread(club_id):
    club = Club.query.get_or_404(club_id)
    if not _can_access_club_messages(club):
        abort(403)

    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if not body:
            flash("Write a message before sending.", "error")
            return redirect(url_for("messages.thread", club_id=club.id))
        if len(body) > 1200:
            flash("Keep messages under 1,200 characters for now.", "error")
            return redirect(url_for("messages.thread", club_id=club.id))

        message = ClubMessage(club_id=club.id, sender_id=current_user.id, body=body)
        db.session.add(message)
        db.session.commit()
        send_new_message_email(message)
        flash("Message sent.", "success")
        return redirect(url_for("messages.thread", club_id=club.id))

    thread_messages = (
        ClubMessage.query
        .filter_by(club_id=club.id)
        .order_by(ClubMessage.created_at.asc())
        .all()
    )
    return render_template(
        "messages.html",
        conversations=_message_clubs(),
        selected_club=club,
        thread_messages=thread_messages,
    )


@bp.route("/message/<int:message_id>/delete", methods=["POST"])
@login_required
def delete_message(message_id):
    message = ClubMessage.query.get_or_404(message_id)
    can_delete = (
        message.sender_id == current_user.id
        or message.club.can_manage(current_user)
        or current_user.is_admin(current_app.config["ADMIN_EMAILS"])
    )
    if not can_delete:
        abort(403)

    message.deleted_at = datetime.utcnow()
    message.deleted_by_id = current_user.id
    db.session.commit()
    flash("Message removed.", "info")
    return redirect(url_for("messages.thread", club_id=message.club_id))
