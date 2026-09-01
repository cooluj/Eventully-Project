import smtplib
import threading
from email.message import EmailMessage

from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_email_token(user, purpose):
    # The pw fingerprint binds the token to the current password, so a used
    # (or otherwise stale) reset link dies the moment the password changes.
    return _serializer().dumps(
        {"uid": user.id, "email": user.email, "pw": (user.password_hash or "")[-12:]},
        salt=purpose,
    )


def load_email_token(token, purpose, max_age=86400):
    return _serializer().loads(token, salt=purpose, max_age=max_age)


def token_matches_user(data, user, require_fingerprint=False):
    """Shared token→user validation, including the password fingerprint.

    Reset links pass require_fingerprint=True so a link dies once the
    password changes (i.e. after it's been used). Verify links only prove
    mailbox ownership, so a missing fingerprint is tolerated there.
    """
    if not user or user.email != data.get("email"):
        return False
    fingerprint = data.get("pw")
    if fingerprint is None:
        return not require_fingerprint
    return fingerprint == (user.password_hash or "")[-12:]


def send_email(to_email, subject, body):
    server = current_app.config.get("MAIL_SERVER")
    if not server:
        current_app.logger.info("Email not configured. To=%s Subject=%s Body=%s", to_email, subject, body)
        return False
    if current_app.config.get("MAIL_USERNAME") and not current_app.config.get("MAIL_PASSWORD"):
        current_app.logger.warning("Email username configured without password. To=%s Subject=%s", to_email, subject)
        return False

    message = EmailMessage()
    message["From"] = current_app.config["MAIL_FROM"]
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(server, current_app.config["MAIL_PORT"], timeout=10) as smtp:
            if current_app.config["MAIL_USE_TLS"]:
                smtp.starttls()
            if current_app.config["MAIL_USERNAME"]:
                smtp.login(current_app.config["MAIL_USERNAME"], current_app.config["MAIL_PASSWORD"])
            smtp.send_message(message)
        return True
    except Exception:
        current_app.logger.exception("Failed to send email to %s", to_email)
        return False


def send_verification_email(user):
    token = make_email_token(user, "verify-email")
    link = url_for("auth.verify_email", token=token, _external=True)
    return send_email(
        user.email,
        "Verify your Eventully email",
        f"Hi {user.name},\n\nVerify your Eventully account here:\n{link}\n\nThis link expires in 24 hours.",
    )


def send_password_reset_email(user):
    token = make_email_token(user, "reset-password")
    link = url_for("auth.reset_password", token=token, _external=True)
    return send_email(
        user.email,
        "Reset your Eventully password",
        f"Hi {user.name},\n\nReset your Eventully password here:\n{link}\n\nThis link expires in 1 hour.",
    )


def send_claim_decision_email(claim):
    if claim.status == "approved":
        subject = f"Your Eventully claim for {claim.club.name} was approved"
        body = (
            f"Hi {claim.requester.name},\n\n"
            f"Your claim for {claim.club.name} was approved. You can now manage the listing, "
            "post events, invite co-officers, and message members from your officer dashboard."
        )
    else:
        subject = f"Update on your Eventully claim for {claim.club.name}"
        body = (
            f"Hi {claim.requester.name},\n\n"
            f"Your claim for {claim.club.name} was not approved yet."
        )
    if claim.decision_note:
        body += f"\n\nAdmin note:\n{claim.decision_note}"
    body += "\n\nEventully"
    return send_email(claim.requester.email, subject, body)


def notify(user_id, kind, title, body="", link=""):
    """Queue an in-app notification row (caller commits the session)."""
    from extensions import db
    from models import Notification
    db.session.add(Notification(
        user_id=user_id, kind=kind, title=title[:200], body=body[:500], link=link[:300]
    ))


def _email_batch_async(recipients, subject, body):
    """Fire-and-forget batched email over one SMTP connection."""
    if not recipients:
        return
    if not current_app.config.get("MAIL_SERVER"):
        for email in recipients:
            current_app.logger.info(
                "Email not configured. To=%s Subject=%s Body=%s", email, subject, body
            )
        return
    app = current_app._get_current_object()
    threading.Thread(
        target=_send_batch, args=(app, sorted(recipients), subject, body), daemon=True
    ).start()


