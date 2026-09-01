"""Token-guarded endpoints for scheduled jobs (weekly digest, day-of
reminders). A scheduler — the repo's GitHub Action, or any cron — hits
these over HTTPS with ?token=$TASKS_TOKEN; without a configured token
they 404 so the surface doesn't exist until it's deliberately enabled.
"""
import hmac
from datetime import timedelta

from flask import Blueprint, abort, current_app, request, url_for

from extensions import db
from models import Event, Membership, User
from notifications import notify, send_personalized_batch
from utils import campus_now, split_upcoming

bp = Blueprint("tasks", __name__, url_prefix="/tasks")


def _require_token():
    expected = current_app.config.get("TASKS_TOKEN", "")
    supplied = request.args.get("token", "") or request.headers.get("X-Tasks-Token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(404)


@bp.route("/digest")
def weekly_digest():
    """'Your clubs this week' — one email per member with upcoming events."""
    _require_token()
    now = campus_now()
    horizon = now + timedelta(days=7)

    upcoming, _ = split_upcoming(Event.query.filter(Event.status != "cancelled").all())
    by_club = {}
    for event in upcoming:
        if event.next_occurrence(now) <= horizon:
            by_club.setdefault(event.club_id, []).append(event)

    outbox = []
    users = (
        User.query.filter(User.digest_opt_out.isnot(True))
        .join(Membership, Membership.user_id == User.id)
        .distinct()
        .all()
    )
    for user in users:
        club_ids = {m.club_id for m in user.memberships}
        lines = []
        for club_id in club_ids:
            for event in by_club.get(club_id, []):
                lines.append(
                    f"• {event.name} — {event.when_primary}, {event.when_secondary}"
                    f" · {event.location} ({event.club.name})"
                )
        if not lines:
            continue
        body = (
            f"Hi {user.name.split(' ')[0]},\n\nYour clubs this week on Eventully:\n\n"
            + "\n".join(sorted(lines))
            + f"\n\nSee everything: {url_for('events.browse', _external=True)}"
            + f"\n\nToo many emails? Turn the digest off in settings: {url_for('auth.settings', _external=True)}"
        )
        outbox.append((user.email, "Your clubs this week · Eventully", body))

    queued = send_personalized_batch(outbox)
    return {"status": "ok", "emails_queued": queued, "users_considered": len(users)}, 200


@bp.route("/reminders")
def event_reminders():
    """Day-of reminders for everyone registered to something happening today."""
    _require_token()
    now = campus_now()
    today = now.date()

    upcoming, _ = split_upcoming(Event.query.filter(Event.status != "cancelled").all())
    todays = [e for e in upcoming if e.next_occurrence(now).date() == today]

    outbox = []
    notified = 0
    for event in todays:
        link = url_for("events.detail", event_id=event.id)
        for rsvp in event.rsvps:
            notify(
                rsvp.user_id, "reminder",
                f"Today: {event.name}",
                f"{event.when_secondary} · {event.location}",
                link,
            )
            notified += 1
            outbox.append((
                rsvp.user.email,
                f"Today: {event.name} · {event.when_secondary.split('·')[0].strip()}",
                (
                    f"Hi {rsvp.user.name.split(' ')[0]},\n\nReminder — you're registered for:\n\n"
                    f"{event.name}\nToday, {event.when_secondary} · {event.location}\n"
                    f"Hosted by {event.club.name}\n\n"
                    f"Details: {url_for('events.detail', event_id=event.id, _external=True)}"
                ),
            ))
    db.session.commit()
    queued = send_personalized_batch(outbox)
    return {"status": "ok", "events_today": len(todays), "reminders": notified, "emails_queued": queued}, 200
