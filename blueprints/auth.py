import time
from collections import defaultdict

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import db
from models import User
from utils import is_safe_next_url

bp = Blueprint("auth", __name__)

# Simple in-memory rate limiter for credential endpoints. Per-process, which
# matches the single-worker gunicorn deploy; swap for Redis if workers scale.
_attempts = defaultdict(list)
MAX_ATTEMPTS = 8
WINDOW_SECONDS = 15 * 60


def _rate_limited(key):
    now = time.time()
    _attempts[key] = [t for t in _attempts[key] if now - t < WINDOW_SECONDS]
    return len(_attempts[key]) >= MAX_ATTEMPTS


def _record_failure(key):
    _attempts[key].append(time.time())


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


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


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

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

        login_user(user, remember=True)
        flash(f"Welcome to Eventully, {user.name.split(' ')[0]}!", "success")
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
        next_url = request.args.get("next")
        if is_safe_next_url(next_url, request.host_url):
            return redirect(next_url)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html", email="")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if _rate_limited(f"reset|{request.remote_addr}"):
            flash("Too many reset requests. Try again later.", "error")
            return render_template("forgot_password.html")
        _record_failure(f"reset|{request.remote_addr}")

        user = User.query.filter_by(email=email).first()
        if user:
            token = _reset_serializer().dumps(user.id)
            link = url_for("auth.reset_password", token=token, _external=True)
            from utils import send_email
            sent = send_email(
                email,
                "Reset your Eventully password",
                f"Hi {user.name.split(' ')[0]},\n\nReset your password here (link expires in 1 hour):\n{link}\n\n"
                "If you didn't ask for this, you can ignore this email.",
            )
            if not sent:
                current_app.logger.warning("SMTP not configured; reset link for %s: %s", email, link)
                if current_app.debug:
                    flash(f"Dev mode (no SMTP): use this link — {link}", "info")
        # Same message either way: don't reveal whether the account exists
        flash("If that account exists, we've emailed a reset link.", "success")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        user_id = _reset_serializer().loads(token, max_age=3600)
    except SignatureExpired:
        flash("That reset link has expired — request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("That reset link isn't valid.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.get(User, user_id)
    if not user:
        flash("That account no longer exists.", "error")
        return redirect(url_for("auth.register"))

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
            flash("Password updated — log in with your new password.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)


@bp.route("/settings/delete", methods=["POST"])
@login_required
def delete_account():
    if not current_user.check_password(request.form.get("password", "")):
        flash("Incorrect password — account not deleted.", "error")
        return redirect(url_for("auth.settings"))

    from models import Club, ClubClaim
    user = current_user._get_current_object()
    # Release any clubs this user officers, and drop their claims
    Club.query.filter_by(officer_id=user.id).update({"officer_id": None, "claimed_at": None})
    ClubClaim.query.filter_by(user_id=user.id).delete()
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Your account and data have been deleted. Take care!", "info")
    return redirect(url_for("main.index"))
