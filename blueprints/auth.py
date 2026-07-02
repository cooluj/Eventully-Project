from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from extensions import db
from models import User

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
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
        return redirect(next_url or url_for("main.dashboard"))

    return render_template("login.html", email="")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))
