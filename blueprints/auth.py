import time
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired

from extensions import db
from models import Club, ClubClaim, ClubMessage, ClubRole, User
from notifications import load_email_token, send_password_reset_email, send_verification_email
from utils import is_safe_next_url

bp = Blueprint("auth", __name__)

# Simple in-memory rate limiter for credential endpoints. Per-process, which
# matches the current single-worker deploy; swap for Redis if workers scale.
_attempts = defaultdict(list)
MAX_ATTEMPTS = 8
WINDOW_SECONDS = 15 * 60


def _rate_limited(key, max_attempts=MAX_ATTEMPTS):
    now = time.time()
    _attempts[key] = [t for t in _attempts[key] if now - t < WINDOW_SECONDS]
    return len(_attempts[key]) >= max_attempts


def _record_failure(key):
    _attempts[key].append(time.time())


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        form = request.form.get("form")

        if form == "profile":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Your name can't be empty.", "error")
            else:
                current_user.name = name
                db.session.commit()
                flash("Profile updated.", "success")

        elif form == "password":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")
            if not current_user.check_password(current):
                flash("Your current password is incorrect.", "error")
            elif len(new) < 8:
                flash("New password must be at least 8 characters.", "error")
            elif new != confirm:
                flash("New passwords don't match.", "error")
            else:
                current_user.set_password(new)
                db.session.commit()
                flash("Password changed.", "success")

        return redirect(url_for("auth.settings"))

    return render_template("settings.html")


@bp.route("/resend-verification", methods=["POST"])
@login_required
def resend_verification():
    if current_user.is_email_verified:
        flash("Your email is already verified.", "info")
        return redirect(request.referrer or url_for("auth.settings"))

    # Cap per user: every send costs real email-provider quota.
    limiter_key = f"verify|{current_user.id}"
    if _rate_limited(limiter_key, max_attempts=3):
        flash("You've requested several verification emails recently — check your inbox and spam folder.", "info")
        return redirect(request.referrer or url_for("auth.settings"))
    _record_failure(limiter_key)

    if send_verification_email(current_user):
        flash("Verification email sent. Check your inbox for the link.", "success")
    else:
        flash("Email delivery is not configured yet, so no verification email was sent.", "info")
    return redirect(request.referrer or url_for("auth.settings"))


@bp.route("/verify-email/<token>")
def verify_email(token):
    try:
        data = load_email_token(token, "verify-email", max_age=86400)
    except SignatureExpired:
        flash("That verification link expired. Request a new one from settings.", "error")
        return redirect(url_for("auth.login"))
    except BadSignature:
        flash("That verification link is invalid.", "error")
        return redirect(url_for("auth.login"))

    user = db.session.get(User, data.get("uid"))
    if not user or user.email != data.get("email"):
        flash("That verification link no longer matches an account.", "error")
        return redirect(url_for("auth.login"))

    user.email_verified_at = datetime.utcnow()
    db.session.commit()
    if not current_user.is_authenticated:
        login_user(user, remember=True)
    flash("Email verified. You're ready to use officer tools.", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        # Generous cap: a whole club signing up from campus WiFi shares one
        # NAT IP, so this only needs to stop scripted abuse.
        limiter_key = f"register|{request.remote_addr}"
        if _rate_limited(limiter_key, max_attempts=50):
            flash("Too many signups from this connection. Try again in 15 minutes.", "error")
            return render_template("register.html", email=email, name=name)
        _record_failure(limiter_key)

        errors = []
        if not name:
            errors.append("Please enter your name.")
        if current_app.config["REQUIRE_EDU_EMAIL"] and not email.endswith(".edu"):
            errors.append("Please use a .edu email address.")
        if "@" not in email:
            errors.append("Please enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords don't match.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with that email already exists. Try logging in instead.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html", email=email, name=name)

        user = User(email=email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        email_sent = send_verification_email(user)

        login_user(user, remember=True)
        if email_sent:
            flash(f"Welcome to Eventully, {user.name.split(' ')[0]}! Check your inbox to verify your email.", "success")
        else:
            flash(
                f"Welcome to Eventully, {user.name.split(' ')[0]}! Email delivery is not configured yet, "
                "so verification is temporarily unavailable.",
                "success",
            )
        return redirect(url_for("main.onboarding"))

    return render_template("register.html", email="", name="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        limiter_key = f"{email}|{request.remote_addr}"
        if _rate_limited(limiter_key):
            flash("Too many failed attempts. Try again in 15 minutes.", "error")
            return render_template("login.html", email=email)

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            _record_failure(limiter_key)
            flash("Incorrect email or password.", "error")
            return render_template("login.html", email=email)

        _attempts.pop(limiter_key, None)
        login_user(user, remember=True)
        flash(f"Welcome back, {user.name.split(' ')[0]}!", "success")
        if current_app.config["EMAIL_VERIFICATION_REQUIRED"] and not user.is_email_verified:
            flash("Verify your email before using officer-only tools.", "info")
        next_url = request.args.get("next")
        if is_safe_next_url(next_url, request.host_url):
            return redirect(next_url)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html", email="")


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        limiter_key = f"reset|{request.remote_addr}"
        if _rate_limited(limiter_key):
            flash("Too many reset requests. Try again later.", "error")
            return render_template("forgot_password.html", email=email)
        _record_failure(limiter_key)

        user = User.query.filter_by(email=email).first()
        if user:
            send_password_reset_email(user)
        flash("If that email exists, a reset link is on the way.", "info")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", email="")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    try:
        data = load_email_token(token, "reset-password", max_age=3600)
    except SignatureExpired:
        flash("That reset link expired. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("That reset link is invalid.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.get(User, data.get("uid"))
    if not user or user.email != data.get("email"):
        flash("That reset link no longer matches an account.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords don't match.", "error")
        else:
            user.set_password(password)
            db.session.commit()
            flash("Password reset. You can log in with your new password.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))


@bp.route("/settings/delete", methods=["POST"])
@login_required
def delete_account():
    if not current_user.check_password(request.form.get("password", "")):
        flash("Incorrect password — account not deleted.", "error")
        return redirect(url_for("auth.settings"))

    user = current_user._get_current_object()
    Club.query.filter_by(officer_id=user.id).update({"officer_id": None, "claimed_at": None})
    ClubClaim.query.filter_by(user_id=user.id).delete()
    ClubClaim.query.filter_by(decided_by=user.id).update({"decided_by": None})
    ClubRole.query.filter_by(user_id=user.id).delete()
    ClubRole.query.filter_by(invited_by_id=user.id).update({"invited_by_id": None})
    ClubMessage.query.filter_by(sender_id=user.id).delete()
    ClubMessage.query.filter_by(deleted_by_id=user.id).update({"deleted_by_id": None})
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Your account and data have been deleted. Take care!", "info")
    return redirect(url_for("main.index"))