def notify_new_event(event):
    """Tell a club's members about a freshly posted event (in-app + email)."""
    from flask import url_for
    link = url_for("events.detail", event_id=event.id)
    url = url_for("events.detail", event_id=event.id, _external=True)
    title = f"{event.club.name} posted: {event.name}"
    body = f"{event.when_primary}, {event.when_secondary} · {event.location}"
    recipients = set()
    for membership in event.club.memberships:
        if membership.user_id == event.created_by:
            continue
        notify(membership.user_id, "event", title, body, link)
        recipients.add(membership.user.email)
    email_body = (
        f"{event.club.name} just posted a new event on Eventully:\n\n"
        f"{event.name}\n{body}\n\nDetails and registration:\n{url}"
    )
    _email_batch_async(recipients, title, email_body)


def notify_event_cancelled(event):
    """Tell everyone who registered that an event is off (in-app + email)."""
    from flask import url_for
    link = url_for("events.detail", event_id=event.id)
    title = f"Cancelled: {event.name}"
    body = f"{event.club.name} cancelled this event ({event.when_primary}, {event.when_secondary})."
    recipients = set()
    for rsvp in event.rsvps:
        notify(rsvp.user_id, "cancelled", title, body, link)
        recipients.add(rsvp.user.email)
    email_body = (
        f"Heads up — {event.club.name} cancelled an event you registered for:\n\n"
        f"{event.name}\n{event.when_primary}, {event.when_secondary} · {event.location}\n\n"
        "Sorry for the change of plans. Your other registrations are unaffected."
    )
    _email_batch_async(recipients, title, email_body)


def send_personalized_batch(messages):
    """Send many (to, subject, body) triples over one SMTP connection on a
    background thread — for digests and reminders, where every body differs."""
    if not messages:
        return 0
    if not current_app.config.get("MAIL_SERVER"):
        for to_email, subject, _ in messages:
            current_app.logger.info("Email not configured. To=%s Subject=%s", to_email, subject)
        return 0
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], timeout=10) as smtp:
                    if app.config["MAIL_USE_TLS"]:
                        smtp.starttls()
                    if app.config["MAIL_USERNAME"]:
                        smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                    for to_email, subject, body in messages:
                        msg = EmailMessage()
                        msg["From"] = app.config["MAIL_FROM"]
                        msg["To"] = to_email
                        msg["Subject"] = subject
                        msg.set_content(body)
                        try:
                            smtp.send_message(msg)
                        except smtplib.SMTPException:
                            app.logger.exception("Failed to send to %s", to_email)
            except Exception:
                app.logger.exception("Personalized batch failed")

    threading.Thread(target=run, daemon=True).start()
    return len(messages)


def send_new_message_email(message):
    """Notify club members/officers of a new message.

    Sends on a background thread over a single SMTP connection: a club with N
    members must not hold the request open for N sequential SMTP handshakes
    (that's a guaranteed gunicorn timeout for any real club).
    """
    recipients = {
        user.email
        for _, user in message.club.officer_users
        if user.id != message.sender_id
    }
    for membership in message.club.memberships:
        if membership.user_id != message.sender_id:
            recipients.add(membership.user.email)
    if not recipients:
        return

    subject = f"New message in {message.club.name}"
    body = f"{message.sender.name} posted in {message.club.name}:\n\n{message.body}"

    if not current_app.config.get("MAIL_SERVER"):
        for email in recipients:
            current_app.logger.info(
                "Email not configured. To=%s Subject=%s Body=%s", email, subject, body
            )
        return

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_send_batch, args=(app, sorted(recipients), subject, body), daemon=True
    )
    thread.start()


def _send_batch(app, recipients, subject, body):
    with app.app_context():
        try:
            with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], timeout=10) as smtp:
                if app.config["MAIL_USE_TLS"]:
                    smtp.starttls()
                if app.config["MAIL_USERNAME"]:
                    smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                for email in recipients:
                    message = EmailMessage()
                    message["From"] = app.config["MAIL_FROM"]
                    message["To"] = email
                    message["Subject"] = subject
                    message.set_content(body)
                    try:
                        smtp.send_message(message)
                    except smtplib.SMTPException:
                        app.logger.exception("Failed to send message email to %s", email)
        except Exception:
            app.logger.exception("Message notification batch failed")
