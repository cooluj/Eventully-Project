import smtplib
from email.message import EmailMessage

from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_email_token(user, purpose):
    return _serializer().dumps({"uid": user.id, "email": user.email}, salt=purpose)


def load_email_token(token, purpose, max_age=86400):
    return _serializer().loads(token, salt=purpose, max_age=max_age)


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
        with smtplib.SMTP(server, current_app.config["MAIL_PORT"]) as smtp:
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


def send_new_message_email(message):
    recipients = {
        user.email
        for _, user in message.club.officer_users
        if user.id != message.sender_id
    }
    for membership in message.club.memberships:
        if membership.user_id != message.sender_id:
            recipients.add(membership.user.email)
    for email in recipients:
        send_email(
            email,
            f"New message in {message.club.name}",
            f"{message.sender.name} posted in {message.club.name}:\n\n{message.body}",
        )
