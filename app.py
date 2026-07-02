import os

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError

from config import Config
from extensions import csrf, db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from blueprints.auth import bp as auth_bp
    from blueprints.main import bp as main_bp
    from blueprints.clubs import bp as clubs_bp
    from blueprints.events import bp as events_bp
    from blueprints.officer import bp as officer_bp
    from blueprints.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(clubs_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(officer_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_admin_flag():
        from flask_login import current_user
        is_admin = (
            current_user.is_authenticated
            and current_user.is_admin(app.config["ADMIN_EMAILS"])
        )
        return {"is_site_admin": is_admin}

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        return render_template("500.html"), 500

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        flash("Your session expired — please try that again.", "error")
        return redirect(request.referrer or url_for("main.index"))

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.cli.command("seed-db")
    def seed_db_command():
        """Load clubs_categorized.csv into the database (skips clubs that already exist)."""
        from seed import seed_clubs
        with app.app_context():
            count = seed_clubs()
            print(f"Seeded {count} new clubs.")

    if app.config["AUTO_SEED"]:
        bootstrap_database(app)

    return app


def bootstrap_database(app):
    """Create tables and load the club directory if the database is empty.

    Runs at import time so gunicorn deploys (no shell, no __main__ block)
    come up working. Both steps are idempotent; races between workers are
    harmless because seeding skips existing rows.
    """
    with app.app_context():
        db.create_all()
        from seed import seed_clubs
        try:
            seed_clubs()
        except Exception:
            app.logger.exception("Database seeding failed; continuing with what exists.")


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
