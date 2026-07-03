from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import User
from utils import is_safe_next_url

bp = Blueprint("auth", __name__)


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

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Incorrect email or password.", "error")
            return render_template("login.html", email=email)

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
