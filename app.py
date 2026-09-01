import os

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import csrf, db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Render/Heroku terminate TLS at a proxy one hop away. Without this,
    # request.remote_addr is the proxy IP (breaking per-IP rate limits) and
    # _external=True links in emails come out http://.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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
    from blueprints.messages import bp as messages_bp
    from blueprints.officer import bp as officer_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.tasks import bp as tasks_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(clubs_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(officer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tasks_bp)

    @app.template_filter("days_ago")
    def days_ago(dt):
        if not dt:
            return ""
        from datetime import datetime
        days = (datetime.utcnow() - dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days} days ago"
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"

    @app.template_filter("short_datetime")
    def short_datetime(dt):
        # DB timestamps are naive UTC; students read Pacific wall time.
        from utils import utc_to_campus
        if not dt:
            return ""
        text = utc_to_campus(dt).strftime("%b %d, %I:%M %p")
        return text.replace(" 0", " ").replace(", 0", ", ")

    @app.template_filter("clock_time")
    def clock_time(dt):
        from utils import utc_to_campus
        if not dt:
            return ""
        return utc_to_campus(dt).strftime("%I:%M %p").lstrip("0")

    @app.context_processor
    def inject_admin_flag():
        from flask_login import current_user
        is_admin = (
            current_user.is_authenticated
            and current_user.is_admin(app.config["ADMIN_EMAILS"])
        )
        return {"is_site_admin": is_admin}

    @app.context_processor
    def inject_demo_flag():
        return {"show_demo_login": app.config["SEED_DEMO_ACCOUNT"]}

    @app.context_processor
    def inject_nav_badges():
        """Unread counts for the nav bell and Messages link."""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {"unread_notifications": 0, "unread_threads": 0}
        from sqlalchemy import func
        from models import ClubMessage, Notification, ThreadRead
        unread_notifications = Notification.query.filter_by(
            user_id=current_user.id, read_at=None
        ).count()
        club_ids = current_user.joined_club_ids | current_user.managed_club_ids
        unread_threads = 0
        if club_ids:
            markers = {
                tr.club_id: tr.last_read_at
                for tr in ThreadRead.query.filter_by(user_id=current_user.id).all()
            }
            latest = (
                db.session.query(ClubMessage.club_id, func.max(ClubMessage.created_at))
                .filter(ClubMessage.club_id.in_(club_ids), ClubMessage.sender_id != current_user.id)
                .group_by(ClubMessage.club_id)
                .all()
            )
            unread_threads = sum(
                1 for club_id, newest in latest
                if markers.get(club_id) is None or newest > markers[club_id]
            )
        return {
            "unread_notifications": unread_notifications,
            "unread_threads": unread_threads,
        }

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

    @app.before_request
    def enforce_canonical_host():
        canonical = app.config["CANONICAL_HOST"]
        if not canonical or request.host.lower() == canonical:
            return None
        # /healthz stays reachable on the host the platform probes;
        # only redirect safe methods so in-flight form posts aren't dropped.
        if request.path == "/healthz" or request.method not in ("GET", "HEAD"):
            return None
        return redirect(
            f"https://{canonical}{request.full_path.rstrip('?')}", code=301
        )

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
    if (
        app.config["SESSION_COOKIE_SECURE"]
        and app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite")
    ):
        app.logger.warning(
            "Running in production mode on SQLite. On hosts with ephemeral disks "
            "(Render, Heroku) ALL DATA IS LOST on every deploy/restart — set "
            "DATABASE_URL to a Postgres instance before inviting real users."
        )
    with app.app_context():
        db.create_all()
        try:
            add_missing_columns(app)
        except Exception:
            app.logger.exception("Column migration failed; continuing.")
        try:
            add_missing_indexes(app)
        except Exception:
            app.logger.exception("Index migration failed; continuing.")
        from seed import seed_clubs
        try:
            seed_clubs()
        except Exception:
            app.logger.exception("Database seeding failed; continuing with what exists.")


def add_missing_columns(app):
    """Minimal forward-only migration: ALTER TABLE ADD COLUMN for any model
    column that doesn't exist yet. Handles simple additive schema changes on
    live SQLite/Postgres databases without a full migration tool.
    """
    inspector = db.inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN {column.name} {column.type.compile(db.engine.dialect)}'
            if column.default is not None and getattr(column.default, "arg", None) is not None \
                    and not callable(column.default.arg):
                default = column.default.arg
                default = f"'{default}'" if isinstance(default, str) else default
                ddl += f" DEFAULT {default}"
            with db.engine.begin() as conn:
                conn.execute(db.text(ddl))
            app.logger.info("Added column %s.%s", table.name, column.name)


def add_missing_indexes(app):
    """Create model-declared indexes that don't exist yet (create_all only
    builds indexes for brand-new tables, never for existing ones)."""
    inspector = db.inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in existing:
                continue
            index.create(db.engine)
            app.logger.info("Created index %s on %s", index.name, table.name)


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
